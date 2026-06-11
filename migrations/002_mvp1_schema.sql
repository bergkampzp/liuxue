-- migrations/002_mvp1_schema.sql
-- 幂等迁移：创建 MVP-1 所需的两张表

CREATE TABLE IF NOT EXISTS raw.uk_official_lists (
    id          SERIAL PRIMARY KEY,
    uk_uni_id   TEXT NOT NULL,          -- 对齐 seeds/dim_uk_university.uk_uni_id
    cn_name_raw TEXT NOT NULL,          -- 名单上的中国院校名原文(可能中英混排)
    band        TEXT NOT NULL,          -- in-list / BandA-D / arwu-tier1-4 等,按校原文
    min_avg_score NUMERIC(4,1),         -- 名单页直接标分数线的填,否则NULL
    source_url  TEXT NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL,
    UNIQUE (uk_uni_id, cn_name_raw, band)
);

CREATE TABLE IF NOT EXISTS raw.waitlist_leads (
    id          SERIAL PRIMARY KEY,
    email       TEXT NOT NULL,
    uk_uni_id   TEXT,                   -- 用户想查但缺数据的学校
    profile_json JSONB,                 -- 用户输入的背景(脱敏前先存)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
