import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import resolve

SETTINGS = dict(REPOSITORY='owner/repo', BRANCH='main', BUILD_WORKFLOW='build.yml', PUBLICATION_JOB='Publish',
                PREVIOUS_SHA='previous', CURRENT_SHA='current', CURRENT_RUN_ID='99',
                VALIDATED_ARTIFACT='pvf-validated', CANDIDATE_ARTIFACT='candidate-version')


def run(number, sha=None, branch='main', event='push'):
    return dict(id=number, head_sha=sha or f'sha{number}', head_branch=branch, event=event, workflow_id=1)


class ResolveTests(unittest.TestCase):
    def resolve(self, validated=(), previous=(), builds=(), unpublished=(), missing=(), invalid=(), download_failure=False, missing_file=(), wrong_workflow=()):
        records = {r['id']: r for r in (*validated, *previous, *builds)}
        def api(repo, path):
            if path == 'actions/workflows/build.yml':
                return {'id': 1}
            number = int(path.split('/')[-1])
            return {**records[number], 'workflow_id': 2 if number in wrong_workflow else 1}
        def pages(repo, path, key, **query):
            if path == 'actions/artifacts':
                return iter(dict(name='pvf-validated', expired=False, workflow_run=r) for r in validated)
            if path.endswith('/runs'):
                return iter(previous if query.get('head_sha') else builds)
            number = int(path.split('/')[2])
            if key == 'jobs':
                return iter([{'name':'Publish', 'conclusion':'failure' if number in unpublished else 'success'}])
            return iter([{'name': 'pvf-validated' if number in [r['id'] for r in validated] else 'candidate-version',
                          'expired': number in missing}])
        def download(args, **kwargs):
            if download_failure:
                raise subprocess.CalledProcessError(1, args)
            number = int(args[3])
            directory = args[args.index('--dir') + 1]
            name = args[args.index('--name') + 1]
            if number in missing_file:
                return
            Path(directory, name + '.txt').write_text('bad version\n' if number in invalid else f'1.0.{number}\n')
        with patch.object(resolve, 'api', side_effect=api), patch.object(resolve, 'pages', side_effect=pages), patch.object(resolve.subprocess, 'run', side_effect=download):
            return resolve.resolve(SETTINGS)

    def test_prefers_validated_even_when_overall_run_not_successful(self):
        self.assertEqual(self.resolve(validated=[run(1)], previous=[run(2)]), ('1.0.1','sha1'))

    def test_falls_back_to_previous_then_deployed_branch(self):
        self.assertEqual(self.resolve(previous=[run(2)], builds=[run(3)]), ('1.0.2','sha2'))
        self.assertEqual(self.resolve(previous=[run(2)], builds=[run(3)], unpublished=[2]), ('1.0.3','sha3'))

    def test_excludes_current_run_and_sha_and_other_branches(self):
        self.assertEqual(self.resolve(builds=[run(99), run(3,'current'), run(4,branch='other'), run(5)]), ('1.0.5','sha5'))

    def test_skips_expired_unpublished_and_malformed_artifacts(self):
        self.assertEqual(self.resolve(validated=[run(1),run(2),run(3),run(4)], missing=[1], unpublished=[2], invalid=[3]), ('1.0.4','sha4'))

    def test_validated_artifacts_must_belong_to_selected_workflow_and_push_event(self):
        self.assertEqual(self.resolve(validated=[run(1),run(2,event='workflow_dispatch'),run(3)], wrong_workflow=[1]), ('1.0.3','sha3'))

    def test_missing_version_file_is_skipped(self):
        self.assertEqual(self.resolve(builds=[run(1),run(2)], missing_file=[1]), ('1.0.2','sha2'))

    def test_returns_empty_when_no_baseline_exists(self):
        self.assertEqual(self.resolve(), ('',''))

    def test_download_failures_are_not_treated_as_no_baseline(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.resolve(builds=[run(1)], download_failure=True)

    def test_paginates(self):
        responses = [{'jobs':list(range(100))}, {'jobs':[100]}]
        with patch.object(resolve, 'api', side_effect=responses) as api:
            self.assertEqual(len(list(resolve.pages('owner/repo','jobs','jobs'))),101)
            self.assertIn('page=2', api.call_args.args[1])

    def test_api_failure_is_a_hard_error(self):
        with patch.object(resolve, 'api', side_effect=subprocess.CalledProcessError(1,['gh'])), patch.dict(resolve.os.environ, SETTINGS):
            self.assertEqual(resolve.main(),1)


if __name__ == '__main__':
    unittest.main()
