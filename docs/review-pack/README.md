# 顾问工作包 · 复核说明

> 版本：2026-06-12  
> 生成命令：`python3 scripts/build_review_pack.py`（幂等，可随时重跑）

---

## 三张表概览

| 文件 | 用途 | 预计工时 |
|------|------|----------|
| H1-专业映射复核表.csv | 复核现有 24 条专业映射规则 + 审阅 26 条扩展草案 | 1 人日 |
| H3-校名归一抽检表.csv | 确认模糊匹配 / 待归一校名的正确 cn_uni_id | 0.5 人日 |
| H7-反推线sanity表.csv | 对反推录取线结果做"像话/不像话/存疑"三档 sanity 签字 | 0.5 人日 |

---

## H1 — 专业映射复核表

**文件：** `H1-专业映射复核表.csv`

**列说明：**

| 列名 | 含义 |
|------|------|
| src_major_category | 学生本科专业大类（中文） |
| tgt_subject_group | 目标申请专业方向 |
| fit_level | 现有判断：对口 / 可转 / 不可转 |
| required_prereqs | 前置课程要求 |
| note | 备注说明 |
| reviewed | 是否已人工复核 |
| n_cases / offer_rate | 来自 int_uk_cases_tagged 的数据佐证（当前无案例数据则显示"暂无案例"） |
| **裁决** | **顾问填写：采用 / 修改 / 否决** |
| **修改值** | **如裁决为"修改"，填写修正后的 fit_level** |
| **备注** | **补充说明** |
| status | existing = 现有规则；draft = 扩展草案待确认 |

**操作方式：**
1. 对 `status=existing` 的 24 行：在"裁决"列填写 `采用` / `修改` / `否决`；如修改则在"修改值"列填写新 fit_level。
2. 对 `status=draft` 的 26 行：逐行判断是否纳入正式规则；填"采用"或"否决"。
3. 填写完毕后将 CSV 交回。

**回流路径：**
- 裁决结果 → 更新 `dbt_liuxue/seeds/dim_major_mapping.csv`，将对应行 `reviewed` 改为 `true`
- 执行 `dbt seed --select dim_major_mapping` 重跑种子表

---

## H3 — 校名归一抽检表

**文件：** `H3-校名归一抽检表.csv`

**列说明：**

| 列名 | 含义 |
|------|------|
| undergrad_school_raw | 案例原始校名 |
| suggested_cn_uni_id | 系统建议的标准化 ID |
| match_method | 匹配方式（exact / alias / fuzzy / NULL=未命中） |
| match_confidence | 匹配置信度 |
| reviewed | 是否已确认 |
| **裁决_确认cn_uni_id** | **顾问填写正确的 cn_uni_id（或确认建议值）** |
| **备注** | **补充说明** |

**操作方式：**
- 对 fuzzy 匹配行：确认 `suggested_cn_uni_id` 是否正确；错误则填写正确 ID
- H3 抽检请重点核对含"分校"字样的 fuzzy 命中行（珠海分校类历史独立办学风险）
- 对 NULL（未命中）行：手动查 `dim_cn_university` 并填写对应 cn_uni_id

**回流路径：**
- 确认的别名关系 → 追加到 `dbt_liuxue/seeds/cn_university_alias.csv`
- 格式：`alias,cn_uni_id`（UTF-8，逗号分隔）
- 追加后执行 `dbt seed --select cn_university_alias` + 重跑 `normalize_cases.py`

> **注：** 当前显示说明行，因 1p3a 案例数据尚未接入。数据到达后重跑 `python3 scripts/build_review_pack.py` 自动填充真实待归一校名。

---

## H7 — 反推线 sanity 表

**文件：** `H7-反推线sanity表.csv`

**列说明：**

| 列名 | 含义 |
|------|------|
| uk_uni_id / subject_group / cn_tier | 维度 key |
| line_low / line_high / line_iso50 | 反推录取线（均分百分制） |
| sample_n / offer_n / reject_n | 样本量 |
| confidence | 置信档位：low / medium / high |
| fallback_level | 回退层级（0=原始组，越大越模糊） |
| **sanity_像话** | **顾问打勾（Y）：线值在合理范围** |
| **sanity_不像话** | **顾问打勾（Y）：线值明显异常** |
| **sanity_存疑** | **顾问打勾（Y）：需进一步核实** |
| **审核备注** | **补充说明** |

**操作方式：**
- 逐行对反推线值做主观判断，三个勾选列选其一填 `Y`
- 重点关注：`confidence=low` 且 `fallback_level≥2` 的行（样本极少，最不可靠）

**回流路径（红线）：**

> **案例反推线在 H7 顾问 sanity 复核签字完成之前，不得出现在任何 web 端结果或 API 响应中。**  
> （出处：英联邦留学数据蓝图 methodology 承诺——"上线前不会出现在任何结果里"）

- H7 签字完成 → 告知研发团队解除 `stg_uk_entry_line_case.sql` 和 `mart/` 的注释门禁
- 具体路径：`dbt_liuxue/models/uk/staging/stg_uk_entry_line_case.sql` 顶部注释说明此门禁

> **注：** 当前显示说明行，因 1p3a 案例数据尚未接入，`raw.uk_entry_line_case` 为空。数据接入并运行 `./run-pipeline.sh case` 后，重跑 `python3 scripts/build_review_pack.py` 自动填充。

---

## 复跑命令

```bash
python3 scripts/build_review_pack.py
```

脚本幂等：每次运行覆盖输出目录下三个 CSV，不修改任何数据库内容。

---

## 整体回流时序

```
顾问填写 H1/H3/H7 CSV → 交回研发
  │
  ├─ H1 裁决 → dim_major_mapping.csv reviewed=true → dbt seed
  ├─ H3 确认 → cn_university_alias.csv 追加 → dbt seed + normalize_cases.py
  └─ H7 签字 → 解除 case 线 web 门禁 → mart/API 接入 → smoke 测试 → 上线
```
