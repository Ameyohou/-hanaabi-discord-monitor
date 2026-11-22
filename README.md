# 南陽醸造 Instagram → Discord 通知

南陽醸造 `hanaabi_official` の通常投稿をMeta公式APIで取得し、新規投稿をDiscord Webhookに送ります。BBC News `bbcnews` は通常投稿＋リールの実運用テスト対象です。PCの常時起動は不要です。

## 現在の運用可否

**投稿取得・Discord配送は実確認済みですが、「必ず30分以内の検知」はGitHub Actions単独では保証できません。** 実履歴でも数時間の起動空白が発生しています。起動回数を増やすだけで解決済みとは扱いません。

2026-11-23 JSTの見直しでは、Git pushに依存した状態保存を廃止し、専用ブランチとGitHub Contents APIによる競合検出付き保存へ変更しました。コード修正と状態更新を分離し、保存失敗・取得失敗・配送失敗を区別します。検証結果と残る制約は [AUDIT.md](AUDIT.md) を参照してください。

公開リポジトリの標準 `ubuntu-latest` ランナーを使うため、現行のGitHub料金ではランナー利用は無料です。Privateや大型ランナーへの変更は無料継続の前提から外れます。Pythonの外部依存なし。将来の料金・API仕様変更は保証しません。

## 構成と通知範囲

|対象|取得対象|状態ファイル（monitor-stateブランチ）|
|---|---|---|
|南陽醸造|FEEDのみ。通常の画像・カルーセル・フィード動画|`state/state.json`|
|BBCテスト|FEEDとREELS。STORY/ADは対象外|`state/bbcnews.json`|

- 通知は投稿日時（JST）、URL、取得できる本文（1500文字まで）。メンションは無効。
- 初回成功時は取得済み投稿を既存として記録し、投稿通知しません。
- 同じIDは再通知しません。本文編集だけでは通知しません。
- BBCは初回移行時の既存リールを記録し、移行前の古い未記録投稿は通知しません。
- 南陽醸造は最大20ページ×100メディアの全ページを確認します。
- BBCは前回の**配送・保存まで成功した時刻から24時間前**まで遡ります。すべてのメディアが境界より古いページまで確認し、既知IDや固定投稿だけを根拠に止めません。初回だけ直近1ページを基準にします。
- 必要ページを取得し終えてから通知します。途中失敗・不正JSON・不明な種別・取得上限超過はエラーです。
- APIに出ない投稿、削除済み投稿、取得期間を超えて遅れて公開された投稿、非公開・権限外の投稿の取得は保証しません。

## 起動間隔と監視の空白

自動起動は `Instagram monitor` に統合しました。毎時7/17/27/37/47/57分にGitHubへ起動機会を設定し、永続状態で前回の試行から30分未満なら外部APIを呼ばず終了します。南陽醸造・BBCは同じ実行で順に確認します。BBC専用ワークフローは手動確認だけです。

これは起動欠落への余裕であり、GitHubの遅延をなくす仕組みではありません。**GitHub自身が起動しなかった時間帯を、そのGitHubジョブ自身が通知することもできません。** 前回成功から90分超の場合、次回成功時に監視空白を通知します。この文言は「空白中も監視できていた」という意味ではありません。

厳密な30分周期が必要なら、独立した外部スケジューラによる起動または実行基盤の変更が必要です。外部サービスは勝手に開設・有効化していません。[extras/](extras/) の外部起動案は任意です。

[GitHub公式のschedule制約](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) に遅延・欠落と公開リポジトリの60日非活動による無効化が記載されています。週1回はActions履歴を確認し、GitHubの失敗メール通知を有効にしてください。

## 状態保存・重複防止・配送の限界

正本は **`monitor-state` ブランチ**です。`main` の `state/` は移行時点の旧記録で、実行時には読みません。Git履歴から復元できます。本文やトークンは状態に保存しません。投稿ID・URL・DiscordメッセージID・取得状況は公開されます。

保存はGitHub Contents APIで元のファイルSHAを指定して更新します。同時変更を検出したら上書きせず停止します。応答が失われた場合は遠隔状態を再読込して一致を照合し、一致すれば成功と判定。不一致かつ元のSHAのままなら同じ保存を最大3回まで試行します。`git push`、force push、rebaseは使いません。

配送手順：

1. 実行開始を永続化する。失敗したらInstagramにもDiscordにも進まない。
2. 必要な全ページを取得・検証。
3. 投稿IDを `pending` に保存してからDiscordへPOST。
4. Discord受理後、IDを `seen` に移し、`pending` を消して保存。
5. 全通知と最終保存が済んだときだけ `last_success` を更新。

**Discord WebhookとGitHubの間に共通トランザクションはないため、完全な配送保証と完全な重複防止は同時には保証できません。** 送信後のネットワーク切断などで成否不明なら、`pending` を残して停止し、盲目的な再送をしません。HTTP 4xxの明確な拒否ならpendingを解除し、次の確認時に再試行できます。HTTP 429をその場で連打しません。レート制限や待機指示がある場合はサービスの指示を優先してください。

`pending` で止まった場合：

1. 対象の定期実行を一時停止。
2. monitor-stateブランチの `pending_url` をDiscordと照合。
3. 届いていればIDをseenに追加しpendingをnullにする。届いていないことを確認できた場合はseenに追加せずpendingだけnullにする。
4. 不明ならそのまま止め、確認が取れるまで再送しない。
5. ファイル変更を保存して手動実行。

保存失敗時はGitHubの実行Summaryと7日保持の `recovery-...` artifactに診断用コピーを残します。このコピーは自動で正本として採用しません。状態保存・設定の異常は別経路でDiscord通知を試みますが、Webhook自体やGitHub全体の停止では通知できません。

## 障害の記録と復旧

Summaryに対象ごとの `status`、`fetched`、`sent`、`already_seen`、`last_fetch_success`、`last_success`、`failures`、`pending` が出ます。

|状態|意味と対応|
|---|---|
|`success`|取得・配送・最終保存が成功。sent=0なら未通知投稿なし|
|`not_due`|前回試行から30分未満。APIへアクセスしていない|
|`failed`|取得や明確な配送拒否。詳細エラーと時刻を確認|
|`delivery_uncertain`|配送成否不明。上記pending手順で確認|
|`error` / `state_save_failed`|状態保存や設定が失敗。Summary・artifact・GitHub権限を確認|

取得等の失敗が3回続いた場合に障害通知、復旧時に復旧通知を送ります。実行自体が数時間遅れたら「3回」は90分とは限りません。状態保存ができない障害は回数を正確に保存できないため、別の運用通知を試みます。運用通知は異常終了時に重複する場合があります。

Meta `200/5258005 API access blocked` を検出した対象は、所有者の確認までAPI呼出しを止めます。Metaの「必要なアクション」や本人確認を解消後、Verify connectionのfetchを一度実行して成功を確認し、Instagram monitorのRun workflowで `resume_meta` を選んで再開します。制限回避はしません。

## 導入（新規）

既に導入済みなら、初期化・トークン再発行・既存状態の削除は不要です。

1. 無料のGitHubアカウントでPublicリポジトリを作成し、このコード一式を直下に置きます。
2. `monitor-state` ブランチをmainから作成します。既存導入では状態ファイルを保持して移行します。
3. MetaのInstagram API **with Facebook Login** をセットアップ。管理するInstagramプロアカウントとFacebookページを連携し、アプリと必要な権限を用意します。対象もAPI対応プロアカウントである必要があります。
4. 必要権限は公式Business Discovery手順で確認。今回確認したものは `instagram_basic`、`instagram_manage_insights`、`pages_read_engagement`、ページ確認に `pages_show_list`。アプリのモードや利用者によって審査・事業者確認が必要な場合があります。
5. Settings → Secrets and variables → Actionsで以下を登録します。

|区分|名前|値|
|---|---|---|
|Secret|`META_ACCESS_TOKEN`|長期化後の文字列。短期トークンと別物です|
|Secret|`META_IG_USER_ID`|自分側の数値IG ID。今回 `17841464909360076`|
|Secret|`DISCORD_WEBHOOK_URL`|Discordのチャンネル設定→連携サービス→WebhookのURL|
|Variable|`META_API_VERSION`|今回実確認した `v27.0`|
|Variable|`MONITOR_ENABLED`|自動監視開始後は `true`|
|Variable|`BBC_TEST_ENABLED`|BBCテストを停止する場合だけ `false`|

`GITHUB_TOKEN` はActionsから自動供給され、状態保存用ジョブだけ `contents: write` を使います。GitHub個人トークンの追加は不要です。組織ポリシーで書込禁止の場合は動きません。

6. Testsの成功を確認。
7. Verify connectionを `fetch` で実行し件数・最新日時をInstagramと照合。
8. Verify connectionを `discord` で実行し、テスト通知が届くか確認。
9. Instagram monitorを初回だけ `initialize=true` で実行。既存投稿通知は来ません。
10. `MONITOR_ENABLED=true` で自動確認を有効化。再実行して既存投稿が重複しないことを確認します。

トークン値はチャット・Issues・公開ファイルに貼りません。デバッガーで期限と実際の権限を確認し、期限前にSecretsを差し替えます。表示される期限を延ばしただけでGitHubの値は更新されません。Metaの本人確認やトークン失効は人の対応が必要です。

## 手動確認

- 通信だけ：Actions → Verify connection → `fetch`（状態を変更しない）
- Discordテスト：同画面で `discord`（テスト通知を1件送る）
- 本番とBBCをすぐ確認：Actions → Instagram monitor → Run workflow
- BBCだけ確認：Actions → BBC test monitor → Run workflow
- 同じ投稿が再通知されないか：成功後にもう一度手動実行し、Summaryの `sent=0` を確認

古い実行のRe-run jobsより、現在のワークフローから新しくRun workflowを使用してください。コードが更新済みでも、古いワークフローの環境変数は古いままの場合があります。

スマホ通知はDiscord・OS側でチャンネルの「すべてのメッセージ」と通知許可を有効にしてください。Discordに配送されたことと、スマホにプッシュが出ることは別です。

## テスト

```sh
python -m unittest discover -s tests -v
```

外部通信なしで実施します。HTTP 401/403/429/500、不正JSON・応答、ページング途中失敗、固定投稿と時間範囲、対象種別、初期化、リール移行、ID重複防止、送信前保存失敗、送信後の応答喪失、別runnerからの再開、保存競合、APIブロック、起動間隔を確認します。単体テスト成功だけで定期起動やMetaの継続アクセスが保証されるわけではありません。

## 代替案と公式資料

Metaが利用できない場合はInstagramアプリの投稿通知を使うか、南陽醸造側の許諾された別フィードを検討します。匿名スクレイピング、非公開API、Cookie流用、CAPTCHAやアクセス制限の回避、有料代行は使いません。

- [Meta Business Discovery](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery/)
- [GitHub schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub Contents API](https://docs.github.com/en/rest/repos/contents)
- [GitHub Actions料金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
