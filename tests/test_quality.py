import pandas as pd

from gfs_analysis import quality as q


def frame(rows):
    df = pd.DataFrame(rows, columns=["response_id", "member_id", "answered_at"])
    df["answered_at"] = pd.to_datetime(df["answered_at"])
    return df


DATA = [
    (1, "A", "2026-09-10 10:00:00"),
    (2, "A", "2026-09-10 10:00:01"),   # A の二重送信
    (3, "A", "2026-09-10 10:00:30"),   # 連鎖して同じ組（直前から 29 秒）
    (4, "A", "2026-10-01 10:00:00"),   # 別日の再回答
    (5, "B", "2026-09-11 10:00:00"),
    (6, "C", "2026-09-12 10:00:00"),
    (7, "C", "2026-09-12 10:05:00"),   # 300 秒差
]


def test_near_duplicate_groups():
    m = q.mark_near_duplicates(frame(DATA), 60).set_index("response_id")
    assert m.loc[1, "near_dup_group"] == m.loc[2, "near_dup_group"] == m.loc[3, "near_dup_group"]
    assert pd.isna(m.loc[4, "near_dup_group"])
    assert pd.isna(m.loc[6, "near_dup_group"])
    assert m.loc[[1, 2], "near_dup_drop"].all()
    assert not m.loc[3, "near_dup_drop"]          # 組の最後の回答を採用


def test_threshold_changes_grouping():
    m = q.mark_near_duplicates(frame(DATA), 600).set_index("response_id")
    assert m.loc[6, "near_dup_group"] == m.loc[7, "near_dup_group"]
    m = q.mark_near_duplicates(frame(DATA), 0).set_index("response_id")
    assert m["near_dup_group"].isna().all()


def test_dedup_modes():
    df = frame(DATA)
    assert len(q.apply_dedup(df, q.DEDUP_ALL, 60)) == 7
    near = q.apply_dedup(df, q.DEDUP_NEAR, 60)
    assert sorted(near["response_id"]) == [3, 4, 5, 6, 7]
    first = q.apply_dedup(df, q.DEDUP_FIRST, 60)
    assert sorted(first["response_id"]) == [1, 5, 6]
    latest = q.apply_dedup(df, q.DEDUP_LATEST, 60)
    assert sorted(latest["response_id"]) == [4, 5, 7]


def test_dedup_does_not_modify_input():
    df = frame(DATA)
    q.apply_dedup(df, q.DEDUP_NEAR, 60)
    assert len(df) == 7 and "near_dup_drop" not in df.columns


def test_duplicate_members():
    d = q.duplicate_members(frame(DATA)).set_index("会員ID")
    assert set(d.index) == {"A", "C"}
    assert d.loc["A", "回答数"] == 4
    assert d.loc["A", "最短間隔(秒)"] == 1
    assert d.loc["C", "最短間隔(秒)"] == 300


def test_empty_frame():
    df = frame([])
    assert q.apply_dedup(df, q.DEDUP_NEAR, 60).empty
    assert q.duplicate_members(df).empty
