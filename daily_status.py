"""One honest daily status message after 20:00 JST, using the existing trigger."""
import datetime as dt
import json
from pathlib import Path
import sys
import os
from monitor import discord, timestamp, MonitorError, record_summary
from state_store import make_store, StateError

JST = dt.timezone(dt.timedelta(hours=9))


def render(state, now):
    def local(value):
        return timestamp(value).astimezone(JST).strftime('%m/%d %H:%M') if value else '記録なし'
    try:
        success = timestamp(state['last_success']) if state.get('last_success') else None
        fresh = success is not None and dt.timedelta(0) <= now - success <= dt.timedelta(minutes=45)
        healthy = (fresh and state.get('last_result', {}).get('status') == 'success'
                   and not state.get('pending') and not state.get('provider_blocked')
                   and state.get('failures', 0) == 0)
        label = '✅ 南陽醸造の監視：正常稼働' if healthy else '⚠️ 南陽醸造の監視：要確認'
        text = (label + '\n日次確認: ' + now.astimezone(JST).strftime('%Y/%m/%d %H:%M JST')
                + '\n最終確認成功: ' + local(state.get('last_success')) + ' JST'
                + '\n最終試行: ' + local(state.get('last_run')) + ' JST'
                + '\n連続失敗: ' + str(state.get('failures', 0)) + '回'
                + '\n監視対象: 通常投稿（BBCテストは停止中）')
        if healthy:
            text += '\n新規投稿がなくても監視は継続しています。'
        elif state.get('pending'):
            text += '\n送信結果が不明な投稿があり、自動再送を停止しています。'
        elif state.get('provider_blocked'):
            text += '\nMetaのアクセス制限の確認が必要です。'
        else:
            text += '\n直近の成功から時間が空いているか、処理に失敗しています。ActionsのSummaryを確認してください。'
        return text
    except (MonitorError, TypeError, ValueError):
        return '⚠️ 南陽醸造の監視：状態を判定できません。記録の形式を確認してください。'


def send_daily(now, state_store, report_store, send, hour=20):
    if now.astimezone(JST).hour < hour:
        return 'not_due'
    day = now.astimezone(JST).date().isoformat()
    report = report_store.read() or {}
    if report.get('sent_date') == day:
        return 'already_sent'
    if report.get('pending_date') == day:
        raise StateError('daily status delivery is uncertain; do not blindly resend today')
    try:
        state = state_store.read()
        message = render(state, now) if isinstance(state, dict) else '⚠️ 南陽醸造の監視：状態記録が見つからず、正常とは判定できません。'
    except StateError:
        message = '⚠️ 南陽醸造の監視：状態記録を取得できず、正常とは判定できません。Actionsを確認してください。'
    if report.get('pending_date'):
        report['last_uncertain_date'] = report['pending_date']
    report['pending_date'] = day
    report_store.save(report)
    try:
        receipt = send(message)
    except MonitorError as error:
        if error.status is not None and 400 <= error.status < 500:
            report['pending_date'] = None
            report_store.save(report)
        raise
    report.update(sent_date=day, pending_date=None, sent_at=dt.datetime.now(dt.timezone.utc).isoformat())
    if isinstance(receipt, dict):
        report['discord_message_id'] = receipt.get('id')
    report_store.save(report)
    return 'sent'


def main():
    config = json.loads(Path(__file__).with_name('monitor_config.json').read_text())
    now = dt.datetime.now(dt.timezone.utc)
    if '--dry-run' in sys.argv:
        print(render(make_store('state/state.json').read() or {}, now))
        return 0
    result = send_daily(now, make_store('state/state.json'), make_store('state/daily-status.json'),
                        lambda text: discord(text, os.environ), config['daily_status_hour_jst'])
    record_summary('daily_status', {'status': result})
    print('Daily status:', result)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (MonitorError, StateError) as error:
        print('ERROR:', error, file=sys.stderr)
        record_summary('daily_status', {'status':'error','error':str(error)})
        sys.exit(1)
