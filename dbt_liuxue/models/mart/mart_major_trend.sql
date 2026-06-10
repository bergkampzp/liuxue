-- 各专业大类的录取趋势
SELECT
    major_category,
    degree,
    year,
    COUNT(*) AS total_applications,
    ROUND(AVG(gpa)::numeric, 2) AS avg_gpa,
    ROUND(AVG(gre_q)::numeric, 1) AS avg_gre_q,
    ROUND(
        SUM(CASE WHEN decision = 'Accepted' THEN 1.0 ELSE 0 END) / NULLIF(COUNT(*), 0), 3
    ) AS acceptance_rate
FROM {{ ref('stg_gradcafe_admissions') }}
WHERE year IS NOT NULL
  AND gpa IS NOT NULL
  AND degree IN ('Masters', 'PhD')
GROUP BY major_category, degree, year
HAVING COUNT(*) >= 20
ORDER BY major_category, degree, year DESC
