# 选校罗盘 Web 服务实施计划（MVP-2 对外体验版）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 三页响应式 Web（index/school/methodology）+ GET /school-ladder 后端 + 静态托管，体现四态徽章话术红线与三个秀肌肉点。

**Architecture:** FastAPI 单进程（现有 api/main.py 追加端点 + 文末 StaticFiles 挂载 web/）。前端手写 CSS（弃 Tailwind CDN——大陆网络风险+无构建链约束）+ 原生 JS ES module。设计：B 活力渐变 × read.cv 极简（680px 窄列，渐变只用于 logo/hero 强调词/CTA/官方徽章），唯一断点 640px。

**Tech Stack:** FastAPI/StaticFiles + 手写 CSS + 原生 JS + pytest（基线 72 passed）

**设计依据:** docs/superpowers/specs/2026-06-12-xuanxiao-luopan-web-design.md + 三角色规格（前端令牌/架构契约/测试矩阵，要点已合并入本计划）

---

## 0. 钉死的契约（三角色冲突已裁决，实现照此，不再议）

**GET /school-ladder?school=<校名> → 200:**
```jsonc
{
  "cn_university": {"cn_uni_id","name_zh","tier_label"},     // resolve_cn_university 原样
  "schools": [          // 恒 30 行（dim_uk_university 全集），qs_rank 升序 null 殿后
    {"uk_uni_id","name_zh","qs_rank",
     "list_status",     // ∈ {"名单内(<band>)","个案审核","不在认可名单","有分数线","未收录"}
     "band_min_score",  // float|null 谢菲逐校线(arwu档的stg.min_avg_score)，仅谢菲tier档非null
     "min_avg_score",   // float|null 一律取 mart tier 线（北极星: 江苏大学×sheffield=75.0）
     "source_type",     // mart行透传; stg名单命中行="official_web"; 未收录=null
     "source_url",      // 名单出处优先(stg)，无则mart，无则null
     "ielts_overall"}], // mart 命中时透传，否则 null
  "disclaimer": "分数线为入学门槛参考，不构成录取承诺；名单与分数以校方当年官网为准"
}
```
**list_status 状态机**（synth_row 纯函数，不查库）：
- sheffield 有 stg 行：band∈arwu-tier1..4 → `名单内(<band>)` + band_min_score=stg.min_avg_score；band∈{see-additional,gpa-scale} → `个案审核`（band_min_score=null，绝不硬出数）
- ucl/bristol/edinburgh（LIST_GATED_SCHOOLS 复用）：有 stg 行 → `名单内(<band>)`（min_avg_score 取 mart 若有，source_url 取 stg 名单出处优先）；无 → `不在认可名单`
- 其余校：mart 按 (uk_uni_id, tier, '通用') 命中 → `有分数线`；不命中 → `未收录`（不许跨 tier 借线）
- 422（校名未识别）：detail = {msg, hint, candidates}（candidates 用新 helper suggest_cn_universities，fuzz≥60 取 3）

**查询防 N+1**：固定 3 查询 + Python 合成——`query_uk_universities()`(30行) / `query_official_list_rows(cn_uni_id)`(新,≤4行) / `query_match_rows(tier,'通用')`(复用)。

**全局口径**：页面总条数 = `SELECT count(*) FROM stg_uk_official_lists`（当前 **3,453**，设计文档 3433 已过期禁用）；免责锚串三页统一含 **"不构成录取承诺"**；页脚全文"录取结果由学校最终决定，本平台数据用于规划参考，不构成录取承诺 · 数据更新于 2026-06"。

**前端徽章映射**：official_web/official_pdf→`.badge-official`(渐变蓝) / aggregator,case_inferred→`.badge-ref`(黄,行文案必含"建议核对官网") / 不在认可名单→`.badge-notlist`(红) / 未收录·个案审核·名单内但无线→`.badge-pending`(灰"案例积累中"+waitlist)。emoji：冲🚀 匹🎯 保✅ 不建议⚠️ 不在名单⛔ 积累中⏳。
**PENDING_SCHOOLS 前端常量**：manchester/kcl（/position 不返回的校固定追加灰行+waitlist 微表单）。
**index 输入四格**：校名/均分/方向(下拉:通用,CS与数据,商科金融,工科,社科)/雅思选填；/position 的 undergrad_major 复用方向值（产品取舍，不加第五格）。前端校验：均分40-100、雅思0-9且0.5步进、校名≥2字符。

---

### Task 1: /school-ladder 后端（TDD 6 用例）

**Files:** Modify `api/main.py`；Create `api/tests/test_school_ladder.py`

- [ ] Step 1 写 6 个失败测试（monkeypatch resolve_cn_university / query_match_rows / query_official_list_rows / query_uk_universities，FAKE 数据按测试矩阵：FAKE_TIER 江苏大学双非；FAKE_MART 含 manchester(aggregator,82,qs35)/ucl(official,90,qs9)/sheffield(official,75,qs92)；FAKE_LIST_ROWS 含 sheffield arwu-tier1/70 与 bristol accepted/null）：
  1. test_ladder_panorama_normal — 200；schools 含 patched 宇宙全部行；sheffield 行 min=75/band_min=70/"arwu-tier1" in list_status/official_web；bristol `名单内(accepted)` 且 min null；qs 升序；aggregator 行 source_url 非空
  2. test_ladder_unknown_school_422 — 422 + detail 含"未识别"+candidates
  3. test_ladder_gated_school_not_on_list — ucl 无 stg 行 → 行仍在(全景不剔除,区别/position)、list_status="不在认可名单"
  4. test_ladder_sheffield_see_additional — band=see-additional → "个案审核"、band_min_score null、mart 线 75 仍在
  5. test_ladder_unlisted_uk_school — manchester `有分数线`且≠"不在认可名单"(非门控不误红)
  6. test_ladder_gated_set_unchanged — LIST_GATED_SCHOOLS=={"ucl","bristol","edinburgh"}
- [ ] Step 2 跑确认 FAIL → Step 3 实现：suggest_cn_universities + query_official_list_rows + query_uk_universities + synth_row(纯函数) + 端点（4-5 次 DB 往返）→ Step 4 `python3 -m pytest api/tests/ -v` 15 passed（9+6）
- [ ] Step 5 真实 DB 冒烟：江苏大学 → sheffield min=75/band_min=70、ucl/edinburgh 红、bristol 名单内；霍格沃茨 422
- [ ] Step 6 Commit "feat: /school-ladder全景端点 — 30校状态机+双线并存契约"

### Task 2: StaticFiles 挂载 + serve.sh

**Files:** Modify `api/main.py`（文末）；Create `serve.sh`、`web/index.html`（临时占位一行"选校罗盘"）

- [ ] mount 写法（必须在所有路由之后）：`app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent/"web", html=True), name="web")`
- [ ] serve.sh（chmod +x）：`exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --app-dir <repo根>`，日志 >> logs/web.log
- [ ] 冒烟：`/` 200 含"选校罗盘"；**四旧端点 + /school-ladder 各打一发不被吞**（挂载顺序最易翻车点）
- [ ] Commit "feat: 静态托管+serve.sh — API路由优先,mount殿后"

### Task 3: web/static/style.css（设计令牌+组件+断点）

**Files:** Create `web/static/style.css`（~320 行）

- [ ] :root 令牌（前端规格全表）：--grad-brand(135deg)/--grad-text(90deg三色)/--grad-cta(双色)/--grad-badge(2563eb→7c3aed)/--grad-panel；色阶 --ink #18181b/--ink-2/--gray #71717a/--muted #a1a1aa/--faint #d4d4d8/--violet；边框 --line/--line-soft/--line-tint；徽章三组底色；圆角 4/10/12/14；字号 34/15/14/13/12/11.5/11/10；--container 680px/--pad-x 24px；--font -apple-system,'PingFang SC'
- [ ] 组件：.nav(+logo色块)/.badge×4态/.result-row(+.is-dim)/.input-group(.field flex 1.4/.7/.9/.7 + .invalid)/.btn-cta(:disabled)/.card+.card-grid/.verify-panel系/.footer/.toast/.grad-text/.ladder 6列网格
- [ ] @media(max-width:640px)：nav 链接隐藏只留CTA、hero 34→26px、input-group 纵向堆叠全宽、verify-row 纵向、card-grid 纵向、.ladder 表头隐藏+行变 2 列卡片(伪元素 data-label 打标签)
- [ ] 验证：`python3 -c` 无法验 CSS——用 Task 4 页面渲染验证；本任务 commit "feat: 设计令牌与组件样式"

### Task 4: index.html + app.js

**Files:** Create `web/index.html`、`web/static/app.js`（ES module，~260 行）

- [ ] index 七段（mockup 序）：nav → hero(34px+grad-text"每个数字都有出处。"+副文含 3,453/不收钱不返佣) → #locate 四格输入+hint → verify-panel(江苏大学→谢菲 2:1 需 75%+官网链接写死+2,891 文案) → #results(静态示例 4 行：谢菲🎯官方/利兹🚀参考黄"建议核对官网"/UCL⛔红/曼大⏳灰+留邮箱) → 双卡入口(方法论/院校查询) → footer(含"不构成录取承诺")+#toast
- [ ] app.js 模块：api()封装(10s AbortController；422→{kind:unrecognized,msg,hint}；其他→unavailable) / toast() / validatePosition(40-100、雅思0.5步进) / renderPosition(TIER_ORDER 分桶+not_on_list ⛔+PENDING_SCHOOLS ⏳+major_fit 顶部条+esc()防XSS+scrollIntoView) / bindWaitlist(行内展开 email+POST /waitlist) / 入口按表单 id 绑定
- [ ] 冒烟：起服务 curl / 200 + grep "每个数字都有出处"/"不构成录取承诺"/"案例积累中"/"谢菲"；浏览器手动提交北极星看渲染
- [ ] Commit "feat: 首页定位 — 七段结构+四态渲染+waitlist钩子"

### Task 5: school.html + renderLadder

**Files:** Create `web/school.html`；Modify `web/static/app.js`

- [ ] 页面：nav(院校查询 active) → 缩小 hero("你的学校，在每所英国大学什么待遇") → 两元素输入条 → #ladder-result → footer
- [ ] renderLadder：.ladder 网格（桌面 6 列/移动卡片化）；字段规则——名单内(band)→蓝标、有分数线按 source_type 蓝/黄、不在认可名单→红+线"—"+.is-dim、未收录/个案审核→灰；min null→"—"；非官方线后缀"（参考）"；band_min_score 非空时谢菲行加注"你校逐校档线 70"
- [ ] 冒烟：curl 200 + grep "名单状态"/"出处"/"不构成录取承诺"；浏览器输入江苏大学看 30 行全景
- [ ] Commit "feat: 院校查询页 — 全景表(桌面网格/移动卡片)"

### Task 6: methodology.html（纯静态，不引 app.js）

**Files:** Create `web/methodology.html`

- [ ] 七段：nav(我们的数据 active) → hero(+grad-text"全部可验证。"+"不收你一分钱，也不接学校返佣") → 数据来源四条目（UCL 84/Bristol 303/爱丁堡 175(Band 分档)/谢菲 **2,891** 逐校分档"随时抽查我们"，每条官方链接写死真实 URL，合计 **3,453**） → 徽章含义四态(用真实 .badge 组件,所见即所得——本页即四态截图基准页) → 反推方法论预告卡(三维分层/防幸存者偏差/P10/"上线前不会出现在任何结果里") → 免责与边界 → footer
- [ ] 冒烟：grep "2,891"/"建议核对官网"/"sheffield.ac.uk"/"ucl.ac.uk"/"不构成录取承诺"/无"3433"
- [ ] Commit "feat: 方法论页 — 数据来源+徽章含义+免责"

### Task 7: 冒烟脚本 + 发布门禁 + 验收文档

**Files:** Create `scripts/smoke-web.sh`；Create `docs/superpowers/plans/web-luopan-acceptance.md`

- [ ] smoke-web.sh（测试矩阵全文落盘）：5 路径 200；三页文案 grep（含三页"不构成录取承诺"）；methodology 总条数与 DB count 动态比对+禁 3433；/school-ladder 北极星双断言（sheffield 75/official+band_min 70、ucl/edinburgh 红、bristol 名单内前缀）；422；/position 北极星不变；四旧端点 200
- [ ] 全量回归 `python3 -m pytest crawlers/tests api/tests -q` → 78 passed
- [ ] 响应式人工检查（浏览器 /browse 或开发者工具）：375px 三页无横向滚动+输入堆叠+ladder 卡片化；1280px 窄列居中+网格表；记录到验收文档
- [ ] 话术红线 UI 清单（测试矩阵第 4 节逐条勾选）+ 出处链接抽 5 个非死链（官方四链死链=阻断）
- [ ] 验收文档落档 + Commit "docs: 选校罗盘Web验收 — 门禁记录"

**发布阻断项**：78 测试零退 / ladder+position 双北极星 / 三页 200+免责锚串 / 四态徽章在场+黄标含"建议核对官网" / 总条数一致禁 3433 / 375px 无横向滚动 / 官方四链非死链。
