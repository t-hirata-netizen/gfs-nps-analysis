import plotly.express as px
import streamlit as st

from gfs_analysis import metrics as m, ui

ui.setup("クロス集計")
conn, df = ui.load()
ui.require_data(df)
f, cond, _ = ui.sidebar_filters(df)
if f.empty:
    st.warning("条件に当てはまる回答がありません。")
    st.stop()

ui.correlation_note()

GROUPS = {
    "変化評価": ("change_label", m.CHANGE_OPTIONS),
    "GFS満足度": ("gfs_label", m.SCORE5_VALUES + [m.MISSING]),
    "サポート満足度": ("support_label", m.SCORE5_VALUES + [m.NOT_USED, m.MISSING]),
    "入学してよかった": ("admission_good", None),
    "再入学したい": ("re_enroll", None),
    "変化理由の分類（複数該当あり）": ("change_category", m.category_order()),
}

st.subheader("グループ別の NPS")
g_name = st.selectbox("グループ分けに使う項目", list(GROUPS))
g_col, g_order = GROUPS[g_name]
data = m.explode_categories(f) if g_col == "change_category" else f
if g_order is None:
    g_order = sorted(data[g_col].dropna().unique().tolist())
g_order = ui.options_present(g_order, data[g_col])
table = m.group_nps(data, g_col, g_order)
if g_col == "change_category":
    st.caption("1つの回答が複数の分類に該当するため、グループの回答数の合計は全体の回答数と一致しません。")

plot = table[table["NPS有効回答数"] > 0]
fig = px.bar(plot, x="グループ", y="NPS", text=plot.apply(lambda r: f"{r['NPS']:.1f}<br>n={r['NPS有効回答数']}", axis=1),
             title=f"{g_name}別の NPS")
fig.update_xaxes(type="category")
fig.update_layout(height=360, margin=dict(t=50, b=10), xaxis_title=None)
st.plotly_chart(fig)
ui.show_table(table)
small = table[(table["注意"] != "") & (table["NPS有効回答数"] > 0)]
if not small.empty:
    st.warning("少数データのグループがあります："
               + "、".join(f"{r['グループ']}（n={r['NPS有効回答数']}）" for _, r in small.iterrows())
               + "。グループ間の差は偶然の可能性があります。")

st.divider()
st.subheader("クロス表（件数・行％）")
c1, c2 = st.columns(2)
row_name = c1.selectbox("行", list(GROUPS), index=0)
col_choices = {"NPS区分": ("nps_category", m.NPS_CATEGORY_OPTIONS), **GROUPS}
col_name = c2.selectbox("列", list(col_choices), index=0)
r_col, r_order = GROUPS[row_name]
c_col, c_order = col_choices[col_name]
data = m.explode_categories(f) if "change_category" in (r_col, c_col) else f
r_order = ui.options_present(r_order or sorted(data[r_col].dropna().unique()), data[r_col])
c_order = ui.options_present(c_order or sorted(data[c_col].dropna().unique()), data[c_col])
if r_col == c_col:
    st.caption("行と列に別の項目を選んでください。")
else:
    counts, pct = m.crosstab(data, r_col, c_col, r_order, c_order)
    st.markdown("**件数**")
    st.dataframe(counts, width="stretch")
    st.markdown("**行％（各行の合計を100%とした割合）**")
    st.dataframe(pct, width="stretch")
    st.caption(f"比較対象：行 {len(r_order)} 区分 × 列 {len(c_order)} 区分。"
               "「未回答」「設問なし」も区分として表示しており、0点や変化なしとしては数えていません。")
