"""クラウドで動かすときのデータ保存

データベース（SQLite）はアプリのローカルに置き、起動時に保存先から復元し、
書き込みのたびに保存先へ送る。アプリは1つだけ動かす前提（同時に書き込むプロセスは1つ）。

保存先（GFS_STORAGE）
- "drive"（既定）: Google ドライブ上のファイル。ファイルはユーザーのドライブに置き、
  サービスアカウントに編集権限を共有する（サービスアカウント自身は容量を持たないため）。
  ドライブの版の履歴で過去の状態に戻せる。
- "gcs": Google Cloud Storage のオブジェクト（Cloud Run 用）。

設定（環境変数。Streamlit Community Cloud ではシークレットの最上位キーが環境変数になる）
- GFS_CLOUD=1
- drive: GFS_DRIVE_FILE_ID=<ファイルID>、サービスアカウントの鍵はシークレット [gcp_service_account]
- gcs:   GFS_DB_BUCKET=<バケット名>, GFS_DB_OBJECT=<オブジェクト名（省略可）>
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Dict, Optional

DEFAULT_OBJECT = "gfs_analysis.db"


SETTING_KEYS = ("GFS_CLOUD", "GFS_STORAGE", "GFS_DRIVE_FILE_ID", "GFS_DB_BUCKET", "GFS_DB_OBJECT")
_secrets_loaded = False


def _load_secrets_into_env() -> None:
    """Streamlit のシークレット（最上位キー）を環境変数に写す。一度だけ行う。シークレットがなければ何もしない"""
    global _secrets_loaded
    if _secrets_loaded:
        return
    _secrets_loaded = True
    try:
        from streamlit.runtime import exists as streamlit_running
        if not streamlit_running():      # テストやスクリプトから呼ばれたときは読まない
            return
    except Exception:
        return
    try:
        import streamlit as st
        for k in SETTING_KEYS:
            if k not in os.environ and k in st.secrets:
                os.environ[k] = str(st.secrets[k])
    except Exception:
        pass


def enabled() -> bool:
    _load_secrets_into_env()
    return os.environ.get("GFS_CLOUD") == "1"


class ConflictError(RuntimeError):
    """保存先が別の場所で更新されていた"""


CONFLICT_MESSAGE = "保存先のデータが別の場所で更新されていました。ページを再読み込みしてからやり直してください。"


# ------------------------------------------------------------------ 保存先
class GCSBackend:
    def __init__(self, bucket, object_name: str = DEFAULT_OBJECT):
        self.bucket, self.object_name = bucket, object_name

    def fetch(self, path: Path) -> int:
        """保存先にあれば path に書き出して世代を返す。なければ 0"""
        blob = self.bucket.blob(self.object_name)
        if not blob.exists():
            return 0
        blob.reload()
        blob.download_to_filename(str(path), if_generation_match=blob.generation)
        return int(blob.generation)

    def push(self, path: Path, expected: int) -> int:
        blob = self.bucket.blob(self.object_name)
        try:
            blob.upload_from_filename(str(path), if_generation_match=expected or 0)
        except Exception as e:
            if e.__class__.__name__ in ("PreconditionFailed", "PreconditionFailedError"):
                raise ConflictError(CONFLICT_MESSAGE) from e
            raise
        return int(blob.generation)


class DriveBackend:
    """Google ドライブの既存ファイル（file_id）を読み書きする。世代 = ファイルの version"""

    def __init__(self, service, file_id: str):
        self.service, self.file_id = service, file_id

    def _version(self) -> int:
        meta = self.service.files().get(fileId=self.file_id, fields="version",
                                        supportsAllDrives=True).execute()
        return int(meta["version"])

    def fetch(self, path: Path) -> int:
        from googleapiclient.http import MediaIoBaseDownload
        version = self._version()
        with open(path, "wb") as f:
            req = self.service.files().get_media(fileId=self.file_id, supportsAllDrives=True)
            dl = MediaIoBaseDownload(f, req)
            done = False
            while not done:
                _, done = dl.next_chunk()
        if path.stat().st_size == 0:      # 空のファイル = まだデータなし
            path.unlink()
        return version

    def push(self, path: Path, expected: int) -> int:
        from googleapiclient.http import MediaFileUpload
        if self._version() != expected:
            raise ConflictError(CONFLICT_MESSAGE)
        media = MediaFileUpload(str(path), mimetype="application/octet-stream", resumable=False)
        meta = self.service.files().update(fileId=self.file_id, media_body=media, fields="version",
                                           supportsAllDrives=True).execute()
        return int(meta["version"])


def _service_account_info() -> Dict:
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
    except Exception:
        pass
    import json
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    raise RuntimeError("サービスアカウントの鍵（gcp_service_account）が設定されていません")


def default_backend():
    kind = os.environ.get("GFS_STORAGE", "drive")
    if kind == "gcs":
        from google.cloud import storage
        bucket = storage.Client().bucket(os.environ["GFS_DB_BUCKET"])
        return GCSBackend(bucket, os.environ.get("GFS_DB_OBJECT", DEFAULT_OBJECT))
    if kind == "drive":
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_info(
            _service_account_info(), scopes=["https://www.googleapis.com/auth/drive"])
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return DriveBackend(service, os.environ["GFS_DRIVE_FILE_ID"])
    raise RuntimeError(f"不明な保存先: {kind}")


# ------------------------------------------------------------------ 復元と保存
class Store:
    def __init__(self, backend, local_path: Path):
        self.backend = backend
        self.local_path = Path(local_path)
        self.generation: Optional[int] = None   # 最後に読み書きした世代（0 = まだない）
        self._lock = threading.Lock()

    def ensure_restored(self) -> None:
        with self._lock:
            if self.generation is not None:
                return
            self.local_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.local_path.with_name(self.local_path.name + ".download")
            gen = self.backend.fetch(tmp)
            if tmp.exists():
                shutil.move(str(tmp), str(self.local_path))
            self.generation = gen

    def save(self, conn: sqlite3.Connection) -> None:
        """書き込み中でも整合した状態で送れるよう、SQLite のバックアップ機能で複製してから送る"""
        with self._lock:
            with tempfile.TemporaryDirectory() as d:
                snap = Path(d) / "snapshot.db"
                dest = sqlite3.connect(str(snap))
                try:
                    conn.backup(dest)
                finally:
                    dest.close()
                try:
                    self.generation = self.backend.push(snap, self.generation or 0)
                except ConflictError:
                    # 次の読み込みで保存先から取り直す（このとき失敗した変更は破棄される）
                    self.generation = None
                    raise


_stores: Dict[str, Store] = {}
_stores_lock = threading.Lock()


def store(local_path: Path, bucket=None, backend=None) -> Store:
    """プロセスごとに1つの Store を使い回す（bucket はテスト用の GCS 代替）"""
    key = str(Path(local_path).resolve())
    with _stores_lock:
        if key not in _stores:
            if backend is None:
                backend = GCSBackend(bucket, os.environ.get("GFS_DB_OBJECT", DEFAULT_OBJECT)) \
                    if bucket is not None else default_backend()
            _stores[key] = Store(backend, Path(local_path))
        return _stores[key]


def reset_for_tests() -> None:
    with _stores_lock:
        _stores.clear()
