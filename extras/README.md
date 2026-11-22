# 任意：GitHubから独立した起動経路（未導入）

GitHub scheduleの起動欠落対策として、Cloudflare Workers CronからGitHub Actionsを30分ごとに起動する実装案です。監視の実行場所はGitHub Actionsのままです。Cloudflareアカウントの開設・接続・デプロイ・秘密情報登録は行っていません。

GitHubとCloudflareの両方が停止すれば起動できず、厳密な時刻や30分以内の到着を保証するものではありません。ただし、単一のGitHub schedule障害から起動元を分離できます。GitHubの混雑でrunner開始が遅れる問題までは解消しません。APIで投稿が遅れて公開される場合もあります。

現行のCloudflare Workers Freeの枠内で48回/日の軽い実行を想定しています。利用時に公式の無料枠と料金条件を確認し、有料プランを選ばないでください。

導入には次の作業と新しいアクセス許可が必要です。

1. Cloudflareの無料アカウントを用意する。
2. GitHubでこのリポジトリだけを対象にしたFine-grained PATを発行する。Repository permissionsは **Actions: Read and write** のみ（Metadata readは自動）。ContentsやMetaアカウントへのアクセスは不要。有効期限を設定し管理する。
3. Cloudflare Workerに、PATを **Secret** 名 `GH_ACTIONS_TOKEN` で登録する。コード・チャットには貼らない。
4. `dispatch-worker.js` と `wrangler.toml` でデプロイする。公開HTTP入口は使わず、Cronだけで起動する。
5. Cronの実行ログとGitHub側 `workflow_dispatch` を確認する。
6. GitHubの永続状態で30分未満の重複起動はAPIアクセスをスキップする。PCの常時起動は不要。

このPATはCloudflareに「このリポジトリのActionsを起動・管理できる権限」を与えます。導入は所有者の許可を得てから行います。終了時はWorkerのCronを停止しPATを失効させます。

- https://developers.cloudflare.com/workers/configuration/cron-triggers/
- https://developers.cloudflare.com/workers/platform/pricing/
- https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
