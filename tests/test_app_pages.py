"""Streamlit 画面をサーバーなしで実行し、エラーが出ないことを確認する"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from gfs_analysis import classify, db, ingest
from gfs_analysis.sample import make_sample_frame, write_survey_excel

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["app.py", "home.py"] + sorted(str(p.relative_to(ROOT)) for p in (ROOT / "pages").glob("*.py"))


@pytest.fixture
def sample_db(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    monkeypatch.setenv("GFS_DB_PATH", str(path))
    conn = db.connect(path)
    ingest.import_survey_file(conn, write_survey_excel(tmp_path / "s.xlsx", make_sample_frame(150, seed=5)))
    classify.auto_classify(conn)
    conn.close()
    return path


@pytest.mark.parametrize("page", PAGES)
def test_page_runs_with_data(sample_db, page):
    at = AppTest.from_file(str(ROOT / page), default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("page", PAGES)
def test_page_runs_without_data(tmp_path, monkeypatch, page):
    monkeypatch.setenv("GFS_DB_PATH", str(tmp_path / "empty.db"))
    at = AppTest.from_file(str(ROOT / page), default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]


def test_filters_narrow_results(sample_db):
    at = AppTest.from_file(str(ROOT / "pages/3_分布.py"), default_timeout=30).run()
    before = at.sidebar.caption[0].value
    at.sidebar.multiselect[1].set_value(["推奨者"]).run()
    assert not at.exception
    after = at.sidebar.caption[0].value
    assert before != after


def test_cross_tab_category_grouping(sample_db):
    at = AppTest.from_file(str(ROOT / "pages/4_クロス集計.py"), default_timeout=30).run()
    at.selectbox[0].set_value("変化理由の分類（複数該当あり）").run()
    assert not at.exception
    at.selectbox[1].set_value("変化理由の分類（複数該当あり）").run()
    at.selectbox[2].set_value("変化評価").run()
    assert not at.exception


@pytest.fixture
def sample_db_with_actions(tmp_path, monkeypatch):
    from gfs_analysis import actions
    from gfs_analysis.sample import action_csv_bytes, link_csv_bytes, make_action_frame
    path = tmp_path / "app2.db"
    monkeypatch.setenv("GFS_DB_PATH", str(path))
    conn = db.connect(path)
    survey = make_sample_frame(150, seed=6)
    ingest.import_survey_file(conn, write_survey_excel(tmp_path / "s.xlsx", survey))
    actions.import_id_links(conn, link_csv_bytes(survey["会員ID"].unique()), "l.csv")
    actions.import_actions(conn, action_csv_bytes(make_action_frame(survey, seed=6)), "a.csv")
    conn.close()
    return path


@pytest.mark.parametrize("page", ["pages/7_アクション×NPS.py", "pages/6_Excel出力.py", "pages/1_データ取込.py"])
def test_action_pages(sample_db_with_actions, page):
    at = AppTest.from_file(str(ROOT / page), default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]
    if page.startswith("pages/7"):
        at.radio[0].set_value("最新の回答（アンケート後を含む）").run()
        assert not at.exception


def test_action_page_without_links(sample_db, tmp_path):
    at = AppTest.from_file(str(ROOT / "pages/7_アクション×NPS.py"), default_timeout=30).run()
    assert not at.exception


@pytest.mark.parametrize("page", ["pages/8_推移.py", "home.py"])
def test_trend_and_home_with_actions(sample_db_with_actions, page):
    at = AppTest.from_file(str(ROOT / page), default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]
    if page.endswith("推移.py"):
        for label in ["日別", "月別"]:
            at.radio[0].set_value(label).run()
            assert not at.exception


def test_data_list_page(sample_db_with_actions):
    at = AppTest.from_file(str(ROOT / "pages/9_データ一覧.py"), default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]
    for label in ["週別（月曜始まり）", "月別"]:
        at.radio[0].set_value(label).run()
        assert not at.exception
    at.selectbox[1].set_value(at.selectbox[1].options[-1]).run()
    assert not at.exception
