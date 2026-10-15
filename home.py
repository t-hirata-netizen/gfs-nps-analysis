"""トップページ"""
import streamlit as st

from datetime import datetime

from gfs_analysis import cloud, db, importer, ui
from gfs_analysis import metrics as m

ui.setup("GFS 自己変容・NPS 分析ツール")
conn, df = ui.load()

if cloud.enabled():
    st.caption("データの保存先：会社の Google ドライブ")
else:
    st.caption(f"データベース: `{db.db_path()}`")

st.subheader("最終取込日")
last = importer.last_imports(conn)
cols = st.columns(len(last))
for col, (label, at) in zip(cols, last.items()):
    if at is None:
        col.metric(label, "未取込")
    else:
        t = datetime.strptime(at, "%Y-%m-%d %H:%M:%S")
        days = (datetime.now().date() - t.date()).days
        col.metric(label, f"{t.month}/{t.day} {t:%H:%M}")
        col.caption("今日" if days == 0 else f"{days}日前")
        if days >= 2:
            col.warning(f"{days}日間 取込がありません")
if not df.empty:
    pending = int(((df["reason_change"].notna()) & (df["class_source"].fillna("") != "manual")).sum())
    if pending:
        st.info(f"人の確認が済んでいない「変化理由」の分類が {pending:,} 件あります（「変化理由の分類」ページ）。")
st.divider()

if df.empty:
    st.info("まだデータがありません。左のメニューの「データ取込」から 60日アンケートの Excel を取り込んでください。")
else:
    s = m.nps_summary(df)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("回答数（全件）", f"{len(df):,}")
    c2.metric("会員数", f"{df['member_id'].nunique():,}")
    c3.metric("NPS 有効回答数", f"{s['有効回答数']:,}")
    c4.metric("NPS（全件）", "-" if s["NPS"] is None else f"{s['NPS']:.1f}")
    st.caption(f"回答期間: {df['answered_at'].min():%Y-%m-%d} 〜 {df['answered_at'].max():%Y-%m-%d}")

st.markdown("""
### 使い方
毎日の作業：**データ取込 → 「まとめて取込」** に、その日ダウンロードした Excel・CSV をまとめて入れるだけです（増えた分だけ追加されます）。

1. **データ取込** — 60日アンケートの Excel を取り込みます（元ファイルは変更しません）。
2. **データ品質** — 重複会員・二重送信の疑い・欠損・不正データを確認します。
3. **分布** — NPS・満足度・変化評価の分布を見ます。
4. **クロス集計** — 変化評価と NPS などの関係を見ます。
5. **変化理由の分類** — 自動分類の案を確認し、人が修正します。
6. **推移** — 日別・週別・月別の NPS・変化評価・アクション進捗の推移を見ます。
7. **データ一覧** — 日別・週別・月別の数字を一覧表で見て、期間ごとの回答明細も確認します。
8. **アクション×NPS** — アクションリストの進捗と、NPS・変化の実感の関係を見ます（アクションリストと ID対応表の取込が必要）。
9. **Excel出力** — 集計結果と分類結果を Excel で保存します。

左のサイドバーの絞り込み（期間・変化評価・NPS区分・重複の扱い）は、分析ページに共通で効きます。

### 集計ルール
- **NPS** = 推奨者率（9〜10）− 批判者率（0〜6）。0〜10 の有効回答だけを分母にします。
- **未回答**は 0 点や「変化なし」として数えません。設問が追加される前の回答は **設問なし** として区別します。
- 有効回答が **30 件未満**の集計には「少数データ」の注意を表示します。
- 相関（同時に見られる傾向）を示すだけで、**因果関係は示しません**。
- 氏名列は取り込みません。ローカル版はこのPCの中だけで動き、クラウド版はデータを会社の Google ドライブに保存します。
""")
