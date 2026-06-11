-- int_uk_cases_tagged: 英联邦案例行级标注（table）
-- 来源：stg_uk_cases
-- 标注内容：
--   1. tier_label：通过 undergrad_school → raw.case_school_map(cn_uni_id非空)
--                  → dim_cn_university.tier_label 获取
--   2. subject_group：基于 program/undergrad_major 关键词规则的专业大类映射
--                     （与 api MAJOR_KEYWORDS 口径对齐）
--                     TODO: 待 ANTHROPIC_API_KEY 就位后接入 LLM 精细打标
-- 说明：undergrad_school 全 NULL 时，join case_school_map 无命中 → 0行 = 正确行为
--       拟合脚本（fit_uk_entry_line.py）从本表读取行级数据

{{
    config(
        materialized='table'
    )
}}

WITH cases AS (
    SELECT * FROM {{ ref('stg_uk_cases') }}
),

school_map AS (
    SELECT undergrad_school_raw, cn_uni_id
    FROM {{ source('raw', 'case_school_map') }}
    WHERE cn_uni_id IS NOT NULL
),

dim_cn AS (
    SELECT cn_uni_id, tier_label
    FROM {{ ref('dim_cn_university') }}
)

SELECT
    c.id,
    c.uk_uni_id,
    c.school_raw,
    c.program,
    c.degree,
    c.decision,
    c.decision_detail,
    c.ielts,
    c.ielts_l,
    c.ielts_r,
    c.ielts_w,
    c.ielts_s,
    c.undergrad_school,
    c.undergrad_major,
    c.year,
    c.source,
    c.source_url,
    c.gpa,
    c.avg_score_pct,
    c.score_scale_inferred,
    sm.cn_uni_id,
    dc.tier_label,
    -- subject_group: 关键词规则映射（program 和 undergrad_major 联合匹配）
    -- TODO: 待 ANTHROPIC_API_KEY 就位后，替换为 LLM 精细打标（保留规则版作回退）
    CASE
        WHEN lower(coalesce(c.program, '') || ' ' || coalesce(c.undergrad_major, ''))
             ~ '(计算机|软件|computer|cs\b|data science|machine learning|人工智能|ai\b)'
            THEN 'CS与数据'
        WHEN lower(coalesce(c.program, '') || ' ' || coalesce(c.undergrad_major, ''))
             ~ '(金融|经济|finance|econom|会计|accounting|business|商科|mba|msc finance)'
            THEN '商科金融'
        WHEN lower(coalesce(c.program, '') || ' ' || coalesce(c.undergrad_major, ''))
             ~ '(机械|电子|电气|土木|engineering|材料|化工|aerospace|civil|electrical|mechanical)'
            THEN '工科'
        WHEN lower(coalesce(c.program, '') || ' ' || coalesce(c.undergrad_major, ''))
             ~ '(法学|law|法律)'
            THEN '法律'
        WHEN lower(coalesce(c.program, '') || ' ' || coalesce(c.undergrad_major, ''))
             ~ '(教育|education|pgce)'
            THEN '教育'
        WHEN lower(coalesce(c.program, '') || ' ' || coalesce(c.undergrad_major, ''))
             ~ '(传媒|media|communication|journalism|新闻)'
            THEN '传媒'
        ELSE '通用'
    END AS subject_group

FROM cases c
JOIN school_map sm
    ON c.undergrad_school IS NOT NULL
   AND trim(c.undergrad_school) = trim(sm.undergrad_school_raw)
JOIN dim_cn dc
    ON sm.cn_uni_id = dc.cn_uni_id
