"""Durable state with optimistic concurrency and reconciliation after lost replies."""
import base64
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request


class StateError(RuntimeError):
    pass


class HTTPFailure(Exception):
    def __init__(self, status):
        self.status = status


def github_request(method, url, token, body=None):
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'HanaabiMonitor/2.0'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise StateError('GitHub state response too large')
            return json.loads(raw)
    except urllib.error.HTTPError as error:
        raise HTTPFailure(error.code) from None
    except (OSError, ValueError):
        raise HTTPFailure(0) from None


def encode(state):
    return (json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


class FileStore:
    def __init__(self, path):
        self.path = Path(path)
    def read(self):
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except ValueError:
            raise StateError('state JSON corrupted; restore from history') from None
    def save(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_bytes(encode(state))
        temp.replace(self.path)


class GitHubStore:
    def __init__(self, repository, branch, path, token, request=github_request, sleep=time.sleep):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise StateError('invalid state repository')
        if branch != 'monitor-state' or not re.fullmatch(r'state/[a-z0-9_.-]+\.json', path):
            raise StateError('invalid state location')
        if not token:
            raise StateError('GitHub state token is missing')
        self.url = 'https://api.github.com/repos/' + repository + '/contents/' + path
        self.branch, self.path, self.token = branch, path, token
        self.request, self.sleep, self.sha = request, sleep, None
        self.loaded = False

    def _read_remote(self):
        try:
            result = self.request('GET', self.url + '?' + urllib.parse.urlencode({'ref': self.branch}), self.token)
        except HTTPFailure as error:
            if error.status == 404:
                return None, None
            raise StateError(f'GitHub state read failed (HTTP {error.status})') from None
        try:
            content = base64.b64decode(result['content'], validate=False)
            state = json.loads(content)
            sha = result['sha']
            if not isinstance(state, dict) or not isinstance(sha, str):
                raise ValueError()
            return state, sha
        except (KeyError, ValueError, TypeError):
            raise StateError('invalid GitHub state response; refusing initialization') from None

    def read(self):
        # A read-only request is safe to retry; no webhook is repeated.
        for attempt in range(3):
            try:
                state, self.sha = self._read_remote()
                self.loaded = True
                return state
            except StateError:
                if attempt == 2:
                    raise
                self.sleep((2, 5)[attempt])

    def save(self, state):
        if not self.loaded:
            raise StateError('state must be read before update')
        # Keep an emergency copy for inspection, never use it as authority on the next runner.
        journal = Path('work/runtime') / Path(self.path).name
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_bytes(encode(state))
        body = {'message': 'Update ' + self.path + ' [skip ci]', 'branch': self.branch,
                'content': base64.b64encode(encode(state)).decode()}
        if self.sha:
            body['sha'] = self.sha
        for attempt in range(3):
            try:
                result = self.request('PUT', self.url, self.token, body)
                new_sha = result['content']['sha']
                if not isinstance(new_sha, str) or not new_sha:
                    raise KeyError('missing SHA')
                self.sha = new_sha
                return
            except (HTTPFailure, KeyError, TypeError):
                # A PUT can succeed even if its response is lost. Reconcile first.
                try:
                    remote, remote_sha = self._read_remote()
                except StateError:
                    remote, remote_sha = None, self.sha
                if remote == state:
                    self.sha = remote_sha
                    return
                if remote_sha != self.sha:
                    raise StateError('state changed concurrently; stopped without overwriting')
                if attempt < 2:
                    self.sleep((2, 5)[attempt])
        raise StateError('GitHub state save unconfirmed; stopped before further delivery')


def make_store(path):
    if os.environ.get('STATE_BACKEND') == 'github':
        return GitHubStore(os.environ.get('GITHUB_REPOSITORY', ''), 'monitor-state', path,
                           os.environ.get('STATE_GITHUB_TOKEN', ''))
    if os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('STATE_BACKEND') != 'local':
        raise StateError('workflow must set STATE_BACKEND=github; use a new Run workflow')
    return FileStore(path)
