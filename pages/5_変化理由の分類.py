import pandas as pd
import streamlit as st

from gfs_analysis import classify, metrics as m, ui

ui.setup("変化理由の分類")
conn, df = ui.load()
ui.require_data(df)
f, cond, _ = ui.sidebar_filters(df)

st.markdown(
    "「変化理由」を **知識・行動・判断・その他・分類不可** に分けます（複数選択可。分類不可は単独）。\n\n"
    "- **知識**：分かるようになった・学んだ　- **行動**：買った・始めた・ニュースやチャートを毎日見る\n"
    "- **判断**：考え方・見方・価値観が変わった　- **その他**：関心・意欲（興味が出た・気になるようになった）\n"
    "- **分類不可**：「まだ分からない」「変わっていない」など、変化の中身が読み取れないもの\n\n"
    "自動分類はローカルのキーワード辞書（`config/change_keywords.yaml`）による**案**です。"
    "確認・修正して保存すると「確認済み」になり、自動分類をやり直しても上書きされません。"
    "「AI確認（人の確認待ち）」は AI が文面を読んで見直したもので、これも自動分類では上書きされません。"
)

c1, c2 = st.columns([1, 3])
if c1.button("自動分類を実行"):
    n = classify.auto_classify(conn)
    ui.save_changes(conn)
    st.success(f"{n:,} 件に分類案を付けました（確認済みのものは変更していません）。")
    st.rerun()

summary = m.category_summary(f)
with_reason = f[f["reason_change"].notna()]
st.caption(f"変化理由の記入あり {len(with_reason):,} 件（絞り込み後）。分類は複数該当があるため合計は件数と一致しません。")
ui.show_table(summary)

st.divider()
status = st.radio("表示する回答", ["すべて", "未確認（自動・AI確認・未分類）のみ", "確認済みのみ"], horizontal=True)
d = with_reason.copy()
if status.startswith("未確認"):
    d = d[d["class_source"] != "manual"]
elif status == "確認済みのみ":
    d = d[d["class_source"] == "manual"]
if d.empty:
    st.caption("該当する回答はありません。")
    st.stop()

labels = m.CATEGORY_LABELS
edit = pd.DataFrame({
    "回答ID": d["response_id"].astype(int),
    "回答日時": d["answered_at"],
    "変化評価": d["change_label"],
    "NPS区分": d["nps_category"],
    "変化理由": d["reason_change"],
    **{labels[c]: d[c].fillna(0).astype(int).astype(bool) for c in m.CATEGORY_COLS},
    "状態": d["class_source"].map(classify.SOURCE_LABELS).fillna("未分類"),
}).reset_index(drop=True)

edited = st.data_editor(
    edit, hide_index=True, width="stretch", height=520,
    disabled=["回答ID", "回答日時", "変化評価", "NPS区分", "変化理由", "状態"],
    column_config={"変化理由": st.column_config.TextColumn(width="large"),
                   **{labels[c]: st.column_config.CheckboxColumn() for c in m.CATEGORY_COLS}},
    key="class_editor",
)

flag_cols = [labels[c] for c in m.CATEGORY_COLS]
changed = (edited[flag_cols] != edit[flag_cols]).any(axis=1)
c1, c2 = st.columns(2)
save_changed = c1.button(f"変更した {int(changed.sum())} 件を保存", type="primary", disabled=not changed.any())
confirm_all = c2.button(f"表示中の {len(edited)} 件をすべて確認済みとして保存")

if save_changed or confirm_all:
    target = edited[changed] if save_changed else edited
    records = [{"response_id": int(r["回答ID"]), **{c: int(r[labels[c]]) for c in m.CATEGORY_COLS}}
               for _, r in target.iterrows()]
    try:
        n = classify.save_manual(conn, records, user=ui.current_user())
        ui.save_changes(conn)
    except ValueError as e:
        st.error("保存できませんでした。\n\n" + str(e))
    else:
        st.success(f"{n:,} 件を確認済みとして保存しました。")
        st.rerun()
