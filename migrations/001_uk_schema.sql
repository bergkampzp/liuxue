-- migrations/001_uk_schema.sql
-- 英联邦支线 raw 层扩展。幂等：可重复执行。

ALTER TABLE raw.liuxue_admissions
    ADD COLUMN IF NOT EXISTS country         TEXT,
    ADD COLUMN IF NOT EXISTS decision_detail TEXT,
    ADD COLUMN IF NOT EXISTS ielts_l         NUMERIC(2,1),
    ADD COLUMN IF NOT EXISTS ielts_r         NUMERIC(2,1),
    ADD COLUMN IF NOT EXISTS ielts_w         NUMERIC(2,1),
    ADD COLUMN IF NOT EXISTS ielts_s         NUMERIC(2,1);

CREATE TABLE IF NOT EXISTS raw.uk_ielts_requirements (
    id            SERIAL PRIMARY KEY,
    uk_school     TEXT NOT NULL,
    profile_level TEXT NOT NULL DEFAULT 'standard',  -- 学校自己的档位原文,如 Standard/Higher
    ielts_overall NUMERIC(2,1) NOT NULL,
    ielts_l       NUMERIC(2,1),
    ielts_r       NUMERIC(2,1),
    ielts_w       NUMERIC(2,1),
    ielts_s       NUMERIC(2,1),
    subject_hint  TEXT,                    -- 该档适用专业说明原文,dbt 层展开到 subject_group
    source_url    TEXT NOT NULL,
    valid_until   DATE,
    verified_at   DATE NOT NULL,
    UNIQUE (uk_school, profile_level)
);
