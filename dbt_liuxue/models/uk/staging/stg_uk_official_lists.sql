-- stg_uk_official_lists: 官方认可名单归一化，cn_name_raw → cn_uni_id
-- 归一策略：精确匹配优先（=），LIKE兜底；未命中保留NULL行供上层使用

WITH raw_lists AS (
    SELECT * FROM {{ source('raw', 'uk_official_lists') }}
),

-- 1. 精确匹配英文名
exact_en AS (
    SELECT
        l.id,
        l.uk_uni_id,
        l.cn_name_raw,
        l.band,
        l.min_avg_score,
        l.source_url,
        l.fetched_at,
        d.cn_uni_id,
        d.tier_label AS cn_tier,
        1 AS match_priority
    FROM raw_lists l
    JOIN {{ ref('dim_cn_university') }} d
        ON lower(trim(l.cn_name_raw)) = lower(trim(d.name_en))
),

-- 2. 精确匹配中文名
exact_zh AS (
    SELECT
        l.id,
        l.uk_uni_id,
        l.cn_name_raw,
        l.band,
        l.min_avg_score,
        l.source_url,
        l.fetched_at,
        d.cn_uni_id,
        d.tier_label AS cn_tier,
        2 AS match_priority
    FROM raw_lists l
    JOIN {{ ref('dim_cn_university') }} d
        ON trim(l.cn_name_raw) = trim(d.name_zh)
    WHERE l.id NOT IN (SELECT id FROM exact_en)
),

-- 3. 别名精确匹配
alias_exact AS (
    SELECT
        l.id,
        l.uk_uni_id,
        l.cn_name_raw,
        l.band,
        l.min_avg_score,
        l.source_url,
        l.fetched_at,
        a.cn_uni_id,
        d.tier_label AS cn_tier,
        3 AS match_priority
    FROM raw_lists l
    JOIN {{ ref('cn_university_alias') }} a
        ON trim(l.cn_name_raw) = trim(a.alias)
    JOIN {{ ref('dim_cn_university') }} d
        ON a.cn_uni_id = d.cn_uni_id
    WHERE l.id NOT IN (SELECT id FROM exact_en)
      AND l.id NOT IN (SELECT id FROM exact_zh)
),

-- 4. LIKE模糊匹配英文名（兜底，可能有误伤）
like_en AS (
    SELECT
        l.id,
        l.uk_uni_id,
        l.cn_name_raw,
        l.band,
        l.min_avg_score,
        l.source_url,
        l.fetched_at,
        d.cn_uni_id,
        d.tier_label AS cn_tier,
        4 AS match_priority
    FROM raw_lists l
    JOIN {{ ref('dim_cn_university') }} d
        ON lower(l.cn_name_raw) LIKE '%' || lower(d.name_en) || '%'
    WHERE l.id NOT IN (SELECT id FROM exact_en)
      AND l.id NOT IN (SELECT id FROM exact_zh)
      AND l.id NOT IN (SELECT id FROM alias_exact)
),

-- 5. LIKE模糊匹配中文名（兜底）
like_zh AS (
    SELECT
        l.id,
        l.uk_uni_id,
        l.cn_name_raw,
        l.band,
        l.min_avg_score,
        l.source_url,
        l.fetched_at,
        d.cn_uni_id,
        d.tier_label AS cn_tier,
        5 AS match_priority
    FROM raw_lists l
    JOIN {{ ref('dim_cn_university') }} d
        ON l.cn_name_raw LIKE '%' || d.name_zh || '%'
    WHERE l.id NOT IN (SELECT id FROM exact_en)
      AND l.id NOT IN (SELECT id FROM exact_zh)
      AND l.id NOT IN (SELECT id FROM alias_exact)
      AND l.id NOT IN (SELECT id FROM like_en)
),

-- 6. 未命中行（cn_uni_id = NULL，保留）
unmatched AS (
    SELECT
        l.id,
        l.uk_uni_id,
        l.cn_name_raw,
        l.band,
        l.min_avg_score,
        l.source_url,
        l.fetched_at,
        NULL::text AS cn_uni_id,
        NULL::text AS cn_tier,
        9 AS match_priority
    FROM raw_lists l
    WHERE l.id NOT IN (SELECT id FROM exact_en)
      AND l.id NOT IN (SELECT id FROM exact_zh)
      AND l.id NOT IN (SELECT id FROM alias_exact)
      AND l.id NOT IN (SELECT id FROM like_en)
      AND l.id NOT IN (SELECT id FROM like_zh)
),

all_matched AS (
    SELECT * FROM exact_en
    UNION ALL SELECT * FROM exact_zh
    UNION ALL SELECT * FROM alias_exact
    UNION ALL SELECT * FROM like_en
    UNION ALL SELECT * FROM like_zh
    UNION ALL SELECT * FROM unmatched
),

-- DISTINCT ON 去重：同 (uk_uni_id, cn_name_raw, band) 取优先级最高的匹配
deduped AS (
    SELECT DISTINCT ON (uk_uni_id, cn_name_raw, band)
        id,
        uk_uni_id,
        cn_name_raw,
        band,
        min_avg_score,
        source_url,
        fetched_at,
        cn_uni_id,
        cn_tier,
        match_priority
    FROM all_matched
    ORDER BY uk_uni_id, cn_name_raw, band, match_priority
)

SELECT
    id,
    uk_uni_id,
    cn_name_raw,
    band,
    min_avg_score,
    source_url,
    fetched_at,
    cn_uni_id,
    cn_tier
FROM deduped
