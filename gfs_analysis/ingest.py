"""60日アンケート Excel の取込

- 元ファイルは読み取るだけで変更しない（バイト列を読み込んでから解析）
- 会員ID は文字列として扱う
- 同じファイルの二重取込は SHA-256 で拒否、同じ回答（会員ID+回答日時）の再取込はスキップ
- 不正値は NULL にして data_issues に記録し、集計に混ぜない
"""
from __future__ import annotations

import hashlib
import io
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd
import yaml

from .db import PROJECT_ROOT
from .metrics import classify_nps

DEFAULT_MAPPING_PATH = PROJECT_ROOT / "config" / "mappings" / "survey60.yaml"

INT_FIELDS = ["gfs_satisfaction", "support_satisfaction", "nps", "change_score"]
TEXT_FIELDS = [
    "admission_good", "re_enroll", "reason_gfs", "reason_support", "reason_admission",
    "reason_recommend", "reason_reenroll", "reason_change", "worries",
]


class DuplicateImportError(Exception):
    """同じファイルが取込済み"""


class MappingError(Exception):
    """必要な列・シートがない"""


@dataclass
class ImportResult:
    batch_id: int
    file_name: str
    row_count: int
    inserted: int
    skipped_existing: int
    skipped_invalid: int
    skipped_in_file_dup: int
    issue_count: int


def load_mapping(path: Union[str, Path] = DEFAULT_MAPPING_PATH) -> Dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ""
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def normalize_member_id(v) -> Optional[str]:
    """会員ID を文字列に正規化。Excel で数値化された 12345.0 は '12345' に戻す。"""
    if _is_blank(v):
        return None
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    s = str(v).strip()
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    return s or None


def parse_int(v, lo: int, hi: int) -> Tuple[Optional[int], Optional[str]]:
    """(値, エラー種別) を返す。空欄は (None, None)。"""
    if _is_blank(v):
        return None, None
    try:
        f = float(str(v).strip())
    except ValueError:
        return None, "数値ではない"
    if not f.is_integer():
        return None, "整数ではない"
    i = int(f)
    if not lo <= i <= hi:
        return None, f"範囲外（{lo}〜{hi}）"
    return i, None


def parse_datetime(v) -> Optional[str]:
    if _is_blank(v):
        return None
    ts = pd.to_datetime(v, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def _text(v) -> Optional[str]:
    if _is_blank(v):
        return None
    return str(v).strip()


def read_survey_frame(data: bytes, mapping: Dict) -> pd.DataFrame:
    sheet = mapping["sheet_name"]
    try:
        raw = pd.read_excel(io.BytesIO(data), sheet_name=sheet, dtype=object)
    except ValueError as e:
        raise MappingError(f"シート「{sheet}」が見つかりません") from e
    missing = [src for src in mapping["columns"].values() if src not in raw.columns]
    if missing:
        raise MappingError("必要な列がありません: " + "、".join(missing))
    return raw


def _question_present(times: List[Optional[str]], values: List[Optional[object]],
                      start: Optional[str]) -> List[int]:
    """設問が存在した回答なら 1。start 未指定なら最初に値が入った日時から存在とみなす。"""
    if start is None:
        answered = [t for t, v in zip(times, values) if t is not None and v is not None]
        start = min(answered) if answered else None
    else:
        start = parse_datetime(start)
    result = []
    for t, v in zip(times, values):
        if v is not None:
            result.append(1)
        elif start is None or t is None:
            result.append(0)
        else:
            result.append(1 if t >= start else 0)
    return result


def import_survey_bytes(conn: sqlite3.Connection, data: bytes, file_name: str,
                        mapping: Optional[Dict] = None,
                        now: Optional[datetime] = None,
                        user: Optional[str] = None) -> ImportResult:
    mapping = mapping or load_mapping()
    source_type = mapping["source_type"]
    sha = file_sha256(data)
    hit = conn.execute(
        "SELECT file_name, imported_at FROM import_batches WHERE source_type=? AND file_sha256=?",
        (source_type, sha),
    ).fetchone()
    if hit:
        raise DuplicateImportError(
            f"同じ内容のファイルは取込済みです（{hit[0]}、{hit[1]}）"
        )

    raw = read_survey_frame(data, mapping)
    cols = mapping["columns"]
    ranges = mapping["ranges"]
    not_used = set(mapping.get("support_not_used_values") or [])
    orig_cat_map = mapping.get("nps_category_original_values") or {}
    q_start = mapping.get("question_start") or {}

    issues: List[Dict] = []
    records: List[Dict] = []
    skipped_invalid = 0

    for idx, row in raw.iterrows():
        row_no = int(idx) + 2  # Excel の行番号（1行目は見出し）
        member_id = normalize_member_id(row[cols["member_id"]])
        answered_at = parse_datetime(row[cols["answered_at"]])

        def issue(field, value, kind, action):
            issues.append({"source_row_no": row_no, "member_id": member_id, "field": field,
                           "raw_value": None if _is_blank(value) else str(value),
                           "issue_type": kind, "action": action})

        if member_id is None:
            issue(cols["member_id"], row[cols["member_id"]], "会員ID欠損", "行を取り込まない")
            skipped_invalid += 1
            continue
        if answered_at is None:
            issue(cols["answered_at"], row[cols["answered_at"]], "回答日時が欠損・不正", "行を取り込まない")
            skipped_invalid += 1
            continue

        rec = {"source_row_no": row_no, "member_id": member_id, "answered_at": answered_at}

        support_raw = row[cols["support_satisfaction"]]
        if not _is_blank(support_raw) and str(support_raw).strip() in not_used:
            rec["support_used"] = 0
            rec["support_satisfaction"] = None
        else:
            rec["support_used"] = None
        for field in INT_FIELDS:
            if field == "support_satisfaction" and rec["support_used"] == 0:
                continue
            lo, hi = ranges[field]
            value, err = parse_int(row[cols[field]], lo, hi)
            if err:
                issue(cols[field], row[cols[field]], err, "空欄として扱う（集計に含めない）")
            rec[field] = value
            rec["_raw_" + field] = not _is_blank(row[cols[field]])
        if rec["support_used"] is None and rec["support_satisfaction"] is not None:
            rec["support_used"] = 1

        for field in TEXT_FIELDS:
            rec[field] = _text(row[cols[field]])

        # 元ファイルの NPS区分 との整合チェック（区分自体は 0〜10 から再計算する）
        orig = _text(row[cols["nps_category_original"]])
        if orig is not None:
            expected = classify_nps(rec["nps"])
            if orig_cat_map.get(orig, orig) != expected:
                issue(cols["nps_category_original"], orig,
                      f"NPS区分の不一致（0〜10からの区分: {expected or 'なし'}）",
                      "0〜10の値から再計算した区分を使う")
        records.append(rec)

    # ファイル内で同じ会員ID+回答日時が重複している行
    seen = set()
    unique_records = []
    in_file_dup = 0
    for rec in records:
        key = (rec["member_id"], rec["answered_at"])
        if key in seen:
            in_file_dup += 1
            issues.append({"source_row_no": rec["source_row_no"], "member_id": rec["member_id"],
                           "field": cols["answered_at"], "raw_value": rec["answered_at"],
                           "issue_type": "ファイル内で会員ID・回答日時が同一の行",
                           "action": "2行目以降を取り込まない"})
            continue
        seen.add(key)
        unique_records.append(rec)

    times = [r["answered_at"] for r in unique_records]
    for field, flag in [("nps", "nps_question_present"), ("change_score", "change_question_present")]:
        # 不正値でもセルに何か入っていれば「設問はあった」とみなす
        raw_flags = [True if r["_raw_" + field] else None for r in unique_records]
        present = _question_present(times, raw_flags, q_start.get(field))
        for r, p in zip(unique_records, present):
            r[flag] = p

    imported_at = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    columns = ["batch_id", "source_row_no", "member_id", "answered_at", "gfs_satisfaction",
               "support_satisfaction", "support_used", "nps", "nps_question_present",
               "change_score", "change_question_present"] + TEXT_FIELDS
    with conn:
        cur = conn.execute(
            """INSERT INTO import_batches (source_type, file_name, file_sha256, sheet_name,
                   row_count, inserted_count, skipped_count, imported_at, imported_by)
               VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)""",
            (source_type, file_name, sha, mapping["sheet_name"], len(raw), imported_at, user),
        )
        batch_id = cur.lastrowid
        for r in unique_records:
            conn.execute(
                """INSERT INTO members (member_id, first_seen_at, last_seen_at) VALUES (?, ?, ?)
                   ON CONFLICT(member_id) DO UPDATE SET
                     first_seen_at = MIN(first_seen_at, excluded.first_seen_at),
                     last_seen_at  = MAX(last_seen_at, excluded.last_seen_at)""",
                (r["member_id"], r["answered_at"], r["answered_at"]),
            )
        before = conn.total_changes
        for r in unique_records:
            r["batch_id"] = batch_id
            conn.execute(
                f"INSERT OR IGNORE INTO survey_responses ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                [r[c] for c in columns],
            )
        inserted = conn.total_changes - before
        for i in issues:
            conn.execute(
                """INSERT INTO data_issues (batch_id, source_row_no, member_id, field,
                       raw_value, issue_type, action) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (batch_id, i["source_row_no"], i["member_id"], i["field"],
                 i["raw_value"], i["issue_type"], i["action"]),
            )
        skipped = len(raw) - inserted
        conn.execute("UPDATE import_batches SET inserted_count=?, skipped_count=? WHERE batch_id=?",
                     (inserted, skipped, batch_id))

    return ImportResult(
        batch_id=batch_id, file_name=file_name, row_count=len(raw), inserted=inserted,
        skipped_existing=len(unique_records) - inserted, skipped_invalid=skipped_invalid,
        skipped_in_file_dup=in_file_dup, issue_count=len(issues),
    )


def import_survey_file(conn: sqlite3.Connection, path: Union[str, Path],
                       mapping: Optional[Dict] = None, user: Optional[str] = None) -> ImportResult:
    path = Path(path)
    return import_survey_bytes(conn, path.read_bytes(), path.name, mapping, user=user)
