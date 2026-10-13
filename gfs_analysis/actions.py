"""アクションリストと ID 対応表の取込・アンケートとの紐づけ・分析

- アクションリストの回答者ID は Liny の登録ID（9桁）で、会員ID とは別体系。
  ID 対応表（Liny の友だち情報エクスポート）で会員ID に変換して紐づける。
- 氏名・メール・電話番号は保存しない。
- 相関は因果関係を示さない（画面・出力で必ず注記する）。
"""
from __future__ import annotations

import io
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd
import yaml
from scipy import stats

from . import metrics as m
from .db import PROJECT_ROOT
from .ingest import (DuplicateImportError, MappingError, _is_blank, file_sha256,
                     normalize_member_id, parse_datetime)

ACTION_MAPPING_PATH = PROJECT_ROOT / "config" / "mappings" / "action_list.yaml"
LINK_MAPPING_PATH = PROJECT_ROOT / "config" / "mappings" / "id_link.yaml"
ENCODINGS = ["utf-8-sig", "cp932"]

TIMING_BEFORE = "アンケート回答時点までの最新回答"
TIMING_LATEST = "最新の回答（アンケート後を含む）"
TIMING_MODES = [TIMING_BEFORE, TIMING_LATEST]


def load_yaml(path: Union[str, Path]) -> Dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_action_mapping() -> Dict:
    return load_yaml(ACTION_MAPPING_PATH)


def _read_csv(data: bytes, **kwargs) -> pd.DataFrame:
    """UTF-8（BOM付き）→ Shift_JIS(cp932) の順に試す"""
    last = None
    for enc in ENCODINGS:
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc, dtype=str,
                               keep_default_na=False, **kwargs)
        except UnicodeDecodeError as e:
            last = e
    raise MappingError(f"文字コードを判定できませんでした（{last}）")


def _check_not_imported(conn, source_type: str, sha: str):
    hit = conn.execute(
        "SELECT file_name, imported_at FROM import_batches WHERE source_type=? AND file_sha256=?",
        (source_type, sha)).fetchone()
    if hit:
        raise DuplicateImportError(f"同じ内容のファイルは取込済みです（{hit[0]}、{hit[1]}）")


def _new_batch(conn, source_type, file_name, sha, row_count, ts) -> int:
    cur = conn.execute(
        """INSERT INTO import_batches (source_type, file_name, file_sha256, sheet_name,
               row_count, inserted_count, skipped_count, imported_at)
           VALUES (?, ?, ?, NULL, ?, 0, 0, ?)""",
        (source_type, file_name, sha, row_count, ts))
    return cur.lastrowid


def _add_issue(conn, batch_id, row_no, ident, field, raw, kind, action):
    conn.execute(
        """INSERT INTO data_issues (batch_id, source_row_no, member_id, field, raw_value,
               issue_type, action) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (batch_id, row_no, ident, field, raw, kind, action))


# ---------------------------------------------------------------- ID 対応表
def read_link_frame(data: bytes, mapping: Dict) -> pd.DataFrame:
    cols = mapping["columns"]
    wanted = [cols["external_id"], cols["member_id"]]
    header = list(_read_csv(data, nrows=0).columns)
    missing = [c for c in wanted if c not in header]
    if missing:
        raise MappingError("必要な列がありません: " + "、".join(missing))
    # 必要な2列だけ読む（メール・電話番号などは読み込まない）
    return _read_csv(data, usecols=wanted)


def import_id_links(conn: sqlite3.Connection, data: bytes, file_name: str,
                    mapping: Optional[Dict] = None, now: Optional[datetime] = None) -> Dict:
    mapping = mapping or load_yaml(LINK_MAPPING_PATH)
    sha = file_sha256(data)
    _check_not_imported(conn, mapping["source_type"], sha)
    df = read_link_frame(data, mapping)
    cols = mapping["columns"]
    ext = df[cols["external_id"]].map(normalize_member_id)
    mem = df[cols["member_id"]].map(normalize_member_id)
    pairs = pd.DataFrame({"ext": ext, "mem": mem, "row": df.index + 2}).dropna(subset=["ext", "mem"])
    blank = len(df) - len(pairs)
    counts = pairs.groupby("ext")["mem"].nunique()
    conflict = set(counts[counts > 1].index)
    good = pairs[~pairs["ext"].isin(conflict)].drop_duplicates("ext")
    ts = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    existing = dict(conn.execute("SELECT external_id, member_id FROM id_links").fetchall())
    changed = [(e, existing[e], mm) for e, mm in zip(good["ext"], good["mem"])
               if e in existing and existing[e] != mm]
    with conn:
        batch_id = _new_batch(conn, mapping["source_type"], file_name, sha, len(df), ts)
        conn.executemany(
            """INSERT INTO id_links (external_id, member_id, batch_id, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(external_id) DO UPDATE SET member_id=excluded.member_id,
                 batch_id=excluded.batch_id, updated_at=excluded.updated_at""",
            [(e, mm, batch_id, ts) for e, mm in zip(good["ext"], good["mem"])])
        for e in sorted(conflict):
            _add_issue(conn, batch_id, None, e, cols["member_id"], None,
                       "1つの登録IDに複数の会員ID", "対応付けしない")
        for e, old, new in changed:
            _add_issue(conn, batch_id, None, e, cols["member_id"], f"{old}→{new}",
                       "対応する会員IDが変わった", "新しい会員IDに更新")
        conn.execute("UPDATE import_batches SET inserted_count=?, skipped_count=? WHERE batch_id=?",
                     (len(good), len(df) - len(good), batch_id))
    return {"ファイルの行数": len(df), "対応付け": len(good), "ID空欄（スキップ）": blank,
            "登録IDの重複・矛盾（スキップ）": len(conflict), "会員IDが変わった": len(changed),
            "batch_id": batch_id}


# ---------------------------------------------------------- アクションリスト
def _clean_answer(v) -> Optional[str]:
    if _is_blank(v):
        return None
    return str(v).strip().rstrip("…").rstrip(".").strip() or None


def read_action_frame(data: bytes, mapping: Dict) -> pd.DataFrame:
    """見出しが重複するため位置で扱う。列名は 0,1,2… になり、見出しは attrs に入れる。"""
    raw = _read_csv(data, header=None)
    if raw.empty:
        raise MappingError("ファイルが空です")
    header = [str(h).strip() for h in raw.iloc[0]]
    body = raw.iloc[1:].reset_index(drop=True)
    for key, name in mapping["columns"].items():
        if name not in header:
            raise MappingError(f"必要な列がありません: {name}")
    for t in mapping["tasks"]:
        i = t["column_index"]
        if i >= len(header) or header[i] != t["header"]:
            got = header[i] if i < len(header) else "（列なし）"
            raise MappingError(
                f"タスク「{t['label']}」の列が想定と違います（{i}列目: 想定「{t['header']}」/ 実際「{got}」）。"
                "config/mappings/action_list.yaml を確認してください。")
    body.attrs["header"] = header
    return body


def import_actions(conn: sqlite3.Connection, data: bytes, file_name: str,
                   mapping: Optional[Dict] = None, now: Optional[datetime] = None) -> Dict:
    mapping = mapping or load_action_mapping()
    sha = file_sha256(data)
    _check_not_imported(conn, mapping["source_type"], sha)
    body = read_action_frame(data, mapping)
    header = body.attrs["header"]
    pos = {k: header.index(v) for k, v in mapping["columns"].items()}
    ts = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    inserted = existing = invalid = 0
    issues = []
    with conn:
        batch_id = _new_batch(conn, mapping["source_type"], file_name, sha, len(body), ts)
        for idx, row in body.iterrows():
            row_no = int(idx) + 2
            rid = normalize_member_id(row[pos["response_id"]])
            ext = normalize_member_id(row[pos["external_id"]])
            at = parse_datetime(row[pos["answered_at"]])
            if rid is None or ext is None or at is None:
                invalid += 1
                issues.append((row_no, ext, "回答ID/回答者ID/回答日時", None,
                               "必須項目の欠損・不正", "行を取り込まない"))
                continue
            name = str(row[pos["respondent_name"]])
            status = re.match(r"^\s*(【[^】]+】)", name)
            cur = conn.execute(
                """INSERT OR IGNORE INTO action_responses
                   (action_response_id, batch_id, external_id, answered_at, member_status)
                   VALUES (?, ?, ?, ?, ?)""",
                (rid, batch_id, ext, at, status.group(1) if status else None))
            if cur.rowcount == 0:
                existing += 1
                continue
            inserted += 1
            for t in mapping["tasks"]:
                ans = _clean_answer(row[t["column_index"]])
                if ans in t["done_values"]:
                    done = 1
                elif ans in t.get("pending_values", []):
                    done = 0
                else:
                    done = None
                    if ans is not None:
                        issues.append((row_no, ext, t["label"], ans, "想定外の回答", "空欄として扱う"))
                conn.execute("INSERT INTO action_answers VALUES (?, ?, ?, ?)",
                             (rid, t["key"], ans, done))
        for i in issues:
            _add_issue(conn, batch_id, *i)
        conn.execute("UPDATE import_batches SET inserted_count=?, skipped_count=? WHERE batch_id=?",
                     (inserted, len(body) - inserted, batch_id))
    return {"ファイルの行数": len(body), "新規保存": inserted, "取込済みのためスキップ": existing,
            "必須項目の不備（スキップ）": invalid, "記録した注意事項": len(issues),
            "batch_id": batch_id}


# ---------------------------------------------------------------- 紐づけ
def load_action_snapshots(conn: sqlite3.Connection, mapping: Optional[Dict] = None) -> pd.DataFrame:
    """1行 = アクションリストの1回答。会員ID は ID 対応表で付与（対応なしは NA）。"""
    mapping = mapping or load_action_mapping()
    keys = [t["key"] for t in mapping["tasks"]]
    base = pd.read_sql_query(
        """SELECT r.action_response_id, r.external_id, l.member_id, r.answered_at, r.member_status
           FROM action_responses r LEFT JOIN id_links l ON l.external_id = r.external_id""", conn)
    ans = pd.read_sql_query("SELECT action_response_id, task_key, done FROM action_answers", conn)
    wide = ans.pivot(index="action_response_id", columns="task_key", values="done") if not ans.empty \
        else pd.DataFrame(columns=keys)
    wide = wide.reindex(columns=keys)
    df = base.merge(wide, left_on="action_response_id", right_index=True, how="left")
    df["answered_at"] = pd.to_datetime(df["answered_at"])
    for k in keys:
        df[k] = pd.to_numeric(df[k]).astype("Int64")
    df["progress"] = df[keys].sum(axis=1, skipna=True).astype("Int64")
    return df


def attach_actions(survey: pd.DataFrame, snaps: pd.DataFrame, timing: str = TIMING_BEFORE,
                   mapping: Optional[Dict] = None) -> pd.DataFrame:
    """アンケートの各回答に、同じ会員のアクションリスト回答（1件）を付ける。

    TIMING_BEFORE: アンケート回答日時以前で最新の回答（時間の前後関係を守る）
    TIMING_LATEST: 時期を問わず最新の回答
    """
    mapping = mapping or load_action_mapping()
    keys = [t["key"] for t in mapping["tasks"]]
    cols = ["member_id", "answered_at", "progress"] + keys
    s = snaps.dropna(subset=["member_id"])[cols].rename(columns={"answered_at": "action_answered_at"})
    out = survey.copy()
    out["_order"] = range(len(out))
    if timing == TIMING_LATEST:
        last = s.sort_values("action_answered_at").drop_duplicates("member_id", keep="last")
        merged = out.merge(last, on="member_id", how="left")
    else:
        left = out.sort_values("answered_at")
        right = s.sort_values("action_answered_at")
        merged = pd.merge_asof(left, right, left_on="answered_at", right_on="action_answered_at",
                               by="member_id", direction="backward")
    linked_members = set(s["member_id"])
    merged["has_action"] = merged["action_answered_at"].notna()
    merged["action_member"] = merged["member_id"].isin(linked_members)
    merged["progress"] = merged["progress"].astype("Int64")
    bins = mapping.get("progress_bins") or [[0, 3], [4, 5], [6, 7], [8, len(keys)]]
    merged["progress_label"] = merged["progress"].map(lambda v: progress_label(v, bins))
    return merged.sort_values("_order").drop(columns="_order").reset_index(drop=True)


def progress_label(v, bins) -> Optional[str]:
    if pd.isna(v):
        return None
    for lo, hi in bins:
        if lo <= int(v) <= hi:
            return f"{lo}〜{hi}項目"
    return None


def progress_order(mapping: Optional[Dict] = None) -> List[str]:
    mapping = mapping or load_action_mapping()
    return [f"{lo}〜{hi}項目" for lo, hi in mapping["progress_bins"]]


# ---------------------------------------------------------------- 分析
def coverage(df: pd.DataFrame) -> pd.DataFrame:
    """アクションリストと紐づいた回答・紐づかない回答の比較（偏りの確認用）"""
    rows = []
    for label, sub in [("アクション回答あり（集計対象）", df[df["has_action"]]),
                       ("アンケート後にのみ回答", df[~df["has_action"] & df["action_member"]]),
                       ("アクション回答なし・ID対応なし", df[~df["action_member"]])]:
        s = m.nps_summary(sub)
        rows.append({"区分": label, "回答数": len(sub), "NPS有効回答数": s["有効回答数"],
                     "NPS": m._r(s["NPS"]),
                     "変化評価の平均": m._r(sub["change_score"].mean(), 2) if sub["change_score"].notna().any() else None})
    return pd.DataFrame(rows)


def progress_table(df: pd.DataFrame, mapping: Optional[Dict] = None) -> pd.DataFrame:
    order = progress_order(mapping)
    g = m.group_nps(df[df["has_action"]], "progress_label", order)
    means = df[df["has_action"]].groupby("progress_label")["change_score"].agg(["mean", "count"])
    g.insert(2, "変化評価の平均", g["グループ"].map(lambda k: m._r(means["mean"].get(k), 2)
                                                   if k in means.index and means["count"][k] else None))
    return g.rename(columns={"グループ": "達成項目数"})


def task_table(df: pd.DataFrame, mapping: Optional[Dict] = None) -> pd.DataFrame:
    mapping = mapping or load_action_mapping()
    d = df[df["has_action"]]
    rows = []
    for t in mapping["tasks"]:
        done, todo = d[d[t["key"]] == 1], d[d[t["key"]] == 0]
        a, b = m.nps_summary(done), m.nps_summary(todo)
        rows.append({
            "タスク": t["label"],
            "達成：NPS": m._r(a["NPS"]), "達成：n": a["有効回答数"],
            "達成：変化評価の平均": m._r(done["change_score"].mean(), 2) if done["change_score"].notna().any() else None,
            "未達成：NPS": m._r(b["NPS"]), "未達成：n": b["有効回答数"],
            "未達成：変化評価の平均": m._r(todo["change_score"].mean(), 2) if todo["change_score"].notna().any() else None,
            "NPSの差（達成−未達成）": m._r(a["NPS"] - b["NPS"]) if a["NPS"] is not None and b["NPS"] is not None else None,
            "注意": "少数データあり" if min(a["有効回答数"], b["有効回答数"]) < m.SMALL_N else "",
        })
    return pd.DataFrame(rows)


def strength_label(r: Optional[float]) -> str:
    if r is None or pd.isna(r):
        return "-"
    a = abs(r)
    if a < 0.1:
        return "ほぼなし"
    if a < 0.3:
        return "弱い"
    if a < 0.5:
        return "中程度"
    return "強い"


def format_p(p: Optional[float]) -> str:
    if p is None or pd.isna(p):
        return "-"
    return "0.001未満" if p < 0.001 else f"{p:.3f}"


def spearman(df: pd.DataFrame, x: str, y: str) -> Dict:
    t = df[[x, y]].dropna().astype(float)
    n = len(t)
    if n < 3 or t[x].nunique() < 2 or t[y].nunique() < 2:
        return {"rho": None, "p": None, "n": n}
    r, p = stats.spearmanr(t[x], t[y])
    return {"rho": float(r), "p": float(p), "n": n}


def correlation_table(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["has_action"]]
    pairs = [("達成項目数 × NPS(0-10)", d, "progress", "nps"),
             ("達成項目数 × 変化評価", d, "progress", "change_score"),
             ("達成項目数 × GFS満足度", d, "progress", "gfs_satisfaction"),
             ("変化評価 × NPS(0-10)（参考：全回答）", df, "change_score", "nps")]
    rows = []
    for label, data, x, y in pairs:
        s = spearman(data, x, y)
        rows.append({"組み合わせ": label, "順位相関ρ": m._r(s["rho"], 2),
                     "強さの目安": strength_label(s["rho"]),
                     "p値": format_p(s["p"]),
                     "n": s["n"],
                     "注意": "少数データ" if s["n"] < m.SMALL_N else ""})
    return pd.DataFrame(rows)


ANALYSIS_NOTES = [
    m.CORRELATION_NOTE,
    "順位相関ρ（スピアマン）は −1〜+1。目安：0.1未満 ほぼなし／0.3未満 弱い／0.5未満 中程度／それ以上 強い。",
    "p値が小さい（例：0.05未満）ほど「偶然だけでは説明しにくい」ことを示しますが、関係の強さや因果は示しません。",
    "アクションリストに回答していない会員は集計に含まれないため、行動に積極的な会員に偏っている可能性があります（「紐づけの状況」を参照）。",
]
