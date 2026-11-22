# 南陽醸造 Instagram → Discord 通知

## 現状（最初にお読みください）

**2026年11月20日、利用者がGraph API Explorer v27.0で実行した結果により、公式APIで対象の通常投稿3件の本文・URL・日時・FEED種別を取得できることを確認しました。** この確認は利用者が共有したAPI応答に基づきます。GitHub Actions上からの接続とDiscord配送は、Secrets登録後の確認が必要です。

初期の匿名公開ページ検証では、HTTP 200のHTMLに投稿一覧がなく、別のWeb取得経路は429でした。このため匿名スクレイピングには依存しません。

非公開API、ログインCookie流用、プロキシ切替、ブラウザー偽装、CAPTCHA回避、スクレイピング代行は使用しません。公式の **Instagram API with Facebook Login / Business Discovery** だけを実装しています。対象の取得権限と3件の実投稿応答は確認済みですが、複数ページの実通信とActions実行は未検証です。匿名でそのまま動く完成サービスではありません。

## できること

- GitHub Actionsで毎時17分・47分（30分間隔、UTC。日本時間も分は同じ）に起動。PCの常時起動は不要。
- `hanaabi_official` の通常フィード投稿のみ通知。画像・カルーセル・FEED動画を対象とし、REELS/STORYは除外。
- 投稿日時（JST）、URL、取得可能な本文を通知。本文はDiscordの文字数制約により最大1500文字。メンション無効化。
- 初回の**成功した取得**で既存投稿をすべて記録し、投稿通知を送らない。
- 投稿IDをGit管理の `state/state.json` に保存。キャッシュ・期限付きartifactに依存しない。
- 全ページを取得し終えてから通知。HTTPエラー・JSON不正・スキーマ不正・途中ページの失敗をエラーとして記録し、終了コード1にする。
- 3回連続失敗で障害通知（約90分が目安、実行遅延で変動）。同じ障害は1回通知し、復旧も通知。障害通知に失敗したら次の実行で再試行。
- 最終成功から90分を超えた場合、次の取得成功時に監視の空白を通知。取得できる未通知投稿を古い順に補完。
- 依存パッケージなし。Python標準ライブラリーのみ。

## 無料運用の条件と限界

**Public（公開）リポジトリ＋標準のubuntu-latestランナー**を使ってください。GitHubの公開リポジトリ向け標準Actionsランナーは無料です。Privateでは無料枠の消費量が月の日数・実行時間・他の用途で変わるため、無料継続を保証できません。大型ランナー、有料サービス、課金APIは使いません。将来の各サービスの料金・仕様変更は保証できません。

コード・投稿ID・取得日時・失敗状況は公開されます。本文と認証情報は状態ファイルに保存しません。WebhookとMetaトークンは必ずSecretsに入れてください。公開できない場合はこの構成を使わず料金条件を再検討してください。

GitHub Actionsのscheduleは厳密なタイマーではなく、遅延・実行の欠落があります。60日間リポジトリ活動がない公開リポジトリではscheduleが無効になる場合もあります。本実装は実行ごとに状態をコミットしますが、永続化失敗やワークフロー停止時はこれを頼りにできません。週1回はActions画面で動作を確認してください。停止中のシステム自身からDiscord通知は送れません。GitHubの失敗通知メールも有効にしてください。独立した外部死活監視は含みません。

APIに残っていない削除済み投稿や取得権限外の投稿は補完できません。1回の取得は100件×最大20ページ。上限を超える場合は部分取得を成功扱いせず停止します。初期取得件数が多いアカウントではAPI利用量に注意してください。429やネットワーク失敗をその場で自動再試行せず、次の定期実行まで待ちます。Metaがより長い待機を要求した場合はワークフローを無効にして待ってください。

## GitHubが初めての方向け

GitHubはコードを保管するサービスです。「リポジトリ」はこの仕組み一式を入れる箱、「Actions」はGitHub側のコンピューターで定期実行する機能、「Secrets」はパスワード等をコードと分けて保存する場所です。

### 1. 公式APIが利用できるか確認する（重要な前提）

Meta Business Discoveryを使うには、一般に**ご自身が管理するInstagramプロアカウント（ビジネスまたはクリエイター）と、それに紐づくFacebookページ**、Meta開発者アプリ、Facebook Loginによる適切な権限のアクセストークンが必要です。調査対象もAPI対応のビジネス／クリエイターアカウントである必要があります。対象が個人アカウントならこのAPIは使えません。

1. [Meta for Developers](https://developers.facebook.com/) でアプリを作成し、Instagram API **with Facebook Login** の公式セットアップを進めます。Instagram LoginだけではこのBusiness Discovery構成は使えません。
2. ご自身のプロアカウントとFacebookページを連携し、公式手順で `instagram_basic`、`instagram_manage_insights`、`pages_read_engagement` 等のBusiness Discoveryに必要な権限を確認します。ページの列挙には別途 `pages_show_list` 等が必要になる場合があります。アプリのモード・利用者・権限により審査や事業者確認が必要な場合があります。現在の公式ドキュメントの指示を優先してください。
3. 公式Graph API Explorer等でトークンを取得し、**自分側のInstagramユーザーID**を確認します。対象のユーザーIDでもInstagramユーザー名でもありません。
4. アプリで利用可能なGraph APIバージョン（今回の取得確認：`v27.0`。実際にサポートされるものを確認）を確認します。
5. 後述のVerify connectionのfetchで、対象の実投稿件数が取得できることを確認します。成功するまで定期運用を始めないでください。

この認証セットアップはDiscordだけでは完結しません。ご自身のプロアカウントがない・審査を通せない場合は、下記の代替案を選んでください。トークンには有効期限・失効があります。公式ツールで期限を確認して更新し、Secretsを差し替えてください。自動延命や無断ログインは実装していません。

### 2. Discordの通知先を作る

通知したいサーバーのチャンネル設定 →「連携サービス」→「ウェブフック」→ 新規作成 →「ウェブフックURLをコピー」。Webhookを作成できる権限が必要です。URLはパスワードと同様の秘密情報です。チャットに貼る必要はありません。

### 3. GitHubにファイルを入れる

1. [GitHub](https://github.com/)で無料アカウントを作成します。
2. 右上の「＋」→「New repository」。名前は例 `hanaabi-discord-monitor`。**Public**を選択し、README追加にチェックして作成します。
3. 配布ZIPを解凍し、`.github` フォルダー、`monitor.py`、`tests`、`README.md`、`.gitignore` をリポジトリの直下に入れます。外側の `hanaabi-monitor` フォルダーごと入れないでください。
4. Web画面の「Add file」→「Upload files」で追加し、「Commit changes」で保存します。隠しフォルダー `.github` が見えない場合はPCの隠しファイル表示を有効にします。アップロードできない場合は「Add file」→「Create new file」で `.github/workflows/monitor.yml` 等のパスを入力して内容を貼り付けてください。
5. `Code` 画面で `.github/workflows/` の下に3つのYAMLがあることを確認します。

リポジトリは公開されますが、次のSecretsの値は公開しません。ZIPやコードにURL・トークンを書き込まないでください。

### 4. Secretsと変数を登録する

リポジトリの Settings → Secrets and variables → Actions → **Secrets** → New repository secret で以下を1件ずつ登録します。

|名前|値|
|---|---|
|`DISCORD_WEBHOOK_URL`|コピーしたDiscord Webhook URL（discord.com形式）|
|`META_ACCESS_TOKEN`|Metaの公式アクセストークン|
|`META_IG_USER_ID`|自分側の連携済みInstagramプロアカウントの数値ID|

同じ画面の **Variables** → New repository variable：

|名前|値|
|---|---|
|`META_API_VERSION`|利用可能なAPIバージョン。今回の取得確認は `v27.0`|

Settings → Actions → GeneralでActionsを許可します。組織側ポリシーやブランチ保護でbotの状態コミットを禁止している場合、この構成は動きません。個人用の新規専用リポジトリが簡単です。状態更新用に監視ジョブだけ `contents: write` を要求します。外部からのPRでSecretsを使う設定はありません。

### 5. 動作確認してから初期化する

1. Actions → **Tests** の最新実行が緑になっていることを確認します。
2. Actions → **Verify connection** → Run workflow → mode=`fetch`。成功し、ログに `Validated FEED posts:` の件数と最新日時が出ることを確認。Instagramで見える最新の通常投稿と日時を照合してください。投稿本文はログに出しません。
3. 同じVerify connectionをmode=`discord`で実行。テスト通知が1件届くことを確認します。どちらも状態は変更しません。
4. Actions → **Instagram monitor** → Run workflow → `initialize` にチェックを入れて実行。既存投稿の通知は来ません。Code画面に `state/state.json` ができ、`initialized: true` になっていることを確認します。
5. 今度はinitializeのチェックを外して手動実行。新規投稿がなければ通知されません。
6. Settings → Secrets and variables → Actions → Variablesで `MONITOR_ENABLED` を値 `true` で追加します。これで毎時17分・47分の自動確認を有効化します。未登録の間は定期ジョブをスキップします。新規投稿の通知は実際の新しい投稿を待って確認してください。

初期化チェックは状態ファイルがない初回のみの許可です。既存状態があれば初期化し直しません。最初の取得失敗時に作成される `initialized: false` の状態は、後の最初の成功時に初期化されます。状態ファイルを削除して初期化し直すと、その間の投稿が既存扱いになるため削除しないでください。

## 障害時の確認・復旧

Actions → Instagram monitor → 赤い実行 → Monitorを開いて `ERROR:` を確認します。

|表示・状況|対応|
|---|---|
|HTTP 401/403、API error|トークン期限・アプリ権限・アカウント種別を公式ツールで確認しSecretsを更新|
|HTTP 429|アクセスを増やさず停止して待機。公式の利用量・待機指示を確認|
|missing fields / unexpected response|APIの仕様・権限・APIバージョンを確認。空一覧に置換しない|
|state missing / corrupted|GitHubのファイル履歴から直前の正常状態を復元。初期化で誤魔化さない|
|git push failed|Actions書込権限・ブランチ保護・同時手動編集を確認。送信前保存失敗なら投稿は送信されない|
|通知が止まる・実行履歴が増えない|Actionsの有効状態、デフォルトブランチのYAML、GitHub Statusを確認し手動実行|
|障害通知も届かない|Discord Webhookと権限を確認。GitHub側停止や永続化失敗ではDiscordへの通知は保証できない|

### 送信成否が不明な場合（pending）

Discord Webhookにはこの用途の重複排除トランザクションがありません。「Discordに届いた直後にGitHubへの保存が失敗」等では、完全な重複防止と完全な配送保証を同時には実現できません。本実装は**通常投稿の自動重複送信防止を優先し、不明時は停止**します。通信エラーが明確な拒否でも、保守的にpendingを維持します。

1. ワークフローを一時的に無効にし、`state/state.json` の `pending` にある投稿IDを確認。
2. Discordに該当投稿が届いたか確認。届いていれば、そのIDを `seen` 配列に追加（既にあれば追加不要）。届いていなければ `seen` に追加しません。不明なら確認が取れるまで再開しないでください。
3. `pending` を `null` に変更しコミット。その他の状態は維持。
4. ワークフローを有効化して手動実行。seenにない投稿は取得できれば通知されます。

投稿IDは数値ではなく文字列（例 `"123456789"`）で保存します。復旧・障害・監視空白の運用通知は投稿と同じpending管理ではないため、異常終了時に再通知される可能性があります。

## テスト

PCにPython 3.12以上がある場合、解凍したフォルダーで以下を実行できます。ローカルテストにSecretsは不要で、外部ネットワークへアクセスしません。GitHubでもTestsが同じテストを実行します。

```sh
python -m unittest discover -s tests -v
```

30件：401/403/429/500、タイムアウト、不正JSON、欠落フィールド、2ページ目の失敗、ページング・循環、FEED選別、空一覧、初回・重複抑止、3回連続失敗と復旧、Discord送信失敗、送信前保存失敗、長時間空白からの補完、メンション抑止を検証。API応答は模擬しているため、この合格だけでは実Instagramの取得成功を示しません。

## 公式APIが使えない場合の代替案

- 最も簡単・無料：Instagramアプリで `@hanaabi_official` の投稿通知をオンにする（Discordへの自動転送にはなりません）。
- 南陽醸造側に協力を依頼し、所有者の認可を受けた公式API連携、または公式のRSS/更新フィードが提供可能か相談する。提供・許諾が確認できれば、そのソース向けに取得部分を変更する必要があります。
- 公式サイト等に許諾済みRSSが実在する場合はRSS監視へ切り替える。現時点で利用可能なフィードを確認できたわけではありません。

「無料・無認証・第三者のInstagram投稿・30分ごと・安定したDiscord通知」の全条件を、今回の検証結果から満たせるとは言えません。有料スクレイピングサービスに置き換えたり制限回避を追加したりしないでください。

参考：
- [Meta Business Discovery](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery/)
- [GitHub scheduleの制約](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub Actions料金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [Discord Webhook](https://discord.com/developers/docs/resources/webhook)

今回確認した自分側Instagram IDは `17841464909360076`、APIバージョンは `v27.0` です。長期トークンの有効期限は利用者確認で2027年1月19日。更新目安は1月12日です（リマインダーの自動設定はしていません）。トークンは共有せず、`META_ACCESS_TOKEN` Secretに登録してください。

Webhook URLは前後の空白を除去し、discord.com、discordapp.com、canary.discord.com、ptb.discord.comのHTTPS Webhookを受け付けます。チャンネルのURLやWebhook IDだけは使えません。

## BBC Newsでの実投稿テスト

`BBC test monitor` を追加しました。初回はデプロイ時に自動実行し、以後毎時23分・53分に `bbcnews` を公式Business Discoveryで確認します。南陽醸造は従来どおり毎時17分・47分です。両ワークフローは同じconcurrencyグループで直列化し、状態コミットの競合を防ぎます。

BBCの状態は `state/bbcnews.json` に分離し、通知には `【テスト】BBC News` を付けます。初回成功時は直近100メディア内の通常投稿を記録するだけで通知しません。次回以降は既知の通常投稿を含むページに到達するまで遡り、未通知のFEED投稿のみ通知します。リールは対象外。最大20ページで境界に到達しなければ部分取得を成功扱いせずエラーになります。BBCの全アーカイブは取得しません。

`Actions → BBC test monitor` の初回が緑になり、ログで `bbcnews: initialized=True` を確認できれば初期化成功です。公式APIからBBCを取得できない場合はログに失敗を記録し、成功とは報告しません。新しい通常投稿が届いた後に手動のRun workflowで再確認し、同じ投稿が再通知されないことも確認できます。実投稿がいつ公開されるかは保証できません。

テスト終了時はSettings → Secrets and variables → Actions → Variablesに `BBC_TEST_ENABLED` を値 `false` で追加して停止します。南陽醸造の監視は続行します。再開時に記録は維持されます。BBCの投稿がDiscordに届くことは配送の確認であり、スマホのプッシュ通知設定はDiscordとOS側で別途確認してください。

BBCテストは新しい順の取得を前提に、既知投稿を含むページ全体を処理してから終了します。過去投稿の並べ替えや遅延公開を完全に補完する保証はありません。本番の南陽醸造は全ページ取得を維持します。

## Metaから明示的なアクセスブロックが返った場合

2026-11-22 JSTの調査で `HTTP 400 / code=200 / error_subcode=5258005 / API access blocked.` を確認しました。`state/meta-api-paused.json` を設置し、BBC・南陽醸造とも定期実行からのMeta API呼出しを停止しています。状態の記録とGitHubログは維持します。制限回避・トークン再発行の繰り返しはしません。

Metaアプリの「必要なアクション」「アラート受信箱」、アプリやFacebook/Instagramの利用制限・確認要求を所有者が確認し、Metaの案内に沿って解消する必要があります。このコードだけから解除はできません。解消後は手動のVerify connection（fetch）で一度だけ公式APIへの接続を確認できます。確認成功後に停止マーカーを削除して再開します。通知済み状態は削除しません。手動の接続確認の繰り返しは避けてください。

## BBCリール監視の追加
BBCのみFEEDとREELSを対象にします。初回移行時に直近の既存リールを記録し、移行時刻より前のリールは後のページ取得でも通知しません。通常投稿の通知済み履歴は維持します。次回以降の新しいリールを同じDiscordへ「リール」と表示して通知します。南陽醸造はFEEDのみです。
