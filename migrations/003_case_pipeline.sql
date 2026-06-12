-- migrations/003_case_pipeline.sql
-- 幂等迁移：案例反推管线所需两张表
-- 跑两遍验证幂等性

-- 校名归一映射表
-- method: exact / alias / fuzzy
-- confidence: 1.0 / 1.0 / 0.92
-- reviewed: 人工复核标记（H3 工作包回流后置 true）
CREATE TABLE IF NOT EXISTS raw.case_school_map (
    undergrad_school_raw TEXT        PRIMARY KEY,
    cn_uni_id            TEXT,                           -- NULL = 未命中（待人工）
    method               TEXT,                           -- exact / alias / fuzzy / NULL
    confidence           NUMERIC(4,2),                   -- 1.0 / 0.92 / NULL
    reviewed             BOOLEAN     NOT NULL DEFAULT false,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 英国入学线反推结果表
-- 按 (uk_uni_id × subject_group × cn_tier) 粒度
-- 注意：此表由 fit_uk_entry_line.py 写入，目前不接入 mart/API
-- 门禁：H7 顾问 sanity 未签，case 线不上 web
CREATE TABLE IF NOT EXISTS raw.uk_entry_line_case (
    id             SERIAL       PRIMARY KEY,
    uk_uni_id      TEXT         NOT NULL,
    subject_group  TEXT         NOT NULL,
    cn_tier        TEXT         NOT NULL,
    line_low       NUMERIC(5,2),                         -- P10 (offer 分位)
    line_high      NUMERIC(5,2),                         -- P25 (offer 分位)
    line_iso50     NUMERIC(5,2),                         -- 等渗 P(录取)=0.5 的分数
    sample_n       INTEGER,
    offer_n        INTEGER,
    reject_n       INTEGER,
    confidence     TEXT,                                  -- low / medium / high
    method         TEXT,                                  -- lower_bound / isotonic+p10p25 / isotonic+bootstrap / all_reject
    fallback_level INTEGER      NOT NULL DEFAULT 0,      -- 0=无回退, 1-4=逐级降
    year_range     TEXT,                                  -- e.g. "2022-2024"
    note           TEXT,
    UNIQUE (uk_uni_id, subject_group, cn_tier)
);
