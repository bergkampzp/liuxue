
  
    

  create  table "warehouse"."public"."feat_competition_index__dbt_tmp"
  
  
    as
  
  (
    -- 专业竞争指数：综合录取率和申请者 GPA 水平
SELECT
    school, program, degree,
    acceptance_rate,
    gpa_p50,
    international_ratio,
    total_cases,
    -- 竞争指数 (0-100): GPA 门槛越高 + 录取率越低 = 越难进
    ROUND(
        (gpa_p50 * 25 - 50) + ((1 - acceptance_rate) * 100)
    )::integer AS competition_score,
    CASE
        WHEN acceptance_rate < 0.2 AND gpa_p50 > 3.7 THEN 'S-Tier (Extremely Selective)'
        WHEN acceptance_rate < 0.35 AND gpa_p50 > 3.5 THEN 'A-Tier (Very Selective)'
        WHEN acceptance_rate < 0.5 THEN 'B-Tier (Selective)'
        ELSE 'C-Tier (Accessible)'
    END AS tier
FROM "warehouse"."public"."int_admissions_cleaned"
WHERE total_cases >= 5
  );
  