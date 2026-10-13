"""日別・週別の推移"""
from __future__ import annotations

import pandas as pd

from . import metrics as m

FREQS = {"日別": "D", "週別（月曜始まり）": "W-SUN", "月別": "M"}


def _period(s: pd.Series, freq: str) -> pd.Series:
    if freq == "D":
        return s.dt.floor("D")
    return s.dt.to_period(freq).dt.start_time


def period_label(ts: pd.Timestamp, freq: str) -> str:
    if freq == "D":
        return f"{ts.month}/{ts.day}"
    if freq.startswith("W"):
        return f"{ts.month}/{ts.day}週"
    return f"{ts.year}年{ts.month}月"


def add_labels(t: pd.DataFrame, freq: str) -> pd.DataFrame:
    if t.empty:
        return t
    return t.assign(期間ラベル=t["期間"].map(lambda p: period_label(p, freq)))


def survey_trend(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """回答日ごとの NPS・変化評価・満足度（有効回答数と少数データの注意つき）"""
    if df.empty:
        return pd.DataFrame()
    d = df.assign(期間=_period(df["answered_at"], freq))
    rows = []
    for p, g in d.groupby("期間"):
        s = m.nps_summary(g)
        rows.append({
            "期間": p, "回答数": len(g),
            "NPS有効回答数": s["有効回答数"], "NPS": m._r(s["NPS"]),
            "変化評価の平均": m._r(g["change_score"].mean(), 2) if g["change_score"].notna().any() else None,
            "変化評価n": int(g["change_score"].notna().sum()),
            "GFS満足度の平均": m._r(g["gfs_satisfaction"].mean(), 2) if g["gfs_satisfaction"].notna().any() else None,
            "少数データ": "○" if s["有効回答数"] < m.SMALL_N else "",
        })
    return add_labels(pd.DataFrame(rows), freq)


def cumulative_nps(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """その期間までの累計 NPS（日々の値のぶれが大きいときの見やすさ用）"""
    if df.empty:
        return pd.DataFrame()
    d = df.assign(期間=_period(df["answered_at"], freq)).sort_values("answered_at")
    rows = []
    for p in sorted(d["期間"].unique()):
        s = m.nps_summary(d[d["期間"] <= p])
        rows.append({"期間": p, "累計NPS": m._r(s["NPS"]), "累計NPS有効回答数": s["有効回答数"]})
    return add_labels(pd.DataFrame(rows), freq)


def action_trend(snaps: pd.DataFrame, freq: str, tasks) -> pd.DataFrame:
    """アクションリストの回答日ごとの回答数・平均達成項目数・各タスクの達成率"""
    if snaps.empty:
        return pd.DataFrame()
    d = snaps.assign(期間=_period(snaps["answered_at"], freq))
    rows = []
    for p, g in d.groupby("期間"):
        r = {"期間": p, "回答数": len(g), "平均達成項目数": m._r(g["progress"].astype(float).mean(), 2)}
        for t in tasks:
            v = g[t["key"]].dropna()
            r[t["label"] + "（%）"] = m._r(v.mean() * 100) if len(v) else None
        rows.append(r)
    return add_labels(pd.DataFrame(rows), freq)


def period_table(survey: pd.DataFrame, snaps: pd.DataFrame, freq: str, tasks) -> pd.DataFrame:
    """1行 = 1期間。アンケートとアクションリストの主要な数字を横に並べた一覧（新しい期間が上）。"""
    if survey.empty and (snaps is None or snaps.empty):
        return pd.DataFrame()
    parts = []
    if not survey.empty:
        d = survey.assign(期間=_period(survey["answered_at"], freq))
        rows = []
        for p, g in d.groupby("期間"):
            s = m.nps_summary(g)
            with_reason = g[g["reason_change"].notna()]
            r = {
                "期間": p,
                "アンケート回答数": len(g),
                "会員数": g["member_id"].nunique(),
                "NPS有効回答数": s["有効回答数"],
                "推奨者": s["推奨者数"], "中立者": s["中立者数"], "批判者": s["批判者数"],
                "NPS": m._r(s["NPS"]),
                "変化評価の平均": m._r(g["change_score"].mean(), 2) if g["change_score"].notna().any() else None,
                "GFS満足度の平均": m._r(g["gfs_satisfaction"].mean(), 2) if g["gfs_satisfaction"].notna().any() else None,
                "サポート満足度の平均": m._r(g["support_satisfaction"].mean(), 2) if g["support_satisfaction"].notna().any() else None,
                "変化理由の記入数": len(with_reason),
            }
            for c in m.CATEGORY_COLS:
                r["分類：" + m.CATEGORY_LABELS[c]] = int((with_reason[c] == 1).sum())
            r["少数データ"] = "○" if s["有効回答数"] < m.SMALL_N else ""
            rows.append(r)
        parts.append(pd.DataFrame(rows).set_index("期間"))
        cum = cumulative_nps(survey, freq).set_index("期間")[["累計NPS"]]
        parts.append(cum)
    if snaps is not None and not snaps.empty:
        a = action_trend(snaps, freq, tasks).set_index("期間").drop(columns="期間ラベル")
        a = a.rename(columns={"回答数": "アクション回答数", "平均達成項目数": "平均達成項目数"})
        a.columns = [c if c in ("アクション回答数", "平均達成項目数") else "達成率：" + c for c in a.columns]
        parts.append(a)
    out = pd.concat(parts, axis=1).sort_index(ascending=False).reset_index().rename(columns={"index": "期間"})
    for c in ["アンケート回答数", "会員数", "NPS有効回答数", "推奨者", "中立者", "批判者", "変化理由の記入数",
              "アクション回答数"] + ["分類：" + m.CATEGORY_LABELS[c] for c in m.CATEGORY_COLS]:
        if c in out:
            out[c] = out[c].fillna(0).astype(int)
    out.insert(0, "期間ラベル", out["期間"].map(lambda p: period_label(p, freq)))
    return out


def rows_in_period(df: pd.DataFrame, start: pd.Timestamp, freq: str) -> pd.DataFrame:
    return df[_period(df["answered_at"], freq) == start]
