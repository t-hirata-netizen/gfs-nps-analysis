import pandas as pd
import pytest

from gfs_analysis import actions, db, ingest
from gfs_analysis.ingest import DuplicateImportError, MappingError
from gfs_analysis.sample import (ACTION_CHOICES, ACTION_HEADER, action_csv_bytes, external_id_for,
                                 link_csv_bytes, make_action_frame, make_sample_frame,
                                 write_survey_excel)
from conftest import row


def action_row(rid, at, ext, level, name="テスト", raw=None):
    answers = raw or [ACTION_CHOICES[i][0] if i < level else ACTION_CHOICES[i][1] for i in range(9)]
    return [str(rid), at, str(ext), name, *answers, ""]


def actions_bytes(rows, encoding="cp932"):
    return action_csv_bytes(pd.DataFrame(rows, columns=range(len(ACTION_HEADER))), encoding)


def test_link_import_reads_only_id_columns(conn):
    res = actions.import_id_links(conn, link_csv_bytes([12345, 67890]), "link.csv")
    assert res["対応付け"] == 2
    assert dict(conn.execute("SELECT external_id, member_id FROM id_links")) == {
        external_id_for(12345): "12345", external_id_for(67890): "67890"}
    dump = "\n".join(conn.iterdump())
    assert "example.com" not in dump and "000-0000-0000" not in dump


def test_link_conflict_is_skipped(conn):
    data = "登録ID,友だち情報_2393157\n111111111,100\n111111111,200\n222222222,300\n".encode("cp932")
    res = actions.import_id_links(conn, data, "link.csv")
    assert res["登録IDの重複・矛盾（スキップ）"] == 1
    assert conn.execute("SELECT COUNT(*) FROM id_links").fetchone()[0] == 1


def test_link_missing_column(conn):
    with pytest.raises(MappingError, match="友だち情報_2393157"):
        actions.import_id_links(conn, "登録ID,会員ID\n1,2\n".encode("cp932"), "x.csv")


def test_action_import_by_position(conn):
    data = actions_bytes([
        action_row(1, "2026/09/10 10:00", 111111111, 4, name="【退会済】山田　太郎"),
        action_row(2, "2026/09/11 10:00", 222222222, 9),
    ])
    res = actions.import_actions(conn, data, "a.csv")
    assert res["新規保存"] == 2
    snaps = actions.load_action_snapshots(conn).set_index("action_response_id")
    assert snaps.loc["1", "progress"] == 4
    assert snaps.loc["1", "deposit"] == 1 and snaps.loc["1", "index_setup"] == 0
    assert snaps.loc["2", "progress"] == 9
    assert snaps.loc["1", "member_status"] == "【退会済】"
    assert "山田" not in "\n".join(conn.iterdump())


def test_action_utf8_and_ellipsis(conn):
    raw = ["まだ…", "決めた", "開設済み", "入金済み", "設定済み", "購入済み", "これから…", "これから", "謎の回答"]
    res = actions.import_actions(conn, actions_bytes([action_row(1, "2026/09/10 10:00", 1, 0, raw=raw)], "utf-8-sig"), "a.csv")
    assert res["新規保存"] == 1
    snaps = actions.load_action_snapshots(conn).iloc[0]
    assert snaps["orientation"] == 0 and snaps["buy_technical"] == 0
    assert pd.isna(snaps["buy_fundamental"])                 # 想定外の回答は空欄扱い
    assert snaps["progress"] == 5
    assert "想定外の回答" in db.load_issues(conn)["issue_type"].tolist()


def test_action_reimport_and_overlap(conn):
    a = action_row(1, "2026/09/10 10:00", 1, 3)
    b = action_row(2, "2026/09/11 10:00", 1, 5)
    actions.import_actions(conn, actions_bytes([a]), "a.csv")
    with pytest.raises(DuplicateImportError):
        actions.import_actions(conn, actions_bytes([a]), "a.csv")
    res = actions.import_actions(conn, actions_bytes([a, b]), "b.csv")
    assert res["新規保存"] == 1 and res["取込済みのためスキップ"] == 1


def test_action_header_mismatch(conn):
    bad = actions_bytes([action_row(1, "2026/09/10 10:00", 1, 3)]).decode("cp932")
    bad = bad.replace('"オリエンテーションは修了しましたか？"', '"別の設問"', 1).encode("cp932")
    with pytest.raises(MappingError, match="オリエンテーション"):
        actions.import_actions(conn, bad, "a.csv")


def _linked(conn, make_excel):
    ingest.import_survey_file(conn, make_excel([
        row(100, "2026-09-20 10:00:00", nps=9, change=5),
        row(200, "2026-09-20 10:00:00", nps=3, change=2),
        row(300, "2026-09-20 10:00:00", nps=8, change=4),   # アクション回答なし
    ]))
    actions.import_id_links(conn, link_csv_bytes([100, 200, 300]), "link.csv")
    actions.import_actions(conn, actions_bytes([
        action_row(1, "2026/09/10 10:00", external_id_for(100), 6),
        action_row(2, "2026/09/25 10:00", external_id_for(100), 9),   # アンケート後
        action_row(3, "2026/09/25 10:00", external_id_for(200), 2),   # アンケート後のみ
    ]), "a.csv")
    return db.load_responses(conn), actions.load_action_snapshots(conn)


def test_attach_respects_timing(conn, make_excel):
    survey, snaps = _linked(conn, make_excel)
    before = actions.attach_actions(survey, snaps, actions.TIMING_BEFORE).set_index("member_id")
    assert before.loc["100", "progress"] == 6          # アンケート前の最新
    assert not before.loc["200", "has_action"]         # アンケート後の回答は使わない
    assert before.loc["200", "action_member"]
    assert not before.loc["300", "action_member"]
    latest = actions.attach_actions(survey, snaps, actions.TIMING_LATEST).set_index("member_id")
    assert latest.loc["100", "progress"] == 9
    assert latest.loc["200", "progress"] == 2
    assert len(before) == len(survey)


def test_analysis_tables(conn, make_excel):
    survey, snaps = _linked(conn, make_excel)
    df = actions.attach_actions(survey, snaps, actions.TIMING_LATEST)
    p = actions.progress_table(df).set_index("達成項目数")
    assert p.loc["8〜9項目", "NPS有効回答数"] == 1 and p.loc["8〜9項目", "NPS"] == 100
    assert p.loc["0〜3項目", "NPS"] == -100
    t = actions.task_table(df).set_index("タスク")
    assert t.loc["口座開設", "達成：n"] == 1 and t.loc["口座開設", "未達成：n"] == 1
    cov = actions.coverage(actions.attach_actions(survey, snaps)).set_index("区分")
    assert cov.loc["アンケート後にのみ回答", "回答数"] == 1
    c = actions.correlation_table(df)
    assert c.loc[0, "n"] == 2 and c.loc[0, "注意"] == "少数データ"


def test_strength_label():
    assert actions.strength_label(0.05) == "ほぼなし"
    assert actions.strength_label(-0.2) == "弱い"
    assert actions.strength_label(0.41) == "中程度"
    assert actions.strength_label(None) == "-"


def test_sample_end_to_end(conn, tmp_path):
    survey = make_sample_frame(200, seed=4)
    ingest.import_survey_file(conn, write_survey_excel(tmp_path / "s.xlsx", survey))
    actions.import_id_links(conn, link_csv_bytes(survey["会員ID"].unique()), "l.csv")
    actions.import_actions(conn, action_csv_bytes(make_action_frame(survey, seed=4)), "a.csv")
    df = actions.attach_actions(db.load_responses(conn), actions.load_action_snapshots(conn),
                                actions.TIMING_LATEST)
    assert df["has_action"].sum() > 50
    c = actions.correlation_table(df).set_index("組み合わせ")
    assert c.loc["達成項目数 × 変化評価", "順位相関ρ"] > 0.3   # サンプルは正の関係を仕込んである


def test_format_p():
    assert actions.format_p(0.0000001) == "0.001未満"
    assert actions.format_p(0.0123) == "0.012"
    assert actions.format_p(None) == "-"
