"""Instagram official Business Discovery -> Discord. Python standard library only."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from state_store import make_store, StateError

TARGET = 'hanaabi_official'

class MonitorError(Exception):
    def __init__(self, message, *, status=None, meta_code=None, meta_subcode=None):
        super().__init__(message)
        self.status, self.meta_code, self.meta_subcode = status, meta_code, meta_subcode
        self.provider_blocked = meta_code == 200 and meta_subcode == 5258005


def request_json(url, *, token=None, payload=None):
    headers = {'User-Agent': 'HanaabiMonitor/1.0', 'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(payload).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=30) as r:
            raw = r.read(8_000_001)
            if len(raw) > 8_000_000:
                raise MonitorError('response too large')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        # Extract only safe numeric codes and fixed classifications, never raw
        # messages/URLs: Meta may echo credentials in diagnostic strings.
        detail = ''
        err = {}
        try:
            err = json.loads(e.read(65536)).get('error', {})
            if not isinstance(err, dict):
                err = {}
            fields = []
            for key in ('code', 'error_subcode'):
                if type(err.get(key)) is int:
                    fields.append(f'{key}={err[key]}')
            message = str(err.get('message', '')).lower()
            categories = [('expired', 'token_expired'), ('invalidated', 'token_invalidated'),
                          ('access token', 'token_error'), ('permission', 'permission_error'),
                          ('limit', 'api_limit'), ('unsupported', 'unsupported_request'),
                          ('nonexisting field', 'unsupported_field')]
            for phrase, category in categories:
                if phrase in message:
                    fields.append(category)
                    break
            if fields:
                detail = ' (Meta ' + ', '.join(fields) + ')'
            # Redact credential-like strings and URLs before exposing Meta's explanation.
            explanation = str(err.get('message', ''))
            for secret in (token, os.environ.get('META_ACCESS_TOKEN'), os.environ.get('DISCORD_WEBHOOK_URL')):
                if secret:
                    explanation = explanation.replace(secret, '[REDACTED]')
            explanation = re.sub(r'https?://\S+', '[URL]', explanation)
            explanation = re.sub(r'[A-Za-z0-9_./+=-]{32,}', '[REDACTED]', explanation)
            explanation = re.sub(r'[\r\n\x00-\x1f]', ' ', explanation)
            if explanation:
                detail += ': ' + explanation[:400]
        except (ValueError, TypeError, AttributeError, OSError):
            pass
        raise MonitorError(f'HTTP {e.code}{detail}; no automatic retry', status=e.code,
                           meta_code=err.get('code'), meta_subcode=err.get('error_subcode')) from None
    except json.JSONDecodeError:
        raise MonitorError('response was not valid JSON') from None
    except urllib.error.URLError as e:
        raise MonitorError('network connection failed (' + type(e.reason).__name__ + ')') from None
    except OSError as e:
        raise MonitorError('network I/O failed (' + type(e).__name__ + ')') from None
    except (ValueError, UnicodeError):
        raise MonitorError('invalid request/header; check Secrets for embedded newlines or non-ASCII characters') from None


def timestamp(value):
    try:
        result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result
    except (AttributeError, TypeError, ValueError):
        raise MonitorError('invalid post timestamp') from None


def fetch_posts(env, request=request_json, *, target=TARGET, known_ids=None, recent_baseline=False, include_reels=False, lower_bound=None):
    if Path('state/meta-api-paused.json').exists() and env.get('ALLOW_META_PROBE') != 'true':
        raise MonitorError('Meta API access is paused after API access blocked (200/5258005); resolve the restriction in Meta before resuming')
    token = env.get('META_ACCESS_TOKEN', '').strip()
    user = env.get('META_IG_USER_ID', '').strip()
    version = env.get('META_API_VERSION', '').strip()
    if not token or not re.fullmatch(r'\d+', user) or not re.fullmatch(r'v\d+\.0', version):
        raise MonitorError('configure META_ACCESS_TOKEN, META_IG_USER_ID and META_API_VERSION')
    if any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise MonitorError('META_ACCESS_TOKEN contains whitespace or non-ASCII characters; paste the token as one line')
    products = {'FEED', 'REELS'} if include_reels else {'FEED'}
    posts, cursors, after = {}, set(), None
    for _ in range(20):
        suffix = '.after(' + after + ')' if after else ''
        fields = f'business_discovery.username({target}){{username,media.limit(100){suffix}{{id,caption,permalink,timestamp,media_product_type}}}}'
        data = request('https://graph.facebook.com/' + version + '/' + user + '?' + urllib.parse.urlencode({'fields': fields}), token=token)
        try:
            discovery = data['business_discovery']
            if discovery['username'].lower() != target:
                raise ValueError()
            media = discovery['media']
            rows = media['data']
            if not isinstance(rows, list):
                raise ValueError()
            for p in rows:
                # Explicit product type prevents Reels/Stories from being mistaken for feed posts.
                if p['media_product_type'] not in ('FEED', 'REELS', 'STORY', 'AD'):
                    raise ValueError()
                if p['media_product_type'] not in products:
                    continue
                if not isinstance(p['id'], str) or not p['id'].isdigit():
                    raise ValueError()
                if not re.fullmatch(r'https://www\.instagram\.com/' + ('(?:p|reel)' if include_reels else 'p') + r'/[A-Za-z0-9_-]+/?', p['permalink']):
                    raise ValueError()
                timestamp(p['timestamp'])
                if 'caption' in p and not isinstance(p['caption'], str):
                    raise ValueError()
                posts[p['id']] = p
            # A complete time window tolerates pinned/known posts near the top.
            page_feed = [p for p in rows if p['media_product_type'] in products]
            window_complete = lower_bound is not None and rows and all(
                timestamp(p['timestamp']) < lower_bound for p in rows)
            if recent_baseline or window_complete or (lower_bound is None and known_ids and page_feed and any(p['id'] in known_ids for p in page_feed)):
                return sorted(posts.values(), key=lambda p: (timestamp(p['timestamp']), p['id']))
            paging = media.get('paging', {})
            cursor = paging.get('cursors', {}).get('after')
            if not rows or (not cursor and not paging.get('next')):
                return sorted(posts.values(), key=lambda p: (timestamp(p['timestamp']), p['id']))
            after = cursor
            if not isinstance(after, str) or not re.fullmatch(r'[A-Za-z0-9_=-]+', after) or after in cursors:
                raise ValueError()
            cursors.add(after)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise MonitorError('API error, missing fields or unexpected response; not an empty feed') from None
    raise MonitorError('pagination limit exceeded; refusing partial results')


def discord(text, env, request=request_json):
    raw = env.get('DISCORD_WEBHOOK_URL', '').strip()
    if not raw:
        raise MonitorError('DISCORD_WEBHOOK_URL Secret is empty')
    try:
        url = urllib.parse.urlsplit(raw)
        if (url.scheme != 'https' or url.netloc not in ('discord.com', 'discordapp.com',
                'canary.discord.com', 'ptb.discord.com') or url.fragment):
            raise MonitorError('DISCORD_WEBHOOK_URL: use Copy Webhook URL in Discord channel settings; expected HTTPS Discord host')
        if not re.fullmatch(r'/api/(?:v[0-9]+/)?webhooks/[0-9]+/[A-Za-z0-9_.-]+/?', url.path):
            raise MonitorError('DISCORD_WEBHOOK_URL: expected /api/webhooks/ID/TOKEN; channel links and webhook IDs alone are not valid')
        query = urllib.parse.parse_qs(url.query, keep_blank_values=True, strict_parsing=True)
        if set(query) - {'wait', 'thread_id', 'with_components'}:
            raise MonitorError('DISCORD_WEBHOOK_URL: unexpected query parameters')
        if 'thread_id' in query and (len(query['thread_id']) != 1 or not query['thread_id'][0].isdigit()):
            raise MonitorError('DISCORD_WEBHOOK_URL: invalid thread_id')
        query['wait'] = ['true']
        endpoint = urllib.parse.urlunsplit((url.scheme, url.netloc, url.path.rstrip('/'),
            urllib.parse.urlencode(query, doseq=True), ''))
    except ValueError:
        raise MonitorError('DISCORD_WEBHOOK_URL: malformed URL; copy it again from Discord') from None
    return request(endpoint, payload={'content': text.encode('utf-16-le')[:3800].decode('utf-16-le', errors='ignore'), 'allowed_mentions': {'parse': []}})


def initial_state():
    return {'version': 1, 'initialized': False, 'seen': [], 'pending': None,
            'failures': 0, 'alerted': False, 'last_success': None, 'last_run': None}


def run(state, fetch, send, save, now, label="南陽醸造", clock=None):
    stamp = clock or (lambda: now)
    state['last_run'] = now.isoformat()
    stats = {'target': label, 'fetched': 0, 'sent': 0, 'already_seen': 0}
    state['last_result'] = stats
    try:
        if state.get('provider_blocked'):
            if os.environ.get('RESUME_META') == 'true':
                state['provider_blocked'] = False
            else:
                raise MonitorError('Meta account access blocked; owner verification is required before resume')
        if state['pending']:
            raise MonitorError('uncertain prior delivery; resolve pending in state before resuming')
        stats['status'] = 'fetching'
        save(state)  # Persist the attempt before using either external API.
        posts = fetch()  # Finish every required page before baseline or delivery.
        state['last_fetch_success'] = stamp().isoformat()
        stats['fetched'] = len(posts)
        stats['by_type'] = {kind: sum(p.get('media_product_type') == kind for p in posts) for kind in ('FEED', 'REELS')}
        stats['status'] = 'fetched'
        if not state['initialized']:
            state['seen'] = [p['id'] for p in posts]
            state['initialized'] = True
        else:
            for p in posts:
                if p['id'] in state['seen']:
                    stats['already_seen'] += 1
                    continue
                state['pending'] = p['id']
                state['pending_url'] = p['permalink']
                state['pending_since'] = now.isoformat()
                stats['status'] = 'delivery_in_progress'
                save(state)  # Must be durable before the POST.
                local = timestamp(p['timestamp']).astimezone(dt.timezone(dt.timedelta(hours=9)))
                receipt = send(f'{label} 新規投稿（{"リール" if p.get("media_product_type") == "REELS" else "通常投稿"}）\n投稿日時: {local:%Y-%m-%d %H:%M:%S} JST\n{p["permalink"]}\n{p.get("caption", "（本文なし／取得不可）")[:1500]}')
                state['seen'].append(p['id'])
                stats['sent'] += 1
                if isinstance(receipt, dict) and receipt.get('id'):
                    state['last_discord_message_id'] = receipt['id']
                state['pending'] = None
                save(state)
        if state['last_success'] and now - timestamp(state['last_success']) > dt.timedelta(minutes=90):
            send(f'{label}: 監視の空白を検出しました（前回成功から90分超）。取得可能な投稿を再確認しました。')
        if state['alerted']:
            send(f'{label}: Instagram投稿取得が復旧しました。')
        state.update(failures=0, alerted=False, last_success=stamp().isoformat(), last_error=None)
        state.pop('pending_url', None)
        state.pop('pending_since', None)
        stats['status'] = 'success'
        save(state)
        return 0
    except MonitorError as e:
        if e.provider_blocked:
            state['provider_blocked'] = True
        # HTTP 4xx is a definitive refusal; only unknown delivery outcomes stay pending.
        if state['pending'] and e.status is not None and 400 <= e.status < 500:
            state['pending'] = None
        stats['status'] = 'delivery_uncertain' if state['pending'] else 'failed'
        state['failures'] += 1
        state['last_error'] = str(e)
        print('ERROR:', e, file=sys.stderr)
        if state['failures'] >= 3 and not state['alerted']:
            try:
                send(f'{label}: Instagram監視障害: {state["failures"]}回連続失敗。GitHub Actionsのログを確認してください。\n{e}')
                state['alerted'] = True
            except MonitorError:
                print('ERROR: failure alert delivery failed', file=sys.stderr)
        save(state)
        return 1


def due_in_slot(state, now):
    # Each UTC half-hour has one check. Avoid cumulative drift from a few
    # seconds of runner/HTTP jitter on a strict elapsed-time threshold.
    previous = state.get('last_run')
    return previous is None or int(timestamp(previous).timestamp() // 1800) < int(now.timestamp() // 1800)


def main(target=TARGET):
    if target not in (TARGET, 'bbcnews'):
        raise MonitorError('unsupported target')
    is_bbc = target == 'bbcnews'
    path = 'state/bbcnews.json' if is_bbc else 'state/state.json'
    store = make_store(path)
    state = store.read()
    if state is not None:
        try:
            expected = initial_state()
            if type(state.get('version')) is not int or state['version'] != 1 or any(k not in state for k in expected):
                raise ValueError()
            if (not isinstance(state['seen'], list)
                    or any(not isinstance(i, str) or not i.isdigit() for i in state['seen'])
                    or type(state['failures']) is not int or state['failures'] < 0
                    or type(state['initialized']) is not bool or type(state['alerted']) is not bool
                    or (state['pending'] is not None and
                        (not isinstance(state['pending'], str) or not state['pending'].isdigit()))):
                raise ValueError()
            for field in ('last_success', 'last_run', 'last_fetch_success', 'reels_since'):
                if state.get(field) is not None:
                    timestamp(state[field])
            if 'reels_enabled' in state and type(state['reels_enabled']) is not bool:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise MonitorError('state corrupted; restore from Git history') from None
    elif is_bbc or os.environ.get('INITIALIZE') == 'true':
        state = initial_state()
    else:
        raise MonitorError('state missing; use manual initialize=true only for first setup')

    if state.get('account', target) != target:
        raise StateError('state account does not match target; refusing to use another account history')
    state['account'] = target

    def save(value):
        store.save(value)

    now = dt.datetime.now(dt.timezone.utc)
    if (os.environ.get('RESPECT_INTERVAL') == 'true' and os.environ.get('FORCE_CHECK') != 'true'
            and not due_in_slot(state, now)):
        record_summary(target, {'status': 'not_due', 'last_fetch_success': state.get('last_fetch_success')})
        print(f'{target}: not due; API was not called')
        return 0
    def fetch():
        migrating = is_bbc and not state.get('reels_enabled', False)
        lookback = timestamp(state['last_success']) - dt.timedelta(hours=24) if is_bbc and state.get('last_success') else None
        posts = fetch_posts(os.environ, target=target,
            known_ids=set(state['seen']) if is_bbc and state['initialized'] else None,
            recent_baseline=is_bbc and (not state['initialized'] or migrating),
            include_reels=is_bbc, lower_bound=lookback)
        if migrating:
            # Only mark existing Reels as seen; never reset existing FEED history.
            for p in posts:
                if p['media_product_type'] == 'REELS' and p['id'] not in state['seen']:
                    state['seen'].append(p['id'])
            state['reels_since'] = dt.datetime.now(dt.timezone.utc).isoformat()
            state['reels_enabled'] = True
            save(state)
            print('BBC Reels baseline recorded; existing Reels will not be sent')
        if is_bbc and state['initialized']:
            # Do not notify unrecorded history older than the original tracking baseline.
            baseline = timestamp(state['reels_since'])
            posts = [p for p in posts if p['id'] in state['seen'] or timestamp(p['timestamp']) >= baseline]
            posts = [p for p in posts if p['media_product_type'] != 'REELS'
                     or p['id'] in state['seen']
                     or timestamp(p['timestamp']) >= timestamp(state['reels_since'])]
        return posts

    try:
        result = run(state, fetch, lambda text: discord(text, os.environ), save,
                     now, label='【テスト】BBC News' if is_bbc else '南陽醸造',
                     clock=lambda: dt.datetime.now(dt.timezone.utc))
    except StateError:
        record_summary(target, {'status': 'state_save_failed', 'pending': state.get('pending'),
                                'last_fetch_success': state.get('last_fetch_success')})
        raise
    record_summary(target, dict(state.get('last_result', {}),
                   last_fetch_success=state.get('last_fetch_success'),
                   last_success=state.get('last_success'), failures=state['failures'], pending=state['pending']))
    print(json.dumps({'target': target, **state.get('last_result', {}), 'seen': len(state['seen'])}, ensure_ascii=False))
    return result


def record_summary(target, value):
    path = Path('work/runtime/summary.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        all_results = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        all_results = {}
    all_results[target] = value
    path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write('\n### ' + target + '\n\n```json\n' + json.dumps(value, ensure_ascii=False, indent=2) + '\n```\n')


def cli():
    targets = [TARGET, 'bbcnews'] if '--all' in sys.argv else ['bbcnews' if '--bbc' in sys.argv else TARGET]
    failed = False
    for target in targets:
        if target == 'bbcnews' and (not json.loads(Path(__file__).with_name('monitor_config.json').read_text()).get('bbc_enabled', False)
                                   or os.environ.get('BBC_TEST_ENABLED') == 'false'):
            continue
        try:
            failed = main(target) != 0 or failed
        except (MonitorError, StateError) as error:
            print(f'ERROR: {target}: {error}', file=sys.stderr)
            record_summary(target, {'status': 'error', 'error': str(error)})
            failed = True
    return int(failed)


if __name__ == '__main__':
    sys.exit(cli())
