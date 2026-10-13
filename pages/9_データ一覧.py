import io

import pandas as pd
import streamlit as st

from gfs_analysis import actions, classify, export, trends, ui
from gfs_analysis import metrics as m

ui.setup("データ一覧")
conn, df = ui.load()
ui.require_data(df)
f, cond, _ = ui.sidebar_filters(df)

freq_label = st.radio("集計の単位", list(trends.FREQS), index=0, horizontal=True)
freq = trends.FREQS[freq_label]
snaps = actions.load_action_snapshots(conn)
tasks = actions.load_action_mapping()["tasks"]
table = trends.period_table(f, snaps, freq, tasks)
if table.empty:
    st.warning("条件に当てはまるデータがありません。")
    st.stop()

st.subheader(f"{freq_label}の一覧（新しい順）")
st.caption("アンケートの数字はサイドバーの絞り込みを反映し、「回答日」で区切っています。アクションリストの数字は絞り込みを反映せず、アクションリストの回答日で区切っています。"
           "NPS は 0〜10 の有効回答のみが分母です。「少数データ」に○がある期間（有効回答30件未満）は値がぶれやすいので注意してください。")

show = table.drop(columns="期間").rename(columns={"期間ラベル": "期間"})
groups = {
    "アンケート": [c for c in show.columns if c in (
        "アンケート回答数", "会員数", "NPS有効回答数", "推奨者", "中立者", "批判者", "NPS", "累計NPS",
        "変化評価の平均", "GFS満足度の平均", "サポート満足度の平均", "少数データ")],
    "変化理由の分類": [c for c in show.columns if c == "変化理由の記入数" or c.startswith("分類：")],
    "アクションリスト": [c for c in show.columns if c in ("アクション回答数", "平均達成項目数") or c.startswith("達成率：")],
}
picked = st.multiselect("表示する項目", list(groups), default=["アンケート", "アクションリスト"])
cols = ["期間"] + [c for g in picked for c in groups[g]]
st.dataframe(show[cols], use_container_width=True, hide_index=True, height=min(38 * (len(show) + 1), 560),
             column_config={"期間": st.column_config.TextColumn(pinned=True)})

st.divider()
st.subheader("期間を選んで回答明細を見る")
labels = table["期間ラベル"].tolist()
sel = st.selectbox("期間", labels)
start = table.loc[table["期間ラベル"] == sel, "期間"].iloc[0]
rows = trends.rows_in_period(f, start, freq).sort_values("answered_at")
if rows.empty:
    st.caption("この期間のアンケート回答はありません（アクションリストの回答のみ）。")
    detail = pd.DataFrame()
else:
    detail = export.detail_frame(rows)
    detail.insert(3, "変化理由の分類", [
        classify.label_list({c: r[c] for c in m.CATEGORY_COLS}) if pd.notna(r["knowledge"]) else ""
        for _, r in rows.iterrows()])
    s = m.nps_summary(rows)
    nps_text = "-" if s["NPS"] is None else f"{s['NPS']:.1f}"
    st.caption(f"{sel}：アンケート {len(rows):,} 件／NPS {nps_text}（有効回答 n={s['有効回答数']}）")
    st.dataframe(detail, use_container_width=True, hide_index=True, height=420,
                 column_config={"回答日時": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")})
    st.caption("会員ID・自由記述を含みます。社外に共有しないでください。")

st.divider()
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as w:
    show.to_excel(w, sheet_name=f"{freq_label[:2]}一覧", index=False)
    pd.DataFrame([{"条件": k, "内容": str(v)} for k, v in cond.items()]).to_excel(w, sheet_name="条件", index=False)
    if not detail.empty:
        detail.to_excel(w, sheet_name=f"明細_{sel.replace('/', '-')}"[:31], index=False)
    for ws in w.book.worksheets:
        export._autofit(ws)
st.download_button("この一覧を Excel でダウンロード", buf.getvalue(),
                   file_name=f"GFS_{freq_label[:2]}一覧_{pd.Timestamp.now():%Y%m%d}.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
