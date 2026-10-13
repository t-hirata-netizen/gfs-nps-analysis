import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from gfs_analysis import actions, trends, ui

ui.setup("推移")
conn, df = ui.load()
ui.require_data(df)
f, cond, _ = ui.sidebar_filters(df)
if f.empty:
    st.warning("条件に当てはまる回答がありません。")
    st.stop()

freq_label = st.radio("集計の単位", list(trends.FREQS), index=1, horizontal=True)
freq = trends.FREQS[freq_label]
st.caption("期間は「回答日」で区切っています。日別は件数が少なく値が大きくぶれやすいため、週別・月別や累計NPSと合わせて見てください。")

st.subheader("60日アンケート")
t = trends.survey_trend(f, freq)
cum = trends.cumulative_nps(f, freq)
fig = go.Figure()
valid = t[t["NPS有効回答数"] > 0]
fig.add_bar(x=valid["期間ラベル"], y=valid["NPS"], name="期間ごとのNPS",
            marker_color=["#c8c8c8" if s else "#4c78a8" for s in valid["少数データ"]],
            customdata=valid[["NPS有効回答数"]], hovertemplate="%{x}<br>NPS %{y}<br>n=%{customdata[0]}<extra></extra>")
fig.add_scatter(x=cum["期間ラベル"], y=cum["累計NPS"], name="累計NPS", mode="lines+markers", line_color="#d9534f")
fig.update_layout(title="NPS の推移（灰色の棒は有効回答30件未満）", height=380, margin=dict(t=50, b=10),
                  legend=dict(orientation="h", y=-0.15), yaxis_title="NPS")
fig.update_xaxes(type="category", categoryorder="array", categoryarray=cum["期間ラベル"])
st.plotly_chart(fig, use_container_width=True)

c1, c2 = st.columns(2)
with c1:
    v = t[t["変化評価の平均"].notna()]
    fig = px.line(v, x="期間ラベル", y="変化評価の平均", markers=True, title="変化評価（1〜5）の平均",
                  hover_data=["変化評価n"])
    fig.update_layout(height=320, margin=dict(t=50, b=10), yaxis_range=[1, 5], xaxis_title=None)
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, use_container_width=True)
with c2:
    fig = px.bar(t, x="期間ラベル", y="回答数", title="回答数")
    fig.update_layout(height=320, margin=dict(t=50, b=10), xaxis_title=None)
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, use_container_width=True)
with st.expander("表で見る"):
    ui.show_table(t.merge(cum.drop(columns="期間ラベル"), on="期間", how="left").drop(columns="期間"))

st.subheader("アクションリスト")
snaps = actions.load_action_snapshots(conn)
if snaps.empty:
    st.caption("アクションリストはまだ取り込まれていません。")
    st.stop()
st.caption("アクションリストの回答日で区切っています（サイドバーの絞り込みは適用されません）。各タスクの達成率は、その期間に回答した人のうち達成済みと答えた割合です。")
tasks = actions.load_action_mapping()["tasks"]
at = trends.action_trend(snaps, freq, tasks)
c1, c2 = st.columns(2)
with c1:
    fig = px.line(at, x="期間ラベル", y="平均達成項目数", markers=True, title=f"平均達成項目数（全{len(tasks)}項目）",
                  hover_data=["回答数"])
    fig.update_layout(height=320, margin=dict(t=50, b=10), xaxis_title=None, yaxis_range=[0, len(tasks)])
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, use_container_width=True)
with c2:
    fig = px.bar(at, x="期間ラベル", y="回答数", title="アクションリストの回答数")
    fig.update_layout(height=320, margin=dict(t=50, b=10), xaxis_title=None)
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, use_container_width=True)
cols = [t_["label"] + "（%）" for t_ in tasks]
long = at.melt(id_vars="期間ラベル", value_vars=cols, var_name="タスク", value_name="達成率（%）")
long["タスク"] = long["タスク"].str.replace("（%）", "", regex=False)
fig = px.line(long, x="期間ラベル", y="達成率（%）", color="タスク", markers=True, title="タスク別の達成率")
fig.update_layout(height=420, margin=dict(t=50, b=10), xaxis_title=None, yaxis_range=[0, 100],
                  legend=dict(orientation="h", y=-0.2))
fig.update_xaxes(type="category")
st.plotly_chart(fig, use_container_width=True)
with st.expander("表で見る"):
    ui.show_table(at.drop(columns="期間"))
