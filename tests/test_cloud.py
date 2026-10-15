"""クラウド保存（Cloud Storage）と操作者の記録のテスト。Cloud Storage は偽物で代用する。"""
import shutil
import sqlite3

import pytest

from conftest import row
from gfs_analysis import classify, cloud, db, ingest


class PreconditionFailed(Exception):
    pass


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name = bucket, name

    @property
    def generation(self):
        return self.bucket.objects[self.name][1] if self.name in self.bucket.objects else None

    def exists(self):
        return self.name in self.bucket.objects

    def reload(self):
        pass

    def download_to_filename(self, path, if_generation_match=None):
        data, gen = self.bucket.objects[self.name]
        if if_generation_match is not None and gen != if_generation_match:
            raise PreconditionFailed()
        open(path, "wb").write(data)

    def upload_from_filename(self, path, if_generation_match=None):
        current = self.generation or 0
        if if_generation_match is not None and current != if_generation_match:
            raise PreconditionFailed()
        self.bucket.objects[self.name] = (open(path, "rb").read(), current + 1)


class FakeBucket:
    def __init__(self):
        self.objects = {}

    def blob(self, name):
        return FakeBlob(self, name)


@pytest.fixture
def cloud_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GFS_CLOUD", "1")
    monkeypatch.setenv("GFS_DB_BUCKET", "test-bucket")
    path = tmp_path / "inst1" / "gfs.db"
    monkeypatch.setenv("GFS_DB_PATH", str(path))
    cloud.reset_for_tests()
    bucket = FakeBucket()
    cloud.store(path, bucket=bucket)
    yield bucket, path
    cloud.reset_for_tests()


def test_first_start_creates_and_saves(cloud_env, make_excel):
    bucket, path = cloud_env
    conn = db.connect()
    assert bucket.objects == {}
    ingest.import_survey_file(conn, make_excel([row(1, "2026-09-10 10:00:00", nps=9, change=5)]))
    db.sync(conn)
    assert bucket.objects["gfs_analysis.db"][1] == 1


def test_restart_restores_from_bucket(cloud_env, make_excel, tmp_path, monkeypatch):
    bucket, path = cloud_env
    conn = db.connect()
    ingest.import_survey_file(conn, make_excel([row(1, "2026-09-10 10:00:00", nps=9, change=5)]))
    db.sync(conn)
    conn.close()
    # 新しいインスタンス（ローカルのファイルなし）として起動し直す
    new_path = tmp_path / "inst2" / "gfs.db"
    monkeypatch.setenv("GFS_DB_PATH", str(new_path))
    cloud.reset_for_tests()
    cloud.store(new_path, bucket=bucket)
    conn2 = db.connect()
    assert conn2.execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0] == 1


def test_conflict_is_detected(cloud_env, make_excel):
    bucket, path = cloud_env
    conn = db.connect()
    db.sync(conn)
    data, gen = bucket.objects["gfs_analysis.db"]
    bucket.objects["gfs_analysis.db"] = (data, gen + 5)   # 別の場所で更新された
    with pytest.raises(cloud.ConflictError):
        db.sync(conn)


def test_local_mode_does_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("GFS_CLOUD", raising=False)
    conn = db.connect(tmp_path / "x.db")
    db.sync(conn)   # 例外にならない


def test_user_is_recorded(conn, make_excel):
    ingest.import_survey_file(conn, make_excel([row(1, "2026-09-10 10:00:00", nps=9, change=5,
                                                    reason_change="NISAを始めた")]), user="a@example.com")
    assert conn.execute("SELECT imported_by FROM import_batches").fetchone()[0] == "a@example.com"
    classify.auto_classify(conn)
    rid = conn.execute("SELECT response_id FROM survey_responses").fetchone()[0]
    classify.save_manual(conn, [{"response_id": rid, "action": 1}], user="b@example.com")
    assert conn.execute("SELECT updated_by FROM change_classifications").fetchone()[0] == "b@example.com"


def test_old_db_gets_new_columns(tmp_path):
    src = tmp_path / "old.db"
    c = sqlite3.connect(src)
    c.execute("""CREATE TABLE import_batches (batch_id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL,
        file_name TEXT NOT NULL, file_sha256 TEXT NOT NULL, sheet_name TEXT, row_count INTEGER NOT NULL,
        inserted_count INTEGER NOT NULL, skipped_count INTEGER NOT NULL, imported_at TEXT NOT NULL,
        UNIQUE (source_type, file_sha256))""")
    c.execute("INSERT INTO import_batches VALUES (1,'survey60','a.xlsx','x',NULL,1,1,0,'2026-10-01 00:00:00')")
    c.commit(); c.close()
    conn = db.connect(src)
    assert conn.execute("SELECT file_name, imported_by FROM import_batches").fetchone() == ("a.xlsx", None)
    shutil.rmtree(tmp_path, ignore_errors=True)


# ---------------------------------------------------------------- Google ドライブ
class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeDriveFiles:
    def __init__(self, drive):
        self.d = drive

    def get(self, fileId, fields, supportsAllDrives):
        return _Req(lambda: {"version": str(self.d.version)})

    def get_media(self, fileId, supportsAllDrives):
        return self.d.content

    def update(self, fileId, media_body, fields, supportsAllDrives):
        def run():
            self.d.content = open(media_body._filename, "rb").read()
            self.d.version += 1
            return {"version": str(self.d.version)}
        return _Req(run)


class FakeDrive:
    def __init__(self, content=b"", version=10):
        self.content, self.version = content, version

    def files(self):
        return FakeDriveFiles(self)


@pytest.fixture
def drive_env(tmp_path, monkeypatch):
    import googleapiclient.http as gh

    class FakeDownload:
        def __init__(self, fh, content):
            self.fh, self.content = fh, content

        def next_chunk(self):
            self.fh.write(self.content)
            return None, True
    monkeypatch.setattr(gh, "MediaIoBaseDownload", FakeDownload)
    monkeypatch.setenv("GFS_CLOUD", "1")
    path = tmp_path / "inst" / "gfs.db"
    monkeypatch.setenv("GFS_DB_PATH", str(path))
    cloud.reset_for_tests()
    drive = FakeDrive()
    cloud.store(path, backend=cloud.DriveBackend(drive, "FILE_ID"))
    yield drive, path
    cloud.reset_for_tests()


def test_drive_empty_file_then_save_and_restore(drive_env, make_excel, tmp_path, monkeypatch):
    drive, path = drive_env
    conn = db.connect()                       # 空のファイル → 新しいデータベース
    ingest.import_survey_file(conn, make_excel([row(1, "2026-09-10 10:00:00", nps=9, change=5)]))
    db.sync(conn)
    assert drive.version == 11 and len(drive.content) > 0
    new_path = tmp_path / "inst2" / "gfs.db"
    monkeypatch.setenv("GFS_DB_PATH", str(new_path))
    cloud.reset_for_tests()
    cloud.store(new_path, backend=cloud.DriveBackend(drive, "FILE_ID"))
    assert db.connect().execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0] == 1


def test_drive_conflict_then_recover(drive_env):
    drive, path = drive_env
    conn = db.connect()
    db.sync(conn)
    drive.version += 3                        # 別の場所で更新された（共有設定の変更など）
    with pytest.raises(cloud.ConflictError):
        db.sync(conn)
    conn2 = db.connect()                      # 再読み込み → 取り直してから保存できる
    db.sync(conn2)
    assert drive.version == 15
