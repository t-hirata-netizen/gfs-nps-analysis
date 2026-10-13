import pandas as pd
import pytest

from gfs_analysis import metrics as m


def frame(nps, present=None, change=None):
    n = len(nps)
    df = pd.DataFrame({
        "nps": pd.array(nps, dtype="Int64"),
        "nps_question_present": pd.array(present or [1] * n, dtype="Int64"),
        "change_score": pd.array(change or [None] * n, dtype="Int64"),
        "change_question_present": pd.array(present or [1] * n, dtype="Int64"),
        "gfs_satisfaction": pd.array([4] * n, dtype="Int64"),
        "support_satisfaction": pd.array([None] * n, dtype="Int64"),
        "support_used": pd.array([None] * n, dtype="Int64"),
    })
    return m.add_labels(df)


@pytest.mark.parametrize("score,expected", [
    (0, "批判者"), (6, "批判者"), (7, "中立者"), (8, "中立者"), (9, "推奨者"), (10, "推奨者"),
])
def test_classify_nps_boundaries(score, expected):
    assert m.classify_nps(score) == expected


def test_classify_nps_rejects_out_of_range():
    with pytest.raises(ValueError):
        m.classify_nps(11)
    assert m.classify_nps(None) is None


def test_nps_score():
    # 推奨2・中立1・批判2 → (2-2)/5 = 0
    s = m.nps_summary(frame([10, 9, 8, 6, 0]))
    assert s["NPS"] == 0
    # 推奨3・批判1 → (3-1)/4*100 = 50
    assert m.nps_summary(frame([9, 10, 10, 3]))["NPS"] == 50


def test_missing_is_not_counted_as_zero():
    # 欠損を 0 点（批判者）にすると NPS が下がる。分母から外すこと。
    s = m.nps_summary(frame([10, 10, None, None], present=[1, 1, 1, 0]))
    assert s["有効回答数"] == 2
    assert s["NPS"] == 100
    assert s["未回答数"] == 1
    assert s["設問なし数"] == 1
    assert s["未回答率(%)"] == pytest.approx(100 / 3)


def test_empty_nps():
    s = m.nps_summary(frame([None], present=[0]))
    assert s["NPS"] is None and s["有効回答数"] == 0


def test_small_sample_flag():
    assert m.nps_summary(frame([9] * 29))["少数データ"] is True
    assert m.nps_summary(frame([9] * 30))["少数データ"] is False


def test_distribution_excludes_missing_from_ratio():
    df = frame([1, 2, 2, None], change=[3, 5, 5, None])
    d = m.distribution(df, "change_label", m.SCORE5_VALUES, [m.MISSING, m.NOT_ASKED]).set_index("区分")
    assert d.loc["5", "件数"] == 2
    assert d.loc["5", "有効回答に占める割合(%)"] == pytest.approx(66.7)
    assert d.loc["未回答", "件数"] == 1
    assert pd.isna(d.loc["未回答", "有効回答に占める割合(%)"])
    assert d.loc["1", "件数"] == 0   # 未回答が「1（変化なし）」に入らない


def test_group_nps_reports_n():
    df = frame([10, 0, 9, 9], change=[5, 5, 1, None])
    g = m.group_nps(df, "change_label", ["1", "5", m.MISSING]).set_index("グループ")
    assert g.loc["5", "NPS有効回答数"] == 2 and g.loc["5", "NPS"] == 0
    assert "少数データ" in g.loc["1", "注意"]


def test_crosstab_totals():
    df = frame([10, 0, 9], change=[5, 5, 1])
    counts, pct = m.crosstab(df, "change_label", "nps_category", ["1", "5"], m.NPS_CATEGORIES)
    assert counts.loc["5", "推奨者"] == 1 and counts.loc["5", "批判者"] == 1
    assert counts.loc["合計", "合計"] == 3
    assert pct.loc["5", "推奨者"] == 50.0
