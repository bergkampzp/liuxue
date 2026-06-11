-- 断言：entry_requirement 中所有 source_url 必须以 http 开头
-- 防止本地路径（如 snapshots/edinburgh_priority_list.pdf）混入死链
-- 返回行数 = 0 则测试通过（dbt singular test 约定）
SELECT
    uk_uni_id,
    cn_tier,
    source_url
FROM {{ ref('entry_requirement') }}
WHERE source_url NOT LIKE 'http%'
