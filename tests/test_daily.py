import pandas as pd

from gfs_analysis import actions, db, importer, trends
from gfs_analysis.sample import (action_csv_bytes, link_csv_bytes, make_action_frame,
                                 make_sample_frame, write_survey_excel)


def _files(tmp_path, n=120, seed=8):
    survey = make_sample_frame(n, seed=seed)
    xlsx = write_survey_excel(tmp_path / f"s{seed}.xlsx", survey).read_bytes()
    return survey, [("アンケート.xlsx", xlsx),
                    ("アクション.csv", action_csv_bytes(make_action_frame(survey, seed=seed))),
                    ("対応表.csv", link_csv_bytes(survey["会員ID"].unique())),
                    ("関係ない.csv", "a,b\n1,2\n".encode())]


def test_detect_kind(tmp_path):
    _, files = _files(tmp_path)
    kinds = {n: importer.detect_kind(n, d) for n, d in files}
    assert kinds == {"アンケート.xlsx": importer.SURVEY, "アクション.csv": importer.ACTION,
                     "対応表.csv": importer.LINK, "関係ない.csv": importer.UNKNOWN}


def test_import_many_and_daily_repeat(conn, tmp_path):
    survey, files = _files(tmp_path)
    res = importer.import_many(conn, files).set_index("種類")
    assert res.loc[importer.SURVEY, "結果"] == "取込完了"
    assert res.loc[importer.UNKNOWN, "結果"] == "スキップ"
    assert list(importer.import_many(conn, files)["結果"]).count("取込完了") == 0   # 翌日同じファイル
    n1 = conn.execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0]
    # 翌日：回答が増えた新しいファイル（前日分を含む全件出力）
    new = make_sample_frame(30, seed=99)
    more = pd.concat([survey, new], ignore_index=True)
    xlsx = write_survey_excel(tmp_path / "day2.xlsx", more).read_bytes()
    importer.import_many(conn, [("day2.xlsx", xlsx)])
    n2 = conn.execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0]
    key = lambda f: set(zip(f["会員ID"].astype(str), f["回答日時"]))  # noqa: E731
    assert n2 - n1 == len(key(new) - key(survey))
    last = importer.last_imports(conn)
    assert all(v is not None for v in last.values())


def test_link_imported_before_actions_in_same_batch(conn, tmp_path):
    _, files = _files(tmp_path)
    importer.import_many(conn, list(reversed(files)))
    snaps = actions.load_action_snapshots(conn)
    assert snaps["member_id"].notna().sum() > 0


def test_trends(conn, tmp_path):
    _, files = _files(tmp_path)
    importer.import_many(conn, files)
    df = db.load_responses(conn)
    for freq in trends.FREQS.values():
        t = trends.survey_trend(df, freq)
        assert t["回答数"].sum() == len(df)
        assert (t["NPS有効回答数"] <= t["回答数"]).all()
    cum = trends.cumulative_nps(df, "W-SUN")
    assert cum["累計NPS有効回答数"].is_monotonic_increasing
    at = trends.action_trend(actions.load_action_snapshots(conn), "D", actions.load_action_mapping()["tasks"])
    assert at["回答数"].sum() == len(actions.load_action_snapshots(conn))
    assert trends.survey_trend(df.iloc[0:0], "D").empty


def test_period_table(conn, tmp_path):
    _, files = _files(tmp_path)
    importer.import_many(conn, files)
    df = db.load_responses(conn)
    snaps = actions.load_action_snapshots(conn)
    tasks = actions.load_action_mapping()["tasks"]
    for freq in trends.FREQS.values():
        t = trends.period_table(df, snaps, freq, tasks)
        assert t["アンケート回答数"].sum() == len(df)
        assert t["アクション回答数"].sum() == len(snaps)
        assert t["期間"].is_monotonic_decreasing
        # 期間の明細件数と一覧の件数が一致する
        for _, r in t.iterrows():
            assert len(trends.rows_in_period(df, r["期間"], freq)) == r["アンケート回答数"]
    assert trends.period_table(df.iloc[0:0], snaps.iloc[0:0], "D", tasks).empty
