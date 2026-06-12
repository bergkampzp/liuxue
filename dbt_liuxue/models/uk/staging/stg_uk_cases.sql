-- stg_uk_cases: 英联邦案例暂存层（view）
-- 数据源：raw.liuxue_admissions
-- 过滤逻辑：school 经清洗后精确命中 dim_uk_university（name_zh 或 name_en）
-- 清洗规则（参考 stg_uk_official_lists 的清洗思路）：
--   1. 去尾部 **（gter 有时在校名末尾带双星号）
--   2. 去括号注释（中文全角括号 （xxx） 和 英文括号 (xxx)）
--   3. trim + lower
-- avg_score_pct 归一：
--   gpa <= 4.5 → gpa * 25，同时 score_scale_inferred = true（4分制换算）
--   40 <= gpa <= 100 → 原值，score_scale_inferred = false（百分制直用）
--   其余 → NULL
-- 透传列：decision / decision_detail / ielts / undergrad_school /
--          undergrad_major / year / source / source_url

WITH admissions AS (
    SELECT * FROM {{ source('raw', 'liuxue_admissions') }}
),

dim_uk AS (
    SELECT uk_uni_id, name_zh, name_en
    FROM {{ ref('dim_uk_university') }}
),

-- 清洗 school 字段
cleaned AS (
    SELECT
        a.*,
        lower(
            trim(
                -- 去英文括号注释 (xxx)
                regexp_replace(
                    -- 去中文全角括号注释 （xxx）
                    regexp_replace(
                        -- 去尾部 **
                        regexp_replace(a.school, '\*+$', ''),
                        '（[^）]*）',
                        ''
                    ),
                    '\([^\)]*\)',
                    ''
                )
            )
        ) AS school_clean
    FROM admissions a
),

-- 精确匹配中文名（直接比较，不 lower）
match_zh AS (
    SELECT
        c.id,
        d.uk_uni_id,
        1 AS match_priority
    FROM cleaned c
    JOIN dim_uk d
        ON trim(c.school) = trim(d.name_zh)
),

-- 精确匹配英文名（lower 比较）
match_en AS (
    SELECT
        c.id,
        d.uk_uni_id,
        2 AS match_priority
    FROM cleaned c
    JOIN dim_uk d
        ON c.school_clean = lower(trim(d.name_en))
    WHERE c.id NOT IN (SELECT id FROM match_zh)
),

all_matches AS (
    SELECT * FROM match_zh
    UNION ALL
    SELECT * FROM match_en
),

-- 每行取最优匹配
best_match AS (
    SELECT DISTINCT ON (id)
        id,
        uk_uni_id
    FROM all_matches
    ORDER BY id, match_priority
),

-- avg_score_pct 归一
final AS (
    SELECT
        a.id,
        m.uk_uni_id,
        a.school                                    AS school_raw,
        a.program,
        a.degree,
        a.decision,
        a.decision_detail,
        a.ielts,
        a.ielts_l,
        a.ielts_r,
        a.ielts_w,
        a.ielts_s,
        a.undergrad_school,
        a.undergrad_major,
        a.year,
        a.source,
        a.source_url,
        a.gpa,
        CASE
            WHEN a.gpa IS NOT NULL AND a.gpa <= 4.5
                 AND ROUND((a.gpa * 25)::numeric, 2) BETWEEN 40 AND 100
                THEN ROUND((a.gpa * 25)::numeric, 2)
            WHEN a.gpa IS NOT NULL AND a.gpa >= 40 AND a.gpa <= 100
                THEN ROUND(a.gpa::numeric, 2)
            ELSE NULL
        END                                         AS avg_score_pct,
        CASE
            WHEN a.gpa IS NOT NULL AND a.gpa <= 4.5
                 AND ROUND((a.gpa * 25)::numeric, 2) BETWEEN 40 AND 100
                THEN true
            WHEN a.gpa IS NOT NULL AND a.gpa >= 40 AND a.gpa <= 100
                THEN false
            ELSE NULL
        END                                         AS score_scale_inferred
    FROM cleaned a
    JOIN best_match m ON a.id = m.id
)

SELECT * FROM final
