"""Instagram official Business Discovery -> Discord. Python standard library only."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

TARGET = 'hanaabi_official'

class MonitorError(Exception):
    pass


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
        # Never print exception URLs, response bodies, tokens or webhook secrets.
        raise MonitorError(f'HTTP {e.code}; no automatic retry') from None
    except (OSError, ValueError):
        raise MonitorError('network failure or invalid JSON') from None


def timestamp(value):
    try:
        result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result
    except (AttributeError, TypeError, ValueError):
        raise MonitorError('invalid post timestamp') from None


def fetch_posts(env, request=request_json):
    token = env.get('META_ACCESS_TOKEN', '')
    user = env.get('META_IG_USER_ID', '')
    version = env.get('META_API_VERSION', '')
    if not token or not re.fullmatch(r'\d+', user) or not re.fullmatch(r'v\d+\.0', version):
        raise MonitorError('configure META_ACCESS_TOKEN, META_IG_USER_ID and META_API_VERSION')
    posts, cursors, after = {}, set(), None
    for _ in range(20):
        suffix = '.after(' + after + ')' if after else ''
        fields = f'business_discovery.username({TARGET}){{username,media.limit(100){suffix}{{id,caption,permalink,timestamp,media_product_type}}}}'
        data = request('https://graph.facebook.com/' + version + '/' + user + '?' + urllib.parse.urlencode({'fields': fields}), token=token)
        try:
            discovery = data['business_discovery']
            if discovery['username'].lower() != TARGET:
                raise ValueError()
            media = discovery['media']
            rows = media['data']
            if not isinstance(rows, list):
                raise ValueError()
            for p in rows:
                # Explicit product type prevents Reels/Stories from being mistaken for feed posts.
                if p['media_product_type'] not in ('FEED', 'REELS', 'STORY', 'AD'):
                    raise ValueError()
                if p['media_product_type'] != 'FEED':
                    continue
                if not isinstance(p['id'], str) or not p['id'].isdigit():
                    raise ValueError()
                if not re.fullmatch(r'https://www\.instagram\.com/p/[A-Za-z0-9_-]+/?', p['permalink']):
                    raise ValueError()
                timestamp(p['timestamp'])
                if 'caption' in p and not isinstance(p['caption'], str):
                    raise ValueError()
                posts[p['id']] = p
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
    url = env.get('DISCORD_WEBHOOK_URL', '')
    if not re.fullmatch(r'https://discord\.com/api/webhooks/\d+/[A-Za-z0-9_-]+', url):
        raise MonitorError('invalid or missing DISCORD_WEBHOOK_URL')
    request(url + '?wait=true', payload={'content': text[:1900], 'allowed_mentions': {'parse': []}})


def initial_state():
    return {'version': 1, 'initialized': False, 'seen': [], 'pending': None,
            'failures': 0, 'alerted': False, 'last_success': None, 'last_run': None}


def run(state, fetch, send, save, now):
    state['last_run'] = now.isoformat()
    try:
        if state['pending']:
            raise MonitorError('uncertain prior delivery; resolve pending in state before resuming')
        posts = fetch()  # Must finish all pages before changing baseline or sending.
        if not state['initialized']:
            state['seen'] = [p['id'] for p in posts]
            state['initialized'] = True
        else:
            for p in posts:
                if p['id'] in state['seen']:
                    continue
                state['pending'] = p['id']
                save(state)  # Durable BEFORE sending: no blind retry after a crash.
                local = timestamp(p['timestamp']).astimezone(dt.timezone(dt.timedelta(hours=9)))
                send(f'南陽醸造 新規投稿\n投稿日時: {local:%Y-%m-%d %H:%M:%S} JST\n{p["permalink"]}\n{p.get("caption", "（本文なし／取得不可）")[:1500]}')
                state['seen'].append(p['id'])
                state['pending'] = None
                save(state)
        if state['last_success'] and now - timestamp(state['last_success']) > dt.timedelta(minutes=90):
            send('監視の空白を検出しました（前回成功から90分超）。取得可能な投稿を再確認しました。')
        if state['alerted']:
            send('Instagram投稿取得が復旧しました。')
        state.update(failures=0, alerted=False, last_success=now.isoformat())
        save(state)
        return 0
    except MonitorError as e:
        state['failures'] += 1
        state['last_error'] = str(e)
        print('ERROR:', e, file=sys.stderr)
        if state['failures'] >= 3 and not state['alerted']:
            try:
                send(f'Instagram監視障害: {state["failures"]}回連続失敗。GitHub Actionsのログを確認してください。\n{e}')
                state['alerted'] = True
            except MonitorError:
                print('ERROR: failure alert delivery failed', file=sys.stderr)
        save(state)
        return 1


def main():
    path = Path('state/state.json')
    if path.exists():
        try:
            state = json.loads(path.read_text())
            expected = initial_state()
            if state.get('version') != 1 or any(k not in state for k in expected):
                raise ValueError()
            if (not isinstance(state['seen'], list)
                    or any(not isinstance(i, str) or not i.isdigit() for i in state['seen'])
                    or type(state['failures']) is not int or state['failures'] < 0
                    or type(state['initialized']) is not bool or type(state['alerted']) is not bool
                    or (state['pending'] is not None and
                        (not isinstance(state['pending'], str) or not state['pending'].isdigit()))):
                raise ValueError()
            if state['last_success'] is not None:
                timestamp(state['last_success'])
        except (ValueError, TypeError, AttributeError):
            raise MonitorError('state corrupted; restore from Git history') from None
    elif os.environ.get('INITIALIZE') == 'true':
        state = initial_state()
    else:
        raise MonitorError('state missing; use manual initialize=true only for first setup')

    def save(value):
        path.parent.mkdir(exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        temp.replace(path)
        if os.environ.get('PERSIST_GIT') == 'true':
            # A persistence failure must stop execution before any later webhook.
            subprocess.run(['git', 'add', str(path)], check=True)
            changed = subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode
            if changed:
                subprocess.run(['git', 'commit', '-m', 'Update monitor state [skip ci]'], check=True, stdout=subprocess.DEVNULL)
                subprocess.run(['git', 'push', 'origin', 'HEAD'], check=True, stdout=subprocess.DEVNULL)
    return run(state, lambda: fetch_posts(os.environ), lambda s: discord(s, os.environ), save,
               dt.datetime.now(dt.timezone.utc))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except MonitorError as e:
        print('ERROR:', e, file=sys.stderr)
        sys.exit(1)
