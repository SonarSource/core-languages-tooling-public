import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
import comment

SETTINGS = dict(PR='12', GH_REPO='owner/repo', URL='https://dashboard', RUN_URL='https://run', NEW='2', LOST='3')


class CommentTests(unittest.TestCase):
    def test_legacy_dashboard_format_is_unchanged(self):
        self.assertEqual(comment.body(SETTINGS), '📊 **Performance Validation** complete\n🆕 2 new · 🗑️ 3 lost issues\n[View dashboard](https://dashboard)')

    def test_legacy_fallback(self):
        self.assertEqual(comment.body({**SETTINGS,'URL':''}), '⚠️ **Performance Validation** finished without publishing a dashboard. [See run logs](https://run).')

    def test_success_and_problem_outcomes(self):
        clean = comment.body({**SETTINGS,'VALIDATE_RESULT':'success'})
        problem = comment.body({**SETTINGS,'VALIDATE_RESULT':'success','REGRESSED':'project','ERRORED':'other'})
        self.assertIn('complete',clean)
        self.assertIn('2 new',clean)
        self.assertIn('reported problems',problem)
        self.assertIn('Regressed: project',problem)
        self.assertIn('Errored: other',problem)

    def test_failure_skipped_cancelled_do_not_show_counts(self):
        for outcome in ('failure','skipped','cancelled'):
            with self.subTest(outcome=outcome):
                text = comment.body({**SETTINGS,'VALIDATE_RESULT':outcome})
                self.assertNotIn('new ·',text)
                self.assertIn('Run logs',text)
        self.assertIn('No baseline',comment.body({**SETTINGS,'VALIDATE_RESULT':'skipped'}))

    def test_explicit_pr_wins(self):
        with patch.object(comment.subprocess,'run') as call:
            self.assertEqual(comment.find_pr({**SETTINGS,'SHA':'sha'}),'12')
            call.assert_not_called()

    def test_discovers_merged_pr_on_requested_branch(self):
        pulls = [[{'number':1,'merged_at':None}, {'number':2,'merged_at':'date','base':{'ref':'other'}},
                  {'number':3,'merged_at':'date','base':{'ref':'main'}}]]
        with patch.object(comment.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(pulls))):
            self.assertEqual(comment.find_pr({**SETTINGS,'PR':'','SHA':'sha','BRANCH':'main'}),'3')

    def test_missing_pr_is_empty(self):
        with patch.object(comment.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'[[]]')):
            self.assertEqual(comment.find_pr({**SETTINGS,'PR':'','SHA':'sha'}),'')

    def test_escapes_content_and_links(self):
        text = comment.body({**SETTINGS,'VALIDATE_RESULT':'success','REGRESSED':'<img> [x](url)', 'URL':'https://host/a)b'})
        self.assertIn('\\<img\\>',text)
        self.assertIn('https://host/a%29b',text)

    def test_posts_body_file_and_cleans_it_up(self):
        def post(args, **kwargs):
            self.assertEqual(args[:4], ['gh','pr','comment','12'])
            path = Path(args[args.index('--body-file') + 1])
            self.assertEqual(path.read_text(), comment.body(SETTINGS))
            self.posted_path = path
        with patch.dict(comment.os.environ, SETTINGS), patch.object(comment.subprocess,'run',side_effect=post):
            self.assertEqual(comment.main(),0)
        self.assertFalse(self.posted_path.exists())

    def test_missing_merged_pr_skips_posting(self):
        with patch.dict(comment.os.environ, SETTINGS), patch.object(comment,'find_pr',return_value=''), patch.object(comment.subprocess,'run') as post:
            self.assertEqual(comment.main(),0)
            post.assert_not_called()

    def test_lookup_error_fails_action(self):
        with patch.dict(comment.os.environ, SETTINGS), patch.object(comment,'find_pr',side_effect=subprocess.CalledProcessError(1,['gh'])):
            self.assertEqual(comment.main(),1)

    def test_rejects_unknown_result(self):
        with self.assertRaises(ValueError):
            comment.body({**SETTINGS,'VALIDATE_RESULT':'unknown'})


if __name__ == '__main__':
    unittest.main()
