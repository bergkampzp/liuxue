
-- 从录取数据中提取学校标准化名称
-- 注：完整的大学信息（排名/国家/官网）通过 sync_rankings.py 单独采集
WITH distinct_schools AS (
    SELECT DISTINCT
        school,
        '' AS country,
        NULL::integer AS qs_rank,
        NULL::integer AS usnews_rank
    FROM raw.gradcafe_admissions
    WHERE school IS NOT NULL
)
SELECT
    ROW_NUMBER() OVER () AS school_id,
    school,
    country,
    qs_rank,
    usnews_rank
FROM distinct_schools
