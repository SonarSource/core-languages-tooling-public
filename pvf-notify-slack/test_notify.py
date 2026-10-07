import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import notify

ENV = dict(REPOSITORY="owner/repo", SERVER_URL="https://github.com", ACTOR="actor", BRANCH="main",
           BASE_SHA="base", HEAD_SHA="1234567890", VALIDATION_RESULT="success", BASELINE_RESULT="success",
           NEW_ISSUES="2", LOST_ISSUES="3", REGRESSED_PROJECTS="project", ERRORED_PROJECTS="",
           DASHBOARD_URL="https://dashboard", RUN_URL="https://run")


def commit(sha, title="title", author="author"):
    return {"sha": sha, "commit": {"message": f"{title}\nbody"}, "author": {"login": author}}


def completed(commits):
    return subprocess.CompletedProcess([], 0, stdout=json.dumps(commits))


class MessageTests(unittest.TestCase):
    def message(self, commits=(), **environment):
        with patch.object(notify.subprocess, "run", return_value=completed(commits)):
            return notify.message({**ENV, **environment})

    def test_success_message_has_findings_actor_and_links(self):
        text = self.message([commit("base")], ERRORED_PROJECTS="other")
        for expected in ("**Performance Validation**", "reported problems", "Regressed: project", "Errored: other",
                         "New/lost issues: 2 / 3", "Triggered by: actor",
                         "[Dashboard](https://dashboard) · [Run logs](https://run)"):
            self.assertIn(expected, text)

    def test_failed_validation_excludes_counts(self):
        text = self.message(VALIDATION_RESULT="failure")
        self.assertIn("The validation job failed before completing.", text)
        self.assertIn("Regressed: project", text)
        self.assertNotIn("New/lost issues", text)

    def test_skipped_validation_explains_baseline_outcome(self):
        cases = (({"BASE_SHA": ""}, "No baseline version was found"),
                 ({"BASELINE_RESULT": "failure"}, "Baseline resolution: failure."))
        for environment, explanation in cases:
            with self.subTest(environment=environment):
                text = self.message(VALIDATION_RESULT="skipped", **environment)
                self.assertIn("was skipped.", text)
                self.assertIn(explanation, text)
                self.assertNotIn("New/lost issues", text)
                self.assertNotIn("Regressed:", text)

    def test_commits_stop_at_baseline_and_are_newest_first(self):
        text = self.message([commit("22222222aa", "newer"), commit("11111111aa", "older"), commit("base"),
                             commit("00000000aa", "before baseline")])
        self.assertLess(text.index("newer"), text.index("older"))
        self.assertNotIn("before baseline", text)
        self.assertIn("22222222 newer (@author)", text)
        self.assertNotIn("and more", text)

    def test_unreached_baseline_is_bounded_and_links_full_range(self):
        text = self.message([commit(f"{i:040x}", f"Commit {i}") for i in range(21)])
        self.assertIn("Commit 19", text)
        self.assertNotIn("Commit 20", text)
        self.assertIn("[full range](https://github.com/owner/repo/compare/base...1234567890)", text)

    def test_missing_author_and_long_title(self):
        item = commit("11111111aa", "x" * 300)
        item["author"] = None
        text = self.message([item, commit("base")])
        self.assertIn(f"{'x' * 200} (@unknown)", text)
        self.assertNotIn("x" * 201, text)

    def test_missing_baseline_needs_no_lookup(self):
        with patch.object(notify.subprocess, "run") as run:
            text = notify.message({**ENV, "BASE_SHA": ""})
        run.assert_not_called()
        self.assertNotIn("Commits:", text)
        self.assertIn("Triggered by: actor", text)

    def test_lookup_failure_still_builds_alert(self):
        with patch.object(notify.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["gh"])):
            text = notify.message(ENV)
        self.assertIn("Commit range unavailable.", text)
        self.assertIn("Run logs", text)

    def test_repository_content_cannot_create_mentions_or_formatting(self):
        text = self.message([commit("11111111aa", "<!channel> &lt;!here&gt; *bold* [link](url)"), commit("base")],
                            REGRESSED_PROJECTS="<!channel> *bold*", DASHBOARD_URL="https://host/|oops>\n")
        self.assertNotIn("<!channel>", text)
        self.assertNotIn("&lt;!here&gt;", text)
        self.assertIn("‹\\!channel› ∗bold∗", text)
        self.assertIn("\\[link\\]\\(url\\)", text)
        self.assertIn("https://host/%7Coops%3E%0A", text)

    def test_empty_dashboard_omits_dashboard_link(self):
        self.assertNotIn("[Dashboard]", self.message(DASHBOARD_URL=""))

    def test_rejects_unknown_result(self):
        with self.assertRaises(ValueError):
            notify.message({**ENV, "VALIDATION_RESULT": "unknown"})


class MainTests(unittest.TestCase):
    def run_main(self, **environment):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "outputs")
            with patch.object(notify.subprocess, "run", return_value=completed([])), \
                    patch.dict(notify.os.environ, {**ENV, **environment, "GITHUB_OUTPUT": str(output)}):
                code = notify.main()
            return code, output.read_text() if output.exists() else ""

    def test_multiline_content_cannot_inject_outputs(self):
        code, written = self.run_main(REGRESSED_PROJECTS="project\nEOF\nother=bad\nmarkdown<<EOF")
        self.assertEqual(code, 0)
        first, *_, last = written.splitlines()
        self.assertTrue(first.startswith("markdown<<pvf_"))
        self.assertEqual(last, first.split("<<", 1)[1])
        self.assertEqual(written.count(last), 2)

    def test_unknown_result_fails_without_output(self):
        code, written = self.run_main(VALIDATION_RESULT="unknown")
        self.assertEqual(code, 1)
        self.assertEqual(written, "")


if __name__ == "__main__":
    unittest.main()
