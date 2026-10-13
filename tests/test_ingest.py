import hashlib

import pandas as pd
import pytest

from conftest import row
from gfs_analysis import db, ingest
from gfs_analysis.sample import make_sample_frame, write_survey_excel


def test_member_id_is_stored_as_text(conn, make_excel):
    path = make_excel([
        row(123456, "2026-09-10 10:00:00", nps=8, change=4),
        row("00789", "2026-09-10 11:00:00", nps=9, change=5),
        row(555.0, "2026-09-10 12:00:00", nps=9, change=5),
    ])
    ingest.import_survey_file(conn, path)
    ids = [r[0] for r in conn.execute("SELECT member_id FROM survey_responses ORDER BY answered_at")]
    assert ids == ["123456", "00789", "555"]
    assert conn.execute("SELECT typeof(member_id) FROM survey_responses").fetchone()[0] == "text"
    assert db.load_responses(conn)["member_id"].tolist() == ["123456", "00789", "555"]


def test_name_column_is_not_stored(conn, make_excel):
    path = make_excel([row(1, "2026-09-10 10:00:00", nps=8, change=4, name="山田花子")])
    ingest.import_survey_file(conn, path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(survey_responses)")]
    assert not any("name" in c or "氏名" in c for c in cols)
    dump = "\n".join(conn.iterdump())
    assert "山田花子" not in dump


def test_same_file_twice_is_rejected(conn, make_excel):
    path = make_excel([row(1, "2026-09-10 10:00:00", nps=8, change=4)])
    ingest.import_survey_file(conn, path)
    with pytest.raises(ingest.DuplicateImportError):
        ingest.import_survey_file(conn, path)
    assert conn.execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0] == 1


def test_overlapping_file_only_adds_new_rows(conn, make_excel):
    a = row(1, "2026-09-10 10:00:00", nps=8, change=4)
    b = row(2, "2026-09-11 10:00:00", nps=3, change=2)
    c = row(3, "2026-09-12 10:00:00", nps=10, change=5)
    ingest.import_survey_file(conn, make_excel([a, b]))
    res = ingest.import_survey_file(conn, make_excel([a, b, c]))
    assert res.inserted == 1
    assert res.skipped_existing == 2
    assert conn.execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0] == 3


def test_multiple_responses_of_same_member_are_kept(conn, make_excel):
    path = make_excel([
        row(1, "2026-09-10 10:00:00", nps=5, change=3),
        row(1, "2026-09-10 10:00:01", nps=5, change=3),   # 二重送信
        row(1, "2026-10-01 10:00:00", nps=9, change=5),   # 別日の再回答
    ])
    res = ingest.import_survey_file(conn, path)
    assert res.inserted == 3
    assert conn.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 1
    first, last = conn.execute("SELECT first_seen_at, last_seen_at FROM members").fetchone()
    assert (first, last) == ("2026-09-10 10:00:00", "2026-10-01 10:00:00")


def test_exact_duplicate_rows_in_file(conn, make_excel):
    r = row(1, "2026-09-10 10:00:00", nps=5, change=3)
    res = ingest.import_survey_file(conn, make_excel([r, r]))
    assert res.inserted == 1
    assert res.skipped_in_file_dup == 1
    issues = db.load_issues(conn)
    assert issues["issue_type"].str.contains("同一").any()


def test_invalid_values_become_null_and_are_logged(conn, make_excel):
    path = make_excel([
        row(1, "2026-09-10 10:00:00", nps=11, change=4, nps_cat="推奨"),
        row(2, "2026-09-10 11:00:00", nps=7.5, change="とても", gfs=6),
        row(3, "2026-09-10 12:00:00", nps=8, change=4, nps_cat="批判"),
        row(None, "2026-09-10 13:00:00", nps=8, change=4),
        row(5, "日時ではない", nps=8, change=4),
    ])
    res = ingest.import_survey_file(conn, path)
    assert res.inserted == 3
    assert res.skipped_invalid == 2
    df = db.load_responses(conn).set_index("member_id")
    assert pd.isna(df.loc["1", "nps"])
    assert df.loc["1", "nps_category"] == "未回答"      # 0 や批判者として数えない
    assert pd.isna(df.loc["2", "nps"]) and pd.isna(df.loc["2", "change_score"])
    assert pd.isna(df.loc["2", "gfs_satisfaction"])
    assert df.loc["3", "nps_category"] == "中立者"      # 元の区分ではなく 0〜10 から再計算
    kinds = db.load_issues(conn)["issue_type"].tolist()
    assert any("範囲外（0〜10）" in k for k in kinds)
    assert any("整数ではない" in k for k in kinds)
    assert any("数値ではない" in k for k in kinds)
    assert any("NPS区分の不一致" in k for k in kinds)
    assert "会員ID欠損" in kinds
    assert any("回答日時" in k for k in kinds)


def test_support_not_used(conn, make_excel):
    path = make_excel([
        row(1, "2026-09-10 10:00:00", nps=8, change=4, support="利用していない"),
        row(2, "2026-09-10 11:00:00", nps=8, change=4, support=5),
    ])
    ingest.import_survey_file(conn, path)
    df = db.load_responses(conn).set_index("member_id")
    assert df.loc["1", "support_label"] == "未利用"
    assert pd.isna(df.loc["1", "support_satisfaction"])
    assert df.loc["2", "support_satisfaction"] == 5
    assert db.load_issues(conn).empty


def test_question_not_present_before_it_was_added(conn, make_excel):
    path = make_excel([
        row(1, "2026-09-01 10:00:00"),                    # 設問追加前
        row(2, "2026-09-08 09:00:00"),                    # 設問追加前
        row(3, "2026-09-08 11:30:00", nps=5, change=3),   # 設問追加後
        row(4, "2026-09-09 10:00:00"),                    # 設問はあったが空欄 → 未回答
    ])
    ingest.import_survey_file(conn, path)
    df = db.load_responses(conn).set_index("member_id")
    assert df.loc["1", "nps_category"] == "設問なし"
    assert df.loc["2", "change_label"] == "設問なし"
    assert df.loc["4", "nps_category"] == "未回答"
    assert df.loc["4", "change_label"] == "未回答"


def test_question_start_override(conn, make_excel):
    mapping = ingest.load_mapping()
    mapping["question_start"] = {"nps": "2026-09-05 00:00:00", "change_score": None}
    path = make_excel([
        row(1, "2026-09-06 10:00:00"),
        row(2, "2026-09-10 10:00:00", nps=5, change=3),
    ])
    ingest.import_survey_file(conn, path, mapping)
    df = db.load_responses(conn).set_index("member_id")
    assert df.loc["1", "nps_category"] == "未回答"
    assert df.loc["1", "change_label"] == "設問なし"


def test_missing_column_raises(conn, tmp_path):
    df = pd.DataFrame([row(1, "2026-09-10 10:00:00")]).drop(columns=["NPS(0-10)"])
    path = tmp_path / "broken.xlsx"
    with pd.ExcelWriter(path) as w:
        df.to_excel(w, sheet_name="60日 全回答", index=False)
    with pytest.raises(ingest.MappingError, match="NPS"):
        ingest.import_survey_file(conn, path)
    assert conn.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0] == 0


def test_original_file_is_not_modified(conn, tmp_path):
    path = write_survey_excel(tmp_path / "orig.xlsx", make_sample_frame(n=50, seed=1))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    mtime = path.stat().st_mtime
    ingest.import_survey_file(conn, path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert path.stat().st_mtime == mtime


def test_sample_data_round_trip(conn, tmp_path):
    df = make_sample_frame(n=200, seed=3)
    path = write_survey_excel(tmp_path / "s.xlsx", df)
    res = ingest.import_survey_file(conn, path)
    assert res.row_count == len(df)
    assert res.inserted == len(df)
    out = db.load_responses(conn)
    assert out["member_id"].nunique() == df["会員ID"].nunique()
