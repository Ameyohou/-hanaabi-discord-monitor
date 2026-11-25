"""Notify persistence/setup failures that cannot safely be recorded in remote state."""
import json
import os
from pathlib import Path
from monitor import discord, MonitorError

path = Path('work/runtime/summary.json')
if path.exists():
    results = json.loads(path.read_text())
    failures = [name for name, result in results.items() if result.get('status') in ('error', 'state_save_failed')]
    if failures:
        try:
            discord('監視システムの状態保存または設定に失敗しました。対象: ' + ', '.join(failures) +
                    '。安全のため、この回の処理を中断しました。定期起動は継続し、次回も保存状態を確認します。GitHub ActionsのSummaryと障害記録を確認してください。', os.environ)
        except MonitorError as error:
            print('Operational alert delivery failed:', error)
