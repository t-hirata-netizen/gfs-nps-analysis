from pathlib import Path

import streamlit as st

from gfs_analysis import actions, classify, db, importer, ingest, ui

ui.setup("データ取込")
conn = db.connect()

BULK = "まとめて取込（毎日の作業）"
SURVEY = "60日アンケート（Excel）"
ACTION = "アクションリスト（CSV）"
LINK = "ID対応表（Liny 友だち情報 CSV）"
kind = st.radio("取り込むデータ", [BULK, SURVEY, ACTION, LINK], horizontal=True)

if kind == BULK:
    st.markdown(
        "その日にダウンロードした **60日アンケート（Excel）・アクションリスト（CSV）・ID対応表（CSV）** を"
        "まとめて入れてください。種類は自動で判別し、前回までに取り込んだ分はスキップして**増えた分だけ**追加します。")
    st.caption("元ファイルは読み取るだけで変更しません。氏名・メール・電話番号は保存しません。")
    ups = st.file_uploader("ファイル（複数選択・ドラッグ可）", type=["xlsx", "csv"],
                           accept_multiple_files=True, key="bulk")
    if ups:
        files = [(u.name, u.getvalue()) for u in ups]
        ui.show_table([{"ファイル": n, "判別した種類": importer.detect_kind(n, d)} for n, d in files])
        if st.button("まとめて取り込む", type="primary"):
            res = importer.import_many(conn, files)
            ui.show_table(res)
            if (res["結果"] == "エラー").any():
                st.error("取り込めなかったファイルがあります。内容を確認してください。")
            else:
                st.success("取込が終わりました。新しい「変化理由」には自動分類の案が付いています（「変化理由の分類」で確認できます）。")
    st.divider()
    st.subheader("取込履歴")
    batches = db.load_batches(conn)
    if not batches.empty:
        batches["source_type"] = batches["source_type"].map(
            {"survey60": "60日アンケート", "action_list": "アクションリスト", "id_link": "ID対応表"})
        ui.show_table(batches.drop(columns=["file_sha256", "sheet_name"]).rename(columns={
            "batch_id": "取込ID", "source_type": "種類", "file_name": "ファイル名", "row_count": "行数",
            "inserted_count": "新規保存", "skipped_count": "スキップ", "imported_at": "取込日時"}))
    st.stop()

if kind == SURVEY:
    mapping = ingest.load_mapping()
    st.markdown(f"60日アンケートの Excel（シート「{mapping['sheet_name']}」）を取り込みます。氏名列は取り込みません。")
    exts = ["xlsx"]
elif kind == ACTION:
    mapping = actions.load_action_mapping()
    st.markdown("アクションリストの回答 CSV を取り込みます。氏名は保存せず、【退会済】などの状態ラベルだけを残します。"
                "会員ID とつなぐには **ID対応表** も取り込んでください。")
    exts = ["csv"]
else:
    mapping = actions.load_yaml(actions.LINK_MAPPING_PATH)
    st.markdown("Liny の友だち情報エクスポート CSV から、**登録ID と 会員ID の2列だけ**を読み込みます。"
                "メールアドレス・電話番号などは読み込みません。新しいファイルを取り込むと対応表が更新されます。")
    exts = ["csv"]
st.caption("元ファイルは読み取るだけで、変更しません。")

tab_upload, tab_path = st.tabs(["ファイルを選ぶ", "パスを入力する"])
data, name = None, None
with tab_upload:
    up = st.file_uploader("ファイル", type=exts, key=f"up_{kind}")
    if up is not None:
        data, name = up.getvalue(), up.name
with tab_path:
    p = st.text_input("ファイルのパス", key=f"path_{kind}", placeholder="/Users/…/Downloads/…")
    if p:
        path = Path(p.strip().strip("'\"")).expanduser()
        if path.is_file():
            data, name = path.read_bytes(), path.name
        else:
            st.error("ファイルが見つかりません。")

if data is not None:
    try:
        if kind == SURVEY:
            n_rows = len(ingest.read_survey_frame(data, mapping))
        elif kind == ACTION:
            n_rows = len(actions.read_action_frame(data, mapping))
        else:
            n_rows = len(actions.read_link_frame(data, mapping))
    except ingest.MappingError as e:
        st.error(str(e))
        st.stop()
    st.success(f"「{name}」を読み込みました：{n_rows:,} 行")
    with st.expander("列の対応"):
        if kind == ACTION:
            ui.show_table([{"項目": t["label"], "列（左から, 0始まり）": t["column_index"],
                            "達成とみなす回答": "、".join(t["done_values"])} for t in mapping["tasks"]])
            st.caption("設問を変えた場合は config/mappings/action_list.yaml を編集してください。")
        else:
            ui.show_table([{"取込先": k, "ファイルの列名": v} for k, v in mapping["columns"].items()])
    auto = kind == SURVEY and st.checkbox("取込後に「変化理由」の自動分類も行う", value=True)
    if st.button("取り込む", type="primary"):
        try:
            if kind == SURVEY:
                r = ingest.import_survey_bytes(conn, data, name, mapping)
                res = {"ファイルの行数": r.row_count, "新規保存": r.inserted,
                       "取込済みのためスキップ": r.skipped_existing,
                       "ファイル内の同一行（スキップ）": r.skipped_in_file_dup,
                       "会員ID・日時の不備（スキップ）": r.skipped_invalid,
                       "記録した注意事項（不正値など）": r.issue_count}
            elif kind == ACTION:
                res = actions.import_actions(conn, data, name, mapping)
            else:
                res = actions.import_id_links(conn, data, name, mapping)
        except ingest.DuplicateImportError as e:
            st.warning(str(e))
        else:
            res.pop("batch_id", None)
            st.success("取り込みました。")
            st.write(res)
            if auto:
                n = classify.auto_classify(conn)
                st.info(f"変化理由 {n:,} 件に自動分類の案を付けました（人が修正したものは上書きしていません）。")

st.divider()
st.subheader("取込履歴")
batches = db.load_batches(conn)
if batches.empty:
    st.caption("まだ取込はありません。")
else:
    batches["source_type"] = batches["source_type"].map(
        {"survey60": "60日アンケート", "action_list": "アクションリスト", "id_link": "ID対応表"}).fillna(batches["source_type"])
    ui.show_table(batches.drop(columns=["file_sha256"]).rename(columns={
        "batch_id": "取込ID", "source_type": "種類", "file_name": "ファイル名",
        "sheet_name": "シート", "row_count": "行数",
        "inserted_count": "新規保存", "skipped_count": "スキップ", "imported_at": "取込日時"}))
