SELECT
    uk_uni_id,
    profile_level,
    ielts_overall, ielts_l, ielts_r, ielts_w, ielts_s,
    subject_hint,
    source_url,
    verified_at,
    valid_until,
    (valid_until < CURRENT_DATE) AS is_stale
FROM {{ ref('uk_ielts_seed') }}
