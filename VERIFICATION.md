# 検証記録

## 2026-11-23 JST 再設計

- ローカル自動テスト：49件成功（GitHub Actionsと同じGITHUB_ACTIONS=true / STATE_BACKEND=local条件でも確認）。
- 4つのワークフローYAMLをパース確認。
- GitHub公式actions/checkout、setup-python v6のタグが指すSHAを公式リポジトリで確認して固定。Node.js 20警告の対象部品を更新。
- 通知済み状態の移行元を確認：南陽醸造371 ID、BBC108 ID。両方ともinitialized=true、pending=null。実行中・queuedのワークフローなし。
- 移行元mainのSHA：2dae311cc3dadb621d9d14f1bf438a0cf5b2685c。
- monitor-stateブランチを上記SHAから作成し、状態をそのまま保持。
- 新しいContents APIによる本番保存・再実行の結果は、この変更のデプロイ後に確認する。
- 任意のCloudflare dispatcher：通信を模擬したテストのみ成功。外部サービスには未導入、認証情報未登録。

## 既存の実確認

- 南陽醸造：公式APIで通常投稿371件を取得。
- BBC：通常投稿とリールを取得し、新規投稿をDiscordに配送。利用者から実メッセージ受信を確認済み。
- Metaアカウントの明示的ブロックは所有者の本人確認後に解消し、手動取得成功を確認済み。将来の失効・ブロックを保証するものではない。
- 旧状態保存のGit push失敗と定期起動の数時間の空白を実ログで確認。従来の構成を安定運用済みとは扱わない。

## 最終判定の制約

テスト成功・手動再実行成功は、今後の全scheduleの30分以内起動を証明しない。GitHub側の定期起動保証がないため、この点は未達／外部起動経路の検討が必要。
