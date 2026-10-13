from datetime import datetime

import streamlit as st

from gfs_analysis import actions, db, export, ui

ui.setup("Excel出力")
conn, df = ui.load()
ui.require_data(df)
f, cond, threshold = ui.sidebar_filters(df)

st.markdown("サイドバーの絞り込み条件で集計した結果と、変化理由の分類結果を Excel に出力します。")
ui.show_table([{"条件": k, "内容": str(v)} for k, v in cond.items()])
st.markdown("""
**シート構成**：概要（条件・NPS・注意事項）／NPS／満足度／変化評価／変化評価×NPS／
変化理由分類_集計／変化理由分類_明細／品質（重複・欠損）／品質_不正データ／
アクション×NPS（アクションリスト取込済みの場合）／明細
""")
st.caption("出力ファイルには会員ID と自由記述が含まれます。社外に共有しないでください。")

if f.empty:
    st.warning("条件に当てはまる回答がありません。")
    st.stop()

snaps = actions.load_action_snapshots(conn)
action_df, timing = None, ""
if not snaps.empty and snaps["member_id"].notna().any():
    timing = st.radio("アクション×NPS で使うアクションリスト回答", actions.TIMING_MODES, horizontal=True)
    action_df = actions.attach_actions(f, snaps, timing)

if st.button("Excel を作成", type="primary"):
    data = export.build_workbook(f, df, cond, db.load_issues(conn), threshold, action_df, timing)
    st.session_state["export_data"] = data
    st.session_state["export_name"] = f"GFS_NPS分析_{datetime.now():%Y%m%d_%H%M}.xlsx"

if "export_data" in st.session_state:
    st.download_button("ダウンロード", st.session_state["export_data"],
                       file_name=st.session_state["export_name"],
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
