"""「変化理由」の分類（知識・行動・判断・その他・分類不可、複数該当可）

自動分類はローカルのキーワード辞書だけで行う（外部 API には送らない）。
人が修正した分類（source=manual）と AI が見直した分類（source=ai）は自動分類で上書きしない。
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

import yaml

from .db import PROJECT_ROOT
from .metrics import CATEGORY_COLS, CATEGORY_LABELS

DEFAULT_KEYWORDS_PATH = PROJECT_ROOT / "config" / "change_keywords.yaml"
AUTO_COLS = ["knowledge", "action", "judgment", "other"]


def load_keywords(path: Union[str, Path] = DEFAULT_KEYWORDS_PATH) -> Dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower().strip()


def suggest(text: str, keywords: Dict) -> Dict[str, int]:
    flags = {c: 0 for c in CATEGORY_COLS}
    t = _norm(text)
    exact = {_norm(x) for x in keywords.get("unclassifiable_exact", [])}
    # 「行動には移せていない」などの否定部分を判定から外す
    for pat in keywords.get("negation_patterns", []):
        t = re.sub(pat, "", t)
    if _norm(text).rstrip("。.!！") not in exact:
        for cat in AUTO_COLS:
            if any(_norm(k) in t for k in keywords["categories"].get(cat, [])):
                flags[cat] = 1
    if not any(flags.values()):
        flags["unclassifiable"] = 1
    return flags


def validate_flags(flags: Dict[str, int]) -> Optional[str]:
    selected = [c for c in CATEGORY_COLS if flags.get(c)]
    if not selected:
        return "分類が1つも選ばれていません"
    if "unclassifiable" in selected and len(selected) > 1:
        return "「分類不可」は他の分類と同時に選べません"
    return None


def _now(now: Optional[datetime]) -> str:
    return (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


_UPSERT = """
INSERT INTO change_classifications
    (response_id, knowledge, action, judgment, other, unclassifiable, source, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(response_id) DO UPDATE SET
    knowledge=excluded.knowledge, action=excluded.action, judgment=excluded.judgment,
    other=excluded.other, unclassifiable=excluded.unclassifiable,
    source=excluded.source, updated_at=excluded.updated_at
"""


def auto_classify(conn: sqlite3.Connection, keywords: Optional[Dict] = None,
                  now: Optional[datetime] = None) -> int:
    """未分類・自動分類の回答に分類案を付ける。人・AI が見直したもの（manual / ai）は触らない。"""
    keywords = keywords or load_keywords()
    rows = conn.execute(
        """SELECT r.response_id, r.reason_change, c.source
           FROM survey_responses r
           LEFT JOIN change_classifications c ON c.response_id = r.response_id
           WHERE r.reason_change IS NOT NULL"""
    ).fetchall()
    ts = _now(now)
    n = 0
    with conn:
        for rid, text, source in rows:
            if source in ("manual", "ai"):
                continue
            f = suggest(text, keywords)
            conn.execute(_UPSERT, (rid, *[f[c] for c in CATEGORY_COLS], "auto", ts))
            n += 1
    return n


def save_manual(conn: sqlite3.Connection, records: Iterable[Dict],
                now: Optional[datetime] = None, source: str = "manual") -> int:
    """人が確認・修正した分類を保存する。1件でも不正があれば何も保存しない。
    source="ai" は AI が見直した分類（人の最終確認待ち）として保存する。"""
    if source not in ("manual", "ai"):
        raise ValueError(f"不明な source: {source}")
    records = list(records)
    errors: List[str] = []
    for r in records:
        err = validate_flags(r)
        if err:
            errors.append(f"回答ID {r['response_id']}: {err}")
    if errors:
        raise ValueError("\n".join(errors))
    ts = _now(now)
    with conn:
        for r in records:
            conn.execute(_UPSERT, (int(r["response_id"]),
                                   *[1 if r.get(c) else 0 for c in CATEGORY_COLS], source, ts))
    return len(records)


SOURCE_LABELS = {"auto": "自動（未確認）", "ai": "AI確認（人の確認待ち）", "manual": "確認済み"}


def label_list(flags: Dict[str, int]) -> str:
    return "・".join(CATEGORY_LABELS[c] for c in CATEGORY_COLS if flags.get(c))
