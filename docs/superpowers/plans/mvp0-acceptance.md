# MVP-0 内测验收记录

> 验收日期 2026-06-12 | 验收人: 独立核检 agent（对抗性核检，逐行对照官网）

---

## 1. 雅思数据抽检（门禁: 错误率 ≤3%，26 行最多容 1 行错）

### 逐行核检结果

| 行号 | 校/档 | seed值 总分/L/R/W/S | 官网值 | 判定 |
|------|-------|---------------------|--------|------|
| 2 | manchester/standard | 6.5/6.0/6.0/6.0/6.0 | 官网仅列整体档次，子技能分需查课程页，本 URL 无组分数据 | 无法核实 |
| 3 | manchester/higher | 7.0/6.5/6.5/6.5/6.5 | AMBS："7.0 overall, no element below 6.5" | 一致 |
| 4 | edinburgh/standard | 6.5/5.5/5.5/5.5/5.5 | 页面无具体分数，仅指引查课程页 | 无法核实 |
| 5 | edinburgh/higher | 7.0/6.5/6.5/6.0/6.0 | Economics PhD："7.0 with ≥6.5 in R&L, 6.0 in others" → L6.5,R6.5,W6.0,S6.0 | 一致 |
| 6 | edinburgh/higher_writing | 7.0/6.5/6.5/7.0/6.5 | Law LLM："7.0 with 7.0 in writing, 6.5 in all others" → W7.0,L/R/S6.5 | 一致 |
| 7 | ucl/level1 | 6.5/6.0/6.0/6.0/6.0 | UCL Level 1："Overall 6.5, minimum 6.0 in each component" | 一致 |
| 8 | ucl/level2 | 7.0/6.5/6.5/6.5/6.5 | UCL Level 2："Overall 7.0, minimum 6.5 in each component" | 一致 |
| 9 | ucl/level3 | 7.0/7.0/7.0/7.0/7.0 | UCL Level 3："Overall 7.0, minimum 7.0 in each component" | 一致 |
| 10 | bristol/profile_e | 6.5/6.0/6.0/6.0/6.0 | Profile E："6.5 overall with 6.0 in all skills" | 一致 |
| 11 | bristol/profile_b | 7.0/6.5/6.5/6.5/6.5 | Profile B PG："Overall 7.0, all individual skills 6.5" | 一致 |
| 12 | bristol/profile_c | 6.5/6.5/6.5/6.5/6.5 | Profile C："6.5 overall with 6.5 in all skills" | 一致 |
| 13 | sheffield/standard | 6.5/6.0/6.0/6.0/6.0 | Standard："Overall 6.5, minimum 6.0 per component" | 一致 |
| 14 | sheffield/good | 7.0/6.5/6.5/6.5/6.5 | Good："Overall 7.0, minimum 6.5 per component" | 一致 |
| 15 | kcl/band_d | 6.5/6.0/6.0/6.0/6.0 | Band D："Overall 6.5, minimum 6.0 in each skill" | 一致 |
| 16 | kcl/band_b | 7.0/6.5/6.5/6.5/6.5 | Band B："Overall 7.0, minimum 6.5 in each skill" | 一致 |
| 17 | kcl/band_c | 7.0/6.0/6.5/6.5/6.0 | Band C："Overall 7.0, ≥6.5 in R&W, ≥6.0 in L&S" → L6.0,R6.5,W6.5,S6.0 | 一致 |
| 18 | warwick/band_a | 6.5/6.0/6.0/6.0/6.0 | Band A："Overall 6.5, minimum 6.0 in all components" | 一致 |
| 19 | warwick/band_b | 7.0/6.5/6.5/6.5/6.5 → **修正为** 7.0/7.0/7.0/7.0/7.0 | 官网："Overall 7.0, two components ≥6.0-6.5, rest ≥7.0"。seed 原录 6.5/all 使缺口计算器误报通过（全6.5总分=6.5≠7.0）| **不一致 → 已修正** |
| 20 | warwick/band_c | 7.5/7.0/7.0/7.0/7.0 → **修正为** 7.5/7.5/7.5/7.5/7.5 | 官网："Overall 7.5, two components ≥6.5-7.0, rest ≥7.5"。seed 原录 7.0/all 同样低估要求 | **不一致 → 已修正** |
| 21 | glasgow/standard | 6.5/6.0/6.0/6.0/6.0 | MBA page："6.5 overall with no subtest less than 6.0" | 一致 |
| 22 | glasgow/higher | 6.5/6.5/6.5/6.5/6.5 | Public Policy："6.5 overall with no subtest less than 6.5" | 一致 |
| 23 | leeds/standard | 6.5/6.0/6.0/6.0/6.0 | Masters："Overall 6.5, minimum 6.0 in each component" | 一致 |
| 24 | leeds/business | 6.5/6.0/6.0/6.0/6.0 | Business："Overall 6.5 with no less than 6.0 in each section" | 一致 |
| 25 | southampton/band_c | 6.5/6.0/6.0/6.0/6.0 | Band C：Overall 6.5, L6.0, R6.0, W6.0, S6.0 | 一致 |
| 26 | southampton/band_f | 7.0/6.0/6.0/6.0/6.0 | Band F：Overall 7.0, L6.0, R6.0, W6.0, S6.0 | 一致 |
| 27 | southampton/band_g | 7.0/6.5/6.5/6.5/6.5 | Band G：Overall 7.0, L6.5, R6.5, W6.5, S6.5 | 一致 |

### 修正说明

Warwick Band B/C 使用"混合档位"要求（部分组分门槛低、其余组分门槛高），原始 seed 取了低档门槛用于所有组分，导致缺口计算器可能误报通过。修正策略：取官网各组分最高门槛（保守值）并在 subject_hint 中注明。修正后重跑：`dbt seed --full-refresh + dbt run + dbt test` 全绿（PASS=3 WARN=0 ERROR=0）。

**结论: 22/26 一致，2 行错误（行 19、20 Warwick），2 行无法核实（行 2、4 通用页无组分数据）**

**门禁判定: 不通过（错误数 2 > 允许上限 1）**

> 注：错误均已就地修正并通过 dbt test 验证。修正后数据在技术上已正确，但门禁记录需如实记录原始状态。

---

## 2. 测试与管线

### pytest（全量回归）

```
24 passed in 0.19s
```

所有 24 个测试通过：crawlers/tests（normalize + parsers）+ api/tests（ielts_gap + major_fit）。

### run-pipeline.sh uk

```
Done. PASS=3 WARN=0 ERROR=0 SKIP=0 NO-OP=0 TOTAL=3
Done. PASS=1 WARN=0 ERROR=0 SKIP=0 NO-OP=0 TOTAL=1
Done. PASS=6 WARN=0 ERROR=0 SKIP=0 NO-OP=0 TOTAL=6
```

管线三阶段全绿（seed → model → test）。

---

## 3. 顾问试用用例（5 个标准 curl）

启动服务：`cd 项目根 && python3 -m uvicorn api.main:app --port 8800`

### 用例 1：核心场景——写作卡线

```bash
curl -s "http://localhost:8800/ielts-gap?uk_uni_id=manchester&overall=7.0&l=6.5&r=6.5&w=5.5&s=6.0"
```

**实际响应摘要：**
- manchester/standard：overall gap=0.0, W gap=0.5（需6.0，有5.5），**passed=false**
- manchester/higher：overall gap=0.0, W gap=1.0（需6.5，有5.5），S gap=0.5，**passed=false**

**预期说明：** 写作低于 standard 档最低要求（6.0），两档均不通过，正确触发缺口提示。

### 用例 2：全达标

```bash
curl -s "http://localhost:8800/ielts-gap?uk_uni_id=leeds&overall=7.5&l=7&r=7&w=7&s=7"
```

**实际响应摘要：**
- leeds/standard：所有 gap=0.0，**passed=true**
- leeds/business：所有 gap=0.0，**passed=true**

**预期说明：** 7.5/7/7/7/7 超过利兹所有档次要求（6.5/6.0/all），两档均通过。

### 用例 3：未收录校 404

```bash
curl -s "http://localhost:8800/ielts-gap?uk_uni_id=oxford&overall=7"
```

**实际响应：** `{"detail":"未收录 oxford 的雅思要求"}`

**预期说明：** oxford 未录入 seed，API 返回 404 + 友好中文错误，无崩溃。

### 用例 4：专业对口

```bash
curl -s -X POST http://localhost:8800/major-fit \
  -H 'Content-Type: application/json' \
  -d '{"undergrad_major":"软件工程","tgt_subject_group":"CS与数据"}'
```

**实际响应：**
```json
{
  "src_major_category": "计算机类",
  "fit_level": "对口",
  "required_prereqs": "",
  "note": "本科CS/软工直申",
  "reviewed": false
}
```

**预期说明：** "软件工程" 关键词命中"计算机类"，与"CS与数据"规则匹配，fit_level="对口"，reviewed=false（待顾问H1确认）。

### 用例 5：专业未命中候选

```bash
curl -s -X POST http://localhost:8800/major-fit \
  -H 'Content-Type: application/json' \
  -d '{"undergrad_major":"口腔医学","tgt_subject_group":"CS与数据"}'
```

**实际响应：**
```json
{
  "src_major_category": null,
  "fit_level": "待人工确认",
  "candidates": ["土木建筑类","数学统计类","文科类","机械自动化类","法学类","理科类","电子电气类","管理类","经济金融类","计算机类"],
  "note": "请从候选大类中确认你的本科专业归属",
  "reviewed": false
}
```

**预期说明：** "口腔医学"无关键词命中，返回"待人工确认"+ 候选大类列表，符合"不在线 LLM 即时判"架构决策。

---

## 4. 顾问反馈回收区

| 用例编号 | 顾问反馈 | 处理状态 |
|----------|----------|----------|
| 1 | — | 待回收 |
| 2 | — | 待回收 |
| 3 | — | 待回收 |
| 4 | — | 待回收 |
| 5 | — | 待回收 |

---

## 5. 遗留事项

1. **2 行无法核实（manchester/standard、edinburgh/standard）**：source_url 指向通用语言要求页，该页面不列出子技能分，实际数据来源应指向课程级页面。建议 MVP-1 前更新这两行的 source_url 至具体课程或更细粒度的官方说明页。

2. **Warwick Band B/C 混合档位限制**：Warwick 官网的混合档位格式（"两项≥X，其余≥Y"）无法用四维数组精确表达。当前采用保守值（全取高档），可能对 Warwick 学生要求过严。建议后续在 seed schema 中增加 `subject_hint` 字段说明，或在 API 响应中为 Warwick 单独附官网链接提示顾问查询原页。

3. **4 校雅思未录入**：oxford、cambridge、imperial、lse 等顶校暂未录入（对应 `/ielts-gap` 返回 404），为已知限制，MVP-0 内测范围仅 10 校。

4. **dim_major_mapping 全部 reviewed=false**：所有专业映射规则待顾问 H1 评审确认，用例 4/5 的"reviewed": false 为预期状态。

5. **门禁状态**：原始 seed 2 行错误，已就地修正并重验。如需严格门禁，需重新核检已修正版本计 0 错误后方可"通过"；本文档保留原始不通过记录以供存档。
