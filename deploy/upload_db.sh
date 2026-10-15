#!/bin/zsh
# 手元のデータベースをクラウドに載せる（初回のみ。個人情報を含むので社内の承認後に実行）
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
SNAP="$(mktemp -d)/gfs_analysis.db"
.venv/bin/python -c "import sqlite3,sys; s=sqlite3.connect('data/gfs_analysis.db'); d=sqlite3.connect(sys.argv[1]); s.backup(d); d.close()" "$SNAP"
gcloud storage cp "$SNAP" "gs://${BUCKET}/gfs_analysis.db"
rm -f "$SNAP"
echo "アップロードしました: gs://${BUCKET}/gfs_analysis.db"
