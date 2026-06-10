
  
    

  create  table "warehouse"."public"."int_admissions_cleaned__dbt_tmp"
  
  
    as
  
  (
    -- 中间层：录取数据按校+学位聚合（GradCafe 数据太分散，单个 program 样本量不够）
WITH base AS (
    SELECT
        school, program, degree, season, year,
        nationality, decision, gpa, gre_q, gre_v, gre_aw, toefl,
        major_category
    FROM "warehouse"."public"."stg_gradcafe_admissions"
    WHERE gpa IS NOT NULL
      AND degree IN ('Masters', 'PhD', 'Bachelors')
)
SELECT
    school,
    NULL AS program,  -- GradCafe 数据太分散，不按 program 聚合
    degree,
    NULL AS season,
    NULL::int AS year,
    -- 录取统计
    COUNT(*) AS total_cases,
    SUM(CASE WHEN decision = 'Accepted' THEN 1 ELSE 0 END) AS accepted_count,
    SUM(CASE WHEN decision = 'Rejected' THEN 1 ELSE 0 END) AS rejected_count,
    ROUND(
        SUM(CASE WHEN decision = 'Accepted' THEN 1.0 ELSE 0 END) / NULLIF(COUNT(*), 0), 3
    ) AS acceptance_rate,
    -- GPA 分位数
    ROUND(AVG(gpa)::numeric, 2) AS gpa_mean,
    ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY gpa)::numeric, 2) AS gpa_p25,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY gpa)::numeric, 2) AS gpa_p50,
    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY gpa)::numeric, 2) AS gpa_p75,
    -- GRE 统计
    ROUND(AVG(gre_q)::numeric, 1) AS gre_q_mean,
    ROUND(AVG(gre_v)::numeric, 1) AS gre_v_mean,
    -- 国际生占比
    ROUND(
        SUM(CASE WHEN nationality = 'International' THEN 1.0 ELSE 0 END) / NULLIF(COUNT(*), 0), 3
    ) AS international_ratio,
    -- 样本量
    COUNT(*) FILTER (WHERE gpa IS NOT NULL) AS gpa_samples
FROM base
GROUP BY school, degree
HAVING COUNT(*) >= 5  -- 至少 5 条案例才纳入统计
  );
  