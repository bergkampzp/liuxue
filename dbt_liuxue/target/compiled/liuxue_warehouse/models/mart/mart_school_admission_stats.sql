-- 学校-专业录取统计（Mart层汇总，给API和Dashboard用）
SELECT
    f.school,
    f.program,
    f.degree,
    f.gpa_p25, f.gpa_p50, f.gpa_p75,
    f.acceptance_rate,
    f.competition_level,
    f.gpa_requirement_level,
    f.sample_size,
    c.competition_score,
    c.tier,
    g.gre_q_mean, g.gre_v_mean,
    g.gre_q_acceptance_delta,
    c.international_ratio
FROM "warehouse"."public"."feat_gpa_threshold" f
LEFT JOIN "warehouse"."public"."feat_competition_index" c
    ON f.school = c.school AND f.program = c.program AND f.degree = c.degree
LEFT JOIN "warehouse"."public"."feat_gre_impact" g
    ON f.school = g.school AND f.program = g.program AND f.degree = g.degree
WHERE f.sample_size >= 5
ORDER BY c.competition_score DESC NULLS LAST