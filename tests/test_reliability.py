import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import monitor as m
from test_monitor import ENV, post, response, NOW


class ReliabilityTests(unittest.TestCase):
    def test_known_pinned_post_does_not_end_time_window(self):
        cutoff=dt.datetime(2026,11,16,tzinfo=dt.timezone.utc)
        pages=iter([response([post('1')],{'cursors':{'after':'abc'}}),
                    response([post('2')],{'cursors':{'after':'def'}}),
                    response([dict(post('3'),timestamp='2026-11-15T00:00:00+00:00')])])
        rows=m.fetch_posts(ENV,lambda *a,**kw:next(pages),known_ids={'1'},lower_bound=cutoff)
        self.assertEqual({p['id'] for p in rows},{'1','2','3'})
    def test_definitive_webhook_refusal_is_safe_to_retry_later(self):
        state=m.initial_state();state.update(initialized=True,seen=['1'])
        def reject(text):raise m.MonitorError('HTTP 429',status=429)
        self.assertEqual(m.run(state,lambda:[post('2')],reject,lambda s:None,NOW),1)
        self.assertIsNone(state['pending']);self.assertNotIn('2',state['seen'])
        self.assertIsNotNone(state['last_fetch_success'])
        self.assertIsNone(state['last_success'])
    def test_blocked_provider_is_not_automatically_retried(self):
        state=m.initial_state();calls=[]
        def blocked():calls.append(1);raise m.MonitorError('API access blocked',meta_code=200,meta_subcode=5258005)
        m.run(state,blocked,lambda s:None,lambda s:None,NOW)
        m.run(state,blocked,lambda s:None,lambda s:None,NOW)
        self.assertEqual(calls,[1]);self.assertTrue(state['provider_blocked'])
    def test_success_clears_stale_error_and_records_counts(self):
        state=m.initial_state();state.update(initialized=True,seen=['1'],last_error='old')
        m.run(state,lambda:[post('1'),post('2')],lambda s:{'id':'123'},lambda s:None,NOW)
        self.assertIsNone(state['last_error']);self.assertEqual(state['last_result']['sent'],1)
        self.assertEqual(state['last_discord_message_id'],'123')
    def test_emoji_content_respects_discord_utf16_limit(self):
        calls=[]
        m.discord('😀'*2000,{'DISCORD_WEBHOOK_URL':'https://discord.com/api/webhooks/123/abc'},lambda *a,**kw:calls.append(kw))
        self.assertLessEqual(len(calls[0]['payload']['content'].encode('utf-16-le')),3800)
    def test_slot_gate_avoids_30_minute_jitter_drift(self):
        now=dt.datetime(2026,11,23,1,30,1,tzinfo=dt.timezone.utc)
        self.assertTrue(m.due_in_slot({'last_run':'2026-11-23T01:00:05+00:00'},now))
        self.assertFalse(m.due_in_slot({'last_run':'2026-11-23T01:30:00+00:00'},now))
    def test_corrupt_or_wrong_account_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=os.getcwd()
            try:
                os.chdir(tmp);Path('state').mkdir()
                for update in [{'account':'bbcnews'},{'last_run':'broken'},{'version':True}]:
                    state=m.initial_state();state.update(update)
                    Path('state/state.json').write_text(json.dumps(state))
                    with patch('monitor.fetch_posts') as fetch:
                        with self.assertRaises((m.StateError,m.MonitorError)):
                            m.main()
                        fetch.assert_not_called()
            finally:os.chdir(old)
    def test_interval_gate_never_calls_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=os.getcwd()
            try:
                os.chdir(tmp);Path('state').mkdir()
                state=m.initial_state();state.update(initialized=True,last_run=dt.datetime.now(dt.timezone.utc).isoformat())
                Path('state/state.json').write_text(json.dumps(state))
                with patch.dict(os.environ,{'RESPECT_INTERVAL':'true','FORCE_CHECK':'false'}),patch('monitor.fetch_posts') as fetch:
                    self.assertEqual(m.main(),0);fetch.assert_not_called()
            finally:os.chdir(old)
