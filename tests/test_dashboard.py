import json

import pytest

from gfs_analysis import actions, dashboard, db, ingest
from gfs_analysis.sample import (action_csv_bytes, link_csv_bytes, make_action_frame,
                                 make_sample_frame, write_survey_excel)


@pytest.fixture
def filled(conn, tmp_path):
    survey = make_sample_frame(150, seed=11)
    ingest.import_survey_file(conn, write_survey_excel(tmp_path / "s.xlsx", survey))
    actions.import_id_links(conn, link_csv_bytes(survey["会員ID"].unique()), "l.csv")
    actions.import_actions(conn, action_csv_bytes(make_action_frame(survey, seed=11)), "a.csv")
    return conn, survey


def test_summary_has_no_personal_values(filled):
    conn, survey = filled
    text = json.dumps(dashboard.build_summary(conn), ensure_ascii=False)
    ids = set(survey["会員ID"].astype(str)) | set(db.load_responses(conn)["member_id"])
    ext = set(actions.load_action_snapshots(conn)["external_id"])
    assert not any(f'"{i}"' in text or f": {i}," in text for i in ids | ext)
    assert "サンプル会員" not in text
    for col in ["reason_change", "reason_gfs", "worries"]:
        for v in db.load_responses(conn)[col].dropna().unique():
            assert v not in text


def test_summary_numbers(filled):
    conn, _ = filled
    s = dashboard.build_summary(conn)
    assert len(s["tasks"]) == 9 and len(s["stages"]) == 6
    assert sum(r["survey_n"] for r in s["weekly"]) == s["kpi"]["responses"]
    assert sum(r["people"] for r in s["stages"]) == s["linked_responses"]
    assert s["deposit"][0]["group"] == "入金していない"


def test_encrypt_roundtrip_and_wrong_password(filled):
    conn, _ = filled
    payload = dashboard.build_summary(conn)
    blob = dashboard.encrypt(payload, "correct-horse-battery")
    assert dashboard.decrypt(blob, "correct-horse-battery") == payload
    with pytest.raises(Exception):
        dashboard.decrypt(blob, "wrong-password-123")
    assert str(payload["kpi"]["responses"]) not in blob["ct"]


def test_write_site(filled, tmp_path):
    conn, _ = filled
    path = dashboard.write_site(conn, "a-long-enough-password", tmp_path / "site")
    html = path.read_text(encoding="utf-8")
    assert "/*__ENCRYPTED__*/null" not in html and '"ct":' in html
    assert 'name="robots" content="noindex' in html
    assert "期間" not in html.split("const ENC")[1][:200]
    assert (tmp_path / "site" / "robots.txt").exists()
    with pytest.raises(ValueError):
        dashboard.write_site(conn, "short", tmp_path / "x")
