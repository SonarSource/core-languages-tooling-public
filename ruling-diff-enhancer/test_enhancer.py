from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import dspy
from dspy.utils import DummyLM

import enhance
from ruling_diff_inputs import find_configurations, parse_comment, prepare_inputs
from ruling_diff_predictor import Review, ReviewRulingChange, review_changes, validate_review


def comment_section(
    rule_key: str = "S9191", project: str = "sample", kind: str = "Added",
    location: str = "line 12", snippet: str = ">>>     12 | call();",
) -> str:
    return (
        f"<details>\n<summary><b>{rule_key}</b> (<code>java</code>) on <b>{project}</b>"
        " - 1 issues removed, 1 issues added</summary>\n\n"
        f"**{kind}** `src/Example.java` ({location})\n```java\n{snippet}\n```\n\n</details>"
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

    def test_rule_headers_inside_code_are_not_parsed(self) -> None:
        injected = '<summary><b>S100</b> (<code>java</code>) on <b>other</b> - 0 issues removed, 1 issues added</summary>'
        changes = parse_comment(comment_section(snippet=injected))
        self.assertEqual([change.rule_key for change in changes], ["S9191"])
        self.assertEqual(changes[0].examples[0]["snippet"], injected)

    def test_handles_rules_without_snippets(self) -> None:
        comment = comment_section().split("\n\n**Added**")[0] + "\nNo source snippets available for this rule.\n</details>"
        change, = parse_comment(comment)
        self.assertEqual(change.examples, [])

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
        with self.assertRaisesRegex(ValueError, "Ambiguous metadata"):
            prepare_inputs(comment_section(), self.root)
        selected = prepare_inputs(comment_section(), self.root, Path("private/sonarpedia.json"))
        self.assertEqual(selected[0]["metadata"]["sonarpedia_path"], "private/sonarpedia.json")

    def test_missing_config_is_actionable(self) -> None:
        with self.assertRaisesRegex(ValueError, "No sonarpedia.json"):
            prepare_inputs(comment_section(), self.root)

    def test_missing_pair_or_unknown_rule_fails(self) -> None:
        write_metadata(self.root)
        for rule_key in ("S100", "S9191"):
            with self.subTest(rule_key=rule_key):
                if rule_key == "S9191":
                    (self.root / "rules/S9191.html").unlink()
                with self.assertRaisesRegex(ValueError, "No HTML/JSON metadata pair"):
                    prepare_inputs(comment_section(rule_key=rule_key), self.root)

    def test_malformed_config_and_metadata_fail(self) -> None:
        config = write_metadata(self.root)
        for contents in ("{", "[]", "{}", '{"rules-metadata-path": 1}'):
            with self.subTest(contents=contents):
                config.write_text(contents, encoding="utf-8")
                with self.assertRaises(ValueError):
                    prepare_inputs(comment_section(), self.root)
        write_metadata(self.root)
        for contents in ("{", "[]", '{"sqKey": "S100"}'):
            with self.subTest(contents=contents):
                (self.root / "rules/S9191.json").write_text(contents, encoding="utf-8")
                with self.assertRaises(ValueError):
                    prepare_inputs(comment_section(), self.root)

    def test_metadata_path_cannot_escape_repository(self) -> None:
        config = write_metadata(self.root)
        config.write_text('{"rules-metadata-path": "../outside"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "escapes repository"):
            prepare_inputs(comment_section(), self.root)

    def test_explicit_configuration_must_be_inside_repository(self) -> None:
        with self.assertRaisesRegex(ValueError, "inside"):
            find_configurations(self.root, self.root.parent / "sonarpedia.json")

    def test_discovered_configuration_cannot_symlink_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            target = write_metadata(Path(outside))
            (self.root / "sonarpedia.json").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "configuration escapes repository"):
                prepare_inputs(comment_section(), self.root)

    def test_metadata_file_cannot_symlink_outside_repository(self) -> None:
        write_metadata(self.root)
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "rule.html"
            target.write_text("External data", encoding="utf-8")
            html_path = self.root / "rules/S9191.html"
            html_path.unlink()
            html_path.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "Rule metadata escapes repository"):
                prepare_inputs(comment_section(), self.root)


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
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_review(Review.model_validate(data), self.examples, 3)
        with self.assertRaisesRegex(ValueError, "max_examples"):
            validate_review(Review.model_validate(review_data()), self.examples, 0)

    def test_representative_cannot_be_mixed_with_bad_cases(self) -> None:
        data = review_data("representative")
        data["selected_examples"].extend(review_data(example_id="E2")["selected_examples"])
        examples = self.examples + [{**self.examples[0], "id": "E2"}]
        with self.assertRaisesRegex(ValueError, "Representative fallback"):
            validate_review(Review.model_validate(data), examples, 3)

    def test_no_examples_requires_low_confidence_and_empty_selection(self) -> None:
        data = review_data()
        data["selected_examples"] = []
        validate_review(Review.model_validate(data), [], 3)
        data["confidence"] = "high"
        with self.assertRaisesRegex(ValueError, "confidence must be low"):
            validate_review(Review.model_validate(data), [], 3)

    def test_invalid_opinion_confidence_or_empty_explanation_is_rejected(self) -> None:
        for field, value in (("opinion", "great"), ("confidence", 0.8), ("summary", "  ")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                Review.model_validate({**review_data(), field: value})

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
        self.assertIn("**Opinion:** negative | **Confidence:** low", rendered)
        self.assertIn("added false positive", rendered)

    def test_typed_dspy_predictor_with_dummy_language_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_metadata(root)
            inputs = prepare_inputs(comment_section(), root)
        lm = DummyLM([{"review": json.dumps(review_data("representative"))}])
        with dspy.context(lm=lm):
            report, = review_changes(inputs, dspy.Predict(ReviewRulingChange))
        self.assertEqual(report["selected_examples"][0]["classification"], "representative")


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

    def test_prepare_only_works_without_site_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_metadata(root)
            comment = root / "comment.md"
            comment.write_text(comment_section(), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-S", str(Path(enhance.__file__).resolve()), str(comment),
                 "--repo", str(root), "--prepare-only"],
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
                patch.object(dspy, "configure_cache") as configure_cache,
                patch.object(dspy, "LM") as language_model,
                patch.object(dspy, "context"),
                patch.object(dspy, "Predict", return_value=predictor),
            ):
                self.assertEqual(enhance.main(), 0)
            language_model.assert_called_once_with(
                "provider/model", cache=False, api_base="http://localhost:8000/v1"
            )
            configure_cache.assert_called_once_with(enable_disk_cache=False, enable_memory_cache=False)
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
                patch.object(dspy, "LM") as language_model,
                patch("sys.stderr"),
            ):
                self.assertEqual(enhance.main(), 1)
            language_model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
