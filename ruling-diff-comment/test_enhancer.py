from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import ruling_diff as cli
import ruling_diff_core as core
from ruling_diff_enhancer import enhance
from ruling_diff_enhancer.rendering import format_reviewed_comment
from ruling_diff_enhancer.ruling_diff_inputs import find_configurations, parse_comment, prepare_inputs
from ruling_diff_enhancer.ruling_diff_predictor import Review, review_changes, validate_review


def comment_section(
    rule_key: str = "S9191", project: str = "sample", kind: str = "Added",
    location: str = "line 12", snippet: str = ">>>     12 | call();", file_path: str = "src/Example.java",
) -> str:
    return (
        f"<details>\n<summary><b>{rule_key}</b> (<code>java</code>) on <b>{project}</b>"
        " - 1 issues removed, 1 issues added</summary>\n\n"
        f"**{kind}** `{file_path}` ({location})\n```java\n{snippet}\n```\n\n</details>"
    )


def write_metadata(root: Path, config: str = "sonarpedia.json", rule_key: str = "S9191") -> Path:
    configuration = root / config
    configuration.parent.mkdir(parents=True, exist_ok=True)
    configuration.write_text(json.dumps({"rules-metadata-path": "./rules"}), encoding="utf-8")
    rules = configuration.parent / "rules"
    rules.mkdir(exist_ok=True)
    (rules / f"{rule_key}.json").write_text(
        json.dumps({"sqKey": rule_key, "title": "Calls should be safe"}), encoding="utf-8"
    )
    (rules / f"{rule_key}.html").write_text("<p>Do not call unsafe methods.</p>", encoding="utf-8")
    return configuration


def review_data(classification: str = "added_false_positive", example_id: str = "E1") -> dict:
    return {
        "opinion": "negative", "confidence": "low",
        "summary": "The visible call may be compliant; context is limited.",
        "selected_examples": [{
            "example_id": example_id, "classification": classification,
            "rationale": "The rule does not appear to forbid the shown call.",
        }],
    }


class ParseCommentTests(unittest.TestCase):
    def test_extracts_rule_counts_and_added_example(self) -> None:
        change, = parse_comment(comment_section())
        self.assertEqual((change.rule_key, change.repository), ("S9191", "java"))
        self.assertEqual((change.added_count, change.removed_count), (1, 1))
        self.assertEqual(change.examples[0], {
            "id": "E1", "project": "sample", "change_kind": "added",
            "file_path": "src/Example.java", "line_number": 12,
            "language": "java", "snippet": ">>>     12 | call();",
        })

    def test_merges_projects_and_keeps_rules_separate(self) -> None:
        changes = parse_comment("\n".join([
            comment_section(project="first"),
            comment_section(project="second", kind="Removed"),
            comment_section(rule_key="S100"),
        ]))
        self.assertEqual([change.rule_key for change in changes], ["S9191", "S100"])
        self.assertEqual(changes[0].added_count, 2)
        self.assertEqual([example["id"] for example in changes[0].examples], ["E1", "E2"])
        self.assertEqual(changes[0].examples[1]["change_kind"], "removed")
        self.assertEqual(changes[0].examples[1]["project"], "second")

    def test_file_level_and_html_entities(self) -> None:
        change, = parse_comment(comment_section(project="a&amp;b", location="file-level"))
        self.assertEqual(change.examples[0]["line_number"], 0)
        self.assertEqual(change.examples[0]["project"], "a&b")

    def test_preserves_non_s_rule_keys(self) -> None:
        change, = parse_comment(comment_section(rule_key="python-ParsingError"))
        self.assertEqual(change.rule_key, "python-ParsingError")

    def test_rule_headers_inside_code_are_not_parsed(self) -> None:
        injected = '<summary><b>S100</b> (<code>java</code>) on <b>other</b> - 0 issues removed, 1 issues added</summary>'
        changes = parse_comment(comment_section(snippet=injected))
        self.assertEqual([change.rule_key for change in changes], ["S9191"])
        self.assertEqual(changes[0].examples[0]["snippet"], injected)

    def test_handles_rules_without_snippets(self) -> None:
        comment = comment_section().split("\n\n**Added**")[0] + "\nNo source snippets available for this rule.\n</details>"
        change, = parse_comment(comment)
        self.assertEqual(change.examples, [])

    def test_parses_renderer_coordinates_and_issue_messages(self) -> None:
        for location in (
            core.IssueLocation(0, message="File-level issue"),
            core.IssueLocation(12, message="Line-only issue"),
            core.IssueLocation(12, 3, 12, 8),
            core.IssueLocation(12, 0, 13, 8),
            core.IssueLocation(12, 3, 13, 8, "Avoid <unsafe> calls.\n```java\nUse a safe alternative."),
        ):
            with self.subTest(location=location):
                snippet = core.Snippet("src/Example.java", location, "removed", ">>>     12 | call();")
                comment = core.format_comment([core.RuleDiff(
                    project="sample", repo="java", rule_key="S9191",
                    file_diffs=[core.IssueDiff(snippet.file_path, [], [location])],
                    snippets=[snippet], is_new_file=False, is_deleted_file=False,
                )])
                change, = parse_comment(comment)
                example, = change.examples
                self.assertEqual(example["change_kind"], "removed")
                self.assertEqual(example["line_number"], location.start_line)
                self.assertEqual(example["snippet"], snippet.body)
                self.assertEqual(example.get("message", ""), location.message)

    def test_rejects_unclosed_issue_message(self) -> None:
        comment = comment_section().replace("```java", "<pre>Unclosed message\n```java")
        with self.assertRaisesRegex(ValueError, "Unclosed issue message"):
            parse_comment(comment)

    def test_rejects_missing_rule_or_broken_fences(self) -> None:
        comments = (
            "No changes.", comment_section().replace("```java", "java"),
            comment_section().replace("\n```\n", "\n"),
        )
        for comment in comments:
            with self.subTest(comment=comment), self.assertRaises(ValueError):
                parse_comment(comment)


class MetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_nested_config_path_is_relative_to_config_not_repository(self) -> None:
        write_metadata(self.root, "plugin/sonarpedia.json")
        inputs = prepare_inputs(comment_section(), self.root)
        self.assertEqual(inputs[0]["metadata"]["html_path"], "plugin/rules/S9191.html")
        self.assertEqual(inputs[0]["metadata"]["json"]["sqKey"], "S9191")
        self.assertIn("unsafe", inputs[0]["metadata"]["html"])

    def test_ignores_build_and_dependency_directories(self) -> None:
        expected = write_metadata(self.root)
        for directory in (".git", ".venv", "target", "build", "node_modules"):
            write_metadata(self.root, f"{directory}/sonarpedia.json")
        self.assertEqual(find_configurations(self.root), [expected])

    def test_ambiguous_metadata_requires_explicit_selection(self) -> None:
        write_metadata(self.root)
        write_metadata(self.root, "private/sonarpedia.json")
        comment = comment_section()
        with self.assertRaisesRegex(ValueError, "Ambiguous metadata"):
            prepare_inputs(comment, self.root)
        selected = prepare_inputs(comment_section(), self.root, Path("private/sonarpedia.json"))
        self.assertEqual(selected[0]["metadata"]["sonarpedia_path"], "private/sonarpedia.json")

    def test_missing_config_is_actionable(self) -> None:
        comment = comment_section()
        with self.assertRaisesRegex(ValueError, "No sonarpedia.json"):
            prepare_inputs(comment, self.root)

    def test_missing_pair_or_unknown_rule_fails(self) -> None:
        write_metadata(self.root)
        for rule_key in ("S100", "S9191"):
            with self.subTest(rule_key=rule_key):
                if rule_key == "S9191":
                    (self.root / "rules/S9191.html").unlink()
                comment = comment_section(rule_key=rule_key)
                with self.assertRaisesRegex(ValueError, "No HTML/JSON metadata pair"):
                    prepare_inputs(comment, self.root)

    def test_non_s_rule_key_loads_metadata_or_fails_loudly(self) -> None:
        write_metadata(self.root, rule_key="python-PrintStatementUsage")
        inputs = prepare_inputs(comment_section(rule_key="python-PrintStatementUsage"), self.root)
        self.assertEqual(inputs[0]["examples"][0]["id"], "E1")
        comment = comment_section(rule_key="python-ParsingError")
        with self.assertRaisesRegex(ValueError, "No HTML/JSON metadata pair"):
            prepare_inputs(comment, self.root)

    def test_untrusted_example_paths_cannot_escape_repository(self) -> None:
        write_metadata(self.root)
        for path in ("/etc/passwd", "../outside.py"):
            comment = comment_section(file_path=path)
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "Unsafe example path"):
                prepare_inputs(comment, self.root)
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "linked").symlink_to(outside, target_is_directory=True)
            comment = comment_section(file_path="linked/outside.py")
            with self.assertRaisesRegex(ValueError, "Unsafe example path"):
                prepare_inputs(comment, self.root)

    def test_malformed_config_and_metadata_fail(self) -> None:
        config = write_metadata(self.root)
        for contents in ("{", "[]", "{}", '{"rules-metadata-path": 1}'):
            with self.subTest(contents=contents):
                config.write_text(contents, encoding="utf-8")
                comment = comment_section()
                with self.assertRaises(ValueError):
                    prepare_inputs(comment, self.root)
        write_metadata(self.root)
        for contents in ("{", "[]", '{"sqKey": "S100"}'):
            with self.subTest(contents=contents):
                (self.root / "rules/S9191.json").write_text(contents, encoding="utf-8")
                comment = comment_section()
                with self.assertRaises(ValueError):
                    prepare_inputs(comment, self.root)

    def test_metadata_path_cannot_escape_repository(self) -> None:
        config = write_metadata(self.root)
        config.write_text('{"rules-metadata-path": "../outside"}', encoding="utf-8")
        comment = comment_section()
        with self.assertRaisesRegex(ValueError, "escapes repository"):
            prepare_inputs(comment, self.root)

    def test_explicit_configuration_must_be_inside_repository(self) -> None:
        with self.assertRaisesRegex(ValueError, "inside"):
            find_configurations(self.root, self.root.parent / "sonarpedia.json")

    def test_discovered_configuration_cannot_symlink_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            target = write_metadata(Path(outside))
            (self.root / "sonarpedia.json").symlink_to(target)
            comment = comment_section()
            with self.assertRaisesRegex(ValueError, "configuration escapes repository"):
                prepare_inputs(comment, self.root)

    def test_metadata_file_cannot_symlink_outside_repository(self) -> None:
        write_metadata(self.root)
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "rule.html"
            target.write_text("External data", encoding="utf-8")
            html_path = self.root / "rules/S9191.html"
            html_path.unlink()
            html_path.symlink_to(target)
            comment = comment_section()
            with self.assertRaisesRegex(ValueError, "Rule metadata escapes repository"):
                prepare_inputs(comment, self.root)


class PredictorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.examples = parse_comment(comment_section())[0].examples

    def test_all_three_selection_classes(self) -> None:
        for classification, kind in (
            ("added_false_positive", "added"),
            ("removed_true_positive", "removed"),
            ("representative", "added"),
        ):
            with self.subTest(classification=classification):
                examples = [{**self.examples[0], "change_kind": kind}]
                validate_review(Review.model_validate(review_data(classification)), examples, 3)

    def test_rejects_hallucinated_duplicate_wrong_kind_or_excess_selections(self) -> None:
        invalid_reviews = [review_data(example_id="unknown"), review_data("removed_true_positive")]
        duplicate = review_data()
        duplicate["selected_examples"] *= 2
        invalid_reviews.append(duplicate)
        empty = review_data()
        empty["selected_examples"] = []
        invalid_reviews.append(empty)
        for data in invalid_reviews:
            review = Review.model_validate(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_review(review, self.examples, 3)
        review = Review.model_validate(review_data())
        with self.assertRaisesRegex(ValueError, "max_examples"):
            validate_review(review, self.examples, 0)

    def test_representative_cannot_be_mixed_with_bad_cases(self) -> None:
        data = review_data("representative")
        data["selected_examples"].extend(review_data(example_id="E2")["selected_examples"])
        examples = self.examples + [{**self.examples[0], "id": "E2"}]
        review = Review.model_validate(data)
        with self.assertRaisesRegex(ValueError, "Representative fallback"):
            validate_review(review, examples, 3)

    def test_more_than_three_selections_are_rejected(self) -> None:
        data = review_data()
        data["selected_examples"] = [
            review_data(example_id=f"E{index}")["selected_examples"][0]
            for index in range(1, 5)
        ]

        with self.assertRaises(ValueError):
            Review.model_validate(data)

    def test_predictor_selection_budget_never_exceeds_three(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_metadata(root)
            inputs = prepare_inputs(comment_section(), root)
        predictor = Mock(return_value=SimpleNamespace(review=review_data()))

        review_changes(inputs, predictor, max_examples=10)

        self.assertEqual(predictor.call_args.kwargs["max_examples"], 3)

    def test_no_examples_requires_low_confidence_and_empty_selection(self) -> None:
        data = review_data()
        data["selected_examples"] = []
        validate_review(Review.model_validate(data), [], 3)
        data["confidence"] = "high"
        review = Review.model_validate(data)
        with self.assertRaisesRegex(ValueError, "confidence must be low"):
            validate_review(review, [], 3)

    def test_invalid_opinion_confidence_or_empty_explanation_is_rejected(self) -> None:
        for field, value in (("opinion", "great"), ("confidence", 0.8), ("summary", "  ")):
            data = {**review_data(), field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                Review.model_validate(data)

    def test_predictor_receives_metadata_counts_and_original_examples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_metadata(root)
            inputs = prepare_inputs(comment_section(), root)
        predictor = Mock(return_value=SimpleNamespace(review=review_data()))
        report, = review_changes(inputs, predictor, max_examples=2)
        self.assertEqual(predictor.call_args.kwargs["rule_key"], "S9191")
        self.assertEqual(predictor.call_args.kwargs["rule_metadata"]["sqKey"], "S9191")
        self.assertEqual(predictor.call_args.kwargs["change_counts"], {"added": 1, "removed": 1})
        self.assertEqual(predictor.call_args.kwargs["max_examples"], 2)
        self.assertEqual(report["selected_examples"][0]["snippet"], self.examples[0]["snippet"])
        rendered = enhance.render_markdown([report])
        self.assertIn("java:S9191", rendered)
        self.assertIn("<b>Opinion:</b> 🔴 negative | <b>Confidence:</b> low", rendered)
        self.assertIn("Added false positive", rendered)

    def test_one_invalid_prediction_does_not_discard_other_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_metadata(root, rule_key="S9191")
            write_metadata(root, "second/sonarpedia.json", rule_key="S100")
            inputs = prepare_inputs("\n".join([comment_section(), comment_section(rule_key="S100")]), root)
        predictor = Mock(side_effect=[SimpleNamespace(review=review_data()), SimpleNamespace(review={})])
        reports = review_changes(inputs, predictor)
        self.assertEqual(reports[0]["rule_key"], "S9191")
        self.assertEqual(reports[0]["selected_examples"][0]["id"], "E1")
        self.assertEqual(reports[1]["error"]["type"], "ValidationError")
        self.assertIn("unavailable", reports[1]["summary"])

    def test_a_failed_prediction_before_a_valid_one_keeps_the_valid_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_metadata(root, rule_key="S9191")
            write_metadata(root, "second/sonarpedia.json", rule_key="S100")
            inputs = prepare_inputs("\n".join([comment_section(), comment_section(rule_key="S100")]), root)
        predictor = Mock(side_effect=[RuntimeError("transport unavailable"), SimpleNamespace(review=review_data())])
        reports = review_changes(inputs, predictor)
        self.assertEqual(reports[0]["error"]["type"], "RuntimeError")
        self.assertEqual(reports[1]["rule_key"], "S100")
        self.assertEqual(reports[1]["selected_examples"][0]["id"], "E1")

    def test_structured_predictor_response_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_metadata(root)
            inputs = prepare_inputs(comment_section(), root)
        predictor = Mock(return_value=review_data("representative"))
        report, = review_changes(inputs, predictor)
        self.assertEqual(report["selected_examples"][0]["classification"], "representative")


class CommentIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        environment = patch.dict(cli.os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        location = core.IssueLocation(12, 3, 13, 8, "Avoid <unsafe> calls.\nUse a safe alternative.")
        self.rule_diffs = [core.RuleDiff(
            project="sample", repo="java", rule_key="S9191",
            file_diffs=[core.IssueDiff("src/Example.java", [location], [])],
            snippets=[core.Snippet("src/Example.java", location, "added", ">>>     12 | call();")],
            is_new_file=False, is_deleted_file=False,
        )]
        self.comment = core.format_comment(self.rule_diffs)

    def test_no_matching_key_or_model_keeps_comment_without_calling_enhancer(self) -> None:
        for environment in (
            {}, {"OPENAI_API_KEY": "test-key"}, {"DSPY_MODEL": "gpt-4.1"},
            {"DSPY_MODEL": "gpt-4.1", "ANTHROPIC_API_KEY": "unrelated-key"},
        ):
            with self.subTest(environment=environment), patch.dict(cli.os.environ, environment):
                with patch.object(cli, "review_comment") as review:
                    self.assertEqual(cli.add_enhancer_review(self.comment, self.rule_diffs), self.comment)
                review.assert_not_called()

    def test_review_is_included_in_preview_and_posted_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_metadata(root)
            for dry_run in (True, False):
                output = StringIO()
                args = SimpleNamespace(
                    dry_run=dry_run, base_sha="base", head_sha="head",
                    pr_number="123", repository="org/repo", ruling_root=None,
                    sources_root="its/sources",
                )
                predictor = Mock(return_value=SimpleNamespace(review=review_data()))
                with (
                    self.subTest(dry_run=dry_run),
                    patch.dict(cli.os.environ, {
                        "DSPY_MODEL": "gpt-4.1", "OPENAI_API_KEY": "test-key",
                        "DSPY_PROVIDER": "direct", "DSPY_API_BASE": "http://localhost:8000/v1",
                    }),
                    patch.object(cli, "parse_args", return_value=args),
                    patch.object(cli, "get_changed_ruling_files", return_value=["ruling.sarif"]),
                    patch.object(cli, "build_rule_diffs", return_value=self.rule_diffs),
                    patch.object(cli.Path, "cwd", return_value=root),
                    patch.object(cli, "post_or_update_comment") as post,
                    patch.object(enhance, "create_predictor", return_value=predictor),
                    redirect_stdout(output),
                ):
                    cli.main()
                comment = output.getvalue() if dry_run else post.call_args.args[2]
                self.assertTrue(comment.startswith("<!-- ruling-diff-comment -->"))
                self.assertIn("## Rule overview", comment)
                self.assertIn("[java:S9191](#ruling-rule-1)", comment)
                self.assertIn(review_data()["summary"], comment)
                self.assertEqual(comment.count("### java:S9191"), 1)
                self.assertEqual(comment.count(self.rule_diffs[0].snippets[0].body), 1)
                self.assertIn("**Confidence:** low", comment)
                self.assertLess(comment.index("## Rule overview"), comment.index("### java:S9191"))
                self.assertLess(len(comment), core.COMMENT_SOFT_LIMIT)
                predictor.assert_called_once()
                example, = predictor.call_args.kwargs["examples"]
                self.assertEqual(example["snippet"], self.rule_diffs[0].snippets[0].body)
                self.assertEqual(example["message"], self.rule_diffs[0].snippets[0].location.message)
                if dry_run:
                    post.assert_not_called()
                else:
                    self.assertEqual(output.getvalue(), "")
                    self.assertEqual(post.call_args.args[:2], ("123", "org/repo"))

    def test_enhancer_failures_preserve_comment_and_do_not_log_secrets(self) -> None:
        for error in (ImportError("secret-key"), ValueError("secret-key"), RuntimeError("secret-key")):
            with (
                self.subTest(error=type(error).__name__),
                patch.dict(cli.os.environ, {"DSPY_MODEL": "gpt-4.1", "OPENAI_API_KEY": "secret-key"}),
                patch.object(cli, "review_comment", side_effect=error),
                self.assertLogs(level="WARNING") as logs,
            ):
                self.assertEqual(cli.add_enhancer_review(self.comment, self.rule_diffs), self.comment)
            self.assertNotIn("secret-key", "\n".join(logs.output))

    def test_oversized_review_is_omitted_without_losing_rule_details(self) -> None:
        comment = core.format_comment(self.rule_diffs, review="x" * core.COMMENT_SOFT_LIMIT)
        self.assertIn("AI review omitted", comment)
        self.assertIn("<summary><b>S9191</b>", comment)
        self.assertLess(len(comment), core.COMMENT_SOFT_LIMIT)


class ReviewedCommentRenderingTests(unittest.TestCase):
    def rule(self, rule_key: str = "S9191", project: str = "sample") -> core.RuleDiff:
        location = core.IssueLocation(12, 3, 13, 8, "Avoid <unsafe> calls.")
        return core.RuleDiff(
            project=project, repo="java", rule_key=rule_key,
            file_diffs=[core.IssueDiff("src/Example.java", [location], [])],
            snippets=[core.Snippet("src/Example.java", location, "added", ">>>     12 | call();")],
            is_new_file=False, is_deleted_file=False,
        )

    def report(self, rules: list[core.RuleDiff], opinion: str = "negative", confidence: str = "low") -> dict:
        change, = parse_comment(core.format_comment(rules))
        return {
            "repository": change.repository, "rule_key": change.rule_key,
            "opinion": opinion, "confidence": confidence, "summary": "Inspect the changed finding.",
            "available_examples": len(change.examples),
            "selected_examples": [{
                **change.examples[0], "classification": "added_false_positive",
                "rationale": "This call may be compliant.",
            }],
        }

    def test_groups_projects_under_one_rule_and_does_not_duplicate_selected_code(self) -> None:
        rules = [self.rule(project="first"), self.rule(project="second")]
        report = self.report(rules)

        comment = format_reviewed_comment(rules, [report])

        self.assertEqual(comment.count("### java:S9191"), 1)
        self.assertIn(
            "### java:S9191 · **Projects:** first, second · **Removed:** 0 · **Added:** 2"
            " · **Automated assessment:** 🔴 negative | **Confidence:** low\n",
            comment,
        )
        self.assertIn("| [java:S9191](#ruling-rule-1) | first, second | 0 / 2 | 🔴 negative | low |", comment)
        self.assertIn('<a name="ruling-rule-1"></a>', comment)
        self.assertIn("#### first", comment)
        self.assertIn("#### second", comment)
        self.assertIn("2 of 2 changed findings shown", comment)
        self.assertNotIn("Automated review received", comment)
        self.assertEqual(comment.count(report["summary"]), 1)
        self.assertEqual(comment.count(report["selected_examples"][0]["rationale"]), 1)
        self.assertEqual(comment.count("```java"), 2)
        self.assertEqual(comment.count(rules[0].snippets[0].body), 2)
        self.assertIn("line 12, column 3 to line 13, end column 8", comment)
        self.assertIn("Avoid &lt;unsafe&gt; calls.", comment)

    def test_sorts_by_assessment_with_stable_rule_order_and_neutral_confidence(self) -> None:
        rules = [self.rule("S200"), self.rule("S100"), self.rule("S300")]
        reports = [
            self.report([rules[0]], "positive", "high"),
            self.report([rules[1]], "negative", "low"),
            self.report([rules[2]], "negative", "high"),
        ]

        comment = format_reviewed_comment(rules, reports)

        self.assertLess(comment.index("### java:S100"), comment.index("### java:S300"))
        self.assertLess(comment.index("### java:S300"), comment.index("### java:S200"))
        self.assertIn("**Automated assessment:** 🔴 negative | **Confidence:** low", comment)
        self.assertIn("**Automated assessment:** 🟢 positive | **Confidence:** high", comment)
        for icon in ("🔴", "🟠", "🟡", "🟢"):
            self.assertNotIn(f"**Confidence:** {icon}", comment)

    def test_all_selected_examples_precede_unselected_examples_across_projects(self) -> None:
        rules = [self.rule(project=project) for project in ("first", "second")]
        for index, rule in enumerate(rules):
            original = rule.snippets[0]
            rule.snippets[:] = [
                core.Snippet(original.file_path, original.location, "added", f"unselected_{index}();"),
                core.Snippet(original.file_path, original.location, "added", f"selected_{index}();"),
            ]
        report = self.report(rules)
        change, = parse_comment(core.format_comment(rules))
        report["selected_examples"] = [
            {**example, "classification": "added_false_positive", "rationale": "A distinct case."}
            for example in change.examples
            if example["snippet"].startswith("selected_")
        ]

        comment = format_reviewed_comment(rules, [report])

        for selected_index in range(2):
            for unselected_index in range(2):
                self.assertLess(
                    comment.index(f"selected_{selected_index}();"),
                    comment.index(f"unselected_{unselected_index}();"),
                )
        for rule in rules:
            for snippet in rule.snippets:
                self.assertEqual(comment.count("\n" + snippet.body + "\n"), 1)

    def test_keeps_unreviewed_rules_and_escapes_project_names_in_the_table(self) -> None:
        rules = [self.rule(), self.rule("S100", "other|<project>")]

        comment = format_reviewed_comment(rules, [self.report([rules[0]])])

        self.assertIn("other&#124;&lt;project&gt; | 0 / 1 | Not reviewed | —", comment)
        self.assertIn("### java:S100", comment)
        self.assertIn("No automated review available for this rule.", comment)
        self.assertEqual(comment.count("```java"), 2)

    def test_large_assessment_preserves_source_examples_within_the_comment_limit(self) -> None:
        rule = self.rule()
        report = self.report([rule])
        report["summary"] = "x" * core.COMMENT_SOFT_LIMIT

        comment = format_reviewed_comment([rule], [report], soft_limit=1500)

        self.assertLessEqual(len(comment), 1500)
        self.assertIn("Automated review omitted", comment)
        self.assertIn(rule.snippets[0].body, comment)
        self.assertEqual(comment.count("<details>"), comment.count("</details>"))

    def test_truncation_keeps_complete_sections_and_only_links_to_present_anchors(self) -> None:
        rules = [self.rule(f"S{number}") for number in range(100, 120)]
        reports = [self.report([rule]) for rule in rules]

        comment = format_reviewed_comment(rules, reports, soft_limit=4000)

        self.assertLessEqual(len(comment), 4000)
        self.assertIn("rule sections omitted", comment)
        self.assertIn("### java:S100", comment)
        self.assertEqual(comment.count("<details>"), comment.count("</details>"))
        for index in range(1, len(rules) + 1):
            if f"](#ruling-rule-{index})" in comment:
                self.assertIn(f'<a name="ruling-rule-{index}"></a>', comment)

    def test_large_overview_is_truncated_without_exceeding_the_budget(self) -> None:
        rules = [self.rule(f"S{number}") for number in range(100, 150)]

        comment = format_reviewed_comment(rules, [], soft_limit=1500)

        self.assertLessEqual(len(comment), 1500)
        self.assertIn("Some rules are omitted from the overview", comment)
        self.assertIn("rule sections omitted", comment)

    def test_no_changes_retains_the_ordinary_empty_comment(self) -> None:
        self.assertEqual(format_reviewed_comment([], []), core.format_comment([]))


class CLITests(unittest.TestCase):
    def test_model_required_unless_preparing_inputs(self) -> None:
        with patch.dict(enhance.os.environ, {}, clear=True):
            with patch.object(sys, "argv", ["enhance.py", "comment.md"]):
                with patch("sys.stderr"), self.assertRaises(SystemExit):
                    enhance.parse_args()

    def test_max_examples_must_be_positive(self) -> None:
        with patch.object(sys, "argv", ["enhance.py", "comment.md", "--prepare-only", "--max-examples", "0"]):
            with patch("sys.stderr"), self.assertRaises(SystemExit):
                enhance.parse_args()

    def test_max_examples_cannot_exceed_three(self) -> None:
        with patch.object(sys, "argv", ["enhance.py", "comment.md", "--prepare-only", "--max-examples", "4"]):
            with patch("sys.stderr"), self.assertRaises(SystemExit):
                enhance.parse_args()

    def test_prepare_only_works_without_site_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_metadata(root)
            comment = root / "comment.md"
            comment.write_text(comment_section(), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-S", "-m", "ruling_diff_enhancer", str(comment),
                 "--repo", str(root), "--prepare-only"],
                cwd=Path(enhance.__file__).resolve().parent.parent,
                capture_output=True, text=True, check=True,
            )
        self.assertEqual(json.loads(result.stdout)[0]["rule_key"], "S9191")
        self.assertEqual(result.stderr, "")

    def test_model_mode_writes_validated_json_without_external_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_metadata(root)
            comment = root / "comment.md"
            comment.write_text(comment_section(), encoding="utf-8")
            output = root / "review.json"
            arguments = [
                "enhance.py", str(comment), "--repo", str(root),
                "--model", "provider/model", "--api-base", "http://localhost:8000/v1",
                "--format", "json", "--output", str(output),
            ]
            predictor = Mock(return_value=SimpleNamespace(review=review_data()))
            with (
                patch.object(sys, "argv", arguments),
                patch.object(enhance, "create_predictor", return_value=predictor),
            ):
                self.assertEqual(enhance.main(), 0)
            report, = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["opinion"], "negative")
            self.assertEqual(report["selected_examples"][0]["example_id"], "E1")

    def test_invalid_input_returns_failure_before_model_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comment = root / "comment.md"
            comment.write_text("No rule sections", encoding="utf-8")
            with (
                patch.object(sys, "argv", ["enhance.py", str(comment), "--repo", str(root), "--model", "provider/model"]),
                patch.object(enhance, "create_predictor") as create_predictor,
                patch("sys.stderr"),
            ):
                self.assertEqual(enhance.main(), 1)
            create_predictor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
