"""開発・テスト用の匿名サンプルデータ生成（実データは一切使わない）

実データと同じ列構成を持ち、以下の「クセ」を再現する:
- 9/8 午前より前は NPS・変化評価の設問がない（空欄）
- 1〜3秒差の二重送信
- 同じ会員の別日の再回答
- 範囲外の値・NPS区分の不一致
- サポート満足度の「利用していない」
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

import numpy as np
import pandas as pd

SHEET = "60日 全回答"
COLUMNS = [
    "回答日時", "会員ID", "氏名", "GFS満足度", "サポート満足度", "NPS(0-10)", "NPS区分",
    "入学してよかった", "再入学したい", "変化を感じる", "GFS理由", "サポ理由", "入学理由",
    "勧める理由", "再入学理由", "変化理由", "悩み・モヤモヤ",
]
QUESTION_START = pd.Timestamp("2026-09-08 11:00:00")

CHANGE_REASONS = [
    "投資信託の仕組みが分かるようになった",
    "用語の意味を理解できるようになった",
    "NISA口座を開設して積立を始めた",
    "家計簿をつけて支出を見直した",
    "値下がりしても冷静に考えられるようになった",
    "長期で考える意識が持てるようになった",
    "仕組みを学んで、実際に積立を始めた",
    "お金の話を家族とするようになった",
    "特になし",
    "まだよくわからない",
]
SHORT_TEXTS = ["講義がわかりやすい", "サポートが丁寧", "もう少し続けたい", "時間が取れない", "特になし"]


def _category(nps):
    if pd.isna(nps):
        return np.nan
    return "推奨" if nps >= 9 else "中立" if nps >= 7 else "批判"


def make_sample_frame(n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-09-01 05:00:00").value
    end = pd.Timestamp("2026-10-13 21:00:00").value
    times = pd.to_datetime(np.sort(rng.integers(start, end, n))).floor("s")
    ids = rng.choice(np.arange(100000, 999999), size=n, replace=False)

    rows = []
    for i, (t, mid) in enumerate(zip(times, ids)):
        asked = t >= QUESTION_START
        nps = int(rng.choice(range(11), p=[.08, .06, .05, .12, .03, .22, .09, .12, .09, .03, .11])) if asked else np.nan
        change = int(rng.choice(range(1, 6), p=[.03, .05, .25, .38, .29])) if asked else np.nan
        support = "利用していない" if rng.random() < .25 else int(rng.choice(range(1, 6), p=[.03, .07, .33, .27, .30]))
        rows.append({
            "回答日時": t.strftime("%Y-%m-%d %H:%M:%S"),
            "会員ID": int(mid),
            "氏名": f"サンプル会員{i:03d}",
            "GFS満足度": int(rng.choice(range(1, 6), p=[.02, .04, .34, .37, .23])),
            "サポート満足度": support,
            "NPS(0-10)": nps,
            "NPS区分": _category(nps),
            "入学してよかった": "はい" if rng.random() < .92 else "いいえ",
            "再入学したい": "はい" if rng.random() < .86 else "いいえ",
            "変化を感じる": change,
            "GFS理由": rng.choice(SHORT_TEXTS) if rng.random() < .3 else np.nan,
            "サポ理由": rng.choice(SHORT_TEXTS) if rng.random() < .25 else np.nan,
            "入学理由": np.nan,
            "勧める理由": rng.choice(SHORT_TEXTS) if rng.random() < .3 else np.nan,
            "再入学理由": np.nan,
            "変化理由": rng.choice(CHANGE_REASONS) if asked and rng.random() < .35 else np.nan,
            "悩み・モヤモヤ": rng.choice(SHORT_TEXTS) if rng.random() < .3 else np.nan,
        })
    df = pd.DataFrame(rows, columns=COLUMNS)

    # 二重送信（1〜3秒差の同一内容）
    extra = []
    for i in rng.choice(n, size=4, replace=False):
        r = df.iloc[i].copy()
        r["回答日時"] = (pd.Timestamp(r["回答日時"]) + pd.Timedelta(seconds=int(rng.integers(1, 4)))).strftime("%Y-%m-%d %H:%M:%S")
        extra.append(r)
    # 同じ会員の別日の再回答
    for i in rng.choice(np.arange(n // 2, n), size=2, replace=False):
        r = df.iloc[i].copy()
        r["回答日時"] = (pd.Timestamp(r["回答日時"]) - pd.Timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
        r["GFS満足度"] = 3
        extra.append(r)
    df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)

    # 不正データ
    df["変化を感じる"] = df["変化を感じる"].astype(object)
    post = df.index[pd.to_datetime(df["回答日時"]) >= QUESTION_START]
    df.loc[post[0], ["NPS(0-10)", "NPS区分"]] = [11, "推奨"]        # 範囲外
    df.loc[post[1], ["NPS(0-10)", "NPS区分"]] = [8, "批判"]         # 区分の不一致
    df.loc[post[2], "GFS満足度"] = 6                                  # 範囲外
    df.loc[post[3], "変化を感じる"] = "とても"                         # 数値でない
    return df.sort_values("回答日時", kind="stable").reset_index(drop=True)


def write_survey_excel(path: Union[str, Path], df: pd.DataFrame) -> Path:
    path = Path(path)
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        pd.DataFrame({"説明": ["匿名サンプルデータ（実在の会員とは無関係）"]}).to_excel(
            w, sheet_name="サマリー", index=False)
        df.to_excel(w, sheet_name=SHEET, index=False)
    return path


# ------------------------------------------------ アクションリスト・ID 対応表のサンプル
ACTION_HEADER = [
    "回答ID", "回答日時", "回答者ID", "回答者名",
    "オリエンテーションは修了しましたか？", "メインで取引する証券口座を決めましたか？",
    "進捗", "進捗", "進捗", "進捗", "進捗", "進捗", "進捗", "その他の回答",
]
ACTION_CHOICES = [
    ("修了した", "まだ"), ("決めた", "まだ迷っている"), ("開設済み", "開設方法がわからない"),
    ("入金済み", "入金方法がわからない"), ("設定済み", "設定方法がわからない"),
    ("購入済み", "買えずに困っている"), ("購入済み", "これから"), ("売却済み", "これから"),
    ("購入済み", "これから"),
]


def external_id_for(member_id) -> str:
    """会員ID → 架空の Liny 登録ID（9桁）"""
    return str(100000000 + int(member_id) * 7 % 900000000)


def make_action_frame(survey: pd.DataFrame, seed: int = 0, share: float = 0.6) -> pd.DataFrame:
    """アンケート回答者の一部について、アクションリスト回答を作る。
    変化評価が高い人ほど進捗が進みやすいようにしてある（相関の確認用）。"""
    rng = np.random.default_rng(seed)
    members = survey.drop_duplicates("会員ID")
    rows, rid = [], 500000000
    for _, r in members.iterrows():
        if rng.random() > share:
            continue
        change = r["変化を感じる"] if isinstance(r["変化を感じる"], (int, float)) and not pd.isna(r["変化を感じる"]) else 3
        level = int(np.clip(rng.normal(2 + float(change) * 1.2, 1.5), 0, 9))
        t0 = pd.Timestamp(r["回答日時"]) - pd.Timedelta(days=int(rng.integers(1, 20)))
        for k in range(int(rng.integers(1, 3))):
            rid += 1
            answers = [ACTION_CHOICES[i][0] if i < level else ACTION_CHOICES[i][1] for i in range(9)]
            rows.append([str(rid), (t0 + pd.Timedelta(days=k * 3)).strftime("%Y/%m/%d %H:%M"),
                         external_id_for(r["会員ID"]), f"サンプル会員{rid % 1000:03d}", *answers, ""])
    # アンケートに回答していない会員のアクション回答
    for i in range(20):
        rid += 1
        rows.append([str(rid), "2026/09/20 12:00", str(900000000 + i), "サンプル非回答者",
                     *[c[1] for c in ACTION_CHOICES], ""])
    return pd.DataFrame(rows, columns=range(len(ACTION_HEADER)))


def action_csv_bytes(frame: pd.DataFrame, encoding: str = "cp932") -> bytes:
    lines = [",".join(f'"{h}"' for h in ACTION_HEADER)]
    for row in frame.itertuples(index=False):
        lines.append(",".join(f'"{v}"' for v in row))
    return ("\r\n".join(lines) + "\r\n").encode(encoding)


def link_csv_bytes(member_ids, encoding: str = "cp932") -> bytes:
    """ID 対応表のサンプル（メール・電話は架空のダミー値）"""
    df = pd.DataFrame({
        "登録ID": [external_id_for(mid) for mid in member_ids],
        "": [f"会員{i}" for i in range(len(member_ids))],
        "友だち情報_1922754": [f"dummy{i}@example.com" for i in range(len(member_ids))],
        "友だち情報_1922753": ["000-0000-0000"] * len(member_ids),
        "友だち情報_2393157": [str(mid) for mid in member_ids],
    })
    return df.to_csv(index=False).encode(encoding)
