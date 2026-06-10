
  
    

  create  table "warehouse"."public"."dash_top_schools__dbt_tmp"
  
  
    as
  
  (
    -- BI看板：Top 20 热门学校
SELECT
    school,
    degree,
    COUNT(DISTINCT program) AS program_diversity,
    SUM(sample_size) AS total_samples,
    ROUND(AVG(acceptance_rate)::numeric, 3) AS avg_acceptance_rate,
    ROUND(AVG(gpa_p50)::numeric, 2) AS avg_gpa_median,
    MAX(tier) AS top_tier
FROM "warehouse"."public"."mart_school_admission_stats"
GROUP BY school, degree
HAVING SUM(sample_size) >= 20
ORDER BY total_samples DESC
LIMIT 20
  );
  