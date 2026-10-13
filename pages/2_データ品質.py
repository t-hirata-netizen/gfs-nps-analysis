import streamlit as st

from gfs_analysis import db, quality as q, ui

ui.setup("データ品質")
conn, df = ui.load()
ui.require_data(df)
_, _, threshold = ui.sidebar_filters(df)
st.caption("このページは絞り込み前の全データを対象にしています（しきい値のみサイドバーの設定を使用）。")

dup = q.duplicate_members(df)
near = q.near_duplicate_table(df, threshold)
issues = db.load_issues(conn)

c1, c2, c3, c4 = st.columns(4)
c1.metric("回答数", f"{len(df):,}")
c2.metric("会員数", f"{df['member_id'].nunique():,}")
c3.metric("複数回答のある会員", f"{len(dup):,}")
c4.metric(f"近接重複（{threshold:g}秒以内）", f"{near['組'].nunique() if not near.empty else 0:,} 組")

st.subheader("近接重複（二重送信の疑い）")
st.markdown(
    f"同じ会員の回答が **{threshold:g} 秒以内**に続いているものです。"
    "データは削除せず保持しています。集計では、サイドバーの「重複の扱い」で除外するかを選べます。"
)
if near.empty:
    st.caption("該当なし")
else:
    ui.show_table(near)

st.subheader("複数回答のある会員")
st.caption("二重送信のほか、別日に回答し直したケースも含みます（最短間隔で見分けられます）。")
ui.show_table(dup) if not dup.empty else st.caption("該当なし")

st.subheader("欠損の状況")
st.caption("「設問なし」は設問が追加される前の回答、「未利用」はサポートを利用していない回答です。どちらも未回答とは分けて数えています。")
ui.show_table(q.missing_report(df))

st.subheader("不正データ・不一致（取込時に記録）")
if issues.empty:
    st.caption("該当なし")
else:
    summary = issues.groupby(["issue_type", "action"]).size().reset_index(name="件数")
    ui.show_table(summary.rename(columns={"issue_type": "内容", "action": "処理"}))
    with st.expander(f"明細（{len(issues):,} 件）"):
        ui.show_table(issues.rename(columns={
            "batch_id": "取込ID", "file_name": "ファイル名", "source_row_no": "Excel行番号",
            "member_id": "会員ID", "field": "列", "raw_value": "元の値",
            "issue_type": "内容", "action": "処理"}))
