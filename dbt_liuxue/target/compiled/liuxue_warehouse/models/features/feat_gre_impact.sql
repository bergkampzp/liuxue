-- GRE 成绩对录取的影响分析
SELECT
    school, program, degree,
    ROUND(AVG(gre_q)::numeric, 1) AS gre_q_mean,
    ROUND(AVG(gre_v)::numeric, 1) AS gre_v_mean,
    -- 国际生录取中 GRE Q 的关键度
    ROUND(
        AVG(CASE WHEN gre_q >= 165 THEN 1.0 ELSE 0.0 END)::numeric, 2
    ) AS gre_q_high_ratio,
    -- GRE 对录取的区分度
    ROUND(
        (
            AVG(CASE WHEN decision = 'Accepted' AND gre_q IS NOT NULL THEN gre_q END) -
            AVG(CASE WHEN decision = 'Rejected' AND gre_q IS NOT NULL THEN gre_q END)
        )::numeric, 1
    ) AS gre_q_acceptance_delta,
    COUNT(*) FILTER (WHERE gre_q IS NOT NULL) AS gre_samples
FROM "warehouse"."public"."stg_gradcafe_admissions"
WHERE degree IN ('Masters', 'PhD')
  AND gre_q IS NOT NULL
GROUP BY school, program, degree
HAVING COUNT(*) FILTER (WHERE gre_q IS NOT NULL) >= 5