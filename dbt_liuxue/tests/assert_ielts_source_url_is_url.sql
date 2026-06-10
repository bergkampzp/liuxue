-- source_url 必须是真 URL（防中文逗号错位让日期混进来）
SELECT * FROM {{ ref('stg_uk_ielts_requirements') }}
WHERE source_url NOT LIKE 'https://%'
   OR valid_until IS NULL
