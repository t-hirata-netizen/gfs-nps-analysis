#!/bin/zsh
# ダブルクリックで GFS 自己変容・NPS 分析ツールを起動します（終了はこのウィンドウを閉じる）
cd "$(dirname "$0")"
if [ ! -x .venv/bin/streamlit ]; then
  echo "初回セットアップ中…"
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
( sleep 3 && open http://localhost:8501 ) &
.venv/bin/streamlit run app.py --server.port 8501 --server.address localhost
