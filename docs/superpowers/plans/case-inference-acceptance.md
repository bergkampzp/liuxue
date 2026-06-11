# 反推线管线 + 顾问工作包 验收记录

> 2026-06-12 | 分支 worktree-case-inference

## 门禁结果（全部通过）

| 门禁 | 结果 | 证据 |
|------|------|------|
| 全量测试零退 | ✅ | 99 passed（79 基线 + 12 归一 + 8 拟合） |
| fit_cell 夹具用例 | ✅ | 8/8（n<5拒出/无拒下界/等渗中样本/bootstrap大样本/权重生效/噪声不崩/回退降档/边界） |
| `./run-pipeline.sh case` 全链 | ✅ | migration→gter增量→归一→dbt→拟合→11 dbt 测试 PASS；产量如实输出（cases=3, 出线格=0=样本不足） |
| **case 线 web 隔离** | ✅ | /school-ladder 与 /position 实测 source_type 域 = {official_web, aggregator}，无 case_inferred |
| 顾问三表落档 | ✅ | H1 50 行（24 现行+26 草案）/ H3、H7 占位说明行 / README 回流路径 |

## 管线就绪状态

`归一(三级匹配,fuzzy闸92) → dbt(stg_uk_cases→int_uk_cases_tagged 行级) → fit_uk_entry_line.py(P10下界/等渗iso50/bootstrap CI/权重0.5/回退降档) → raw.uk_entry_line_case → stg_uk_entry_line_case(未接mart/API)`

**数据一到即跑**：管线对 0 行输入全程优雅（"样本不足，0 格出线"），对夹具数据产出正确统计量。

## 数据缺口（用户侧解锁项）

1. **1p3a Cloudflare cookie**（反推线唯一结构化数据源：列表页含本科校/GPA/雅思/结果）+ 英联邦版块 fid 核实——提供后：`python3 crawlers/sync_1point3acres.py --cookie '...' --fid <UK版块>` → `./run-pipeline.sh case` 即出线
2. **gter 登录 token**（深分页 401 实测，11.9 万条在墙内）——当前仅首页 20 条/次滴灌
3. 无 ANTHROPIC_API_KEY——LLM 打标/抽取走规则版，升级点已留 TODO

## 红线声明

**raw.uk_entry_line_case 的任何数据在顾问 H7 sanity 复核签字前，不得接入 mart_uk_school_match_v1 / entry_requirement / 任何 API 响应**（methodology 页对用户承诺"上线前不会出现在任何结果里"）。接入时必须同步把 smoke-web.sh 的 source_type 域断言更新为包含 case_inferred 并验证黄标话术。

## 顾问工作包（docs/review-pack/）

- H1-专业映射复核表.csv：50 行，预计 1 人日
- H3-校名归一抽检表.csv：待 1p3a 数据自动填充，预计 0.5 人日
- H7-反推线sanity表.csv：待出线格自动填充，预计 0.5 人日
- 复跑生成：`python3 scripts/build_review_pack.py`
