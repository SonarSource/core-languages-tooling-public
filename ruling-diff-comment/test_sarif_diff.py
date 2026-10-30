import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import ruling_diff_core as core
import ruling_diff_io as io
from ruling_diff_core_lib.models_and_constants import IssueLocation
from ruling_diff_core_lib.sarif import parse_sarif_report


def result(filename="alpha:src/A.java", region=None, **metadata):
    physical = {"artifactLocation": {"uri": filename}}
    if region is not None:
        physical["region"] = region
    return {"locations": [{"physicalLocation": physical}], **metadata}


def report(*results):
    return json.dumps({"version": "2.1.0", "runs": [{"results": list(results)}]})


def parse(content):
    return parse_sarif_report(content, "java-S100.sarif", "head")


class SarifDiffTest(unittest.TestCase):
    def setUp(self):
        self.region = {"startLine": 10, "startColumn": 2, "endLine": 12, "endColumn": 5}

    def test_parses_all_selected_coordinates(self):
        self.assertEqual(
            parse(report(result(region=self.region))),
            {"alpha:src/A.java": [IssueLocation(10, 2, 12, 5)]},
        )

    def test_each_coordinate_change_is_a_removal_and_addition(self):
        before = parse(report(result(region=self.region)))
        for field in self.region:
            with self.subTest(field=field):
                changed = {**self.region, field: self.region[field] + 1}
                after = parse(report(result(region=changed)))
                diff = core.diff_sarif_reports(before, after)[0]
                self.assertEqual(diff.removed_locations, [IssueLocation(10, 2, 12, 5)])
                self.assertEqual(diff.added_locations, [IssueLocation(
                    changed["startLine"], changed["startColumn"], changed["endLine"], changed["endColumn"]
                )])

    def test_source_filename_change_is_detected_including_parent_directory(self):
        before = parse(report(result(filename="alpha:src/A.java", region=self.region)))
        after = parse(report(result(filename="alpha:other/A.java", region=self.region)))
        diffs = core.diff_sarif_reports(before, after)
        self.assertEqual([diff.file_path for diff in diffs], ["other/A.java", "src/A.java"])
        self.assertEqual(diffs[0].added_locations, [IssueLocation(10, 2, 12, 5)])
        self.assertEqual(diffs[1].removed_locations, [IssueLocation(10, 2, 12, 5)])

    def test_rule_id_and_other_metadata_are_ignored(self):
        before = result(region=self.region, ruleId="java:S100", message={"text": "same"}, level="warning")
        after = result(region=self.region, ruleId="different", message={"text": "same"}, level="error")
        after["relatedLocations"] = [{"message": {"text": "secondary"}}]
        self.assertEqual(core.diff_sarif_reports(parse(report(before)), parse(report(after))), [])

    def test_message_only_change_is_a_removal_and_addition(self):
        before = parse(report(result(region=self.region, message={"text": "old"})))
        for message in ("new", "Old", "old "):
            with self.subTest(message=message):
                after = parse(report(result(region=self.region, message={"text": message})))
                diff = core.diff_sarif_reports(before, after)[0]
                self.assertEqual(diff.removed_locations, [IssueLocation(10, 2, 12, 5, "old")])
                self.assertEqual(diff.added_locations, [IssueLocation(10, 2, 12, 5, message)])

    def test_different_messages_at_same_location_remain_distinct_and_sorted(self):
        first = result(region=self.region, message={"text": "first"})
        second = result(region=self.region, message={"text": "second"})
        before = parse(report(second, first, first))
        self.assertEqual(core.diff_sarif_reports(before, parse(report(first, second))), [])
        removed = core.diff_sarif_reports(before, None)[0].removed_locations
        self.assertEqual([location.message for location in removed], ["first", "second"])
        diff = core.diff_sarif_reports(before, parse(report(first)))[0]
        self.assertEqual(diff.removed_locations, [IssueLocation(10, 2, 12, 5, "second")])
        self.assertEqual(diff.added_locations, [])

    def test_message_defaults_and_invalid_types(self):
        self.assertEqual(parse(report(result())), parse(report(result(message={"text": ""}))))
        for message in (None, "message", {"text": None}, {"text": 123}):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, "java-S100.sarif at head.*message"):
                    parse(report(result(message=message)))

    def test_comparison_collects_changes_after_first_mismatch(self):
        before = parse(report(result(message={"text": "old"}), result(filename="alpha:src/B.java")))
        after = parse(report(result(message={"text": "new"}), result(filename="alpha:src/C.java")))
        diffs = core.diff_sarif_reports(before, after)
        self.assertEqual([diff.file_path for diff in diffs], ["src/A.java", "src/B.java", "src/C.java"])
        self.assertEqual(sum(len(diff.removed_locations) for diff in diffs), 2)
        self.assertEqual(sum(len(diff.added_locations) for diff in diffs), 2)

    def test_order_and_duplicate_counts_do_not_matter(self):
        first = result(region=self.region)
        second = result(region={**self.region, "startColumn": 3})
        old = parse(report(first, first, second))
        self.assertEqual(core.diff_sarif_reports(old, parse(report(second, first, first))), [])
        self.assertEqual(core.diff_sarif_reports(old, parse(report(first, second))), [])

    def test_missing_coordinates_remain_distinct_from_explicit_values(self):
        for field in ("startColumn", "endLine", "endColumn"):
            with self.subTest(field=field):
                missing = {key: value for key, value in self.region.items() if key != field}
                diffs = core.diff_sarif_reports(
                    parse(report(result(region=missing))), parse(report(result(region=self.region)))
                )
                self.assertEqual(len(diffs[0].removed_locations), 1)
                self.assertEqual(len(diffs[0].added_locations), 1)

    def test_location_coordinates_cannot_be_none(self):
        for field in ("start_line", "start_column", "end_line", "end_column"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(TypeError, field):
                    IssueLocation(**{field: None})

    def test_missing_coordinates_default_to_zero_without_rendering_them(self):
        location = parse(report(result(region={"startLine": 10})))["alpha:src/A.java"][0]
        self.assertEqual(location.sort_key(), (10, 0, 10, 0, ""))
        snippet = core.Snippet("src/A.java", location, "added", "code")
        comment = core.format_comment([core.RuleDiff(
            "alpha", "java", "S100", [core.IssueDiff("src/A.java", [location], [])],
            [snippet], False, False,
        )])
        self.assertIn("`src/A.java` (line 10)", comment)
        self.assertNotIn("column 0", comment)
        self.assertNotIn("to line 0", comment)

    def test_file_level_and_line_only_findings(self):
        self.assertEqual(parse(report(result())), {"alpha:src/A.java": [IssueLocation()]})
        self.assertEqual(
            parse(report(result(region={"startLine": 10}))),
            {"alpha:src/A.java": [IssueLocation(10, 0, 10, 0)]},
        )
        self.assertEqual(parse(report(result())), parse(report(result(region={}))))

    def test_missing_end_line_defaults_to_start_line_like_lits(self):
        implicit = parse(report(result(region={"startLine": 10, "startColumn": 2, "endColumn": 5})))
        explicit = parse(report(result(region={
            "startLine": 10, "startColumn": 2, "endLine": 10, "endColumn": 5,
        })))
        self.assertEqual(implicit, {"alpha:src/A.java": [IssueLocation(10, 2, 10, 5)]})
        self.assertEqual(core.diff_sarif_reports(implicit, explicit), [])

    def test_precise_lits_output_preserves_columns_and_ignores_offsets(self):
        # Ranges from romain/precise-sarif-locations DumpTest, already 1-based.
        first = result(filename="file", ruleId="repo:rule", message={"text": "first"}, region={
            "startLine": 2, "startColumn": 2, "endLine": 3, "endColumn": 4,
            "charOffset": 5, "charLength": 8, "byteOffset": 7, "byteLength": 11,
        })
        second = result(filename="file", ruleId="repo:rule", message={"text": "second"}, region={
            "startLine": 2, "startColumn": 5, "endLine": 2, "endColumn": 8,
            "charOffset": 8, "charLength": 3, "byteOffset": 10, "byteLength": 3,
        })
        document = {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": "LITS"}},
                      "columnKind": "utf16CodeUnits", "results": [first, second]}],
        }
        parsed = parse(json.dumps(document))
        self.assertEqual(parsed, {"file": [IssueLocation(2, 2, 3, 4, "first"), IssueLocation(2, 5, 2, 8, "second")]})
        first["locations"][0]["physicalLocation"]["region"].update(
            charOffset=0, charLength=0, byteOffset=0, byteLength=0
        )
        self.assertEqual(core.diff_sarif_reports(parsed, parse(json.dumps(document))), [])
        first["locations"][0]["physicalLocation"]["region"]["endColumn"] = 6
        changed = core.diff_sarif_reports(parsed, parse(json.dumps(document)))[0]
        self.assertEqual(changed.removed_locations, [IssueLocation(2, 2, 3, 4, "first")])
        self.assertEqual(changed.added_locations, [IssueLocation(2, 2, 3, 6, "first")])

    def test_message_only_changes_generate_snippets_and_escaped_messages(self):
        path = "its/ruling/src/test/resources/expected/alpha/java-S100.sarif"
        contents = {
            ref: parse(report(result(region=self.region, message={"text": message})))
            for ref, message in (("base", "old <message>"), ("head", "new & improved"))
        }
        action_io = io.GitHubActionIO()
        with patch.object(action_io, "load_sarif_at_ref", side_effect=lambda _, ref: contents[ref]), patch.object(
            action_io, "load_text_at_ref", return_value="source"
        ):
            diffs = core.build_rule_diffs([path], "base", "head", action_io)
        self.assertEqual([snippet.change_kind for snippet in diffs[0].snippets], ["removed", "added"])
        comment = core.format_comment(diffs)
        self.assertIn("1 issues removed, 1 issues added", comment)
        self.assertIn("<pre>old &lt;message&gt;</pre>", comment)
        self.assertIn("<pre>new &amp; improved</pre>", comment)

    def test_lits_line_only_and_file_level_output(self):
        parsed = parse(report(
            result(region={"startLine": 2, "endLine": 2}),
            result(),
        ))
        self.assertEqual(parsed, {"alpha:src/A.java": [IssueLocation(2, 0, 2, 0), IssueLocation()]})
        for location, expected_header in (
            (parsed["alpha:src/A.java"][0], "`src/A.java` (line 2)"),
            (parsed["alpha:src/A.java"][1], "`src/A.java` (file-level)"),
        ):
            with self.subTest(location=location):
                snippet = core.Snippet("src/A.java", location, "added", "code")
                comment = core.format_comment([core.RuleDiff(
                    "alpha", "java", "S100", [core.IssueDiff("src/A.java", [location], [])],
                    [snippet], False, False,
                )])
                self.assertIn(expected_header, comment)

    def test_all_runs_and_primary_locations_are_read(self):
        first = result(region=self.region)
        first["locations"].extend(result(filename="alpha:src/B.java")["locations"])
        document = {"runs": [{"results": [first]}, {}, {"results": [result()]}]}
        parsed = parse(json.dumps(document))
        self.assertEqual(len(parsed["alpha:src/A.java"]), 2)
        self.assertEqual(parsed["alpha:src/B.java"], [IssueLocation()])

    def test_empty_added_and_deleted_reports(self):
        self.assertEqual(parse(report()), {})
        self.assertEqual(parse('{"runs": []}'), {})
        populated = parse(report(result(region=self.region)))
        self.assertEqual(core.diff_sarif_reports(None, populated)[0].added_locations, [IssueLocation(10, 2, 12, 5)])
        self.assertEqual(core.diff_sarif_reports(populated, None)[0].removed_locations, [IssueLocation(10, 2, 12, 5)])
        self.assertEqual(core.diff_sarif_reports(populated, {})[0].removed_locations, [IssueLocation(10, 2, 12, 5)])

    def test_report_missing_at_revision_returns_none(self):
        response = subprocess.CompletedProcess(
            [], 128, stdout="", stderr="path does not exist in 'base'"
        )
        with patch.object(io.subprocess, "run", return_value=response):
            self.assertIsNone(io.load_sarif_at_ref("java-S100.sarif", "base"))

    def test_invalid_reports_fail_with_file_and_revision_context(self):
        invalid = ["{", "[]", "{}", '{"runs": {}}', '{"runs": [null]}',
                   '{"runs": [{"results": {}}]}', report({}), report({"locations": []}),
                   report({"locations": [None]}), report({"locations": [{"physicalLocation": {}}]})]
        for content in invalid:
            with self.subTest(content=content):
                with self.assertRaisesRegex(ValueError, "java-S100.sarif at head"):
                    parse(content)

    def test_invalid_coordinate_and_filename_types_are_rejected(self):
        for field in self.region:
            for value in (0, -1, True, "10", None):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValueError, field):
                        parse(report(result(region={**self.region, field: value})))
        for filename in (None, "", 123):
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(ValueError, "filename"):
                    parse(report(result(filename=filename)))

    def test_distinct_columns_on_same_line_generate_distinct_snippets(self):
        path = "its/ruling/src/test/resources/expected/alpha/java-S100.sarif"
        contents = {
            "base": parse(report(result(region=self.region))),
            "head": parse(report(
                result(region={**self.region, "startColumn": 3}),
                result(region={**self.region, "startColumn": 4}),
            )),
        }
        action_io = io.GitHubActionIO()
        with patch.object(action_io, "load_sarif_at_ref", side_effect=lambda _, ref: contents[ref]), patch.object(
            action_io, "load_text_at_ref", side_effect=lambda _, ref: f"source at {ref}"
        ) as load_source:
            diffs = core.build_rule_diffs([path], "base", "head", action_io)
        self.assertEqual([snippet.location.start_column for snippet in diffs[0].snippets], [2, 3, 4])
        self.assertIn("source at base", diffs[0].snippets[0].body)
        self.assertIn("source at head", diffs[0].snippets[1].body)
        self.assertEqual(load_source.call_count, 2)
        comment = core.format_comment(diffs)
        self.assertIn("1 issues removed, 2 issues added", comment)
        self.assertIn("line 10, column 2 to line 12, end column 5", comment)
        self.assertIn("column 3", comment)
        self.assertIn("column 4", comment)

    def test_git_loading_discovery_diff_and_comment_integration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            path = "its/ruling/src/test/resources/expected/alpha/java-S100.sarif"
            expectation = root / path
            expectation.parent.mkdir(parents=True)
            source = root / "src/A.java"
            source.parent.mkdir(parents=True)
            source.write_text("\n".join(f"source line {line}" for line in range(1, 20)))

            def git(*args):
                return subprocess.check_output(["git", "-C", directory, *args], text=True).strip()

            git("init", "--quiet")
            expectation.write_text(report(result(region=self.region)))
            git("add", ".")
            git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--quiet", "-m", "base")
            base = git("rev-parse", "HEAD")
            expectation.write_text(report(result(region={**self.region, "endColumn": 8})))
            git("add", ".")
            git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--quiet", "-m", "head")
            head = git("rev-parse", "HEAD")
            action_io = io.GitHubActionIO()
            real_run = subprocess.run

            def run_in_repo(command, **kwargs):
                return real_run(command, cwd=directory, **kwargs)

            with patch.object(io.subprocess, "run", side_effect=run_in_repo), patch.object(
                action_io, "resolve_source_path", return_value="src/A.java"
            ):
                changed = io.get_changed_ruling_files(base, head)
                self.assertEqual(changed, [path])
                diffs = core.build_rule_diffs(changed, base, head, action_io)
            comment = core.format_comment(diffs)
            self.assertIn("end column 5", comment)
            self.assertIn("end column 8", comment)
            self.assertIn("source line 10", comment)
            self.assertEqual(diffs[0].rule_key, "S100")


if __name__ == "__main__":
    unittest.main()
