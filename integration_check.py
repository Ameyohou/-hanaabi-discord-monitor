"""Explicit live delivery check using one existing post and isolated durable state."""
import datetime as dt
import json
import os
import sys
from monitor import fetch_posts, discord, initial_state, run, MonitorError, record_summary
from state_store import make_store, StateError


def main():
    store = make_store('state/integration.json')
    previous = store.read()
    if previous and previous.get('pending'):
        raise StateError('previous integration delivery is uncertain; inspect Discord before repeating')
    posts = fetch_posts(os.environ, target='bbcnews', recent_baseline=True, include_reels=True)
    if not posts:
        raise MonitorError('no BBC media available for live verification')
    post = posts[-1]
    state = initial_state()
    state['initialized'] = True  # Explicit diagnostic only; production baselines are never touched.
    state['test_run_id'] = os.environ.get('GITHUB_RUN_ID', 'local')
    now = dt.datetime.now(dt.timezone.utc)
    label = '【動作確認・既存投稿を使用】BBC News'
    first = run(state, lambda: [post], lambda text: discord(text, os.environ), store.save, now, label)
    if first or state['last_result']['sent'] != 1:
        raise StateError('first live diagnostic delivery did not complete')
    message_id = state.get('last_discord_message_id')
    if not message_id:
        raise StateError('Discord did not return a message receipt')
    # Re-read authority, as a fresh runner would. Production files are not involved.
    state = store.read()
    second = run(state, lambda: [post], lambda text: discord(text, os.environ), store.save,
                 dt.datetime.now(dt.timezone.utc), label)
    if second or state['last_result']['sent'] != 0:
        raise StateError('duplicate suppression verification failed')
    result = {'status':'success','first_sent':1,'second_sent':0,'discord_message_id':message_id,
              'post_url':post['permalink'],'production_state_changed':False}
    record_summary('integration', result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (MonitorError, StateError) as error:
        record_summary('integration', {'status':'error','error':str(error)})
        print('ERROR:', error, file=sys.stderr)
        sys.exit(1)
