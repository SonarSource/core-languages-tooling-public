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
        self.assertEqual(payload.mode, "light")

    def test_parse_payload_full_mode(self):
        for flag in ("full", "FULL"):
            with self.subTest(flag=flag):
                payload = _parse_payload([flag], ['S'])
                self.assertEqual(payload.mode, "full")
                self.assertEqual(payload.rules, [])
                self.assertEqual(payload.languages, [])
                self.assertTrue(payload.all_flag)

    def test_parse_payload_full_mode_preserves_filters_and_flags(self):
        payload = _parse_payload(["full", "S123", "java", "fps", "Full"], ['S'])
        self.assertEqual(payload.mode, "full")
        self.assertEqual(payload.rules, ["S123"])
        self.assertEqual(payload.languages, ["java", "Full"])
        self.assertTrue(payload.fps)
        self.assertFalse(payload.all_flag)

    def test_parse_payload_lowercase_rule_ids(self):
        payload = _parse_payload(["s1234", "S567"], ['S'])
        self.assertEqual(payload.rules, ["S1234", "S567"])
        self.assertEqual(payload.languages, [])

    def test_parse_payload_dotted_rule_prefixes(self):
        prefixes = ['S', 'M23_', 'MC-2012_', 'MC-2023_', 'MC-2025_',
                    'MC-AMD1_', 'MC-AMD2_', 'MC-AMD3_']
        for prefix in prefixes:
            with self.subTest(prefix=prefix):
                payload = _parse_payload([prefix.lower() + "17.3.1", "FPS", "c++"], [prefix.lower()])
                self.assertEqual(payload.rules, [prefix + "17.3.1"])
                self.assertEqual(payload.languages, ["c++"])
                self.assertTrue(payload.fps)
                self.assertFalse(payload.all_flag)

    def test_parse_payload_rejects_malformed_rule_suffixes(self):
        for suffix in ("", ".3", "17.", "17..3", "17.3x", "17.3\n", "+17", "-17", "1_7"):
            with self.subTest(suffix=suffix):
                token = "MC-2012_" + suffix
                payload = _parse_payload([token, "S123"], ['MC-2012_', 'S'])
                self.assertEqual(payload.rules, ["S123"])
                self.assertEqual(payload.languages, [token])
                self.assertFalse(payload.all_flag)

    def test_parse_payload_preserves_flags_and_unknown_tokens(self):
        for flag in ("ALL", "all", "*"):
            with self.subTest(flag=flag):
                payload = _parse_payload(
                    [flag, "fps", "mc-2012_17.3", "c++", "All", "Fps", "MC-AMD1_17.3"],
                    ['MC-2012_'],
                )
                self.assertEqual(payload.rules, [])
                self.assertEqual(payload.languages, ["c++", "All", "Fps", "MC-AMD1_17.3"])
                self.assertTrue(payload.fps)
                self.assertTrue(payload.all_flag)

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

    def test_parse_payload_language_starting_with_rule_prefix(self):
        payload = _parse_payload(["swift", "sql", "S123"], ['S'])
        self.assertEqual(payload.languages, ["swift", "sql"])
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
                with patch("sys.argv", ["pvf_comment_parser.py", "--comment=/pvf", "--rule-prefixes=S"]):
                    main()
            text = output_path.read_text(encoding="utf-8")
            self.assertIn("found=true", text)
            self.assertIn("rules-request=", text)
            self.assertNotIn("rules-request=S", text)
            self.assertIn("mode=light\n", text)

    def test_main_mode_outputs(self):
        for comment, expected_mode, expected_rules in (
            ("/pvf", "light", ""),
            ("/pvf all", "light", ""),
            ("/pvf S123", "light", "S123"),
            ("/pvf full", "full", ""),
            ("/pvf FULL", "full", ""),
            ("/pvf full S123", "full", "S123"),
            ("/pvf full all S123", "full", ""),
        ):
            with self.subTest(comment=comment), tempfile.TemporaryDirectory() as tmp_dir:
                output_path = pathlib.Path(tmp_dir) / "output"
                with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}):
                    with patch("sys.argv", ["pvf_comment_parser.py", "--comment=" + comment]):
                        main()
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    f"found=true\nrules-request={expected_rules}\nfps=false\n"
                    f"languages=[]\nmode={expected_mode}\n",
                )

    def test_main_accepts_hyphen_leading_body(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = pathlib.Path(tmp_dir) / "output"
            output_path.touch()
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}):
                with patch("sys.argv", ["pvf_comment_parser.py", "--comment=-fps S123", "--rule-prefixes=S"]):
                    main()
            text = output_path.read_text(encoding="utf-8")
            self.assertIn("found=false", text)

    def test_main_writes_not_found_outputs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = pathlib.Path(tmp_dir) / "output"
            output_path.touch()
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}):
                with patch("sys.argv", ["pvf_comment_parser.py", "--comment=hello", "--rule-prefixes=S"]):
                    main()
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "found=false\nrules-request=\nfps=false\nlanguages=[]\nmode=light\n",
            )

    def test_main_rule_prefixes_multiple_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = pathlib.Path(tmp_dir) / "output"
            output_path.touch()
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}):
                with patch(
                    "sys.argv",
                    ["pvf_comment_parser.py", "--comment=/pvf S123 M23_042", "--rule-prefixes=S M23_"],
                ):
                    main()
            text = output_path.read_text(encoding="utf-8")
            self.assertIn("found=true", text)
            self.assertIn("rules-request=S123,M23_042", text)

    def test_main_dotted_rules_outputs(self):
        for comment, expected_rules, expected_fps, expected_languages in (
            ("/pvf MC-2012_17.3 MC-AMD1_17.3", "MC-2012_17.3,MC-AMD1_17.3", "false", "[]"),
            ("/pvf mc-2012_17.3 Mc-AmD1_17.3 s123 m23_042 fps c++",
             "MC-2012_17.3,MC-AMD1_17.3,S123,M23_042", "true", '["c++"]'),
        ):
            with self.subTest(comment=comment), tempfile.TemporaryDirectory() as tmp_dir:
                output_path = pathlib.Path(tmp_dir) / "output"
                with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}):
                    with patch("sys.argv", [
                        "pvf_comment_parser.py", "--comment=" + comment,
                        "--rule-prefixes=S M23_ MC-2012_ MC-AMD1_",
                    ]):
                        main()
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    f"found=true\nrules-request={expected_rules}\nfps={expected_fps}\n"
                    f"languages={expected_languages}\nmode=light\n",
                )


if __name__ == "__main__":
    unittest.main()
