"""集計ロジック（NPS・分布・クロス集計）

方針:
- NPS は 0〜10 の有効回答のみを分母にする。未回答・設問なしは分母に入れない。
- 未回答を 0 や「変化なし」として数えない。
- 件数が SMALL_N 未満の集計には「少数データ」フラグを付ける。
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

SMALL_N = 30

CORRELATION_NOTE = (
    "※ここに示す関係は「同時に見られる傾向（相関）」です。"
    "一方が他方の原因である（因果関係がある）ことを示すものではありません。"
)

PROMOTER, PASSIVE, DETRACTOR = "推奨者", "中立者", "批判者"
MISSING, NOT_ASKED, NOT_USED = "未回答", "設問なし", "未利用"

NPS_CATEGORIES = [PROMOTER, PASSIVE, DETRACTOR]
NPS_CATEGORY_OPTIONS = NPS_CATEGORIES + [MISSING, NOT_ASKED]
NPS_VALUES = [str(i) for i in range(11)]
SCORE5_VALUES = [str(i) for i in range(1, 6)]
CHANGE_OPTIONS = SCORE5_VALUES + [MISSING, NOT_ASKED]

CATEGORY_COLS = ["knowledge", "action", "judgment", "other", "unclassifiable"]
CATEGORY_LABELS = {
    "knowledge": "知識",
    "action": "行動",
    "judgment": "判断",
    "other": "その他",
    "unclassifiable": "分類不可",
}
UNCLASSIFIED, NO_REASON = "未分類", "記述なし"

COLUMN_LABELS = {
    "response_id": "回答ID",
    "member_id": "会員ID",
    "answered_at": "回答日時",
    "gfs_satisfaction": "GFS満足度",
    "support_satisfaction": "サポート満足度",
    "support_label": "サポート満足度（区分）",
    "nps": "NPS(0-10)",
    "nps_category": "NPS区分",
    "change_score": "変化評価",
    "change_label": "変化評価（区分）",
    "admission_good": "入学してよかった",
    "re_enroll": "再入学したい",
    "reason_gfs": "GFS理由",
    "reason_support": "サポ理由",
    "reason_admission": "入学理由",
    "reason_recommend": "勧める理由",
    "reason_reenroll": "再入学理由",
    "reason_change": "変化理由",
    "worries": "悩み・モヤモヤ",
}
TEXT_COLS = [
    "reason_gfs", "reason_support", "reason_admission", "reason_recommend",
    "reason_reenroll", "reason_change", "worries",
]


def classify_nps(score) -> Optional[str]:
    """0〜10 → 推奨者(9-10)/中立者(7-8)/批判者(0-6)。欠損は None。"""
    if score is None or pd.isna(score):
        return None
    score = int(score)
    if not 0 <= score <= 10:
        raise ValueError(f"NPS は 0〜10 の範囲です: {score}")
    if score >= 9:
        return PROMOTER
    if score >= 7:
        return PASSIVE
    return DETRACTOR


def _score_label(value, present) -> str:
    if pd.notna(value):
        return str(int(value))
    return MISSING if int(present) == 1 else NOT_ASKED


def add_labels(df: pd.DataFrame) -> pd.DataFrame:
    """集計・絞り込み用の表示ラベル列を追加する"""
    df = df.copy()
    df["nps_label"] = [
        _score_label(v, p) for v, p in zip(df["nps"], df["nps_question_present"])
    ]
    df["nps_category"] = [
        classify_nps(v) if pd.notna(v) else (MISSING if int(p) == 1 else NOT_ASKED)
        for v, p in zip(df["nps"], df["nps_question_present"])
    ]
    df["change_label"] = [
        _score_label(v, p) for v, p in zip(df["change_score"], df["change_question_present"])
    ]
    df["gfs_label"] = [str(int(v)) if pd.notna(v) else MISSING for v in df["gfs_satisfaction"]]
    df["support_label"] = [
        str(int(v)) if pd.notna(v) else (NOT_USED if (pd.notna(u) and int(u) == 0) else MISSING)
        for v, u in zip(df["support_satisfaction"], df["support_used"])
    ]
    return df


def nps_summary(df: pd.DataFrame) -> Dict:
    valid = df["nps"].dropna().astype(int)
    n = int(len(valid))
    promoters = int((valid >= 9).sum())
    detractors = int((valid <= 6).sum())
    passives = n - promoters - detractors
    n_missing = int((df["nps_category"] == MISSING).sum())
    n_not_asked = int((df["nps_category"] == NOT_ASKED).sum())
    asked = n + n_missing

    def pct(x):
        return x / n * 100 if n else None

    return {
        "対象行数": int(len(df)),
        "有効回答数": n,
        "未回答数": n_missing,
        "設問なし数": n_not_asked,
        "未回答率(%)": n_missing / asked * 100 if asked else None,
        "推奨者数": promoters,
        "中立者数": passives,
        "批判者数": detractors,
        "推奨者率(%)": pct(promoters),
        "中立者率(%)": pct(passives),
        "批判者率(%)": pct(detractors),
        "NPS": (promoters - detractors) / n * 100 if n else None,
        "少数データ": n < SMALL_N,
    }


def distribution(df: pd.DataFrame, label_col: str, valid_values: List[str],
                 extra_labels: List[str]) -> pd.DataFrame:
    """有効回答の分布。未回答等は件数だけ示し、割合の分母には入れない。"""
    counts = df[label_col].value_counts()
    n_valid = int(sum(counts.get(v, 0) for v in valid_values))
    rows = []
    for v in valid_values:
        c = int(counts.get(v, 0))
        rows.append({"区分": v, "件数": c,
                     "有効回答に占める割合(%)": round(c / n_valid * 100, 1) if n_valid else None,
                     "扱い": "有効回答"})
    for v in extra_labels:
        rows.append({"区分": v, "件数": int(counts.get(v, 0)),
                     "有効回答に占める割合(%)": None, "扱い": "集計対象外"})
    return pd.DataFrame(rows)


def score_stats(series: pd.Series) -> Dict:
    valid = series.dropna()
    n = int(len(valid))
    return {
        "有効回答数": n,
        "平均": float(valid.mean()) if n else None,
        "中央値": float(valid.median()) if n else None,
        "少数データ": n < SMALL_N,
    }


def group_nps(df: pd.DataFrame, group_col: str, order: Optional[List[str]] = None) -> pd.DataFrame:
    """グループ別の NPS。各グループの件数と少数データフラグを必ず添える。"""
    groups = order if order is not None else sorted(df[group_col].dropna().unique().tolist())
    rows = []
    for g in groups:
        sub = df[df[group_col] == g]
        s = nps_summary(sub)
        rows.append({
            "グループ": g,
            "回答数": s["対象行数"],
            "NPS有効回答数": s["有効回答数"],
            "推奨者率(%)": _r(s["推奨者率(%)"]),
            "批判者率(%)": _r(s["批判者率(%)"]),
            "NPS": _r(s["NPS"]),
            "注意": ("有効回答なし" if s["有効回答数"] == 0
                     else "少数データ（n<%d）" % SMALL_N if s["少数データ"] else ""),
        })
    return pd.DataFrame(rows)


def crosstab(df: pd.DataFrame, row_col: str, col_col: str,
             row_order: Optional[List[str]] = None,
             col_order: Optional[List[str]] = None):
    """件数のクロス表と行％のクロス表を返す（合計行・列つき）"""
    counts = pd.crosstab(df[row_col], df[col_col])
    if row_order is not None:
        counts = counts.reindex([r for r in row_order], fill_value=0)
    if col_order is not None:
        counts = counts.reindex(columns=[c for c in col_order], fill_value=0)
    counts["合計"] = counts.sum(axis=1)
    counts.loc["合計"] = counts.sum(axis=0)
    row_pct = counts.div(counts["合計"].where(counts["合計"] > 0), axis=0) * 100
    row_pct = row_pct.round(1)
    counts.index.name = row_col
    row_pct.index.name = row_col
    return counts, row_pct


def explode_categories(df: pd.DataFrame) -> pd.DataFrame:
    """変化理由の分類を1行1カテゴリに展開する（複数該当があるため合計は回答数と一致しない）"""
    records = []
    for _, row in df.iterrows():
        if pd.isna(row.get("reason_change")):
            labels = [NO_REASON]
        elif pd.isna(row.get("knowledge")):
            labels = [UNCLASSIFIED]
        else:
            labels = [CATEGORY_LABELS[c] for c in CATEGORY_COLS if row.get(c) == 1] or [UNCLASSIFIED]
        for lab in labels:
            r = row.to_dict()
            r["change_category"] = lab
            records.append(r)
    if not records:
        return df.assign(change_category=pd.Series(dtype=object))
    return pd.DataFrame(records)


def category_order() -> List[str]:
    return [CATEGORY_LABELS[c] for c in CATEGORY_COLS] + [UNCLASSIFIED, NO_REASON]


def category_summary(df: pd.DataFrame) -> pd.DataFrame:
    """分類ごとの該当件数（変化理由の記入がある回答が分母）"""
    with_reason = df[df["reason_change"].notna()]
    n = len(with_reason)
    classified = with_reason[with_reason["knowledge"].notna()]
    rows = []
    for c in CATEGORY_COLS:
        k = int((classified[c] == 1).sum())
        rows.append({"分類": CATEGORY_LABELS[c], "該当件数": k,
                     "記述ありに占める割合(%)": _r(k / n * 100) if n else None})
    rows.append({"分類": UNCLASSIFIED, "該当件数": int(n - len(classified)),
                 "記述ありに占める割合(%)": _r((n - len(classified)) / n * 100) if n else None})
    return pd.DataFrame(rows)


def _r(x, digits: int = 1):
    return None if x is None else round(float(x), digits)
