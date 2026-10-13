import streamlit as st

from gfs_analysis import metrics as m, ui

ui.setup("分布")
conn, df = ui.load()
ui.require_data(df)
f, cond, _ = ui.sidebar_filters(df)
if f.empty:
    st.warning("条件に当てはまる回答がありません。")
    st.stop()

s = m.nps_summary(f)
st.subheader("NPS")
c1, c2, c3, c4 = st.columns(4)
c1.metric("NPS", "-" if s["NPS"] is None else f"{s['NPS']:.1f}")
def _pct(p):
    return "" if p is None else f" {p:.1f}%"


c2.metric(f"推奨者{_pct(s['推奨者率(%)'])}", f"{s['推奨者数']:,}")
c3.metric(f"中立者{_pct(s['中立者率(%)'])}", f"{s['中立者数']:,}")
c4.metric(f"批判者{_pct(s['批判者率(%)'])}", f"{s['批判者数']:,}")
ui.n_caption(s["有効回答数"], s["未回答数"], s["設問なし数"], extra="推奨者=9〜10点・中立者=7〜8点・批判者=0〜6点")

col1, col2 = st.columns([2, 1])
with col1:
    d = m.distribution(f, "nps_label", m.NPS_VALUES, [m.MISSING, m.NOT_ASKED])
    d["NPS区分"] = d["区分"].map(lambda v: m.classify_nps(int(v)) if v.isdigit() else v)
    ui.bar(d, "NPS（0〜10）の分布", ui.NPS_COLORS, "NPS区分")
with col2:
    dc = m.distribution(f, "nps_category", m.NPS_CATEGORIES, [m.MISSING, m.NOT_ASKED])
    dc["NPS区分"] = dc["区分"]
    ui.bar(dc, "NPS区分", ui.NPS_COLORS, "NPS区分")

st.divider()
col1, col2 = st.columns(2)
with col1:
    st.subheader("GFS満足度")
    d = m.distribution(f, "gfs_label", m.SCORE5_VALUES, [m.MISSING])
    st_ = m.score_stats(f["gfs_satisfaction"])
    ui.bar(d, f"GFS満足度（平均 {st_['平均']:.2f}）" if st_["平均"] is not None else "GFS満足度")
    ui.n_caption(st_["有効回答数"], int((f["gfs_label"] == m.MISSING).sum()))
with col2:
    st.subheader("サポート満足度")
    d = m.distribution(f, "support_label", m.SCORE5_VALUES, [m.NOT_USED, m.MISSING])
    st_ = m.score_stats(f["support_satisfaction"])
    ui.bar(d, f"サポート満足度（平均 {st_['平均']:.2f}）" if st_["平均"] is not None else "サポート満足度")
    ui.n_caption(st_["有効回答数"], int((f["support_label"] == m.MISSING).sum()),
                 extra=f"利用していない {int((f['support_label'] == m.NOT_USED).sum()):,}（集計対象外）")

st.divider()
st.subheader("変化評価（1〜5、5=強く変化を感じる）")
d = m.distribution(f, "change_label", m.SCORE5_VALUES, [m.MISSING, m.NOT_ASKED])
st_ = m.score_stats(f["change_score"])
ui.bar(d, f"変化評価（平均 {st_['平均']:.2f}）" if st_["平均"] is not None else "変化評価")
ui.n_caption(st_["有効回答数"], int((f["change_label"] == m.MISSING).sum()),
             int((f["change_label"] == m.NOT_ASKED).sum()))

with st.expander("分布の表"):
    for title, col, vals, extra in [
        ("NPS", "nps_label", m.NPS_VALUES, [m.MISSING, m.NOT_ASKED]),
        ("GFS満足度", "gfs_label", m.SCORE5_VALUES, [m.MISSING]),
        ("サポート満足度", "support_label", m.SCORE5_VALUES, [m.NOT_USED, m.MISSING]),
        ("変化評価", "change_label", m.SCORE5_VALUES, [m.MISSING, m.NOT_ASKED]),
    ]:
        st.markdown(f"**{title}**")
        ui.show_table(m.distribution(f, col, vals, extra))
