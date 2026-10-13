import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gfs_analysis import db  # noqa: E402
from gfs_analysis.sample import COLUMNS, write_survey_excel  # noqa: E402


def row(member_id, answered_at, nps=np.nan, change=np.nan, gfs=4, support=3,
        nps_cat=None, reason_change=np.nan, name="テスト"):
    """テスト用の1行（Excel の列名で作る）"""
    if nps_cat is None and not pd.isna(nps):
        nps_cat = "推奨" if nps >= 9 else "中立" if nps >= 7 else "批判"
    r = {c: np.nan for c in COLUMNS}
    r.update({"会員ID": member_id, "回答日時": answered_at, "氏名": name, "GFS満足度": gfs,
              "サポート満足度": support, "NPS(0-10)": nps, "NPS区分": nps_cat,
              "変化を感じる": change, "入学してよかった": "はい", "再入学したい": "はい",
              "変化理由": reason_change})
    return r


@pytest.fixture
def make_excel(tmp_path):
    counter = {"n": 0}

    def _make(rows, name=None):
        counter["n"] += 1
        df = pd.DataFrame(rows, columns=COLUMNS).astype(object)
        return write_survey_excel(tmp_path / (name or f"survey_{counter['n']}.xlsx"), df)
    return _make


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()
