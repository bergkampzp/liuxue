# 反推线管线 + 顾问工作包 实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** 建成完整的案例反推管线（归一→dbt case 支线→等渗拟合→置信标注），用夹具 TDD 驱动；gter 规模化爬取（~1.5万行）；产出 H1/H3/H7 三份顾问工作包。**反推线未过顾问 H7 复核不得进 web**（methodology 页已承诺"上线前不会出现在任何结果里"）。

**环境事实（已探明，决定方案）:** 无 ANTHROPIC_API_KEY → 抽取/打标全走规则版，LLM 升级留接口注释；sklearn 1.8 在（IsotonicRegression 可用）；gter 总量 119,734 条但 message 是短评论、本科/均分登录可见 → **gter 不喂反推线**，只补 con-offer/热度；反推唯一数据源 = 1p3a 列表页结构化字段（已支持解析，待用户提供 Cloudflare cookie + 英联邦版块 fid）。

**统计方法（蓝图已定，照实现）:** 按 (uk_uni_id × subject_group × cn_tier) 分组；n<5 不出线；无拒信只给下界 P10+low；8≤n<30 等渗 P(录取)=0.5 + P10-P25 区间 + medium；n≥30 P15+bootstrap CI+high；score_scale_inferred 样本权重 0.5；四级回退每级降一档 confidence。

---

### R-T1: gter 规模化爬取（后台，先启动）
- [ ] `cd crawlers && nohup python3 sync_gter.py --max-pages 750 > /tmp/gter_crawl.log 2>&1 &`（~15k 行，1s 间隔约 20 分钟；增量去重已内建）
- [ ] 期间继续后续任务；收尾时 `SELECT count(*),count(*) FILTER (WHERE decision_detail IS NOT NULL) FROM raw.liuxue_admissions WHERE source='gter'` 记录产量
- [ ] 无单独 commit（数据入库不入 git）

### R-T2: 校名归一管线（TDD）
**Files:** Create `scripts/normalize_cases.py`、`scripts/tests/test_normalize_cases.py`、`migrations/003_case_pipeline.sql`
- [ ] 003 迁移（幂等）：`raw.case_school_map(undergrad_school_raw TEXT PK, cn_uni_id TEXT, method TEXT, confidence NUMERIC, reviewed BOOL DEFAULT false, created_at)` + `raw.uk_entry_line_case(uk_uni_id,subject_group,cn_tier,line_low,line_high,line_iso50,sample_n,offer_n,reject_n,confidence,method,fallback_level,year_range,note, UNIQUE(uk_uni_id,subject_group,cn_tier))`
- [ ] normalize_cases.py：读 `SELECT DISTINCT undergrad_school FROM raw.liuxue_admissions WHERE undergrad_school IS NOT NULL` → 三级匹配（dim 中英文精确 → alias 精确 → rapidfuzz≥92 高闸）→ UPSERT case_school_map(method=exact/alias/fuzzy, confidence=1.0/1.0/0.92)；未命中行写 map 表 cn_uni_id=NULL（=待人工）；`--export-review PATH` 导出未归一+fuzzy 行 CSV（H3 工作包原料）。**fuzzy 闸 92 比 API 的 85 更严**——归一错误会污染 tier 进而污染线（蓝图教训）
- [ ] TDD：精确/别名/模糊命中/不命中四用例（monkeypatch fetch_all 风格或 sqlite 内存——选 monkeypatch 与 api 测试同风格）
- [ ] Commit "feat: 案例校名归一管线 — 三级匹配+92高闸+复核导出"

### R-T3: dbt case 支线
**Files:** Create `dbt_liuxue/models/uk/staging/stg_uk_cases.sql`、`dbt_liuxue/models/uk/intermediate/int_uk_cases_tagged.sql`；Modify `_sources.yml`（补 case_school_map/uk_entry_line_case）、`_uk_models.yml`（测试）
- [ ] stg_uk_cases（view）：raw.liuxue_admissions 中 school 命中 dim_uk_university（name_zh/name_en 清洗后精确，复用 stg_uk_official_lists 的清洗思路）的行；avg_score_pct 归一（<=4.5 视为 4 分制×25 打 score_scale_inferred 标记 / 40-100 直用 / 其余 NULL）；带 decision/decision_detail/ielts/undergrad_school/year/source
- [ ] int_uk_cases_tagged（table）：join case_school_map(仅 cn_uni_id 非空) → dim_cn_university.tier_label；subject_group 用 SQL CASE 关键词规则（与 api MAJOR_KEYWORDS 同口径的大类映射，LLM 打标留 TODO 注释）；行级保留（拟合脚本要读）
- [ ] 测试：accepted_values(tier/decision)、avg_score_pct 40-100 or null、not_null 关键列
- [ ] Commit "feat: dbt case支线 — stg_uk_cases+int_uk_cases_tagged(行级)"

### R-T4: 等渗拟合脚本（核心，TDD 夹具驱动）
**Files:** Create `scripts/fit_uk_entry_line.py`、`scripts/tests/test_fit_entry_line.py`、`dbt_liuxue/models/uk/staging/stg_uk_entry_line_case.sql`
- [ ] 纯函数核心 `fit_cell(scores_offer, scores_reject, weights) -> dict|None`：实现统计方法（顶部规格）；`fit_all(rows) -> list[dict]` 分组+四级回退（年份放宽→相邻大类→tier 合并双非→放弃,每级 fallback_level+1 且 confidence 降档）；main() 读 int_uk_cases_tagged → TRUNCATE+写 raw.uk_entry_line_case
- [ ] TDD 夹具用例（不依赖 DB）：n<5→None；全 offer 无拒→只有 line_low(P10)+low+note 含"或高估"；n=12 有拒→iso50 在 offer/reject 分界邻域+区间+medium；n≥30→P15+CI+high；inferred 权重 0.5 生效（构造对照样本断言加权分位差异）；单调性（iso 翻转样本不崩）
- [ ] stg_uk_entry_line_case.sql：薄封装 + is_stale 字段；dbt 测试 line 值域 60-95、confidence accepted_values
- [ ] **不接入 mart/API**（门禁：H7 未签不进 web），SQL 顶部注释写明
- [ ] Commit "feat: 等渗反推拟合 — fit_cell纯函数+四级回退+置信标注(未接web)"

### R-T5: 管线编排
**Files:** Modify `run-pipeline.sh`
- [ ] 加 `case` 子命令：psql 003 迁移 → sync_gter 增量(--max-pages 50) → normalize_cases.py → dbt run --select stg_uk_cases int_uk_cases_tagged → fit_uk_entry_line.py → dbt run --select stg_uk_entry_line_case → dbt test --select models/uk → 产量统计（cases 行数/归一率/出线格子数 by confidence）
- [ ] 跑通全链（当前数据量小，出线可能 0 格——如实输出"样本不足"）
- [ ] Commit "feat: run-pipeline.sh case子命令 — 反推线全链编排"

### R-T6: 顾问工作包（H1/H3/H7）
**Files:** Create `docs/review-pack/README.md`、`H1-专业映射复核表.csv`、`H3-校名归一抽检表.csv`、`H7-反推线sanity表.csv`（生成脚本 `scripts/build_review_pack.py`）
- [ ] H1：dim_major_mapping 24 行导出 + 每行附数据佐证列（int_uk_cases_tagged 中该 (src大类×tgt大类) 的 n_cases/offer_rate，无数据填"暂无案例"）+ 空白裁决列(采用/修改/否决+修改值) + 追加 ~26 行扩展草案（高频组合规则建议,标 draft）
- [ ] H3：normalize_cases --export-review 的输出（未归一 top 频次 + fuzzy 命中待确认行,带建议 cn_uni_id）+ 回流说明（确认行进 seeds/cn_university_alias.csv）
- [ ] H7：uk_entry_line_case 全量导出（空则表头+说明"待 1p3a 数据"）+ "像不像话"勾选列
- [ ] README：三表用途/预计工时(H1≈1人日 H3≈0.5 H7≈0.5)/回流操作/红线（H7 未签 case 线不上 web）
- [ ] Commit "docs: 顾问工作包 — H1复核/H3抽检/H7 sanity 三表+回流说明"

### R-T7: 验收
- [ ] 全量 pytest（79+新增）零退；`./run-pipeline.sh case` 全链绿；gter 产量记录
- [ ] 验收文档 `docs/superpowers/plans/case-inference-acceptance.md`：管线就绪状态、数据缺口（1p3a cookie+fid 待用户）、门禁声明
- [ ] Commit "docs: 反推线管线验收 — 就绪待数据"

**发布门禁：** 全量测试零退；fit_cell 六夹具用例全过；管线全链可跑（数据不足时如实输出而非报错）；case 线确认未出现在 /position /school-ladder 任何响应（smoke 断言 source_type 域不含 case_inferred）；三份顾问表落档。
