import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE_DIR = pathlib.Path(__file__).parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from pvf_comment_parser import _extract_pvf_payload, _parse_payload, main


class PvfCommentParserTest(unittest.TestCase):
    def test_parse_payload_rules_fps_and_languages(self):
        payload = _parse_payload(["fps", "vbnet", "csharp", "S123", "S456"], ['S'])
        self.assertEqual(payload.rules, ["S123", "S456"])
        self.assertEqual(payload.languages, ["vbnet", "csharp"])
        self.assertTrue(payload.fps)
        self.assertFalse(payload.all_flag)

    def test_parse_payload_lowercase_rule_ids(self):
        payload = _parse_payload(["s1234", "S567"], ['S'])
        self.assertEqual(payload.rules, ["S1234", "S567"])

    def test_parse_payload_m23_prefix(self):
        payload = _parse_payload(["c++", "c#", "M23_042", "S1234"], ['M23_', 'S'])
        self.assertEqual(payload.rules, ["M23_042", "S1234"])
        self.assertEqual(payload.languages, ["c++", "c#"])

    def test_extract_rejects_pvfoobar(self):
        self.assertIsNone(_extract_pvf_payload("/pvfoobar java"))

    def test_parse_payload_language_tokens_with_special_chars(self):
        payload = _parse_payload(["c++", "c#", "objective-c", "S123"], ['S'])
        self.assertEqual(payload.languages, ["c++", "c#", "objective-c"])
        self.assertEqual(payload.rules, ["S123"])

    def test_parse_payload_all_flag_clears_rules(self):
        for tokens in (["all", "S123", "java"], ["*", "S123"]):
            with self.subTest(tokens=tokens):
                payload = _parse_payload(tokens, ['S'])
                self.assertTrue(payload.all_flag)
                self.assertEqual(payload.rules, [])

    def test_main_bare_pvf_means_all_rules(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = pathlib.Path(tmp_dir) / "output"
            output_path.touch()
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}):
                with patch("sys.argv", ["pvf_comment_parser.py", "--comment=/pvf", "--rule-prefix=S"]):
                    main()
            text = output_path.read_text(encoding="utf-8")
            self.assertIn("found=true", text)
            self.assertIn("rules-request=", text)
            self.assertNotIn("rules-request=S", text)

    def test_main_accepts_hyphen_leading_body(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = pathlib.Path(tmp_dir) / "output"
            output_path.touch()
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}):
                with patch("sys.argv", ["pvf_comment_parser.py", "--comment=-fps S123", "--rule-prefix=S"]):
                    main()
            text = output_path.read_text(encoding="utf-8")
            self.assertIn("found=false", text)

    def test_main_writes_not_found_outputs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = pathlib.Path(tmp_dir) / "output"
            output_path.touch()
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}):
                with patch("sys.argv", ["pvf_comment_parser.py", "--comment=hello", "--rule-prefix=S"]):
                    main()
            self.assertIn("found=false", output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
