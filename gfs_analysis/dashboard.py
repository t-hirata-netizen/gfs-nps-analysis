"""チーム共有用ダッシュボードの書き出し（集計値のみ・パスワードで暗号化）

- 会員ID・氏名・自由記述は一切含めない（集計値だけを JSON にする）
- JSON を AES-GCM で暗号化し、鍵はパスワードから PBKDF2-SHA256 で作る
- 出力は 1 枚の index.html。ブラウザがパスワードで復号して表示する（GitHub Pages 用）
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from . import actions, db, trends
from . import metrics as m
from . import quality as q

TEMPLATE_PATH = Path(__file__).with_name("dashboard_template.html")
PBKDF2_ITERATIONS = 600_000

STAGE_OF = {"orientation": 1, "account_decided": 1, "account_opened": 1, "deposit": 2,
            "index_setup": 3, "buy_known": 4, "buy_technical": 5, "sell_technical": 5,
            "buy_fundamental": 5, None: 6}
STAGE_NAMES = {1: "準備（オリエン〜口座開設）", 2: "入金", 3: "積立設定",
               4: "初めての個別株購入", 5: "分析して売買", 6: "全タスク達成"}
BUY_KEYS = ["buy_known", "buy_technical", "sell_technical", "buy_fundamental"]


def _r(x, d=1):
    return None if x is None or pd.isna(x) else round(float(x), d)


def _first_gap(row, keys) -> Optional[str]:
    for k in keys:
        if row[k] != 1:
            return k
    return None


def build_summary(conn: sqlite3.Connection, threshold_sec: float = q.DEFAULT_NEAR_DUP_SECONDS) -> Dict:
    """ダッシュボードに載せる集計値（個人を特定する値を含まない）"""
    mapping = actions.load_action_mapping()
    tasks = mapping["tasks"]
    keys = [t["key"] for t in tasks]
    survey = q.apply_dedup(db.load_responses(conn), q.DEDUP_NEAR, threshold_sec)
    if survey.empty:
        raise ValueError("アンケートのデータがありません")
    snaps = actions.load_action_snapshots(conn)
    s = m.nps_summary(survey)

    out: Dict = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    out["kpi"] = {
        "period_start": survey["answered_at"].min().strftime("%Y-%m-%d"),
        "period_end": survey["answered_at"].max().strftime("%Y-%m-%d"),
        "responses": int(len(survey)), "nps_n": s["有効回答数"], "nps": _r(s["NPS"]),
        "promoter_rate": _r(s["推奨者率(%)"] / 100, 4) if s["推奨者率(%)"] is not None else None,
        "detractor_rate": _r(s["批判者率(%)"] / 100, 4) if s["批判者率(%)"] is not None else None,
        "change_mean": _r(survey["change_score"].mean(), 2),
    }

    t = trends.survey_trend(survey, "W-SUN")
    c = trends.cumulative_nps(survey, "W-SUN")
    w = t.merge(c[["期間", "累計NPS"]], on="期間", how="left")
    out["weekly"] = [{
        "week_start": r["期間"].strftime("%Y-%m-%d"), "survey_n": int(r["回答数"]),
        "nps_n": int(r["NPS有効回答数"]), "nps": _r(r["NPS"]), "cumulative_nps": _r(r["累計NPS"]),
        "change_mean": _r(r["変化評価の平均"], 2)} for _, r in w.iterrows()]

    out["tasks"], out["stages"], out["deposit"], out["gate"] = [], [], [], {}
    if not snaps.empty:
        ordered = snaps.sort_values("answered_at")
        last = ordered.drop_duplicates("external_id", keep="last").copy()
        last["stuck"] = last.apply(lambda r: _first_gap(r, keys), axis=1)
        first = ordered.drop_duplicates("external_id", keep="first").copy()
        first["stuck"] = first.apply(lambda r: _first_gap(r, keys), axis=1)
        counts = ordered.groupby("external_id").size()
        f = first[first["external_id"].isin(set(counts[counts > 1].index))].set_index("external_id")
        lf = last.set_index("external_id").loc[f.index]
        ans = pd.read_sql_query("SELECT action_response_id, task_key, answer, done FROM action_answers", conn)
        la = ans[ans["action_response_id"].isin(last["action_response_id"])]
        for i, tk in enumerate(tasks, 1):
            k = tk["key"]
            idx = f.index[f["stuck"] == k]
            explicit = [v for v in tk.get("pending_values", []) if v not in ("まだ", "これから")]
            trouble = int(la[(la["task_key"] == k) & (la["answer"].isin(explicit))].shape[0]) if explicit else None
            out["tasks"].append({
                "step": i, "task": tk["label"], "done_rate": _r((last[k] == 1).mean(), 4),
                "stuck_n": int((last["stuck"] == k).sum()), "trouble_n": trouble,
                "trouble_label": "・".join(explicit) if explicit else None,
                "cleared_rate": _r((lf.loc[idx, k] == 1).mean(), 4) if len(idx) else None,
                "cleared_base": int(len(idx))})
        out["action_respondents"] = int(last["external_id"].nunique())
        nd = last[last["deposit"] != 1]
        out["gate"] = {"not_deposited": int(len(nd)),
                       "not_deposited_traded": int(nd[BUY_KEYS].eq(1).any(axis=1).sum())}

        linked = actions.attach_actions(survey, snaps, actions.TIMING_BEFORE, mapping)
        d = linked[linked["has_action"]].copy()
        out["linked_responses"] = int(len(d))
        if not d.empty:
            d["stage"] = d.apply(lambda r: STAGE_OF[_first_gap(r, keys)], axis=1)
            for st in range(1, 7):
                g = d[d["stage"] == st]
                x = m.nps_summary(g)
                out["stages"].append({
                    "stage": STAGE_NAMES[st], "people": int(len(g)), "nps_n": x["有効回答数"],
                    "nps": _r(x["NPS"]), "change_mean": _r(g["change_score"].mean(), 2)})
            for name, g in [("入金していない", d[d["deposit"] != 1]), ("入金済み", d[d["deposit"] == 1]),
                            ("入金済み・全タスク達成", d[(d["deposit"] == 1) & (d["progress"] == len(keys))])]:
                x = m.nps_summary(g)
                out["deposit"].append({"group": name, "people": int(len(g)), "nps_n": x["有効回答数"],
                                       "nps": _r(x["NPS"]), "change_mean": _r(g["change_score"].mean(), 2)})

    cs = m.category_summary(survey)
    gn = m.group_nps(m.explode_categories(survey), "change_category", m.category_order()).set_index("グループ")
    out["categories"] = []
    for _, r in cs.iterrows():
        if r["分類"] == m.UNCLASSIFIED and r["該当件数"] == 0:
            continue
        label = "その他（関心・意欲）" if r["分類"] == "その他" else r["分類"]
        out["categories"].append({"category": label, "count": int(r["該当件数"]),
                                  "share": _r(r["記述ありに占める割合(%)"] / 100, 4) if r["記述ありに占める割合(%)"] is not None else None,
                                  "nps_n": int(gn.loc[r["分類"], "NPS有効回答数"]), "nps": _r(gn.loc[r["分類"], "NPS"])})
    return out


def encrypt(payload: Dict, password: str, salt: Optional[bytes] = None, iv: Optional[bytes] = None) -> Dict:
    salt = salt or os.urandom(16)
    iv = iv or os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=PBKDF2_ITERATIONS).derive(password.encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, json.dumps(payload, ensure_ascii=False).encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": PBKDF2_ITERATIONS,
            "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def decrypt(blob: Dict, password: str) -> Dict:
    """テスト・確認用（ブラウザ側と同じ方式）"""
    d = lambda s: base64.b64decode(s)  # noqa: E731
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=d(blob["salt"]),
                     iterations=blob["iter"]).derive(password.encode("utf-8"))
    return json.loads(AESGCM(key).decrypt(d(blob["iv"]), d(blob["ct"]), None))


def render_html(blob: Dict) -> str:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    return html.replace("/*__ENCRYPTED__*/null", json.dumps(blob))


def write_site(conn: sqlite3.Connection, password: str, out_dir: Path) -> Path:
    if len(password) < 12:
        raise ValueError("パスワードは12文字以上にしてください")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    path.write_text(render_html(encrypt(build_summary(conn), password)), encoding="utf-8")
    (out_dir / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return path
