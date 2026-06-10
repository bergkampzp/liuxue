-- BI看板：录取全景
SELECT
    competition_level,
    degree,
    COUNT(DISTINCT school) AS school_count,
    COUNT(DISTINCT program) AS program_count,
    ROUND(AVG(acceptance_rate)::numeric, 3) AS avg_acceptance_rate,
    ROUND(AVG(gpa_p50)::numeric, 2) AS avg_gpa_median,
    SUM(sample_size) AS total_samples
FROM "warehouse"."public"."mart_school_admission_stats"
GROUP BY competition_level, degree
ORDER BY degree, avg_acceptance_rate