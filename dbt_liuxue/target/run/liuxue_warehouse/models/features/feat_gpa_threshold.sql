
  
    

  create  table "warehouse"."public"."feat_gpa_threshold__dbt_tmp"
  
  
    as
  
  (
    -- 各校各专业的 GPA 录取阈值（按学位分层）
SELECT
    school, program, degree,
    gpa_p25, gpa_p50, gpa_p75,
    acceptance_rate,
    total_cases AS sample_size,
    CASE
        WHEN acceptance_rate >= 0.7 THEN 'Low Competition'
        WHEN acceptance_rate >= 0.4 THEN 'Moderate'
        ELSE 'High Competition'
    END AS competition_level,
    -- GPA 分级建议
    CASE
        WHEN gpa_p75 >= 3.8 THEN 'Ultra Competitive'
        WHEN gpa_p50 >= 3.5 THEN 'Competitive'
        WHEN gpa_p50 >= 3.2 THEN 'Moderate'
        ELSE 'Accessible'
    END AS gpa_requirement_level
FROM "warehouse"."public"."int_admissions_cleaned"
WHERE gpa_samples >= 5  -- 至少 5 个 GPA 样本
  );
  