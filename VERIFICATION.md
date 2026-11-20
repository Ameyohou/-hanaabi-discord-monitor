# 検証結果（2026-11-18 JST）

- Instagramプロフィールへの通常GET：HTTP 200、プロフィールタイトル取得。取得HTMLには `/p/`、`/reel/`、`taken_at`、`edge_owner_to_timeline_media`、`media_count`、`xdt_api` なし。実投稿の日時・URL・本文の組を抽出できず。
- Web取得サービス経由：HTTP 429。応答元がInstagramか中継かは断定不可。制限回避や再試行の連打は行わず。
- Meta公式ドキュメントは検索結果でBusiness Discoveryの存在・対象種別を確認。直接取得は429。最新の必要権限・審査要件は導入時に公式画面で再確認が必要。
- Meta公式API実通信：2026-11-20に利用者がGraph API Explorer v27.0で実行し、共有された応答で hanaabi_official の通常投稿3件（FEED）の本文・URL・日時を確認。こちらからの認証付き実通信、全ページ取得、GitHubランナー経由は未検証。
- Discord実配送：Webhook未提供のため未実施。
- ローカル自動テスト：18件成功。HTTP障害などはモックによる検証で、Instagramの実取得成功を意味しない。
- GitHub Actions：3つのYAMLをパース確認。GitHubのリポジトリ未指定・Secrets未登録のため、GitHub上での実行、状態コミットとpush、定期起動は未検証。
- 動作に必要な外部Pythonパッケージなし。

## 残作業

1. 公式API認証の前提を満たすか確認。満たせない場合はREADMEの代替案を選ぶ。
2. 公開GitHubリポジトリ作成とファイルの配置。
3. Secrets 3件とAPIバージョン変数1件を登録。
4. TestsとVerify connectionのfetch/discordを実行。Instagramの実投稿と日時を照合。
5. 初回のみinitialize=trueで実行し、状態が保存されることを確認。
6. initialize=falseで再実行し、既存投稿の重複通知がないことを確認。
7. 次の新規投稿で実通知を確認。Actions履歴とトークン期限を継続確認。

## 納品保存先について

指定された `/codex/browser/projectless/0001-github-instagram-hanaabi-official-discord-github/output` は、この実行環境ではルートファイルシステムが読み取り専用で作成できません。書込権限の付与後も同じでした。代わりに `/workspace/output` にZIPとREADMEを保存しました。コードの作成・ローカルテストには影響しません。
