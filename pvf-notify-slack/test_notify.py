import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch
import notify

SETTINGS = dict(REPOSITORY='owner/repo', BRANCH='main', BASE_SHA='base', HEAD_SHA='head', MERGER='fallback',
                VALIDATE_RESULT='success', RESOLVE_RESULT='success', REGRESSED='project', ERRORED='',
                NEW='2', LOST='3', URL='https://dashboard', RUN_URL='https://run',
                SLACK_CHANNEL='channel', SLACK_USERNAME='PVF', SLACK_WEBHOOK='https://secret-webhook')


def commit(index):
    return dict(sha=f'{index:040x}', commit={'message':f'Commit {index}\nbody'}, author={'login':'author'})


class NotifyTests(unittest.TestCase):
    def test_bounded_commits_and_deduplicated_mergers(self):
        def api(repo,path):
            if path.startswith('compare/'):
                return {'total_commits':25,'commits':[commit(i) for i in range(25)]}
            if path.startswith('commits/'):
                return [{'number':1,'merged_at':'date','base':{'ref':'main'}}]
            return {'merged_by':{'login':'merger'}}
        with patch.object(notify,'api',side_effect=api):
            context = notify.attribution(SETTINGS)
        self.assertEqual(len(context[0]),20)
        self.assertEqual(context[2],['merger'])
        self.assertIn('… and 5 more',notify.message(SETTINGS,context))

    def test_final_compare_pages_are_used(self):
        def api(repo,path):
            if path.startswith('compare/'):
                if 'page=2' in path:
                    return {'commits':[commit(100)]}
                return {'total_commits':101,'commits':[commit(i) for i in range(100)]}
            return []
        with patch.object(notify,'api',side_effect=api):
            context = notify.attribution(SETTINGS)
        self.assertEqual([c['sha'] for c in context[0]], [commit(i)['sha'] for i in range(81,101)])

    def test_lookup_failure_preserves_alert(self):
        with patch.object(notify,'api',side_effect=subprocess.CalledProcessError(1,['gh'])):
            context = notify.attribution(SETTINGS)
        self.assertEqual(context[2],['fallback'])
        self.assertIn('Commit range unavailable',notify.message(SETTINGS,context))
        self.assertIn('Regressed: project',notify.message(SETTINGS,context))

    def test_missing_baseline_needs_no_lookup(self):
        with patch.object(notify,'api') as api:
            context = notify.attribution({**SETTINGS,'BASE_SHA':''})
            api.assert_not_called()
        self.assertEqual(context[2],['fallback'])

    def test_associated_pr_lookup_failure_retains_author(self):
        with patch.object(notify,'api',side_effect=[{'total_commits':1,'commits':[commit(1)]},subprocess.CalledProcessError(1,['gh'])]):
            context = notify.attribution(SETTINGS)
        self.assertEqual(context[2],['author'])
        self.assertIn('Mergers: author',notify.message(SETTINGS,context))

    def test_pr_details_lookup_failure_retains_author(self):
        responses = [
            {'total_commits':1,'commits':[commit(1)]},
            [{'number':1,'merged_at':'date','base':{'ref':'main'}}],
            subprocess.CalledProcessError(1,['gh']),
        ]
        with patch.object(notify,'api',side_effect=responses):
            context = notify.attribution(SETTINGS)
        self.assertEqual(context[2],['author'])

    def test_missing_merger_retains_author(self):
        for pull in ({}, {'merged_by':None}, {'merged_by':{}}, {'merged_by':{'login':''}}):
            with self.subTest(pull=pull):
                responses = [
                    {'total_commits':1,'commits':[commit(1)]},
                    [{'number':1,'merged_at':'date','base':{'ref':'main'}}],
                    pull,
                ]
                with patch.object(notify,'api',side_effect=responses):
                    context = notify.attribution(SETTINGS)
                self.assertEqual(context[2],['author'])

    def test_lookup_failure_without_author_uses_final_fallback(self):
        for author in ({}, {'author':None}):
            for actor, expected in (('fallback','fallback'), ('','unknown')):
                with self.subTest(author=author,actor=actor):
                    item = commit(1)
                    del item['author']
                    item.update(author)
                    responses = [
                        {'total_commits':1,'commits':[item]},
                        subprocess.CalledProcessError(1,['gh']),
                    ]
                    with patch.object(notify,'api',side_effect=responses):
                        context = notify.attribution({**SETTINGS,'MERGER':actor})
                    self.assertEqual(context[2],[expected])

    def test_author_fallback_is_deduplicated(self):
        responses = [
            {'total_commits':2,'commits':[commit(1),commit(2)]},
            subprocess.CalledProcessError(1,['gh']),
            [],
        ]
        with patch.object(notify,'api',side_effect=responses):
            context = notify.attribution(SETTINGS)
        self.assertEqual(context[2],['author'])

    def test_skipped_failed_do_not_show_counts(self):
        for outcome in ('failure','skipped'):
            text = notify.message({**SETTINGS,'VALIDATE_RESULT':outcome},([],0,['fallback'],False))
            self.assertNotIn('New/lost issues',text)
        text = notify.message({**SETTINGS,'VALIDATE_RESULT':'skipped','RESOLVE_RESULT':'failure'},([],0,['fallback'],False))
        self.assertIn('Baseline resolution did not complete',text)

    def test_escapes_slack_mentions_and_formatting(self):
        text = notify.message({**SETTINGS,'REGRESSED':'<!channel> *bold*','URL':'https://host/|oops>'},([],0,['fallback'],False))
        self.assertNotIn('<!channel>',text)
        self.assertIn('&lt;!channel&gt; ∗bold∗',text)
        self.assertIn('%7Coops%3E',text)

    def test_posts_json_and_checks_response(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'ok'
        with patch.object(notify.urllib.request,'urlopen',return_value=response) as call:
            notify.send(SETTINGS,'message')
            request = call.call_args.args[0]
            self.assertEqual(json.loads(request.data)['text'],'message')
            self.assertEqual(call.call_args.kwargs['timeout'],30)
        response.read.return_value = b'invalid_payload'
        with patch.object(notify.urllib.request,'urlopen',return_value=response), self.assertRaises(ValueError):
            notify.send(SETTINGS,'message')

    def test_delivery_failure_does_not_log_webhook(self):
        with patch.dict(notify.os.environ,SETTINGS), patch.object(notify,'attribution',return_value=([],0,['fallback'],False)), patch.object(notify,'send',side_effect=ValueError('https://secret-webhook')), patch('builtins.print') as output:
            self.assertEqual(notify.main(),1)
            self.assertNotIn('https://secret-webhook',str(output.call_args_list))


if __name__ == '__main__':
    unittest.main()
