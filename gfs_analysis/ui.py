"""Streamlit 画面の共通部品（サイドバーの絞り込み・グラフなど）"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

from . import db
from . import metrics as m
from . import quality as q

NPS_COLORS = {m.PROMOTER: "#2e8b57", m.PASSIVE: "#9e9e9e", m.DETRACTOR: "#d9534f",
              m.MISSING: "#e0e0e0", m.NOT_ASKED: "#f0f0f0"}


# Streamlit は <html lang="en"> で出力するため、ブラウザが「英語のページ」と誤認して
# 自動翻訳してしまう（NPS→「国立公園」など）。日本語・翻訳不要と宣言し直す。
_NO_TRANSLATE_JS = """
<script>
const d = window.parent.document;
d.documentElement.lang = "ja";
d.documentElement.setAttribute("translate", "no");
d.documentElement.classList.add("notranslate");
if (!d.querySelector('meta[name="google"]')) {
  const m = d.createElement("meta");
  m.name = "google"; m.content = "notranslate";
  d.head.appendChild(m);
}
</script>
"""


def setup(title: str):
    st.set_page_config(page_title=f"GFS分析｜{title}", layout="wide")
    components.html(_NO_TRANSLATE_JS, height=0)
    st.title(title)


def load() -> Tuple[object, pd.DataFrame]:
    conn = db.connect()
    return conn, db.load_responses(conn)


def require_data(df: pd.DataFrame):
    if df.empty:
        st.info("まだデータがありません。左のメニューの「データ取込」から Excel を取り込んでください。")
        st.stop()


# --- ページをまたいで絞り込み条件を保持する ---
def _keep(key: str, default):
    store = "_keep_" + key
    if store not in st.session_state:
        st.session_state[store] = default
    st.session_state[key] = st.session_state[store]


def _save(key: str):
    st.session_state["_keep_" + key] = st.session_state[key]


def sidebar_filters(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict, float]:
    """重複の扱い → 期間・変化評価・NPS区分 の順に絞り込む"""
    sb = st.sidebar
    sb.header("絞り込み")
    _keep("f_threshold", q.DEFAULT_NEAR_DUP_SECONDS)
    threshold = sb.number_input(
        "近接重複のしきい値（秒）", min_value=0, max_value=3600, step=10, key="f_threshold",
        on_change=_save, args=("f_threshold",),
        help="同じ会員の回答がこの秒数以内に続いていたら、二重送信の疑いとして1組にまとめます。")
    _keep("f_dedup", q.DEDUP_NEAR)
    mode = sb.selectbox("重複の扱い", q.DEDUP_MODES, key="f_dedup",
                        on_change=_save, args=("f_dedup",))

    dmin, dmax = df["answered_at"].min().date(), df["answered_at"].max().date()
    stored = st.session_state.get("_keep_f_period")
    if not (isinstance(stored, (tuple, list)) and len(stored) == 2
            and dmin <= stored[0] <= stored[1] <= dmax):
        st.session_state["_keep_f_period"] = (dmin, dmax)
    _keep("f_period", (dmin, dmax))
    period = sb.date_input("期間（回答日）", min_value=dmin, max_value=dmax, key="f_period",
                           on_change=_save, args=("f_period",))
    if not isinstance(period, (tuple, list)) or len(period) != 2:
        period = (dmin, dmax)

    _keep("f_change", m.CHANGE_OPTIONS)
    change = sb.multiselect("変化評価（5=強く変化を感じる）", m.CHANGE_OPTIONS, key="f_change",
                            on_change=_save, args=("f_change",))
    _keep("f_nps", m.NPS_CATEGORY_OPTIONS)
    nps = sb.multiselect("NPS区分", m.NPS_CATEGORY_OPTIONS, key="f_nps",
                         on_change=_save, args=("f_nps",))

    out = q.apply_dedup(df, mode, threshold)
    out = out[(out["answered_at"].dt.date >= period[0]) & (out["answered_at"].dt.date <= period[1])]
    out = out[out["change_label"].isin(change) & out["nps_category"].isin(nps)]

    sb.caption(f"対象 {len(out):,} 件 / 全 {len(df):,} 件（会員 {out['member_id'].nunique():,} 名）")
    conditions = {
        "期間": f"{period[0]} 〜 {period[1]}",
        "変化評価": "、".join(change) if len(change) < len(m.CHANGE_OPTIONS) else "すべて",
        "NPS区分": "、".join(nps) if len(nps) < len(m.NPS_CATEGORY_OPTIONS) else "すべて",
        "重複の扱い": mode,
        "近接重複のしきい値(秒)": threshold,
        "対象回答数": len(out),
        "対象会員数": int(out["member_id"].nunique()),
        "全回答数": len(df),
        "出力日時": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    return out, conditions, float(threshold)


def n_caption(n_valid: int, n_missing: int = 0, n_not_asked: int = 0, extra: str = ""):
    """グラフの下に n・欠損を必ず表示する"""
    asked = n_valid + n_missing
    rate = f"{n_missing / asked * 100:.1f}%" if asked else "-"
    text = f"有効回答 n={n_valid:,}｜未回答 {n_missing:,}（未回答率 {rate}）"
    if n_not_asked:
        text += f"｜設問なし {n_not_asked:,}（集計対象外）"
    if extra:
        text += "｜" + extra
    st.caption(text)
    if n_valid < m.SMALL_N:
        st.warning(f"有効回答が {n_valid} 件と少ないため（{m.SMALL_N} 件未満）、割合や平均は大きくぶれる可能性があります。")


def bar(dist: pd.DataFrame, title: str, colors: Dict[str, str] = None, color_col: str = None):
    """distribution() の結果のうち有効回答だけを棒グラフにする"""
    d = dist[dist["扱い"] == "有効回答"].copy()
    d["表示"] = d.apply(lambda r: f"{r['件数']}件<br>{r['有効回答に占める割合(%)'] or 0:.1f}%", axis=1)
    kwargs = {}
    if color_col:
        kwargs = dict(color=color_col, color_discrete_map=colors)
    fig = px.bar(d, x="区分", y="件数", text="表示", title=title, **kwargs)
    fig.update_traces(textposition="outside", cliponaxis=False)
    # 色分けしても棒を横にずらさない（1区分1色のため）
    fig.update_layout(height=360, margin=dict(t=50, b=10), xaxis_title=None, barmode="relative",
                      yaxis_title="件数", showlegend=False)
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, width="stretch")


def correlation_note():
    st.info(m.CORRELATION_NOTE)


def show_table(df: pd.DataFrame, **kwargs):
    st.dataframe(df, width="stretch", hide_index=True, **kwargs)


def options_present(values: List[str], series: pd.Series) -> List[str]:
    return [v for v in values if v in set(series)]
