-- 断言：stg_uk_entry_line_case 中 line_iso50 / line_low 非 null 时必须在 60-95 之间
-- 返回行数 = 0 则测试通过（dbt singular test 约定）
SELECT
    uk_uni_id,
    subject_group,
    cn_tier,
    line_iso50,
    line_low,
    line_high
FROM {{ ref('stg_uk_entry_line_case') }}
WHERE
    (line_iso50 IS NOT NULL AND (line_iso50 < 60 OR line_iso50 > 95))
    OR
    (line_low IS NOT NULL AND (line_low < 60 OR line_low > 95))
