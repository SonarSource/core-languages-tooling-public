import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import resolve

TODAY = date(2026, 10, 7)
SETTINGS = dict(REPOSITORY="owner/repo", BRANCH="main", BUILD_WORKFLOW="build.yml", PUBLICATION_JOB="Publish",
                CURRENT_SHA="current")


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.runs = []
        self.versions = {}
        self.unpublished = set()
        self.expired = set()
        self.downloads = []
        self.checked_jobs = []

    def build(self, number, day=7, sha=None, **artifacts):
        self.runs.append(dict(id=number, head_sha=sha or f"sha{number}",
                              created_at=f"2026-10-{day:02d}T12:00:00Z"))
        for name, version in artifacts.items():
            self.versions[number, name.replace("_", "-")] = version

    def pages(self, repository, path, key, **query):
        self.assertEqual(repository, "owner/repo")
        if path == "actions/workflows/build.yml/runs":
            self.assertEqual(query, {"event": "push", "branch": "main"})
            return iter(self.runs)
        run_id = int(path.split("/")[2])
        if key == "jobs":
            self.checked_jobs.append(run_id)
            return iter([{"name": "Publish", "conclusion": "failure" if run_id in self.unpublished else "success"}])
        self.assertEqual(key, "artifacts")
        return iter({"name": name, "expired": (number, name) in self.expired}
                    for number, name in self.versions if number == run_id)

    def download(self, args, **kwargs):
        self.assertEqual(args[:3], ["gh", "run", "download"])
        run_id = int(args[3])
        name = args[args.index("--name") + 1]
        self.downloads.append((run_id, name))
        version = self.versions[run_id, name]
        if isinstance(version, Exception):
            raise version
        if version is not None:
            Path(args[args.index("--dir") + 1], name + ".txt").write_bytes(version.encode("utf-8"))

    def resolve(self):
        with patch.object(resolve, "pages", side_effect=self.pages), \
                patch.object(resolve.subprocess, "run", side_effect=self.download):
            return resolve.resolve(SETTINGS, today=TODAY)

    def test_prefers_newest_validated_build(self):
        self.build(4, candidate_version="1.0.4")
        self.build(3, pvf_validated="1.0.3")
        self.build(2, pvf_validated="1.0.2")
        self.assertEqual(self.resolve(), ("1.0.3", "sha3"))
        self.assertEqual(self.checked_jobs, [4, 3])

    def test_uses_yesterdays_latest_published_build_and_stops(self):
        self.build(4, candidate_version="1.0.4")
        self.build(3, day=6, candidate_version="1.0.3")
        self.build(2, day=6, pvf_validated="1.0.2")
        self.assertEqual(self.resolve(), ("1.0.3", "sha3"))
        self.assertEqual(self.checked_jobs, [4, 3])

    def test_prefers_validated_artifact_on_boundary_build(self):
        self.build(3, day=6, candidate_version="candidate", pvf_validated="validated")
        self.assertEqual(self.resolve(), ("validated", "sha3"))

    def test_uses_nearest_earlier_build_when_yesterday_has_none(self):
        self.build(4, candidate_version="1.0.4")
        self.build(3, day=3, candidate_version="1.0.3")
        self.build(2, day=2, pvf_validated="1.0.2")
        self.assertEqual(self.resolve(), ("1.0.3", "sha3"))
        self.assertEqual(self.checked_jobs, [4, 3])

    def test_same_day_candidate_is_not_a_fallback(self):
        self.build(4, candidate_version="1.0.4")
        self.assertEqual(self.resolve(), ("", ""))
        self.assertEqual(self.downloads, [])

    def test_excludes_all_rebuilds_of_current_commit(self):
        self.build(5, sha="current", pvf_validated="validated")
        self.build(4, day=6, sha="current", candidate_version="other-build-version")
        self.build(3, day=6, candidate_version="1.0.3")
        self.assertEqual(self.resolve(), ("1.0.3", "sha3"))
        self.assertEqual(self.checked_jobs, [3])

    def test_different_commits_can_have_same_version(self):
        self.build(4, sha="current", pvf_validated="1.0")
        self.build(3, pvf_validated="1.0")
        self.assertEqual(self.resolve(), ("1.0", "sha3"))

    def test_skips_unpublished_builds(self):
        self.build(4, day=6, candidate_version="1.0.4")
        self.unpublished.add(4)
        self.build(3, day=6, candidate_version="1.0.3")
        self.assertEqual(self.resolve(), ("1.0.3", "sha3"))

    def test_skips_expired_and_malformed_recent_markers(self):
        self.build(5, pvf_validated="1.0.5")
        self.expired.add((5, "pvf-validated"))
        self.build(4, pvf_validated="bad version\n")
        self.build(3, pvf_validated="1.0.3\n")
        self.assertEqual(self.resolve(), ("1.0.3", "sha3"))
        self.assertEqual(self.downloads, [(4, "pvf-validated"), (3, "pvf-validated")])

    def test_malformed_boundary_marker_uses_candidate(self):
        self.build(3, day=6, pvf_validated=None, candidate_version="1.0.3")
        self.assertEqual(self.resolve(), ("1.0.3", "sha3"))

    def test_skips_unusable_fallback_builds(self):
        self.build(5, day=6, candidate_version="expired")
        self.expired.add((5, "candidate-version"))
        self.build(4, day=6, candidate_version="")
        self.build(3, day=5, candidate_version=None)
        self.build(2, day=5, candidate_version="1.0.2")
        self.assertEqual(self.resolve(), ("1.0.2", "sha2"))

    def test_calendar_boundary_is_midnight_utc(self):
        self.build(3, day=6, candidate_version="1.0.3")
        self.runs[0]["created_at"] = "2026-10-06T23:59:59Z"
        self.assertEqual(self.resolve(), ("1.0.3", "sha3"))
        self.runs[0]["created_at"] = "2026-10-07T00:00:00Z"
        self.assertEqual(self.resolve(), ("", ""))

    def test_empty_history_returns_empty_outputs(self):
        self.assertEqual(self.resolve(), ("", ""))

    def test_download_failure_is_an_error(self):
        self.build(3, pvf_validated=subprocess.CalledProcessError(1, ["gh"]))
        with self.assertRaises(subprocess.CalledProcessError):
            self.resolve()

    def test_paginates(self):
        responses = [{"jobs": list(range(100))}, {"jobs": [100]}]
        with patch.object(resolve, "api", side_effect=responses) as api:
            self.assertEqual(len(list(resolve.pages("owner/repo", "jobs", "jobs"))), 101)
            self.assertIn("page=2", api.call_args.args[1])

    def test_api_failure_is_an_error(self):
        with patch.object(resolve, "api", side_effect=subprocess.CalledProcessError(1, ["gh"])), \
                patch.dict(resolve.os.environ, SETTINGS):
            self.assertEqual(resolve.main(), 1)

    def test_main_writes_outputs_for_match_and_empty_result(self):
        for result in (("1.0.3", "sha3"), ("", "")):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as directory:
                output = Path(directory, "output")
                with patch.object(resolve, "resolve", return_value=result), \
                        patch.dict(resolve.os.environ, GITHUB_OUTPUT=str(output)):
                    self.assertEqual(resolve.main(), 0)
                self.assertEqual(output.read_text(), f"baseline-version={result[0]}\nbaseline-sha={result[1]}\n")


if __name__ == "__main__":
    unittest.main()
