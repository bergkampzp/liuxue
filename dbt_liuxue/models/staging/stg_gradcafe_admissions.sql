-- 清洗 GradCafe 原始数据：类型转换、过滤无效记录
WITH cleaned AS (
    SELECT
        id,
        school,
        program,
        -- 推断学位层级
        CASE
            WHEN program ILIKE '%phd%' OR program ILIKE '%doctor%' THEN 'PhD'
            WHEN program ILIKE '%master%' OR program ILIKE '%ms %' OR program ILIKE '%m.eng%'
                OR program ILIKE '%mba%' OR program ILIKE '%m.a.%' THEN 'Masters'
            WHEN program ILIKE '%bachelor%' OR program ILIKE '%b.s.%' OR program ILIKE '%undergrad%' THEN 'Bachelors'
            ELSE 'Other'
        END AS degree,
        season,
        year,
        nationality,
        CASE
            WHEN decision ILIKE '%accept%' THEN 'Accepted'
            WHEN decision ILIKE '%reject%' THEN 'Rejected'
            WHEN decision ILIKE '%wait%' THEN 'Waitlisted'
            WHEN decision ILIKE '%interview%' THEN 'Interview'
            ELSE 'Other'
        END AS decision,
        decision_date,
        -- GPA 范围校验
        CASE WHEN gpa > 0 AND gpa <= 4.0 THEN gpa ELSE NULL END AS gpa,
        CASE WHEN gre_q >= 130 AND gre_q <= 170 THEN gre_q ELSE NULL END AS gre_q,
        CASE WHEN gre_v >= 130 AND gre_v <= 170 THEN gre_v ELSE NULL END AS gre_v,
        CASE WHEN gre_aw >= 0 AND gre_aw <= 6.0 THEN gre_aw ELSE NULL END AS gre_aw,
        CASE WHEN toefl >= 0 AND toefl <= 120 THEN toefl ELSE NULL END AS toefl,
        comment,
        source_url,
        major_category,
        crawled_at
    FROM raw.gradcafe_admissions
    WHERE school IS NOT NULL
      AND school != ''
)
SELECT * FROM cleaned
