import copy
import datetime as dt
import unittest
from unittest.mock import patch
import urllib.error
import monitor as m

NOW = dt.datetime(2026, 11, 18, tzinfo=dt.timezone.utc)
ENV = {'META_ACCESS_TOKEN': 'secret', 'META_IG_USER_ID': '123', 'META_API_VERSION': 'v25.0'}

def post(i='1', product='FEED'):
    return {'id': i, 'permalink': 'https://www.instagram.com/p/ABC' + i + '/',
            'timestamp': '2026-11-17T12:00:00+0000', 'caption': '@everyone hello', 'media_product_type': product}

def response(rows, paging=None):
    return {'business_discovery': {'username': m.TARGET, 'media': {'data': rows, 'paging': paging or {}}}}

class FetchTests(unittest.TestCase):
    def test_http_errors_are_failures_and_secret_not_exposed(self):
        for code in [401, 403, 429, 500]:
            with self.subTest(code=code), patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError('https://secret', code, 'secret', {}, None)):
                with self.assertRaises(m.MonitorError) as e:
                    m.request_json('https://example.com')
                self.assertNotIn('secret', str(e.exception))
    def test_bad_json(self):
        with patch('urllib.request.urlopen') as p:
            p.return_value.__enter__.return_value.read.return_value = b'<html>login</html>'
            with self.assertRaises(m.MonitorError): m.request_json('https://example.com')
    def test_network_error(self):
        with patch('urllib.request.urlopen', side_effect=TimeoutError()):
            with self.assertRaises(m.MonitorError): m.request_json('https://example.com')
    def test_schema_errors(self):
        for data in [{}, {'error': {'message': 'token'}}, response([{}]), response([dict(post(), timestamp='bad')]), response([dict(post(), media_product_type='UNKNOWN')])]:
            with self.subTest(data=data), self.assertRaises(m.MonitorError):
                m.fetch_posts(ENV, lambda *a, **k: data)
    def test_empty_is_valid_only_with_expected_schema(self):
        self.assertEqual(m.fetch_posts(ENV, lambda *a, **k: response([])), [])
    def test_pagination_and_filter(self):
        calls = []
        pages = iter([response([post('1'), post('2', 'REELS')], {'next': 'ignored', 'cursors': {'after': 'abc'}}), response([post('3'), post('1')])])
        def fetch(url, **kw):
            calls.append(url)
            return next(pages)
        self.assertEqual([p['id'] for p in m.fetch_posts(ENV, fetch)], ['1', '3'])
        self.assertIn('after%28abc%29', calls[1])
    def test_business_discovery_cursor_without_next(self):
        pages = iter([response([post('1')], {'cursors': {'after': 'abc'}}), response([post('2')], {'cursors': {'after': 'def'}}), response([])])
        rows = m.fetch_posts(ENV, lambda *a, **k: next(pages))
        self.assertEqual([p['id'] for p in rows], ['1', '2'])
    def test_later_page_failure(self):
        pages = iter([response([post()], {'next': 'x', 'cursors': {'after': 'abc'}}), {}])
        with self.assertRaises(m.MonitorError): m.fetch_posts(ENV, lambda *a, **k: next(pages))
    def test_repeating_cursor(self):
        with self.assertRaises(m.MonitorError):
            m.fetch_posts(ENV, lambda *a, **k: response([post()], {'next': 'x', 'cursors': {'after': 'abc'}}))

class StateTests(unittest.TestCase):
    def setUp(self):
        self.state = m.initial_state()
        self.sent, self.saved = [], []
    def run_monitor(self, rows=None, fetch=None, send=None, save=None):
        return m.run(self.state, fetch or (lambda: rows or []), send or self.sent.append,
                     save or (lambda s: self.saved.append(copy.deepcopy(s))), NOW)
    def initialized(self):
        self.run_monitor([post()])
    def test_first_run_and_duplicate(self):
        self.initialized()
        self.assertEqual(self.sent, [])
        self.run_monitor([post()])
        self.assertEqual(self.sent, [])
    def test_new_posts_only_and_pending_saved_first(self):
        self.initialized()
        def send(message):
            self.assertEqual(self.saved[-1]['pending'], '2')
            self.sent.append(message)
        self.assertEqual(self.run_monitor([post('1'), post('2')], send=send), 0)
        self.assertIn('JST', self.sent[0])
        self.run_monitor([post('2')])
        self.assertEqual(len(self.sent), 1)
    def test_failure_does_not_initialize_or_change_seen(self):
        def fail(): raise m.MonitorError('HTTP 429')
        self.assertEqual(self.run_monitor(fetch=fail), 1)
        self.assertFalse(self.state['initialized'])
        self.assertEqual(self.state['seen'], [])
        self.assertIsNone(self.state['last_success'])
    def test_three_failures_alert_once_then_recover(self):
        def fail(): raise m.MonitorError('HTTP 429')
        for _ in range(4): self.run_monitor(fetch=fail)
        self.assertEqual(len(self.sent), 1)
        self.run_monitor([post()])
        self.assertIn('復旧', self.sent[-1])
        self.assertEqual(self.state['failures'], 0)
    def test_webhook_uncertain_not_retried(self):
        self.initialized()
        def fail(msg): raise m.MonitorError('network failure')
        self.assertEqual(self.run_monitor([post('2')], send=fail), 1)
        self.assertEqual(self.state['pending'], '2')
        self.run_monitor([post('2')])
        self.assertEqual(self.sent, [])
    def test_persistence_failure_prevents_send(self):
        self.initialized()
        def fail(s): raise RuntimeError('push failed')
        with self.assertRaises(RuntimeError): self.run_monitor([post('2')], save=fail)
        self.assertEqual(self.sent, [])
    def test_long_gap_backfills_multiple_posts(self):
        self.initialized()
        self.state['last_success'] = (NOW - dt.timedelta(hours=4)).isoformat()
        self.run_monitor([post('1'), post('2'), post('3')])
        self.assertEqual(len(self.sent), 3)
        self.assertIn('空白', self.sent[-1])
    def test_alert_failure_retried_next_run(self):
        def fail_fetch(): raise m.MonitorError('HTTP 500')
        def fail_send(msg): raise m.MonitorError('HTTP 429')
        for _ in range(3): self.run_monitor(fetch=fail_fetch, send=fail_send)
        self.assertFalse(self.state['alerted'])
        self.run_monitor(fetch=fail_fetch)
        self.assertTrue(self.state['alerted'])
    def test_webhook_normalizes_official_urls(self):
        urls = ['  https://discord.com/api/webhooks/123/abc\n',
                'https://discordapp.com/api/webhooks/123/a.b_-/',
                'https://discord.com/api/v10/webhooks/123/abc?wait=false&thread_id=456']
        for url in urls:
            calls = []
            m.discord('test', {'DISCORD_WEBHOOK_URL': url}, lambda endpoint, **k: calls.append(endpoint))
            self.assertIn('wait=true', calls[0])
            self.assertNotIn('wait=false', calls[0])
    def test_webhook_rejects_untrusted_or_incomplete_urls(self):
        for url in ['', 'http://discord.com/api/webhooks/123/abc',
                    'https://discord.com.evil.example/api/webhooks/123/abc',
                    'https://discord.com/channels/123/456',
                    'https://discord.com/api/webhooks/123',
                    'https://discord.com/api/webhooks/123/abc?thread_id=bad']:
            with self.subTest(url=url), self.assertRaises(m.MonitorError):
                m.discord('test', {'DISCORD_WEBHOOK_URL': url}, lambda *a, **k: self.fail('must not send'))
    def test_mentions_disabled_and_length(self):
        calls = []
        m.discord('@everyone' * 500, {'DISCORD_WEBHOOK_URL':'https://discord.com/api/webhooks/123/abc'}, lambda *a, **k: calls.append(k))
        self.assertEqual(calls[0]['payload']['allowed_mentions'], {'parse': []})
        self.assertLessEqual(len(calls[0]['payload']['content']), 1900)

if __name__ == '__main__': unittest.main()
