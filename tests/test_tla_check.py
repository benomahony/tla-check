"""Run the checker against small specs that pass, break an invariant, break a temporal property, or fail to parse."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))

import tla_check


class CheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Uses the jar named by TLA2TOOLS, or downloads the default release once for every test."""
        cls.directory = tempfile.TemporaryDirectory()
        given = os.environ.get("TLA2TOOLS")
        cls.jar = Path(given) if given else tla_check.download("1.7.4", "", Path(cls.directory.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def check(self, name: str) -> tla_check.Check:
        """Checks the fixture of that name with one worker."""
        return tla_check.check(FIXTURES / name / "Counter.cfg", self.jar, ["-workers", "1"])

    def test_a_spec_that_holds_passes(self) -> None:
        result = self.check("passing")
        self.assertTrue(result.passed, result.output)
        self.assertIsNone(result.annotation)

    def test_a_broken_invariant_points_at_its_definition(self) -> None:
        result = self.check("invariant")
        self.assertFalse(result.passed)
        self.assertEqual((result.annotation.path.name, result.annotation.line), ("Counter.tla", 8))
        self.assertIn("Small", result.annotation.message)

    def test_a_broken_temporal_property_points_at_its_definition(self) -> None:
        result = self.check("temporal")
        self.assertFalse(result.passed)
        self.assertEqual(result.annotation.line, 7)
        self.assertIn("Reaches", result.annotation.message)

    def test_a_parse_error_points_where_tlc_found_it(self) -> None:
        result = self.check("parse")
        self.assertFalse(result.passed)
        self.assertEqual(result.annotation.line, 5)
        self.assertIn("Missing", result.annotation.message)


class InputTests(unittest.TestCase):
    def test_configs_finds_every_match_once(self) -> None:
        found = tla_check.configs(["**/*.cfg", "tests/fixtures/passing/*.cfg"], ROOT)
        self.assertEqual(len(found), 4)

    def test_a_config_without_a_spec_beside_it_is_left_out(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "setup.cfg").write_text("[metadata]\n")
            (Path(directory) / "Spec.cfg").write_text("SPECIFICATION Spec\n")
            (Path(directory) / "Spec.tla").write_text("---- MODULE Spec ----\n====\n")
            self.assertEqual([path.name for path in tla_check.configs(["*.cfg"], Path(directory))], ["Spec.cfg"])

    def test_no_matching_config_is_an_error(self) -> None:
        with self.assertRaises(tla_check.CheckError):
            tla_check.configs(["nowhere/*.cfg"], ROOT)

    def test_an_unknown_version_needs_a_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(tla_check.CheckError):
            tla_check.download("9.9.9", "", Path(directory))

    def test_properties_are_read_from_the_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "Spec.cfg"
            config.write_text("SPECIFICATION Spec\nINVARIANT TypeOK\nPROPERTIES\n    Live \\* the main one\n    Fair\n")
            self.assertEqual(tla_check.properties(config), [("Live", 4), ("Fair", 5)])

    def test_messages_stay_on_one_line(self) -> None:
        self.assertEqual(tla_check.escape("50%\nnext"), "50%25%0Anext")


if __name__ == "__main__":
    unittest.main()
