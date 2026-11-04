#!/usr/bin/env python3
"""Model check each TLA+ configuration matching a pattern with TLC, and report every violation as a GitHub
annotation on the definition it breaks, with its counterexample in the job summary."""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CHECKSUMS = {
    "1.7.4": "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88",
}
RELEASE = "https://github.com/tlaplus/tlaplus/releases/download/v{version}/tla2tools.jar"
VIOLATION = re.compile(r"^Error: (?:Invariant|Temporal property|Action property) (\w+) (?:is|was) violated", re.M)
ERROR = re.compile(r"^(?:Error: .+|\*\*\* ?Parse Error ?\*\*\*|Semantic error.*|Fatal errors while parsing.*)$", re.M)
LOCATION = re.compile(r"line (\d+), col (\d+) to line \d+, col \d+ of module (\w+)")
SUMMARY_LIMIT = 60_000
KEYWORDS = frozenset({"SPECIFICATION", "INIT", "NEXT", "INVARIANT", "INVARIANTS", "PROPERTY", "PROPERTIES", "CONSTANT",
                      "CONSTANTS", "CONSTRAINT", "CONSTRAINTS", "ACTION_CONSTRAINT", "ACTION_CONSTRAINTS", "SYMMETRY",
                      "VIEW", "CHECK_DEADLOCK", "POSTCONDITION", "ALIAS"})
TEMPORAL = "Error: Temporal properties were violated."


class CheckError(ValueError):
    """The action's inputs cannot be used; the message says what to change in the workflow."""


@dataclass(frozen=True)
class Annotation:
    """Where a failure points: a file, a line in it, and the message to show there."""
    path: Path
    line: int
    message: str


@dataclass(frozen=True)
class Check:
    """One configuration's TLC run: its config and spec, whether it passed, TLC's output, and where it failed."""
    config: Path
    spec: Path
    passed: bool
    output: str
    annotation: Annotation | None


def download(version: str, checksum: str, directory: Path) -> Path:
    """Downloads tla2tools.jar for version into directory and checks it against checksum, or the known one."""
    expected = checksum or CHECKSUMS.get(version.removeprefix("v"))
    if expected is None:
        raise CheckError(f"no known checksum for TLC {version}; pass its sha256 input, or use one of {', '.join(CHECKSUMS)}")
    url = RELEASE.format(version=version.removeprefix("v"))
    jar = directory / "tla2tools.jar"
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            jar.write_bytes(response.read())
    except OSError as error:
        raise CheckError(f"could not download {url} ({error}); check that TLC {version} is listed at https://github.com/tlaplus/tlaplus/releases") from error
    actual = hashlib.sha256(jar.read_bytes()).hexdigest()
    if actual != expected:
        raise CheckError(f"{url} has sha256 {actual}, not {expected}; check the version and sha256 inputs")
    assert jar.stat().st_size > 0, f"{jar} is empty after a download whose checksum matched"
    assert jar.parent == directory, f"{jar} was written outside {directory}"
    return jar


def configs(patterns: list[str], root: Path) -> list[Path]:
    """Every file matching the patterns under root that has a spec of the same name beside it, each once, in a
    stable order, so that other .cfg files, such as setup.cfg, are left out."""
    found = sorted({path for pattern in patterns for path in root.glob(pattern) if path.is_file() and path.with_suffix(".tla").is_file()})
    if not found:
        raise CheckError(f"nothing matching {' '.join(patterns)} under {root} has a spec of the same name beside it; set the configs input to your TLC .cfg files")
    assert all(path.is_relative_to(root) for path in found), f"configs {found} reach outside {root}"
    assert len(found) == len(set(found)), f"configs listed {found} more than once"
    return found


def definition_line(spec: Path, name: str) -> int | None:
    """The line where spec defines name, as `name ==` or `name(...) ==` at the start of a line."""
    pattern = re.compile(rf"^{re.escape(name)}\s*(?:\([^)]*\))?\s*==")
    lines = spec.read_text(encoding="utf-8", errors="replace").splitlines()
    found = next((number for number, line in enumerate(lines, 1) if pattern.match(line)), None)
    assert found is None or 1 <= found <= len(lines), f"{name} found at line {found} of {len(lines)} in {spec}"
    assert found is None or name in lines[found - 1], f"line {found} of {spec} does not define {name}"
    return found


def properties(config: Path) -> list[tuple[str, int]]:
    """The temporal properties a TLC configuration checks, each with the line of the config that names it."""
    named: list[tuple[str, int]] = []
    section = ""
    for number, line in enumerate(config.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", line.split("\\*")[0]):
            if word in KEYWORDS:
                section = word
            elif section in ("PROPERTY", "PROPERTIES"):
                named.append((word, number))
    assert all(number >= 1 for _, number in named), f"properties of {config} have line numbers {named}"
    assert all(word not in KEYWORDS for word, _ in named), f"properties of {config} include keywords: {named}"
    return named


def annotate(config: Path, spec: Path, output: str) -> Annotation:
    """Where a failed run points: the definition of a violated property, the first location TLC names in one of
    the spec's modules, or else the config itself, with TLC's first error line as the message."""
    errors = ERROR.findall(output)
    first = LOCATION.search(output)
    detail = next((line.strip() for line in output[first.end():].splitlines() if line.strip()), "") if first else ""
    message = errors[0] if errors else "TLC failed without naming an error; see the job log"
    message = f"{message} {detail}" if detail and not message.startswith("Error: ") else message
    violated = VIOLATION.search(output)
    line = definition_line(spec, violated.group(1)) if violated else None
    candidates = properties(config) if TEMPORAL in output and line is None else []
    if line is not None:
        found = Annotation(spec, line, message)
    elif len(candidates) == 1 and (defined := definition_line(spec, candidates[0][0])) is not None:
        found = Annotation(spec, defined, f"Error: Temporal property {candidates[0][0]} was violated.")
    elif candidates:
        found = Annotation(config, candidates[0][1], f"{message} One of: {', '.join(name for name, _ in candidates)}.")
    else:
        located = [(spec.parent / f"{module}.tla", int(row)) for row, _, module in LOCATION.findall(output)]
        existing = [(path, row) for path, row in located if path.is_file()]
        found = Annotation(*existing[0], message) if existing else Annotation(config, 1, message)
    assert found.line >= 1, f"annotation for {config} points at line {found.line}"
    assert found.message, f"annotation for {config} has no message"
    return found


def check(config: Path, jar: Path, arguments: list[str]) -> Check:
    """Runs TLC on config and the spec of the same name beside it."""
    spec = config.with_suffix(".tla")
    with tempfile.TemporaryDirectory() as metadir:
        command = ["java", "-XX:+UseParallelGC", "-cp", str(jar.resolve()), "tlc2.TLC", *arguments,
                   "-metadir", metadir, "-config", config.name, spec.name]
        try:
            run = subprocess.run(command, cwd=config.parent, capture_output=True, text=True, check=False)
        except FileNotFoundError as error:
            raise CheckError("java is not on PATH; TLC needs Java 11 or later, which GitHub's hosted runners have, or add actions/setup-java") from error
    output = run.stdout + run.stderr
    passed = run.returncode == 0
    result = Check(config, spec, passed, output, None if passed else annotate(config, spec, output))
    assert result.passed == (result.annotation is None), f"{config} passed={result.passed} with annotation {result.annotation}"
    assert result.spec.stem == config.stem, f"{config} was checked against {result.spec}"
    return result


def escape(text: str) -> str:
    """Text made safe for a GitHub workflow command's message."""
    escaped = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    assert "\n" not in escaped, f"escaped message {escaped!r} still spans lines"
    assert len(escaped) >= len(text), f"escaping shortened {text!r}"
    return escaped


def workflow_command(result: Check, root: Path) -> str:
    """The ::error command that annotates a failed check where it points."""
    assert result.annotation is not None, f"{result.config} passed; annotate only failures"
    path = result.annotation.path.resolve()
    shown = path.relative_to(root.resolve()) if path.is_relative_to(root.resolve()) else path
    command = f"::error file={shown},line={result.annotation.line},title=TLC {result.config.name}::{escape(result.annotation.message)}"
    assert command.startswith("::error file="), f"workflow command {command!r} is malformed"
    return command


def summary(results: list[Check], root: Path) -> str:
    """The job summary: a line per configuration, then each failure's output, shortened to fit."""
    lines = ["## TLC", "", "| Configuration | Result |", "| --- | --- |"]
    lines += [f"| `{result.config.relative_to(root)}` | {'passed' if result.passed else 'failed'} |" for result in results]
    budget = SUMMARY_LIMIT // max(1, sum(not result.passed for result in results))
    for result in results:
        if not result.passed:
            shown = result.output if len(result.output) <= budget else "...\n" + result.output[-budget:]
            lines += ["", f"<details><summary>{result.config.relative_to(root)}</summary>", "", "```", shown.strip(), "```", "", "</details>"]
    text = "\n".join(lines)
    assert text.startswith("## TLC"), f"summary opens with {text[:10]!r}"
    assert text.count("<details>") == sum(not result.passed for result in results), "summary lacks a section per failure"
    return text


def main() -> int:
    """Parses the inputs, downloads TLC unless given, checks every configuration, and reports each result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configs", default="**/*.cfg", help="Space-separated glob patterns of TLC configurations")
    parser.add_argument("--args", default="-workers auto", help="Extra TLC arguments")
    parser.add_argument("--version", default="1.7.4", help="The TLC release to download")
    parser.add_argument("--sha256", default="", help="The release jar's checksum, needed for a version not built in")
    parser.add_argument("--jar", type=Path, help="Use this tla2tools.jar instead of downloading one")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory() as directory:
            jar = args.jar or download(args.version, args.sha256, Path(directory))
            results = [check(config, jar, shlex.split(args.args)) for config in configs(args.configs.split(), args.root)]
    except CheckError as error:
        print(f"::error::{escape(str(error))}")
        return 1
    for result in results:
        print(f"{'passed' if result.passed else 'FAILED'} {result.config.relative_to(args.root)}")
        if not result.passed:
            print(result.output)
            print(workflow_command(result, args.root))
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary(results, args.root) + "\n")
    failed = sum(not result.passed for result in results)
    assert 0 <= failed <= len(results), f"{failed} of {len(results)} checks failed"
    assert results, "no checks ran; configs raises CheckError when none match"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
