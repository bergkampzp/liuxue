
  
    

  create  table "warehouse"."public"."dash_competition_heatmap__dbt_tmp"
  
  
    as
  
  (
    -- BI看板：竞争烈度热力图（专业名称关键词分类）
SELECT
    CASE
        WHEN program ILIKE '%computer sci%' THEN 'CS'
        WHEN program ILIKE '%data sci%' THEN 'DS'
        WHEN program ILIKE '%electrical%' THEN 'EE'
        WHEN program ILIKE '%statistic%' THEN 'Stats'
        WHEN program ILIKE '%economics%' THEN 'Econ'
        WHEN program ILIKE '%finance%' THEN 'Finance'
        ELSE 'Other'
    END AS major_group,
    degree,
    ROUND(AVG(acceptance_rate)::numeric, 3) AS avg_acceptance_rate,
    ROUND(AVG(gpa_p50)::numeric, 2) AS avg_gpa_median,
    ROUND(AVG(competition_score)::numeric, 0) AS avg_competition_score,
    MAX(tier) AS top_tier,
    COUNT(*) AS program_count
FROM "warehouse"."public"."mart_school_admission_stats"
GROUP BY 1, degree
HAVING COUNT(*) >= 3
ORDER BY avg_competition_score DESC
  );
  