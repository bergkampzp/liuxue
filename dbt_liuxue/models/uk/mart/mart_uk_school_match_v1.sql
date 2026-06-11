-- mart_uk_school_match_v1: 每行 = (英国校 × subject_group × cn_tier) 聚合线 + 基线雅思
--
-- tier 级聚合规则：
--   同 (uk_uni_id, subject_group, cn_tier) 取 MAX(min_avg_score)，保守上限（宁严勿松）
--   官方行存在则 source_type='official_web' / confidence='high'
--   每校雅思取 ielts_overall 最高档作为保守基线（宁严勿松）

WITH tier_lines AS (
    SELECT
        uk_uni_id,
        subject_group,
        cn_tier,
        MAX(min_avg_score) AS min_avg_score,                          -- 保守上限
        COUNT(DISTINCT cn_uni_id) AS n_schools_in_band,
        -- 官方行存在时取官方 source_type（字典序 official_pdf < official_web 均 < aggregator 不适用，用 CASE 判断）
        MAX(CASE WHEN source_type LIKE 'official%' THEN source_type ELSE NULL END) AS official_source,
        MIN(source_type) AS any_source,
        MIN(source_url)  AS source_url,
        MIN(confidence)  AS confidence_raw                            -- high < low < medium 字典序；官方行另外覆盖
    FROM {{ ref('entry_requirement') }}
    WHERE cn_tier IS NOT NULL
    GROUP BY 1, 2, 3
),
baseline_ielts AS (
    SELECT DISTINCT ON (uk_uni_id)
        uk_uni_id,
        profile_level,
        ielts_overall,
        ielts_l,
        ielts_r,
        ielts_w,
        ielts_s,
        source_url AS ielts_source_url
    FROM {{ ref('stg_uk_ielts_requirements') }}
    ORDER BY uk_uni_id, ielts_overall DESC                            -- 取该校最高雅思档作保守基线
)
SELECT
    t.uk_uni_id,
    u.name_zh,
    u.qs_rank,
    t.subject_group,
    t.cn_tier,
    t.min_avg_score,
    COALESCE(t.official_source, t.any_source)                 AS source_type,
    t.source_url,
    CASE
        WHEN t.official_source IS NOT NULL THEN 'high'
        ELSE t.confidence_raw
    END                                                       AS confidence,
    t.n_schools_in_band,
    b.profile_level                                           AS ielts_profile,
    b.ielts_overall,
    b.ielts_l,
    b.ielts_r,
    b.ielts_w,
    b.ielts_s,
    b.ielts_source_url
FROM tier_lines t
JOIN {{ ref('dim_uk_university') }} u USING (uk_uni_id)
LEFT JOIN baseline_ielts b USING (uk_uni_id)
