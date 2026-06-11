-- 断言：mart_uk_school_match_v1 的粒度 (uk_uni_id, subject_group, cn_tier) 无重复行
-- 返回行数 = 0 则测试通过（dbt singular test 约定）
SELECT uk_uni_id, subject_group, cn_tier, count(*)
FROM {{ ref('mart_uk_school_match_v1') }}
GROUP BY 1, 2, 3
HAVING count(*) > 1
