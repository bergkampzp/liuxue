-- stg_uk_entry_line_case
-- **未接入 mart/API——H7 顾问复核未签不得进 web**
-- 薄封装：透传 raw.uk_entry_line_case 所有字段 + confidence 已含。
-- 此模型仅供顾问复核（H7 工作包），未经签核严禁接入任何查询接口或前端页面。

{{ config(materialized='view') }}

SELECT
    uk_uni_id,
    subject_group,
    cn_tier,
    line_low,
    line_high,
    line_iso50,
    sample_n,
    offer_n,
    reject_n,
    confidence,
    method,
    fallback_level,
    year_range,
    note
FROM {{ source('raw', 'uk_entry_line_case') }}
