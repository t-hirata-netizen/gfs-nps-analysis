# GFS 自己変容・NPS 分析ツール

60日アンケートを取り込み、自己変容の実感（変化評価・変化理由）と NPS・満足度の関係を分析する社内ツールです。
ローカル PC だけで動きます。外部 API への送信はしません（Streamlit の利用統計送信も `.streamlit/config.toml` で無効化済み）。

## 起動

Finder で **`GFS分析ツールを起動.command` をダブルクリック**するとブラウザで開きます（終了は出てきたウィンドウを閉じる）。
初回に「開発元を確認できない」と出た場合は、右クリック →「開く」で開いてください。

ターミナルから起動する場合:

```bash
cd ~/my-project/gfs-nps-analysis
.venv/bin/streamlit run app.py --server.address localhost
```

ブラウザで http://localhost:8501 が開きます。実データの DB は `data/gfs_analysis.db` に作られます。

サンプルデータで試す場合（実データ DB とは別ファイルになります）:

```bash
.venv/bin/python scripts/make_sample_data.py
GFS_DB_PATH=data/sample.db .venv/bin/streamlit run app.py --server.address localhost --server.address localhost
```

## 毎日の作業

1. 60日アンケート（Excel）・アクションリスト（CSV）・Liny 友だち情報（CSV）をダウンロード
2. ツールの **データ取込 →「まとめて取込（毎日の作業）」** に3ファイルをまとめてドラッグ →「まとめて取り込む」
   - 種類は自動判別。前回までの分はスキップされ、**増えた分だけ**追加される
   - 新しい「変化理由」には自動分類の案が付く（「変化理由の分類」で確認）
3. ホームの「最終取込日」で取込漏れがないか確認。**推移** ページで日別・週別・月別の変化を見る

## 初回セットアップ（別の PC で使う場合）

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## テスト

```bash
.venv/bin/python -m pytest -q
```

## 画面

| ページ | 内容 |
|---|---|
| データ取込 | Excel を取込（同じファイルの二重取込は拒否、既存の回答はスキップ）。取込履歴 |
| データ品質 | 近接重複（二重送信の疑い）・複数回答の会員・欠損・不正データ |
| 分布 | NPS・GFS満足度・サポート満足度・変化評価の分布（n・欠損率つき） |
| クロス集計 | グループ別 NPS、任意の2項目のクロス表（相関の注意書きつき） |
| 推移 | 日別・週別・月別の NPS（期間別＋累計）・変化評価・アクション進捗のグラフ |
| データ一覧 | 日別・週別・月別の数字の一覧表、期間ごとの回答明細、Excel ダウンロード |
| 変化理由の分類 | 自動分類の案 → 人が確認・修正して保存 |
| アクション×NPS | アクションリストの達成項目数・タスク別に NPS・変化評価を比較、順位相関 |
| Excel出力 | 絞り込み条件での集計・分類結果を Excel に出力 |

## 集計ルール

- NPS = 推奨者率（9〜10）− 批判者率（0〜6）。0〜10 の有効回答のみが分母。区分は元ファイルの「NPS区分」ではなく 0〜10 から再計算。
- 未回答は 0 点・「変化なし」として数えない。設問追加前の回答は「設問なし」として区別（`question_start` で日時指定も可。未指定なら最初に値が入った日時で自動判定）。
- サポート満足度の「利用していない」は「未利用」として平均から除外。
- 範囲外・数値以外の値は空欄扱いにして「不正データ」として記録（集計に混ぜない）。
- 同一会員の複数回答はすべて保持。集計時に「近接重複を除く／全回答／会員ごと初回／会員ごと最新」を選ぶ。
  - **近接重複**：同じ会員の回答が しきい値（既定 60 秒）以内に続いたもの。二重送信の疑いとして1組にまとめ、組の最後の回答を採用。
- 有効回答 30 件未満は「少数データ」と表示。
- 相関は因果として表示しない。

## 設定ファイル

- `config/mappings/survey60.yaml` … Excel の列名との対応、値の範囲、設問追加日時
- `config/change_keywords.yaml` … 変化理由の自動分類キーワード
- `config/mappings/action_list.yaml`, `diagnosis.yaml` … 【仮】将来のアクションリスト・診断アプリ用。実 CSV に合わせて書き換える

## フォルダ

```
app.py, pages/        Streamlit 画面
gfs_analysis/         取込・品質・集計・分類・出力のロジックと schema.sql
config/               列対応・キーワード
scripts/              サンプルデータ生成
sample_data/          匿名サンプル（Git 管理対象）
data/, output/        実データ・DB・出力（Git 管理外）
tests/                自動テスト
```

## チーム共有ダッシュボード（パスワード付き）

公開URL: https://t-hirata-netizen.github.io/gfs-nps-dashboard/

- 集計値だけを AES-GCM で暗号化して 1 枚の HTML にしたもの（会員ID・氏名・自由記述は含まない）。
- パスワードは `data/dashboard_password.txt`（Git 管理外）。変えるときはこのファイルを書き換えて書き出し直す。

更新手順（データを取り込んだあと）:

```bash
.venv/bin/python scripts/build_dashboard.py
cp site/index.html ../gfs-nps-dashboard-site/
cd ../gfs-nps-dashboard-site && git add -A && git commit -m "ダッシュボード更新" && git push
```

## クラウド版（Google Cloud Run・会社の Google アカウントでログイン）

チームの各自がブラウザから取込・分類・閲覧できるようにする構成です。

- 認証：Cloud Run の IAP で、会社ドメインの Google アカウントだけがログインできる
- データ：SQLite を Cloud Storage（非公開・世代管理あり）に保存。起動時に復元し、書き込みのたびに保存
- 同時書き込みを避けるため、Cloud Run の最大インスタンス数は 1
- 取込履歴・分類の保存には、ログインした人のメールアドレスを記録
- クラウドでは「パスを入力する」取込は使えない（ファイルのアップロードのみ）

手順（`deploy/config.example.sh` を `deploy/config.sh` にコピーして値を入れてから）:

```bash
deploy/setup.sh       # 初回：API 有効化・バケット・サービスアカウント
deploy/upload_db.sh   # 初回：手元のデータを載せる（個人情報を含むので社内承認後）
deploy/deploy.sh      # 初回・更新のたび：ビルドして公開
```

## データの扱い

- 元の Excel は読み取るだけで変更しない。
- 氏名列は取り込まない。会員ID は文字列で保存。
- `data/`・`output/`・サンプル以外の Excel/CSV は `.gitignore` で除外済み。
- 出力した Excel には会員ID と自由記述が含まれるため、社外に共有しないこと。

## アクションリストとの紐づけ

- アクションリスト CSV の「回答者ID」は Liny の登録ID（9桁）で、会員ID とは別の番号。
- **ID対応表**（Liny 友だち情報エクスポート CSV）の「登録ID」と「友だち情報_2393157」（会員ID）の2列だけを読み込み、つなぐ。メール・電話番号は読み込まない。
- アクションリストの「進捗」列は見出しが重複しているため、`config/mappings/action_list.yaml` で列の位置とタスク名を指定。設問を変えたらここを直す。
- 既定では「アンケート回答時点までの最新のアクションリスト回答」を使う（時間の前後関係を守るため）。
- CSV の文字コードは UTF-8 / Shift_JIS(cp932) を自動判定。

## 今後の拡張

`diagnosis_results`（会員ID・診断種類・実施日時・結果）のテーブルは作成済み。診断アプリの CSV が届いたら `config/mappings/diagnosis.yaml` を合わせて取込処理を追加する。
