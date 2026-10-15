# Streamlit Community Cloud で公開する手順（無料・支払い登録なし）

チームの各自が、招待されたメールアドレス（会社の Google アカウント）でログインして使う構成です。
データベースは会社の Google ドライブに置き、アプリはサービスアカウントで読み書きします。

## 1. サービスアカウントを作る（Google Cloud・支払い登録は不要）

1. https://console.cloud.google.com で、会社のアカウントでプロジェクトを作る（請求先の設定はしない）
2. 「API とサービス」→「ライブラリ」で **Google Drive API** を有効にする
3. 「IAM と管理」→「サービス アカウント」→ 作成（名前の例：`gfs-nps-app`、ロールは付けなくてよい）
4. 作ったサービスアカウント →「鍵」→「鍵を追加」→「JSON」→ ダウンロード
   - 「組織のポリシーで鍵の作成が無効」と出たら、Workspace 管理者に相談（別の方式に切り替え可能）
   - 鍵ファイルはパスワードと同じ扱い。Git に入れない・人に送らない

## 2. データベースをドライブに置く

1. 手元の `data/gfs_analysis.db` を、会社の Google ドライブにアップロード（ファイル名はそのまま）
2. そのファイルを右クリック →「共有」→ サービスアカウントのメールアドレス（`…@….iam.gserviceaccount.com`）を **編集者** で追加
3. ファイルの URL `https://drive.google.com/file/d/<ここがファイルID>/view` からファイルIDを控える

## 3. Streamlit Community Cloud に出す

1. https://share.streamlit.io に GitHub アカウントでサインアップ
2. 「Create app」→ リポジトリ `t-hirata-netizen/gfs-nps-analysis`、ブランチ `main`、ファイル `app.py`
3. 「Advanced settings」で Python **3.11** を選び、Secrets に `.streamlit/secrets.example.toml` の形で値を入れる
   （サービスアカウントの JSON の各項目を `[gcp_service_account]` の下に書き写す）
4. デプロイ後、アプリの「Share」→ **Only specific people can view this app** にして、チームのメールアドレスを招待

## 運用

- アプリは1つだけ動く（同時に書き込むのは1プロセス）。書き込みのたびにドライブへ保存される
- ドライブの「版を管理」から過去の状態に戻せる
- 招待された人は他の人も招待できるので、メンバーの追加・削除は担当者を決めて行う
