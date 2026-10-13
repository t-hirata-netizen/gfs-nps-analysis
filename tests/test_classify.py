import pytest

from conftest import row
from gfs_analysis import classify, db, ingest


@pytest.fixture
def kw():
    return classify.load_keywords()


@pytest.mark.parametrize("text,expected", [
    ("投資信託の仕組みが分かるようになった", {"knowledge"}),
    ("NISA口座を開設して積立を始めた", {"action"}),
    ("値下がりしても冷静に考えられるようになった", {"judgment"}),
    ("仕組みを学んで、実際に積立を始めた", {"knowledge", "action"}),
    ("特になし", {"unclassifiable"}),
    ("まだよくわからない", {"unclassifiable"}),
    ("ＮＩＳＡを始めた", {"action"}),   # 全角も一致
    ("相場の話題に興味が出てきた", {"other"}),
    ("考え方は変わったけれど、まだ行動には移せていない", {"judgment"}),
    ("まだ積立を始めていない", {"unclassifiable"}),
    ("まだ何も実践できていない", {"unclassifiable"}),
    ("相場の味方が変わった", {"judgment"}),   # 「見方」の誤字
])
def test_suggest(kw, text, expected):
    flags = classify.suggest(text, kw)
    assert {k for k, v in flags.items() if v} == expected


def test_validate_flags():
    assert classify.validate_flags({"knowledge": 1}) is None
    assert classify.validate_flags({"knowledge": 1, "action": 1}) is None
    assert classify.validate_flags({}) is not None
    assert classify.validate_flags({"unclassifiable": 1, "other": 1}) is not None


def _setup(conn, make_excel):
    ingest.import_survey_file(conn, make_excel([
        row(1, "2026-09-10 10:00:00", nps=8, change=4, reason_change="NISAを始めた"),
        row(2, "2026-09-10 11:00:00", nps=8, change=4, reason_change="特になし"),
        row(3, "2026-09-10 12:00:00", nps=8, change=4),
    ]))


def test_auto_classify_only_rows_with_text(conn, make_excel, kw):
    _setup(conn, make_excel)
    assert classify.auto_classify(conn, kw) == 2
    df = db.load_responses(conn).set_index("member_id")
    assert df.loc["1", "action"] == 1 and df.loc["1", "class_source"] == "auto"
    assert df.loc["2", "unclassifiable"] == 1


def test_manual_is_not_overwritten_by_auto(conn, make_excel, kw):
    _setup(conn, make_excel)
    classify.auto_classify(conn, kw)
    rid = db.load_responses(conn).set_index("member_id").loc["2", "response_id"]
    classify.save_manual(conn, [{"response_id": rid, "other": 1}])
    classify.auto_classify(conn, kw)
    df = db.load_responses(conn).set_index("member_id")
    assert df.loc["2", "other"] == 1 and df.loc["2", "unclassifiable"] == 0
    assert df.loc["2", "class_source"] == "manual"


def test_save_manual_is_all_or_nothing(conn, make_excel, kw):
    _setup(conn, make_excel)
    ids = db.load_responses(conn)["response_id"].tolist()
    with pytest.raises(ValueError):
        classify.save_manual(conn, [
            {"response_id": ids[0], "knowledge": 1},
            {"response_id": ids[1], "unclassifiable": 1, "knowledge": 1},
        ])
    assert conn.execute("SELECT COUNT(*) FROM change_classifications").fetchone()[0] == 0


def test_ai_review_is_not_overwritten(conn, make_excel, kw):
    _setup(conn, make_excel)
    classify.auto_classify(conn, kw)
    rid = db.load_responses(conn).set_index("member_id").loc["1", "response_id"]
    classify.save_manual(conn, [{"response_id": rid, "judgment": 1}], source="ai")
    classify.auto_classify(conn, kw)
    r = db.load_responses(conn).set_index("member_id").loc["1"]
    assert r["class_source"] == "ai" and r["judgment"] == 1 and r["action"] == 0


def test_migrates_old_check_constraint(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("""CREATE TABLE change_classifications (
        response_id INTEGER PRIMARY KEY, knowledge INTEGER NOT NULL DEFAULT 0,
        action INTEGER NOT NULL DEFAULT 0, judgment INTEGER NOT NULL DEFAULT 0,
        other INTEGER NOT NULL DEFAULT 0, unclassifiable INTEGER NOT NULL DEFAULT 0,
        source TEXT NOT NULL CHECK (source IN ('auto', 'manual')), updated_at TEXT NOT NULL)""")
    old.execute("INSERT INTO change_classifications VALUES (1, 1, 0, 0, 0, 0, 'auto', 'x')")
    old.commit()
    old.close()
    conn = db.connect(path)
    assert conn.execute("SELECT knowledge, source FROM change_classifications").fetchall() == [(1, "auto")]
    conn.execute("UPDATE change_classifications SET source='ai'")
