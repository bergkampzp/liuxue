-- 断言：entry_requirement 中所有分数线必须在 60-95 之间
-- 返回行数 = 0 则测试通过（dbt singular test 约定）
SELECT
    uk_uni_id,
    cn_tier,
    min_avg_score,
    source_type
FROM {{ ref('entry_requirement') }}
WHERE min_avg_score < 60
   OR min_avg_score > 95
