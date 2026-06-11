-- entry_requirement: 统一选校定位分数线（官方优先 > TestDaily种子）
--
-- 官方源规则：
--   sheffield: arwu-tier1/2/3/4 直接用行上的 min_avg_score（排除 gpa-scale/see-additional）
--   ucl:       band='in-list' → min_avg_score=85（官网原文：2:1 requires min weighted avg 85%）
--   edinburgh: band='priority-list' → min_avg_score=85（官网原文：Band A requires 85%；
--              Band B/C: minimum 80% for Priority List universities；priority-list DB行未细分band，
--              取保守上限85% — 防Band A项目误报达标）
--   bristol:   不出线（accepted名单仅判内外，无明确分数线）
--
-- 合并规则：同(uk_uni_id, cn_tier) 官方已有非空线 → 种子行不出（NOT EXISTS）

WITH

-- ── 1. Sheffield 官方线（行上自带 min_avg_score）────────────────────────────────
sheffield_official AS (
    SELECT
        s.uk_uni_id,
        '通用'                          AS subject_group,
        s.cn_tier,
        s.cn_uni_id,
        s.min_avg_score,
        'official_web'                  AS source_type,
        s.source_url,
        'high'                          AS confidence
    FROM {{ ref('stg_uk_official_lists') }} s
    WHERE s.uk_uni_id = 'sheffield'
      AND s.band IN ('arwu-tier1', 'arwu-tier2', 'arwu-tier3', 'arwu-tier4')
      AND s.min_avg_score IS NOT NULL
      AND s.cn_uni_id IS NOT NULL  -- 仅已归一的行出官方线
),

-- ── 2. UCL 官方线（in-list 院校 → 2:1 要求 85%）─────────────────────────────────
-- 官网原文："Upper second-class (2:1): Bachelor's degree with a minimum weighted
-- average mark of 85%." (UCL China page, 2026/27 entry)
ucl_official AS (
    SELECT DISTINCT
        s.uk_uni_id,
        '通用'                          AS subject_group,
        s.cn_tier,
        s.cn_uni_id,
        85.0                            AS min_avg_score,
        'official_web'                  AS source_type,
        s.source_url,
        'high'                          AS confidence
    FROM {{ ref('stg_uk_official_lists') }} s
    WHERE s.uk_uni_id = 'ucl'
      AND s.band = 'in-list'
      AND s.cn_uni_id IS NOT NULL
),

-- ── 3. Edinburgh 官方线（priority-list 院校 → 保守取 85%）────────────────────────
-- 官网原文："Band A requires 85%"
-- "Band B: a minimum of 80% awarded by a university on our Priority List"
-- "Band C: a minimum of 80%, awarded by a university on our Priority List"
-- priority-list DB行未细分Band字母，取保守上限85% — 防Band A项目误报达标
-- (law-school / art-college 暂排除，留待 P1 处理)
edinburgh_official AS (
    SELECT DISTINCT
        s.uk_uni_id,
        '通用'                          AS subject_group,
        s.cn_tier,
        s.cn_uni_id,
        85.0                            AS min_avg_score,
        'official_web'                  AS source_type,
        s.source_url,
        'high'                          AS confidence
    FROM {{ ref('stg_uk_official_lists') }} s
    WHERE s.uk_uni_id = 'edinburgh'
      AND s.band = 'priority-list'
      AND s.cn_uni_id IS NOT NULL
),

-- ── 4. 合并三个官方源 ──────────────────────────────────────────────────────────
official_all AS (
    SELECT * FROM sheffield_official
    UNION ALL
    SELECT * FROM ucl_official
    UNION ALL
    SELECT * FROM edinburgh_official
),

-- ── 5. TestDaily 种子线（官方已覆盖的 uk_uni_id+cn_tier 组合则剔除）────────────────
seed_filtered AS (
    SELECT
        t.uk_uni_id,
        t.subject_group,
        t.cn_tier,
        NULL::text                      AS cn_uni_id,   -- 种子行无法精确到院校
        t.min_avg_score::numeric,
        t.source_type,
        t.source_url,
        t.confidence
    FROM {{ ref('testdaily_lines_seed') }} t
    WHERE NOT EXISTS (
        SELECT 1
        FROM official_all o
        WHERE o.uk_uni_id    = t.uk_uni_id
          AND o.cn_tier      = t.cn_tier
          AND o.subject_group = t.subject_group  -- MVP-2: 防商科种子被通用线误杀
    )
),

-- ── 6. 最终合并输出 ─────────────────────────────────────────────────────────────
final AS (
    SELECT * FROM official_all
    UNION ALL
    SELECT * FROM seed_filtered
)

SELECT
    uk_uni_id,
    subject_group,
    cn_tier,
    cn_uni_id,
    min_avg_score,
    source_type,
    source_url,
    confidence
FROM final
WHERE min_avg_score IS NOT NULL
