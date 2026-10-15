"""チーム共有用ダッシュボード（パスワード付き）を書き出す

    .venv/bin/python scripts/build_dashboard.py

- パスワードは data/dashboard_password.txt（Git 管理外）。なければランダムに作る
- 出力は site/（Git 管理外）。公開用リポジトリへのコピーと push は別途行う
"""
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gfs_analysis import dashboard, db  # noqa: E402

PW_FILE = ROOT / "data" / "dashboard_password.txt"
OUT_DIR = ROOT / "site"


def load_or_create_password() -> str:
    if PW_FILE.exists():
        return PW_FILE.read_text(encoding="utf-8").strip()
    alphabet = string.ascii_letters + string.digits
    pw = "-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(4))
    PW_FILE.parent.mkdir(parents=True, exist_ok=True)
    PW_FILE.write_text(pw + "\n", encoding="utf-8")
    PW_FILE.chmod(0o600)
    print(f"新しいパスワードを作成しました: {PW_FILE}")
    return pw


if __name__ == "__main__":
    path = dashboard.write_site(db.connect(), load_or_create_password(), OUT_DIR)
    print(f"書き出しました: {path}")
