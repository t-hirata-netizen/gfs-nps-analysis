import plotly.express as px
import streamlit as st

from gfs_analysis import actions, ui

ui.setup("アクション × NPS・変化")
conn, df = ui.load()
ui.require_data(df)
f, cond, _ = ui.sidebar_filters(df)

snaps = actions.load_action_snapshots(conn)
if snaps.empty:
    st.info("アクションリストがまだ取り込まれていません。「データ取込」から アクションリスト と ID対応表 を取り込んでください。")
    st.stop()
if snaps["member_id"].isna().all():
    st.info("ID対応表がまだ取り込まれていないため、会員ID とつなげられません。「データ取込」から取り込んでください。")
    st.stop()

mapping = actions.load_action_mapping()
timing = st.radio("どの時点のアクションリスト回答を使うか", actions.TIMING_MODES, horizontal=True,
                  help="「アンケート回答時点まで」は、アンケートより後に進んだ分を含めないため、時間の前後関係がはっきりします。")
d = actions.attach_actions(f, snaps, timing, mapping)
ui.correlation_note()

st.subheader("紐づけの状況")
cov = actions.coverage(d)
ui.show_table(cov)
unlinked = int(snaps["member_id"].isna().sum())
st.caption(f"アクションリスト全 {len(snaps):,} 回答のうち、ID対応表で会員ID に変換できなかった回答 {unlinked:,} 件。"
           "アクション回答のない会員は以下の集計に含まれません（集計対象に偏りがある可能性）。")
target = d[d["has_action"]]
if target.empty:
    st.warning("条件に当てはまり、アクションリスト回答と紐づく回答がありません。")
    st.stop()

st.subheader("相関（順位相関）")
ui.show_table(actions.correlation_table(d))
st.caption("目安：|ρ| 0.1未満 ほぼなし／0.3未満 弱い／0.5未満 中程度／それ以上 強い。p値は「偶然だけで説明しにくいか」の目安で、強さや因果は示しません。")

st.subheader("達成項目数ごとの NPS・変化評価")
pt = actions.progress_table(d, mapping)
c1, c2 = st.columns(2)
plot = pt[pt["NPS有効回答数"] > 0]
with c1:
    fig = px.bar(plot, x="達成項目数", y="NPS", title="達成項目数別の NPS",
                 text=plot.apply(lambda r: f"{r['NPS']:.1f}<br>n={r['NPS有効回答数']}", axis=1))
    fig.update_layout(height=340, margin=dict(t=50, b=10), xaxis_title=None)
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, use_container_width=True)
with c2:
    p2 = pt[pt["変化評価の平均"].notna()]
    fig = px.bar(p2, x="達成項目数", y="変化評価の平均", title="達成項目数別の 変化評価（1〜5）の平均",
                 text=p2["変化評価の平均"].map(lambda v: f"{v:.2f}"))
    fig.update_layout(height=340, margin=dict(t=50, b=10), xaxis_title=None, yaxis_range=[1, 5])
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, use_container_width=True)
ui.show_table(pt)

st.subheader("タスク別：達成した人・していない人の比較")
tt = actions.task_table(d, mapping)
ui.show_table(tt)
st.caption("タスクは独立ではありません（後半のタスクを達成した人は、前半もほぼ達成しています）。個々のタスクの効果を切り分けたものではありません。")
