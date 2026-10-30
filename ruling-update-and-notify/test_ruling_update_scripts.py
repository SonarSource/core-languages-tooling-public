from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cleanup_fix_pr
import create_fix_pr
import find_ruling_directory
import sync_ruling_artifacts


class SyncArtifactsTests(unittest.TestCase):
    def test_copies_merged_artifacts_and_removes_temporary_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            destination = root / "ruling"
            (artifacts / "expected/project").mkdir(parents=True)
            (destination / "expected/project").mkdir(parents=True)
            (artifacts / "expected/project" / "new.json").write_text("new")
            (destination / "expected/project" / "existing.json").write_text("existing")

            sync_ruling_artifacts.sync_artifacts(destination, artifacts, "success")

            self.assertEqual((destination / "expected/project" / "new.json").read_text(), "new")
            self.assertEqual((destination / "expected/project" / "existing.json").read_text(), "existing")
            self.assertFalse(artifacts.exists())

    def test_syncs_python_enterprise_results_with_or_without_expected_wrapper(self) -> None:
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                resources = Path("private/its-enterprise/ruling/src/test/resources")
                expected = root / resources / "expected"
                (expected / "project").mkdir(parents=True)
                (expected / "project/python-S100.json").write_text("old")
                (expected / "project/python-S200.json").write_text("unchanged")
                artifacts = root / "artifacts"
                artifact_root = artifacts / "expected" if wrapped else artifacts
                (artifact_root / "project").mkdir(parents=True)
                (artifact_root / "project/python-S100.json").write_text("new")
                (artifact_root / "project/python-S300.json").write_text("added")

                ruling_root, sources_root = find_ruling_directory.find_ruling_paths(root)
                self.assertEqual(ruling_root, resources)
                self.assertEqual(sources_root, Path("private/its-enterprise/sources_ruling"))
                sync_ruling_artifacts.sync_artifacts(root / ruling_root, artifacts, "success")

                self.assertEqual((expected / "project/python-S100.json").read_text(), "new")
                self.assertEqual((expected / "project/python-S200.json").read_text(), "unchanged")
                self.assertEqual((expected / "project/python-S300.json").read_text(), "added")
                self.assertFalse((root / resources / "project").exists())
                self.assertFalse((expected / "expected").exists())
                self.assertFalse(artifacts.exists())

    def test_failure_annotation_stays_inside_log_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(sync_ruling_artifacts.os.environ, {
                "RULING_ROOT": directory, "DOWNLOAD_OUTCOME": "failure",
            }), patch.object(sync_ruling_artifacts, "ARTIFACT_DIRECTORY", Path(directory) / "missing"):
                log = StringIO()
                with redirect_stdout(log):
                    self.assertEqual(sync_ruling_artifacts.main(), 1)
                lines = log.getvalue().splitlines()
                self.assertEqual(lines[0], "::group::Syncing ruling artifacts")
                self.assertTrue(any(line.startswith("::error::") for line in lines[1:-1]))
                self.assertEqual(lines[-1], "::endgroup::")

    def test_rejects_missing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "No artifacts were downloaded"):
                sync_ruling_artifacts.sync_artifacts(root, root / "missing", "success")
            with self.assertRaisesRegex(RuntimeError, "Failed to download artifacts"):
                sync_ruling_artifacts.sync_artifacts(root, root / "missing", "failure")


class FixPullRequestTests(unittest.TestCase):
    @patch.object(create_fix_pr, "create_fix_pr", return_value=("https://example.test/1", "b" * 40, "a" * 40))
    def test_main_publishes_fix_base_and_head(self, create) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output"
            with patch.dict(create_fix_pr.os.environ, {
                "GITHUB_OUTPUT": str(output_path),
            }):
                self.assertEqual(create_fix_pr.main([
                    "--target-ref", "feature", "--ruling-root", "its/ruling", "--pr-number", "1",
                ]), 0)
            self.assertEqual(output_path.read_text(),
                f"fix-pr-url=https://example.test/1\nfix-base-sha={'b' * 40}\nfix-sha={'a' * 40}\n")
            create.assert_called_once_with("feature", "its/ruling", "1", "", dry_run=False)

    @patch.object(create_fix_pr, "create_fix_pr", return_value=("", "b" * 40, "a" * 40))
    def test_main_dry_run_needs_no_github_environment(self, create) -> None:
        with patch.dict(create_fix_pr.os.environ, {}, clear=True):
            self.assertEqual(create_fix_pr.main([
                "--dry-run", "--target-ref", "feature", "--ruling-root", "its/ruling",
                "--sources-root", "its/sources",
            ]), 0)
        create.assert_called_once_with("feature", "its/ruling", "", "its/sources", dry_run=True)

    @patch.object(create_fix_pr, "create_fix_pr", return_value=("", "b" * 40, "a" * 40))
    @patch.object(create_fix_pr, "find_default_target_ref", return_value="master")
    def test_main_dry_run_detects_ruling_layout(self, default_target, create) -> None:
        for ruling_root, sources_root in find_ruling_directory.RULING_LAYOUTS:
            with self.subTest(ruling_root=ruling_root), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / ruling_root / "expected").mkdir(parents=True)
                with patch.dict(create_fix_pr.os.environ, {}, clear=True), \
                        patch.object(create_fix_pr.Path, "cwd", return_value=root):
                    self.assertEqual(create_fix_pr.main(["--dry-run"]), 0)
                create.assert_called_with("master", str(ruling_root), "", str(sources_root), dry_run=True)
        self.assertEqual(default_target.call_count, len(find_ruling_directory.RULING_LAYOUTS))

    @patch.object(create_fix_pr, "create_fix_pr", return_value=("", "b" * 40, "a" * 40))
    @patch.object(create_fix_pr, "find_default_target_ref", return_value="main")
    def test_main_dry_run_preserves_sources_override(self, default_target, create) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / find_ruling_directory.PUBLIC_ROOT / "expected").mkdir(parents=True)
            with patch.dict(create_fix_pr.os.environ, {}, clear=True), \
                    patch.object(create_fix_pr.Path, "cwd", return_value=root):
                self.assertEqual(create_fix_pr.main(["--dry-run", "--sources-root", "custom/sources"]), 0)
        create.assert_called_once_with(
            "main", str(find_ruling_directory.PUBLIC_ROOT), "", "custom/sources", dry_run=True
        )
        default_target.assert_called_once_with()

    @patch.object(create_fix_pr, "create_fix_pr", return_value=("", "b" * 40, "a" * 40))
    @patch.object(create_fix_pr, "find_ruling_paths")
    @patch.object(create_fix_pr, "find_default_target_ref")
    def test_main_explicit_options_bypass_detection(self, default_target, paths, create) -> None:
        with patch.dict(create_fix_pr.os.environ, {}, clear=True):
            self.assertEqual(create_fix_pr.main([
                "--dry-run", "--target-ref", "feature", "--ruling-root", "custom/ruling",
                "--sources-root", "custom/sources", "--pr-number", "123",
            ]), 0)
        paths.assert_not_called()
        default_target.assert_not_called()
        create.assert_called_once_with("feature", "custom/ruling", "123", "custom/sources", dry_run=True)

    @patch.object(create_fix_pr, "create_fix_pr", return_value=("", "b" * 40, "a" * 40))
    @patch.object(create_fix_pr, "find_ruling_paths", return_value=(Path("detected/ruling"), Path("detected/sources")))
    @patch.object(create_fix_pr, "find_default_target_ref", return_value="master")
    def test_main_ignores_legacy_configuration_environment(self, default_target, paths, create) -> None:
        with patch.dict(create_fix_pr.os.environ, {
            "TARGET_REF": "old-target", "RULING_ROOT": "old/ruling",
            "SOURCES_ROOT": "old/sources", "PR_NUMBER": "999",
        }, clear=True):
            self.assertEqual(create_fix_pr.main(["--dry-run"]), 0)
        paths.assert_called_once_with(Path.cwd())
        default_target.assert_called_once_with()
        create.assert_called_once_with("master", "detected/ruling", "", "detected/sources", dry_run=True)

    @patch.object(create_fix_pr, "create_fix_pr")
    @patch.object(create_fix_pr, "find_ruling_paths", side_effect=ValueError("No expected ruling directory found"))
    def test_main_reports_ruling_detection_errors(self, paths, create) -> None:
        with patch.dict(create_fix_pr.os.environ, {}, clear=True), \
                patch.object(create_fix_pr.sys, "stderr", new_callable=StringIO) as errors:
            self.assertEqual(create_fix_pr.main(["--dry-run"]), 1)
        self.assertIn("No expected ruling directory found", errors.getvalue())
        create.assert_not_called()

    def test_default_target_prefers_master_then_main(self) -> None:
        for branches, expected in ((["main", "master"], "master"), (["master"], "master"), (["main"], "main")):
            with self.subTest(branches=branches):
                remote = SimpleNamespace(returncode=0, stdout="\n".join(
                    f"{'a' * 40}\trefs/heads/{branch}" for branch in branches
                ))
                with patch.object(create_fix_pr.subprocess, "run", return_value=remote) as process:
                    self.assertEqual(create_fix_pr.find_default_target_ref(), expected)
                self.assertEqual(process.call_args.args[0], (
                    "git", "ls-remote", "--exit-code", "--heads", "origin",
                    "refs/heads/master", "refs/heads/main",
                ))

    def test_default_target_reports_missing_branches_and_remote_errors(self) -> None:
        for returncode, message in ((2, "Neither master nor main"), (128, "Could not inspect")):
            with self.subTest(returncode=returncode), \
                    patch.object(create_fix_pr.subprocess, "run", return_value=SimpleNamespace(
                        returncode=returncode, stdout="",
                    )), self.assertRaisesRegex(RuntimeError, message):
                create_fix_pr.find_default_target_ref()

    @patch.object(create_fix_pr, "create_fix_pr", return_value=("", "b" * 40, "a" * 40))
    def test_main_dry_run_does_not_write_github_outputs(self, create) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output"
            output_path.write_text("existing outputs\n")
            with patch.dict(create_fix_pr.os.environ, {
                "GITHUB_OUTPUT": str(output_path),
            }):
                self.assertEqual(create_fix_pr.main([
                    "--dry-run", "--target-ref", "feature", "--ruling-root", "its/ruling",
                ]), 0)
            self.assertEqual(output_path.read_text(), "existing outputs\n")

    def test_dry_run_never_pushes_or_calls_github(self) -> None:
        for branch_exists in (False, True):
            for changed in (False, True):
                with self.subTest(branch_exists=branch_exists, changed=changed):
                    remote = SimpleNamespace(
                        returncode=0 if branch_exists else 2,
                        stdout=f"{'c' * 40}\trefs/heads/fix/update-ruling-for-feature\n"
                        if branch_exists else "",
                    )
                    head_sha = "a" * 40 if changed else "b" * 40
                    with patch.object(create_fix_pr.subprocess, "run", return_value=remote), \
                            patch.object(create_fix_pr, "run") as run, \
                            patch.object(create_fix_pr, "output", side_effect=["b" * 40, head_sha]) as get_output, \
                            patch.object(create_fix_pr, "transfer_ruling_changes"), \
                            patch.object(create_fix_pr, "has_staged_changes", return_value=changed), \
                            patch.object(create_fix_pr, "generate_ruling_diff", return_value="## Ruling Diff Summary") as diff, \
                            redirect_stdout(StringIO()) as preview:
                        result = create_fix_pr.create_fix_pr(
                            "feature", "its/ruling", "123", "its/sources", dry_run=True
                        )
                    self.assertEqual(result, ("", "b" * 40, head_sha))
                    self.assertFalse(any("push" in call.args or call.args[0] == "gh"
                        for call in run.call_args_list))
                    self.assertFalse(any(call.args[0] == "gh" for call in get_output.call_args_list))
                    self.assertIn("Dry run: skipping push", preview.getvalue())
                    if changed:
                        diff.assert_called_once_with("its/ruling", "its/sources", "b" * 40, head_sha)
                        self.assertIn("Title: Update ruling results for PR #123", preview.getvalue())
                        self.assertIn("Base: feature\nHead: fix/update-ruling-for-feature", preview.getvalue())
                        self.assertIn("Auto-generated ruling update for PR #123.", preview.getvalue())
                        self.assertIn("## Ruling Diff Summary", preview.getvalue())
                    else:
                        diff.assert_not_called()
                        self.assertIn("No ruling changes to commit.", preview.getvalue())

    @patch.object(create_fix_pr.subprocess, "run")
    def test_output_does_not_capture_stderr(self, process) -> None:
        process.return_value.stdout = "result\n"
        self.assertEqual(create_fix_pr.output("gh", "pr", "create"), "result")
        self.assertEqual(process.call_args.kwargs, {
            "check": True, "stdout": create_fix_pr.subprocess.PIPE, "text": True,
        })

    @patch.object(create_fix_pr, "run")
    @patch.object(create_fix_pr, "generate_ruling_diff", return_value="## Ruling Diff Summary")
    @patch.object(create_fix_pr, "has_staged_changes", return_value=True)
    @patch.object(create_fix_pr, "transfer_ruling_changes")
    @patch.object(create_fix_pr.subprocess, "run", return_value=SimpleNamespace(returncode=2, stdout=""))
    def test_new_branch_creates_a_pull_request(self, remote, transfer, staged, diff, run) -> None:
        head_shas = iter(("b" * 40, "a" * 40))

        def command_output(*command: str, **kwargs) -> str:
            if command[:3] == ("gh", "pr", "create"):
                return "https://github.com/org/repo/pull/1"
            if "rev-parse" in command:
                return next(head_shas)
            return ""

        with patch.object(create_fix_pr, "output", side_effect=command_output) as get_output:
            url, base_sha, sha = create_fix_pr.create_fix_pr(
                "feature", "its/ruling", "123", "its/sources"
            )

        self.assertEqual(url, "https://github.com/org/repo/pull/1")
        self.assertEqual(base_sha, "b" * 40)
        self.assertEqual(sha, "a" * 40)
        self.assertTrue(any(
            call.args[0] == "git" and call.args[3:] == (
                "push", "origin", "HEAD:refs/heads/fix/update-ruling-for-feature",
            ) for call in run.call_args_list
        ))
        run.assert_any_call(
            "gh", "pr", "comment", "123", "--body",
            "⚖️ Ruling update ready for review: https://github.com/org/repo/pull/1",
        )
        self.assertFalse(any("stash" in call.args or "switch" in call.args for call in run.call_args_list))
        diff.assert_called_once_with(
            "its/ruling", "its/sources", "b" * 40, "a" * 40
        )
        get_output.assert_any_call(
            "gh", "pr", "create", "--title", "Update ruling results for PR #123",
            "--base", "feature", "--head", "fix/update-ruling-for-feature", "--body",
            "Auto-generated ruling update for PR #123.\n\n## Ruling Diff Summary\n\n"
            + create_fix_pr.GENERATED_MARKER,
        )
        remote.assert_called_once()
        transfer.assert_called_once()
        staged.assert_called_once()

    @patch.object(create_fix_pr, "run")
    @patch.object(create_fix_pr, "has_staged_changes", return_value=False)
    @patch.object(create_fix_pr, "transfer_ruling_changes")
    @patch.object(create_fix_pr.subprocess, "run", return_value=SimpleNamespace(
        returncode=0, stdout=f"{'c' * 40}\trefs/heads/fix/update-ruling-for-feature\n",
    ))
    def test_existing_branch_reuses_its_pull_request(self, remote, transfer, staged, run) -> None:
        def command_output(*command: str, **kwargs) -> str:
            if command[:3] == ("gh", "pr", "list"):
                return "https://github.com/org/repo/pull/1"
            if "rev-parse" in command:
                return "b" * 40
            return ""

        with patch.object(create_fix_pr, "output", side_effect=command_output) as get_output:
            url, base_sha, sha = create_fix_pr.create_fix_pr("feature", "its/ruling", "")

        self.assertEqual(url, "https://github.com/org/repo/pull/1")
        self.assertEqual(base_sha, "b" * 40)
        self.assertEqual(sha, "b" * 40)
        self.assertFalse(any(call.args[:3] == ("gh", "pr", "create") for call in get_output.call_args_list))
        self.assertFalse(any("push" in call.args for call in run.call_args_list))
        remote.assert_called_once()
        transfer.assert_called_once()
        staged.assert_called_once()

    @patch.object(create_fix_pr, "run")
    @patch.object(create_fix_pr, "generate_ruling_diff", return_value="## Ruling Diff Summary")
    @patch.object(create_fix_pr, "has_staged_changes", return_value=True)
    @patch.object(create_fix_pr, "transfer_ruling_changes")
    @patch.object(create_fix_pr.subprocess, "run", return_value=SimpleNamespace(
        returncode=0, stdout=f"{'c' * 40}\trefs/heads/fix/update-ruling-for-feature\n",
    ))
    def test_existing_pull_request_description_is_updated(self, remote, transfer, staged, diff, run) -> None:
        def command_output(*command: str, **kwargs) -> str:
            if command[:3] == ("gh", "pr", "list"):
                return "https://github.com/org/repo/pull/1"
            return ""

        with patch.object(create_fix_pr, "output", side_effect=command_output) as get_output:
            create_fix_pr.create_fix_pr("feature", "its/ruling", "")

        run.assert_any_call(
            "gh", "pr", "edit", "https://github.com/org/repo/pull/1", "--body",
            "Auto-generated ruling update for feature.\n\n## Ruling Diff Summary\n\n"
            + create_fix_pr.GENERATED_MARKER,
        )
        self.assertFalse(any(call.args[:3] == ("gh", "pr", "create") for call in get_output.call_args_list))

    def test_pr_body_without_ruling_diff(self) -> None:
        self.assertEqual(create_fix_pr.pr_body("feature", ""),
            f"Auto-generated ruling update for feature.\n\n{create_fix_pr.GENERATED_MARKER}")

    @patch.object(create_fix_pr, "generate_comment", return_value="## Ruling Diff Summary\n")
    def test_generate_ruling_diff_calls_python_directly(self, generate) -> None:
        with patch.object(create_fix_pr.subprocess, "run") as process:
            diff = create_fix_pr.generate_ruling_diff("its/ruling", "its/sources", "b", "a")
        self.assertEqual(diff, "## Ruling Diff Summary")
        generate.assert_called_once_with("b", "a", "its/ruling/expected", "its/sources")
        process.assert_not_called()

    @patch.object(create_fix_pr, "generate_comment", return_value=None)
    def test_generate_ruling_diff_without_changes_returns_empty(self, generate) -> None:
        self.assertEqual(create_fix_pr.generate_ruling_diff("its/ruling", "", "b", "a"), "")
        generate.assert_called_once_with(
            "b", "a", "its/ruling/expected", "private/its-enterprise/sources_ruling"
        )

    def test_generate_ruling_diff_failure_returns_empty(self) -> None:
        with patch.object(create_fix_pr, "generate_comment", side_effect=RuntimeError("git failed")), \
                redirect_stdout(StringIO()) as warning:
            self.assertEqual(create_fix_pr.generate_ruling_diff("its/ruling", "", "b", "a"), "")
        self.assertIn("::warning::Could not generate the ruling diff", warning.getvalue())

    def test_dirty_checkout_does_not_block_clean_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            origin = root / "origin.git"
            source = root / "source"
            target = root / "target"
            ruling_root = Path("its/ruling/src/test/resources")
            project = ruling_root / "expected/project"

            def git(*arguments: str, cwd: Path) -> str:
                return subprocess.run(
                    ("git", *arguments), cwd=cwd, check=True, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True,
                ).stdout.strip()

            git("init", "--bare", str(origin), cwd=root)
            git("init", "-b", "feature", str(source), cwd=root)
            git("config", "user.name", "Test", cwd=source)
            git("config", "user.email", "test@example.com", cwd=source)
            (source / project).mkdir(parents=True)
            (source / "pom.xml").write_text("original")
            (source / project / "report.json").write_text("old")
            (source / project / "deleted.json").write_text("old")
            git("add", ".", cwd=source)
            git("commit", "-m", "Initial files", cwd=source)
            git("remote", "add", "origin", str(origin), cwd=source)
            git("push", "-u", "origin", "feature", cwd=source)

            git("clone", "--branch", "feature", str(origin), str(target), cwd=root)
            git("config", "user.name", "Test", cwd=target)
            git("config", "user.email", "test@example.com", cwd=target)
            (target / "pom.xml").write_text("target branch version")
            git("add", "pom.xml", cwd=target)
            git("commit", "-m", "Move target branch", cwd=target)
            git("push", "origin", "feature", cwd=target)

            (source / "pom.xml").write_text("dirty local version")
            (source / project / "report.json").write_text("new")
            (source / project / "deleted.json").unlink()
            (source / project / "added.json").write_text("added")

            original_output = create_fix_pr.output
            def fake_output(*command: str, **kwargs) -> str:
                if command[:3] in (("gh", "pr", "create"), ("gh", "pr", "list")):
                    return "https://example.test/fix"
                return original_output(*command, **kwargs)

            original_run = create_fix_pr.run
            def fake_run(*command: str) -> None:
                if command[0] != "gh":
                    original_run(*command)

            previous_directory = Path.cwd()
            try:
                os.chdir(source)
                refs_before = git("--git-dir", str(origin), "show-ref", cwd=root)
                status_before = git("status", "--porcelain", cwd=source)
                original_process_run = subprocess.run

                def dry_run_command(command, **kwargs):
                    self.assertNotEqual(command[0], "gh")
                    self.assertNotIn("push", command)
                    return original_process_run(command, **kwargs)

                with patch.object(create_fix_pr.subprocess, "run", side_effect=dry_run_command), \
                        redirect_stdout(StringIO()) as preview:
                    url, base, head = create_fix_pr.create_fix_pr(
                        "feature", str(ruling_root), "123", dry_run=True
                    )
                self.assertEqual(url, "")
                self.assertEqual(base, git("rev-parse", "HEAD", cwd=target))
                self.assertNotEqual(head, base)
                self.assertEqual(git("--git-dir", str(origin), "show-ref", cwd=root), refs_before)
                self.assertEqual(git("status", "--porcelain", cwd=source), status_before)
                self.assertEqual(git("worktree", "list", "--porcelain", cwd=source).count("worktree "), 1)
                self.assertIn("Title: Update ruling results for PR #123", preview.getvalue())
                with patch.object(create_fix_pr, "output", side_effect=fake_output), \
                        patch.object(create_fix_pr, "run", side_effect=fake_run):
                    url, base, head = create_fix_pr.create_fix_pr("feature", str(ruling_root), "")
                    self.assertEqual(url, "https://example.test/fix")
                    self.assertEqual(base, git("rev-parse", "HEAD", cwd=target))
                    self.assertEqual(head, git("--git-dir", str(origin), "rev-parse",
                        "refs/heads/fix/update-ruling-for-feature", cwd=root))
                    (source / project / "report.json").write_text("newer")
                    _, _, updated_head = create_fix_pr.create_fix_pr("feature", str(ruling_root), "")
                    self.assertNotEqual(updated_head, head)
                    (target / project / "report.json").write_text("conflicting target version")
                    git("add", str(project / "report.json"), cwd=target)
                    git("commit", "-m", "Change target ruling", cwd=target)
                    git("push", "origin", "feature", cwd=target)
                    with self.assertRaises(subprocess.CalledProcessError):
                        create_fix_pr.create_fix_pr("feature", str(ruling_root), "")
            finally:
                os.chdir(previous_directory)

            fix_ref = "refs/heads/fix/update-ruling-for-feature"
            self.assertEqual(git("--git-dir", str(origin), "show", f"{fix_ref}:pom.xml", cwd=root),
                "target branch version")
            self.assertEqual(git("--git-dir", str(origin), "show",
                f"{fix_ref}:{project}/report.json", cwd=root), "newer")
            self.assertEqual(git("--git-dir", str(origin), "show",
                f"{fix_ref}:{project}/added.json", cwd=root), "added")
            self.assertNotIn(str(project / "deleted.json"),
                git("--git-dir", str(origin), "ls-tree", "-r", "--name-only", fix_ref, cwd=root))
            self.assertEqual((source / "pom.xml").read_text(), "dirty local version")
            self.assertEqual((source / project / "added.json").read_text(), "added")
            self.assertEqual(git("worktree", "list", "--porcelain", cwd=source).count("worktree "), 1)


class FindRulingDirectoryTests(unittest.TestCase):
    def test_selects_public_or_private_expected_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / find_ruling_directory.PUBLIC_ROOT / "expected").mkdir(parents=True)
            self.assertEqual(find_ruling_directory.find_ruling_paths(root), (
                find_ruling_directory.PUBLIC_ROOT, Path("its/sources"),
            ))

            (root / find_ruling_directory.PUBLIC_ROOT / "expected").rmdir()
            (root / find_ruling_directory.PRIVATE_ROOT / "expected").mkdir(parents=True)
            self.assertEqual(find_ruling_directory.find_ruling_paths(root), (
                find_ruling_directory.PRIVATE_ROOT, Path("private/its/sources"),
            ))

    def test_reports_missing_and_ambiguous_expected_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public_expected = root / find_ruling_directory.PUBLIC_ROOT / "expected"
            private_expected = root / find_ruling_directory.PRIVATE_ROOT / "expected"
            with self.assertRaisesRegex(ValueError, "No expected ruling directory found") as missing:
                find_ruling_directory.find_ruling_paths(root)
            self.assertIn(str(find_ruling_directory.PUBLIC_ROOT / "expected"), str(missing.exception))
            self.assertIn(str(find_ruling_directory.PRIVATE_ROOT / "expected"), str(missing.exception))

            public_expected.mkdir(parents=True)
            private_expected.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "Multiple expected ruling directories exist") as ambiguous:
                find_ruling_directory.find_ruling_paths(root)
            self.assertIn(str(find_ruling_directory.PUBLIC_ROOT / "expected"), str(ambiguous.exception))
            self.assertIn(str(find_ruling_directory.PRIVATE_ROOT / "expected"), str(ambiguous.exception))

    def test_rejects_enterprise_layout_alongside_other_layouts(self) -> None:
        enterprise_expected = Path("private/its-enterprise/ruling/src/test/resources/expected")
        for other in (find_ruling_directory.PUBLIC_ROOT, find_ruling_directory.PRIVATE_ROOT):
            with self.subTest(other=other), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / enterprise_expected).mkdir(parents=True)
                (root / other / "expected").mkdir(parents=True)
                with self.assertRaisesRegex(ValueError, "Multiple expected ruling directories exist") as ambiguous:
                    find_ruling_directory.find_ruling_paths(root)
                self.assertIn(str(enterprise_expected), str(ambiguous.exception))
                self.assertIn(str(other / "expected"), str(ambiguous.exception))

    def test_main_publishes_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output"
            with (
                patch.dict(find_ruling_directory.os.environ, {"GITHUB_OUTPUT": str(output_path)}),
                patch.object(find_ruling_directory, "find_ruling_paths", return_value=(
                    find_ruling_directory.PUBLIC_ROOT, Path("its/sources"),
                )),
            ):
                self.assertEqual(find_ruling_directory.main(), 0)
            self.assertEqual(output_path.read_text(),
                "ruling-root=its/ruling/src/test/resources\nsources-root=its/sources\n")


class CleanupFixPullRequestTests(unittest.TestCase):
    @patch.object(cleanup_fix_pr.subprocess, "run")
    def test_closes_open_pr_and_deletes_fix_branch(self, process) -> None:
        process.side_effect = [
            SimpleNamespace(returncode=0, stdout="OPEN\n"),
            SimpleNamespace(returncode=0),
            SimpleNamespace(returncode=1),
        ]
        self.assertTrue(cleanup_fix_pr.cleanup_fix_pr("feature"))
        branch = "fix/update-ruling-for-feature"
        self.assertEqual(process.call_args_list[0].args[0],
            ("gh", "pr", "view", branch, "--json", "state", "--jq", ".state"))
        self.assertEqual(process.call_args_list[1].args[0][:4], ("gh", "pr", "close", branch))
        self.assertEqual(process.call_args_list[2].args[0],
            ("git", "push", "origin", "--delete", branch))
        self.assertTrue(process.call_args_list[1].kwargs["check"])
        self.assertFalse(process.call_args_list[2].kwargs["check"])

    @patch.object(cleanup_fix_pr.subprocess, "run")
    def test_no_open_pr_does_not_delete_branch(self, process) -> None:
        for result in (SimpleNamespace(returncode=1, stdout=""),
                       SimpleNamespace(returncode=0, stdout="CLOSED\n")):
            process.reset_mock()
            process.return_value = result
            self.assertFalse(cleanup_fix_pr.cleanup_fix_pr("feature"))
            process.assert_called_once()

    @patch.object(cleanup_fix_pr.subprocess, "run")
    def test_close_failure_prevents_branch_deletion(self, process) -> None:
        process.side_effect = [
            SimpleNamespace(returncode=0, stdout="OPEN\n"),
            cleanup_fix_pr.subprocess.CalledProcessError(1, "gh pr close"),
        ]
        with self.assertRaises(cleanup_fix_pr.subprocess.CalledProcessError):
            cleanup_fix_pr.cleanup_fix_pr("feature")
        self.assertEqual(process.call_count, 2)


if __name__ == "__main__":
    unittest.main()
