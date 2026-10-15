import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from gfs_analysis import actions, trends, ui
from gfs_analysis import metrics as m

ui.setup("推移")
conn, df = ui.load()
ui.require_data(df)
f, cond, _ = ui.sidebar_filters(df)
if f.empty:
    st.warning("条件に当てはまる回答がありません。")
    st.stop()

freq_label = st.radio("集計の単位", list(trends.FREQS), index=1, horizontal=True)
freq = trends.FREQS[freq_label]
snaps = actions.load_action_snapshots(conn)
tasks = actions.load_action_mapping()["tasks"]
table = trends.period_table(f, snaps, freq, tasks)

NUM = st.column_config.NumberColumn
PERIOD = {"期間": st.column_config.TextColumn(pinned=True)}

# ---------------------------------------------------------------- 60日アンケート
st.subheader("60日アンケート（新しい順）")
st.caption("回答日で区切っています。NPS は 0〜10 の有効回答のみが分母。「少数データ」に○がある期間（有効回答30件未満）は値がぶれやすいので注意してください。")
survey_cols = ["期間ラベル", "アンケート回答数", "NPS有効回答数", "推奨者", "中立者", "批判者", "NPS", "累計NPS",
               "変化評価の平均", "GFS満足度の平均", "サポート満足度の平均", "少数データ"]
s = table[[c for c in survey_cols if c in table.columns]]
s = s[s["アンケート回答数"] > 0].rename(columns={"期間ラベル": "期間", "アンケート回答数": "回答数"})
st.dataframe(s, width="stretch", hide_index=True, height=min(38 * (len(s) + 1), 560), column_config={
    **PERIOD,
    "回答数": NUM(format="%d"), "NPS有効回答数": NUM(format="%d"),
    "推奨者": NUM(format="%d"), "中立者": NUM(format="%d"), "批判者": NUM(format="%d"),
    "NPS": NUM(format="%.1f"), "累計NPS": NUM(format="%.1f"),
    "変化評価の平均": NUM(format="%.2f"), "GFS満足度の平均": NUM(format="%.2f"), "サポート満足度の平均": NUM(format="%.2f"),
})

# ---------------------------------------------------------------- アクションリスト
if "アクション回答数" in table.columns:
    st.subheader("アクションリスト（新しい順）")
    st.caption("アクションリストの回答日で区切っています（サイドバーの絞り込みは適用されません）。達成率は、その期間に回答した人のうち「済み」と答えた割合です。")
    rate_cols = [c for c in table.columns if c.startswith("達成率：")]
    a = table[["期間ラベル", "アクション回答数", "平均達成項目数"] + rate_cols]
    a = a[a["アクション回答数"] > 0].rename(columns={"期間ラベル": "期間", "アクション回答数": "回答数"})
    a = a.rename(columns={c: c.replace("達成率：", "") for c in rate_cols})
    st.dataframe(a, width="stretch", hide_index=True, height=min(38 * (len(a) + 1), 560), column_config={
        **PERIOD, "回答数": NUM(format="%d"), "平均達成項目数": NUM(format="%.2f"),
        **{c: NUM(format="%.1f") for c in a.columns if c.endswith("（%）")},
    })

# ---------------------------------------------------------------- グラフ（補助）
with st.expander("グラフで見る"):
    t = trends.survey_trend(f, freq)
    cum = trends.cumulative_nps(f, freq)
    valid = t[t["NPS有効回答数"] > 0]
    fig = go.Figure()
    fig.add_bar(x=valid["期間ラベル"], y=valid["NPS"], name="期間ごとのNPS",
                text=[f"{v:.1f}<br>n={n}" for v, n in zip(valid["NPS"], valid["NPS有効回答数"])], textposition="outside",
                marker_color=["#c8c8c8" if s_ else "#4c78a8" for s_ in valid["少数データ"]])
    fig.add_scatter(x=cum["期間ラベル"], y=cum["累計NPS"], name="累計NPS", mode="lines+markers+text",
                    text=[f"{v:.1f}" for v in cum["累計NPS"]], textposition="top center", line_color="#d9534f")
    fig.update_layout(title="NPS の推移（灰色の棒は有効回答30件未満）", height=420, margin=dict(t=50, b=10),
                      legend=dict(orientation="h", y=-0.15), yaxis_title="NPS", yaxis_range=[-110, 15])
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=cum["期間ラベル"])
    st.plotly_chart(fig, width="stretch")

    v = t[t["変化評価の平均"].notna()]
    fig = px.line(v, x="期間ラベル", y="変化評価の平均", markers=True, text=v["変化評価の平均"].map(lambda x: f"{x:.2f}"),
                  title="変化評価（1〜5）の平均")
    fig.update_traces(textposition="top center")
    fig.update_layout(height=320, margin=dict(t=50, b=10), yaxis_range=[1, 5.3], xaxis_title=None)
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, width="stretch")

    if not snaps.empty:
        at = trends.action_trend(snaps, freq, tasks)
        fig = px.line(at, x="期間ラベル", y="平均達成項目数", markers=True,
                      text=at["平均達成項目数"].map(lambda x: f"{x:.2f}"), title=f"平均達成項目数（全{len(tasks)}項目）")
        fig.update_traces(textposition="top center")
        fig.update_layout(height=320, margin=dict(t=50, b=10), xaxis_title=None, yaxis_range=[0, len(tasks)])
        fig.update_xaxes(type="category")
        st.plotly_chart(fig, width="stretch")

st.caption(m.CORRELATION_NOTE)
