"""毎日の取込：複数ファイルの種類を自動判別してまとめて取り込む"""
from __future__ import annotations

import io
import sqlite3
from typing import Dict, List, Optional, Tuple

import pandas as pd

from . import actions, classify, ingest

SURVEY, ACTION, LINK, UNKNOWN = "60日アンケート", "アクションリスト", "ID対応表", "不明"
ORDER = [LINK, ACTION, SURVEY]   # 対応表を先に入れると、同じ回のアクションリストもすぐ紐づく


def detect_kind(name: str, data: bytes) -> str:
    if name.lower().endswith((".xlsx", ".xlsm")):
        try:
            sheets = pd.ExcelFile(io.BytesIO(data)).sheet_names
        except Exception:
            return UNKNOWN
        return SURVEY if ingest.load_mapping()["sheet_name"] in sheets else UNKNOWN
    if name.lower().endswith(".csv"):
        try:
            header = list(actions._read_csv(data, nrows=0).columns)
        except Exception:
            return UNKNOWN
        link_cols = actions.load_yaml(actions.LINK_MAPPING_PATH)["columns"]
        if all(c in header for c in link_cols.values()):
            return LINK
        act_cols = actions.load_action_mapping()["columns"]
        if all(c in header for c in act_cols.values()):
            return ACTION
    return UNKNOWN


def import_many(conn: sqlite3.Connection, files: List[Tuple[str, bytes]]) -> pd.DataFrame:
    """files: [(ファイル名, 中身)]。1ファイルずつ結果を返す（失敗しても他は続ける）。"""
    tagged = [(detect_kind(n, d), n, d) for n, d in files]
    tagged.sort(key=lambda t: ORDER.index(t[0]) if t[0] in ORDER else len(ORDER))
    rows = []
    for kind, name, data in tagged:
        status, detail = "取込完了", ""
        try:
            if kind == SURVEY:
                r = ingest.import_survey_bytes(conn, data, name)
                n_class = classify.auto_classify(conn)
                detail = (f"新規 {r.inserted:,} 件（既存 {r.skipped_existing:,} 件はスキップ）"
                          f"／注意事項 {r.issue_count:,} 件／変化理由の自動分類 {n_class:,} 件")
            elif kind == ACTION:
                r = actions.import_actions(conn, data, name)
                detail = f"新規 {r['新規保存']:,} 件（既存 {r['取込済みのためスキップ']:,} 件はスキップ）"
            elif kind == LINK:
                r = actions.import_id_links(conn, data, name)
                detail = f"対応付け {r['対応付け']:,} 件／会員IDが変わった {r['会員IDが変わった']:,} 件"
            else:
                status, detail = "スキップ", "種類を判別できませんでした（列名・シート名を確認してください）"
        except ingest.DuplicateImportError:
            status, detail = "スキップ", "同じ内容のファイルは取込済みです"
        except ingest.MappingError as e:
            status, detail = "エラー", str(e)
        rows.append({"ファイル": name, "種類": kind, "結果": status, "内容": detail})
    return pd.DataFrame(rows)


def last_imports(conn: sqlite3.Connection) -> Dict[str, Optional[str]]:
    names = {"survey60": SURVEY, "action_list": ACTION, "id_link": LINK}
    got = dict(conn.execute(
        "SELECT source_type, MAX(imported_at) FROM import_batches GROUP BY source_type").fetchall())
    return {label: got.get(key) for key, label in names.items()}
