"""GFS 自己変容・NPS 分析ツール

起動: .venv/bin/streamlit run app.py
"""
import streamlit as st

st.navigation([
    st.Page("home.py", title="ホーム", icon=":material/home:", default=True),
    st.Page("pages/1_データ取込.py", title="データ取込", icon=":material/upload_file:"),
    st.Page("pages/2_データ品質.py", title="データ品質", icon=":material/fact_check:"),
    st.Page("pages/3_分布.py", title="分布", icon=":material/bar_chart:"),
    st.Page("pages/4_クロス集計.py", title="クロス集計", icon=":material/table_chart:"),
    st.Page("pages/8_推移.py", title="推移", icon=":material/show_chart:"),
    st.Page("pages/9_データ一覧.py", title="データ一覧", icon=":material/calendar_month:"),
    st.Page("pages/5_変化理由の分類.py", title="変化理由の分類", icon=":material/label:"),
    st.Page("pages/7_アクション×NPS.py", title="アクション×NPS", icon=":material/directions_run:"),
    st.Page("pages/6_Excel出力.py", title="Excel出力", icon=":material/download:"),
]).run()
