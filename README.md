# tla-check

A GitHub Action that model checks TLA+ specifications with [TLC](https://github.com/tlaplus/tlaplus) and fails the job on any violation, with an annotation on the definition it breaks and the counterexample in the job summary.

```yaml
jobs:
  model:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: benomahony/tla-check@v0.1.0
```

Every `.cfg` file with a `.tla` file of the same name beside it is checked, so `spec/Overwatch.cfg` checks `spec/Overwatch.tla`. Other `.cfg` files, such as `setup.cfg`, are left out. The job fails if nothing qualifies.

## Inputs

| Input | Default | What it does |
| --- | --- | --- |
| `configs` | `**/*.cfg` | Space-separated glob patterns of TLC configuration files |
| `args` | `-workers auto` | Extra TLC arguments, such as `-workers 4 -depth 50` |
| `version` | `1.7.4` | The TLC release to download |
| `sha256` | | The SHA-256 of that release's `tla2tools.jar`, needed for any version other than 1.7.4 |

The download is always checked against a SHA-256. TLC's `v1.8.0` release is rebuilt nightly, so its jar has no fixed checksum, which is why the action defaults to 1.7.4, the latest release that doesn't change.

## What a failure looks like

- **A broken invariant or temporal property** is annotated on the line that defines it. TLC 1.7.4 doesn't say which temporal property failed, so when the configuration checks more than one, the annotation goes on the configuration and lists them.
- **A deadlock** is annotated on the action in the counterexample.
- **A parse or semantic error** is annotated where TLC found it, with its message, such as ``Unknown operator: `Missing'``.
- **The counterexample**, TLC's full output, is in the job log and, shortened to fit, in the job summary.

TLC needs Java 11 or later, which GitHub's hosted Linux and macOS runners have. On a self-hosted runner without it, add `actions/setup-java` first. The action also needs `python3`.

## Develop

```sh
python3 -m unittest discover -s tests
python3 tla_check.py --configs 'tests/fixtures/passing/*.cfg'
```

The tests run TLC on four small specs: one that holds, one that breaks an invariant, one that breaks a temporal property and one that doesn't parse. They download TLC once, or use the jar that `TLA2TOOLS` names.
