# 双一流档 Mart 回退参照211线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 当 mart_uk_school_match_v1 中某 (uk_uni_id, subject_group) 没有双一流真实行但有211行时，自动派生一条双一流回退行（source_type=aggregator, confidence=low），使双一流院校选校结果从 1-2 所增加到 ≥6 所，且北极星 sheffield×江苏大学=75 不变。

**Architecture:** 在 mart_uk_school_match_v1.sql 的 tier_lines CTE 之后新增 fallback CTE，从211行派生双一流行，用 NOT EXISTS 防止与真实双一流行重复，最后 UNION ALL 两者输出。API 层无需改动（aggregator+low 已触发黄标话术）。

**Tech Stack:** PostgreSQL / dbt (Jinja SQL)、FastAPI（只验证不改动）、pytest

---

## 文件结构

| 文件 | 动作 |
|---|---|
| `dbt_liuxue/models/uk/mart/mart_uk_school_match_v1.sql` | **Modify** — 在 SELECT 前插入 fallback CTE，改写最终 SELECT |
| `dbt_liuxue/tests/assert_mart_no_dup_grain.sql` | 只读验证（不改） |
| `api/main.py` | 只读验证（不改） |

---

### Task 1: 读懂现状，确认北极星基线

**Files:**
- Read: `dbt_liuxue/models/uk/mart/mart_uk_school_match_v1.sql`
- Read: `dbt_liuxue/seeds/testdaily_lines_seed.csv`

- [ ] **Step 1: 确认 entry_requirement 种子中211行存在**

```bash
grep "211" /home/zp/work/guoji-agent/dbt_liuxue/seeds/testdaily_lines_seed.csv
```

Expected: 看到多行 oxford/cambridge/imperial/lse/manchester/glasgow 的 cn_tier=211 行。

- [ ] **Step 2: 确认当前双一流校结果稀少**

```bash
curl -s -X POST http://localhost:8000/position \
  -H 'Content-Type: application/json' \
  -d '{"undergrad_school":"宁波大学","avg_score":82,"undergrad_major":"软件工程","tgt_subject_group":"通用"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('双一流结果:', len(d['schools']), '所')"
```

Expected: 1-2 所（问题复现）。

- [ ] **Step 3: 确认北极星基线**

```bash
curl -s -X POST http://localhost:8000/position \
  -H 'Content-Type: application/json' \
  -d '{"undergrad_school":"江苏大学","avg_score":82,"undergrad_major":"软件工程","tgt_subject_group":"通用"}' \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
sh = [r for r in d['schools'] if r['uk_uni_id'] == 'sheffield'][0]
print('sheffield min_avg_score =', sh['min_avg_score'])
assert sh['min_avg_score'] == 75.0, f'北极星偏移! {sh}'
print('北极星基线 OK')
"
```

Expected: `sheffield min_avg_score = 75.0` / `北极星基线 OK`

---

### Task 2: 修改 mart_uk_school_match_v1.sql，加入双一流 fallback CTE

**Files:**
- Modify: `dbt_liuxue/models/uk/mart/mart_uk_school_match_v1.sql`

**改动逻辑：**
- `tier_lines` 按 (uk_uni_id, subject_group, cn_tier) 聚合，结构不变。
- 新增 `fallback_shuangyiliu` CTE：从 tier_lines 中取 cn_tier='211' 的行，派生 cn_tier='双一流'，仅当同 (uk_uni_id, subject_group) 没有真实双一流行时插入（NOT EXISTS 防重）。
- 最终 SELECT 从 `tier_lines` 改为 `tier_lines UNION ALL fallback_shuangyiliu`，对应 CTE 命名为 `all_lines`。

- [ ] **Step 1: 写新版 SQL**

将 `/home/zp/work/guoji-agent/dbt_liuxue/models/uk/mart/mart_uk_school_match_v1.sql` 改为：

```sql
-- mart_uk_school_match_v1: 每行 = (英国校 × subject_group × cn_tier) 聚合线 + 基线雅思
--
-- tier 级聚合规则：
--   同 (uk_uni_id, subject_group, cn_tier) 取 MAX(min_avg_score)，保守上限（宁严勿松）
--   官方行存在则 source_type='official_web' / confidence='high'
--   每校雅思取 ielts_overall 最高档作为保守基线（宁严勿松）
--
-- 双一流回退规则（2026-06-12）：
--   若某 (uk_uni_id, subject_group) 无真实双一流行但有211行，
--   则派生一条双一流回退行，取211线的 min_avg_score，
--   source_type='aggregator', confidence='low'（黄标参考，不冒充官方）

WITH tier_lines AS (
    SELECT
        uk_uni_id,
        subject_group,
        cn_tier,
        MAX(min_avg_score) AS min_avg_score,                          -- 保守上限
        COUNT(DISTINCT cn_uni_id) AS n_schools_in_band,
        -- 官方行存在时取官方 source_type（字典序 official_pdf < official_web 均 < aggregator 不适用，用 CASE 判断）
        MAX(CASE WHEN source_type LIKE 'official%' THEN source_type ELSE NULL END) AS official_source,
        MIN(source_type) AS any_source,
        MIN(source_url)  AS source_url,
        MIN(confidence)  AS confidence_raw                            -- high < low < medium 字典序；官方行另外覆盖
    FROM {{ ref('entry_requirement') }}
    WHERE cn_tier IS NOT NULL
    GROUP BY 1, 2, 3
),
-- 双一流回退：当 (uk_uni_id, subject_group) 有211行但无双一流行时，派生双一流行
fallback_shuangyiliu AS (
    SELECT
        tl.uk_uni_id,
        tl.subject_group,
        '双一流'                AS cn_tier,
        tl.min_avg_score,                                             -- 沿用211线（宁严勿松）
        tl.n_schools_in_band,
        NULL::text              AS official_source,
        'aggregator'            AS any_source,
        tl.source_url,
        'low'                   AS confidence_raw
    FROM tier_lines tl
    WHERE tl.cn_tier = '211'
      AND NOT EXISTS (
          SELECT 1
          FROM tier_lines ex
          WHERE ex.uk_uni_id    = tl.uk_uni_id
            AND ex.subject_group = tl.subject_group
            AND ex.cn_tier      = '双一流'
      )
),
all_lines AS (
    SELECT * FROM tier_lines
    UNION ALL
    SELECT * FROM fallback_shuangyiliu
),
baseline_ielts AS (
    SELECT DISTINCT ON (uk_uni_id)
        uk_uni_id,
        profile_level,
        ielts_overall,
        ielts_l,
        ielts_r,
        ielts_w,
        ielts_s,
        source_url AS ielts_source_url
    FROM {{ ref('stg_uk_ielts_requirements') }}
    ORDER BY uk_uni_id, ielts_overall DESC                            -- 取该校最高雅思档作保守基线
)
SELECT
    t.uk_uni_id,
    u.name_zh,
    u.qs_rank,
    t.subject_group,
    t.cn_tier,
    t.min_avg_score,
    COALESCE(t.official_source, t.any_source)                 AS source_type,
    t.source_url,
    CASE
        WHEN t.official_source IS NOT NULL THEN 'high'
        ELSE t.confidence_raw
    END                                                       AS confidence,
    t.n_schools_in_band,
    b.profile_level                                           AS ielts_profile,
    b.ielts_overall,
    b.ielts_l,
    b.ielts_r,
    b.ielts_w,
    b.ielts_s,
    b.ielts_source_url
FROM all_lines t
JOIN {{ ref('dim_uk_university') }} u USING (uk_uni_id)
LEFT JOIN baseline_ielts b USING (uk_uni_id)
```

- [ ] **Step 2: 运行 dbt 重建 mart**

```bash
cd /home/zp/work/guoji-agent/dbt_liuxue && \
  /home/zp/anaconda3/bin/dbt run --select mart_uk_school_match_v1
```

Expected: `Completed successfully` / `1 of 1 OK`。若报错需检查 SQL 语法。

---

### Task 3: 运行 dbt 测试验证唯一粒度不破

**Files:**
- Test: `dbt_liuxue/tests/assert_mart_no_dup_grain.sql`

- [ ] **Step 1: 运行 uk 模型测试集**

```bash
cd /home/zp/work/guoji-agent/dbt_liuxue && \
  /home/zp/anaconda3/bin/dbt test --select models/uk
```

Expected: 所有 test PASS，包括 `assert_mart_no_dup_grain`（返回0行，即无重复粒度）。

若 `assert_mart_no_dup_grain` 失败，说明 fallback 产生了重复——需检查 NOT EXISTS 条件中 `subject_group` 是否完整匹配。

---

### Task 4: 验证双一流校结果 ≥6 所 + 回退行标注正确

- [ ] **Step 1: 测试三所双一流校**

```bash
for s in 宁波大学 河南大学 南方科技大学; do
  curl -s -X POST http://localhost:8000/position \
    -H 'Content-Type: application/json' \
    -d "{\"undergrad_school\":\"$s\",\"avg_score\":82,\"undergrad_major\":\"软件工程\",\"tgt_subject_group\":\"通用\"}" \
    | python3 -c "
import json,sys
d=json.load(sys.stdin)
schools=d['schools']
src_types=[r['source_type'][:4] for r in schools[:3]]
confidences=[r['confidence'] for r in schools[:3]]
print('$s', d['identity']['tier_label'], len(schools),'所线', src_types, confidences)
assert len(schools) >= 6, f'双一流校只有{len(schools)}所线，期望>=6'
assert all(r['source_type'] == 'aggregator' for r in schools if r['confidence'] == 'low'), '回退行source_type错误'
print('OK')
"
done
```

Expected: 每所学校 `≥6 所线`，source_type 显示 `aggr`（aggregator 前4字），confidence=low。

- [ ] **Step 2: 验证北极星不变**

```bash
curl -s -X POST http://localhost:8000/position \
  -H 'Content-Type: application/json' \
  -d '{"undergrad_school":"江苏大学","avg_score":82,"undergrad_major":"软件工程","tgt_subject_group":"通用"}' \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
sh=[r for r in d['schools'] if r['uk_uni_id']=='sheffield'][0]
assert sh['min_avg_score']==75.0, sh
print('北极星OK sheffield=75')
"
```

Expected: `北极星OK sheffield=75`

- [ ] **Step 3: 验证回退行话术含"参考线"**

```bash
curl -s -X POST http://localhost:8000/position \
  -H 'Content-Type: application/json' \
  -d '{"undergrad_school":"宁波大学","avg_score":82,"undergrad_major":"软件工程","tgt_subject_group":"通用"}' \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
for r in d['schools'][:3]:
    exp=r['explanation']
    assert '参考线' in exp or '第三方' in exp, f'话术缺少参考提示: {exp}'
    print(r['uk_uni_id'], r['confidence'], exp[:60])
print('话术OK')
"
```

Expected: 每条 explanation 含"第三方整理参考线"或"参考线"。

---

### Task 5: 全量回归测试

- [ ] **Step 1: 运行 pytest**

```bash
cd /home/zp/work/guoji-agent && \
  python3 -m pytest scripts/tests crawlers/tests api/tests -q
```

Expected: 105 tests passed（不退步）。若有失败需排查。

---

### Task 6: 重启 web 服务

- [ ] **Step 1: 重启 uvicorn**

```bash
pkill uvicorn 2>/dev/null || true
sleep 1
cd /home/zp/work/guoji-agent && nohup bash serve.sh > /tmp/serve.log 2>&1 &
sleep 3
curl -s http://localhost:8000/health | python3 -c "import json,sys; print(json.load(sys.stdin))"
```

Expected: `{"status":"ok"}` 或类似健康检查响应。

---

### Task 7: 提交

- [ ] **Step 1: 核查 diff**

```bash
git -C /home/zp/work/guoji-agent diff dbt_liuxue/models/uk/mart/mart_uk_school_match_v1.sql
```

Expected: 只看到 fallback_shuangyiliu CTE + `all_lines` CTE + FROM 改为 `all_lines t`，无其余意外变更。

- [ ] **Step 2: 提交**

```bash
git -C /home/zp/work/guoji-agent add dbt_liuxue/models/uk/mart/mart_uk_school_match_v1.sql
git -C /home/zp/work/guoji-agent commit -m "$(cat <<'EOF'
fix: 双一流档mart回退参照211线 — 补34所双一流校选校(标low/aggregator不冒充官方)

- mart_uk_school_match_v1 新增 fallback_shuangyiliu CTE
- 当 (uk_uni_id, subject_group) 有211行但无双一流行时派生双一流回退行
- source_type=aggregator / confidence=low 触发黄标话术，不冒充官方
- NOT EXISTS 防重，assert_mart_no_dup_grain 仍通过
- 北极星：sheffield×江苏大学(211) min_avg_score=75 不变

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

Expected: 输出 `[main <sha>] fix: 双一流档mart回退参照211线 ...`

---

## 验收标准汇总

| 验收项 | 目标值 |
|---|---|
| 双一流校线数（宁波大学/河南大学/南方科技大学） | ≥6 所各 |
| 回退行 source_type | aggregator |
| 回退行 confidence | low |
| 回退行 explanation | 含"第三方整理参考线" |
| 北极星 sheffield×江苏大学 | min_avg_score=75.0 不变 |
| assert_mart_no_dup_grain | PASS（0行） |
| pytest | ≥105 tests passed |

---

## Self-Review

**Spec coverage:**
- [x] fallback CTE 仅在无双一流真实行时生成（NOT EXISTS）
- [x] source_type=aggregator（不冒充官方），confidence=low
- [x] 唯一粒度约束通过（NOT EXISTS 保证无重复）
- [x] 北极星测试作为验收步骤明确列出
- [x] API 话术无需改动（aggregator+low 已触发"第三方整理参考线"黄标）

**Placeholder scan:** 无 TBD/TODO/placeholder，所有步骤含完整命令和期望输出。

**Type consistency:** `tier_lines` CTE 列名与 `fallback_shuangyiliu` 完全一致（9列），`all_lines` UNION ALL 无列数不匹配风险。
