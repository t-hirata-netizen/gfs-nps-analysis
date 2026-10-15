"""SQLite 接続とデータ読み出し"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from . import cloud, metrics

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "gfs_analysis.db"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")

INT_COLS = [
    "gfs_satisfaction", "support_satisfaction", "support_used", "nps",
    "nps_question_present", "change_score", "change_question_present",
]
CLASS_COLS = ["knowledge", "action", "judgment", "other", "unclassifiable"]


def db_path() -> Path:
    """環境変数 GFS_DB_PATH があればそちらを使う（サンプル用 DB の切り替えなど）"""
    return Path(os.environ.get("GFS_DB_PATH", DEFAULT_DB_PATH))


def connect(path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    path = Path(path) if path else db_path()
    if cloud.enabled() and str(path) != ":memory:":
        cloud.store(path).ensure_restored()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection):
    """古い DB のスキーマを現在の形に合わせる（データは保持）"""
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='change_classifications'"
    ).fetchone()[0]
    if "'ai'" not in sql:
        # source に 'ai'（AI が見直し・人の確認待ち）を追加。SQLite は CHECK を変更できないため作り直す
        # （既存データをそのまま写すだけなので、作り直しの間だけ外部キー検査を止める）
        conn.execute("PRAGMA foreign_keys = OFF")
        with conn:
            conn.execute("ALTER TABLE change_classifications RENAME TO _old_change_classifications")
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            cols = "response_id, knowledge, action, judgment, other, unclassifiable, source, updated_at"
            conn.execute(f"INSERT INTO change_classifications ({cols}) SELECT {cols} FROM _old_change_classifications")
            conn.execute("DROP TABLE _old_change_classifications")
        conn.execute("PRAGMA foreign_keys = ON")
    # 操作した人の記録欄（後から追加した列）
    for table, col in [("import_batches", "imported_by"), ("change_classifications", "updated_by")]:
        if col not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
            with conn:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")


def sync(conn: sqlite3.Connection) -> None:
    """書き込みの後に呼ぶ。クラウドではデータベースを Cloud Storage に保存する（ローカルでは何もしない）"""
    if cloud.enabled():
        cloud.store(db_path()).save(conn)


def load_responses(conn: sqlite3.Connection) -> pd.DataFrame:
    """アンケート回答（分類結果つき）を DataFrame で返す。同一会員の複数回答もすべて含む。"""
    df = pd.read_sql_query(
        """
        SELECT r.*, c.knowledge, c.action, c.judgment, c.other, c.unclassifiable,
               c.source AS class_source, c.updated_at AS class_updated_at
        FROM survey_responses r
        LEFT JOIN change_classifications c ON c.response_id = r.response_id
        ORDER BY r.answered_at, r.response_id
        """,
        conn,
    )
    df["answered_at"] = pd.to_datetime(df["answered_at"])
    for col in INT_COLS + CLASS_COLS:
        df[col] = pd.to_numeric(df[col]).astype("Int64")
    df["member_id"] = df["member_id"].astype(str)
    return metrics.add_labels(df)


def load_batches(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM import_batches ORDER BY batch_id DESC", conn
    )


def load_issues(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT i.batch_id, b.file_name, i.source_row_no, i.member_id,
               i.field, i.raw_value, i.issue_type, i.action
        FROM data_issues i JOIN import_batches b ON b.batch_id = i.batch_id
        ORDER BY i.batch_id, i.source_row_no
        """,
        conn,
    )
