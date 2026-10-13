-- GFS 自己変容・NPS 分析ツール スキーマ
-- 会員ID は必ず TEXT。日時は 'YYYY-MM-DD HH:MM:SS' の文字列で保存する。

CREATE TABLE IF NOT EXISTS members (
    member_id     TEXT PRIMARY KEY,
    first_seen_at TEXT,
    last_seen_at  TEXT
);

-- 取込単位。同じファイル（SHA-256 一致）の二重取込を防ぐ
CREATE TABLE IF NOT EXISTS import_batches (
    batch_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type    TEXT NOT NULL,          -- survey60 / action_list / diagnosis
    file_name      TEXT NOT NULL,
    file_sha256    TEXT NOT NULL,
    sheet_name     TEXT,
    row_count      INTEGER NOT NULL,       -- ファイルの行数
    inserted_count INTEGER NOT NULL,       -- 新規に保存した行数
    skipped_count  INTEGER NOT NULL,       -- 既存・重複・不正で保存しなかった行数
    imported_at    TEXT NOT NULL,
    UNIQUE (source_type, file_sha256)
);

-- 60日アンケート。不正値は NULL にして data_issues に記録する（集計に混ぜない）
CREATE TABLE IF NOT EXISTS survey_responses (
    response_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id                INTEGER NOT NULL REFERENCES import_batches(batch_id),
    source_row_no           INTEGER,
    member_id               TEXT NOT NULL REFERENCES members(member_id),
    answered_at             TEXT NOT NULL,
    gfs_satisfaction        INTEGER,       -- 1-5
    support_satisfaction    INTEGER,       -- 1-5（未利用・未回答は NULL）
    support_used            INTEGER,       -- 1=利用 0=利用していない NULL=不明
    nps                     INTEGER,       -- 0-10
    nps_question_present    INTEGER NOT NULL DEFAULT 1,  -- 0=設問がなかった時期の回答
    change_score            INTEGER,       -- 1-5（5=強く変化を感じる）
    change_question_present INTEGER NOT NULL DEFAULT 1,
    admission_good          TEXT,
    re_enroll               TEXT,
    reason_gfs              TEXT,
    reason_support          TEXT,
    reason_admission        TEXT,
    reason_recommend        TEXT,
    reason_reenroll         TEXT,
    reason_change           TEXT,
    worries                 TEXT,
    UNIQUE (member_id, answered_at)        -- 同じ回答の再取込を防ぐ（同一会員の別日時の回答は保持）
);
CREATE INDEX IF NOT EXISTS idx_survey_member ON survey_responses(member_id, answered_at);

-- 取込時に見つかった不正データ・欠損・不一致の記録
CREATE TABLE IF NOT EXISTS data_issues (
    issue_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      INTEGER NOT NULL REFERENCES import_batches(batch_id),
    source_row_no INTEGER,
    member_id     TEXT,
    field         TEXT,
    raw_value     TEXT,
    issue_type    TEXT NOT NULL,
    action        TEXT NOT NULL
);

-- 変化理由の分類（複数軸可）。source=auto はキーワード自動判定、ai は AI が見直したもの（人の確認待ち）、
-- manual は人が確認・修正したもの
CREATE TABLE IF NOT EXISTS change_classifications (
    response_id    INTEGER PRIMARY KEY REFERENCES survey_responses(response_id),
    knowledge      INTEGER NOT NULL DEFAULT 0,
    action         INTEGER NOT NULL DEFAULT 0,
    judgment       INTEGER NOT NULL DEFAULT 0,
    other          INTEGER NOT NULL DEFAULT 0,
    unclassifiable INTEGER NOT NULL DEFAULT 0,
    source         TEXT NOT NULL CHECK (source IN ('auto', 'ai', 'manual')),
    updated_at     TEXT NOT NULL
);

-- ===== アクションリスト =====
-- Liny 登録ID ↔ 会員ID。会員IDとの紐づけは集計時に行う（対応表を更新すると過去分にも反映される）
CREATE TABLE IF NOT EXISTS id_links (
    external_id TEXT PRIMARY KEY,
    member_id   TEXT NOT NULL,
    batch_id    INTEGER REFERENCES import_batches(batch_id),
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_id_links_member ON id_links(member_id);

-- アクションリストの1回答（毎回9タスクすべての状況を答える＝その時点のスナップショット）
CREATE TABLE IF NOT EXISTS action_responses (
    action_response_id TEXT PRIMARY KEY,   -- フォームの回答ID
    batch_id           INTEGER NOT NULL REFERENCES import_batches(batch_id),
    external_id        TEXT NOT NULL,      -- 回答者ID（Liny 登録ID）
    answered_at        TEXT NOT NULL,
    member_status      TEXT                -- 【退会済】【休学中】など（氏名は保存しない）
);
CREATE INDEX IF NOT EXISTS idx_action_external ON action_responses(external_id, answered_at);

CREATE TABLE IF NOT EXISTS action_answers (
    action_response_id TEXT NOT NULL REFERENCES action_responses(action_response_id),
    task_key           TEXT NOT NULL,
    answer             TEXT,
    done               INTEGER,            -- 1=達成 0=未達成 NULL=空欄・想定外の回答
    PRIMARY KEY (action_response_id, task_key)
);

-- 第1段階で用意した仮テーブル（未使用のまま廃止）
DROP TABLE IF EXISTS action_list_entries;

-- ===== 将来の拡張（テーブルのみ用意） =====
CREATE TABLE IF NOT EXISTS diagnosis_results (
    result_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id       INTEGER NOT NULL REFERENCES import_batches(batch_id),
    member_id      TEXT NOT NULL,
    diagnosis_type TEXT,
    taken_at       TEXT,
    result         TEXT,
    UNIQUE (member_id, diagnosis_type, taken_at)
);
CREATE INDEX IF NOT EXISTS idx_diagnosis_member ON diagnosis_results(member_id, taken_at);
