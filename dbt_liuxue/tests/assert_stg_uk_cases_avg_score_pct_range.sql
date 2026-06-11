-- 断言：stg_uk_cases 中 avg_score_pct 非 null 时必须在 40-100 之间
-- 返回行数 = 0 则测试通过（dbt singular test 约定）
SELECT
    id,
    uk_uni_id,
    gpa,
    avg_score_pct,
    score_scale_inferred
FROM {{ ref('stg_uk_cases') }}
WHERE avg_score_pct IS NOT NULL
  AND (avg_score_pct < 40 OR avg_score_pct > 100)
