"""データ品質チェックと重複の扱い"""
from __future__ import annotations

from typing import List

import pandas as pd

from .metrics import COLUMN_LABELS, MISSING, NOT_ASKED, NOT_USED, TEXT_COLS

DEFAULT_NEAR_DUP_SECONDS = 60

DEDUP_NEAR = "近接重複を除く（各組の最後の回答を採用）"
DEDUP_ALL = "全回答（重複も含めてすべて）"
DEDUP_FIRST = "会員ごとに最初の回答のみ"
DEDUP_LATEST = "会員ごとに最新の回答のみ"
DEDUP_MODES: List[str] = [DEDUP_NEAR, DEDUP_ALL, DEDUP_FIRST, DEDUP_LATEST]


def mark_near_duplicates(df: pd.DataFrame, threshold_sec: float) -> pd.DataFrame:
    """同じ会員の回答が threshold_sec 秒以内に連続していたら同じ組にまとめる。

    near_dup_group: 組番号（単独回答は NA）
    near_dup_drop : 組の中で最後の回答以外は True（二重送信の疑い）
    """
    out = df.copy()
    if out.empty:
        out["near_dup_group"] = pd.Series(dtype="Int64")
        out["near_dup_drop"] = pd.Series(dtype=bool)
        return out
    d = out.sort_values(["member_id", "answered_at", "response_id"])
    gap = d.groupby("member_id")["answered_at"].diff().dt.total_seconds()
    cluster = (gap.isna() | (gap > threshold_sec)).cumsum()
    size = cluster.map(cluster.value_counts())
    last_id = d["response_id"].groupby(cluster).transform("last")
    dup_clusters = cluster[size > 1]
    numbering = {c: i + 1 for i, c in enumerate(dup_clusters.unique())}
    out["near_dup_group"] = cluster.map(numbering).reindex(out.index).astype("Int64")
    out["near_dup_drop"] = ((size > 1) & (d["response_id"] != last_id)).reindex(out.index)
    return out


def apply_dedup(df: pd.DataFrame, mode: str, threshold_sec: float) -> pd.DataFrame:
    if mode == DEDUP_ALL or df.empty:
        return df
    if mode == DEDUP_NEAR:
        marked = mark_near_duplicates(df, threshold_sec)
        return df[~marked["near_dup_drop"]]
    ordered = df.sort_values(["answered_at", "response_id"])
    if mode == DEDUP_FIRST:
        return ordered.drop_duplicates("member_id", keep="first").sort_index()
    if mode == DEDUP_LATEST:
        return ordered.drop_duplicates("member_id", keep="last").sort_index()
    raise ValueError(f"不明な重複の扱い: {mode}")


def duplicate_members(df: pd.DataFrame) -> pd.DataFrame:
    """複数回答のある会員の一覧"""
    cols = ["会員ID", "回答数", "最初の回答", "最後の回答", "最短間隔(秒)"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    d = df.sort_values("answered_at")
    g = d.groupby("member_id")
    res = pd.DataFrame({
        "回答数": g.size(),
        "最初の回答": g["answered_at"].min(),
        "最後の回答": g["answered_at"].max(),
        "最短間隔(秒)": g["answered_at"].apply(lambda s: s.diff().dt.total_seconds().min()),
    })
    res = res[res["回答数"] > 1].reset_index().rename(columns={"member_id": "会員ID"})
    return res[cols].sort_values(["最短間隔(秒)", "会員ID"]).reset_index(drop=True)


def near_duplicate_table(df: pd.DataFrame, threshold_sec: float) -> pd.DataFrame:
    marked = mark_near_duplicates(df, threshold_sec)
    m = marked[marked["near_dup_group"].notna()].sort_values(["near_dup_group", "answered_at"])
    return pd.DataFrame({
        "組": m["near_dup_group"],
        "会員ID": m["member_id"],
        "回答日時": m["answered_at"],
        "NPS": m["nps"],
        "変化評価": m["change_score"],
        "GFS満足度": m["gfs_satisfaction"],
        "集計での扱い（近接重複を除く場合）": m["near_dup_drop"].map({True: "除外", False: "採用"}),
    }).reset_index(drop=True)


def missing_report(df: pd.DataFrame) -> pd.DataFrame:
    """項目ごとの欠損。設問なし・未利用は未回答と分けて表示する。"""
    rows = []
    for col, label_col in [("gfs_satisfaction", "gfs_label"), ("support_satisfaction", "support_label"),
                           ("nps", "nps_label"), ("change_score", "change_label")]:
        labels = df[label_col]
        not_asked = int((labels == NOT_ASKED).sum())
        not_used = int((labels == NOT_USED).sum())
        missing = int((labels == MISSING).sum())
        target = len(df) - not_asked - not_used
        rows.append({
            "項目": COLUMN_LABELS[col],
            "全行数": len(df),
            "設問なし": not_asked,
            "未利用": not_used,
            "回答対象": target,
            "有効回答": target - missing,
            "未回答": missing,
            "未回答率(%)": round(missing / target * 100, 1) if target else None,
        })
    for col in TEXT_COLS:
        filled = int(df[col].notna().sum())
        rows.append({
            "項目": COLUMN_LABELS[col] + "（自由記述）",
            "全行数": len(df), "設問なし": 0, "未利用": 0, "回答対象": len(df),
            "有効回答": filled, "未回答": len(df) - filled,
            "未回答率(%)": round((len(df) - filled) / len(df) * 100, 1) if len(df) else None,
        })
    return pd.DataFrame(rows)
