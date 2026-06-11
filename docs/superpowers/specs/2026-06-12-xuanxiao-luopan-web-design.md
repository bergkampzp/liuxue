# 选校罗盘 Web 服务 — 设计文档

> 2026-06-12 | 已经用户确认（视觉方向 + 架构 + 范围）
> 里程碑定位：MVP-2 对外体验版——把 MVP-1 的数据能力做成可传播的 Web 产品

## 背景与目标

MVP-1 已交付数据底座（四源官方名单 3433 条、entry_requirement 450 行、四个 API）和一个最小 Streamlit 前端。本里程碑把它升级为**对外可传播的 Web 服务**，体现核心能力与三个秀肌肉点（谢菲当场验证 / 透明方法论 / 不在名单反例），服务双非·DIY 客群。

**产品名：选校罗盘**。视觉：B 活力渐变 × read.cv 极简排版（用户经视觉伴侣确认 homepage-v1 mockup）——白底窄列（680px）大留白，渐变（#7c3aed→#db2777→#f59e0b）只用于 logo 色块/hero 强调词/CTA/官方徽章。**硬性要求：响应式适配手机+电脑**（断点 640px，输入区纵向堆叠、导航折叠）。

## 架构

```
api/main.py（现有 FastAPI 进程）
 ├─ 现有: /position /ielts-gap /major-fit /waitlist
 ├─ 新增: GET /school-ladder?school=<中文校名>
 └─ 新增: StaticFiles 挂载 web/ → 单进程同时服务 API+页面
web/
 ├─ index.html        首页定位（已确认 mockup 结构）
 ├─ school.html       院校查询页
 ├─ methodology.html  方法论页（纯静态）
 └─ static/ style.css(设计令牌+断点) + app.js(原生JS fetch+渲染)
```
无构建链、无 node。后续量大再迁 React 不亏。

## /school-ladder 后端

`GET /school-ladder?school=江苏大学`：
1. 复用 `resolve_cn_university`（精确+别名+rapidfuzz）；未识别 → 422 + 候选提示
2. 组合查询现有表（**不新建 dbt 模型**）：
   - `stg_uk_official_lists`：该校(cn_uni_id)在四源名单中的 band + 谢菲逐校 min_avg_score
   - `mart_uk_school_match_v1`：按该校 tier 取各英国校线 + source + 雅思基线
3. 输出每所英国校一行：`{uk_uni_id, name_zh, qs_rank, list_status(名单内/BandX/不在认可名单/未收录), min_avg_score, source_type, source_url, ielts_overall}`
4. 名单门控校（ucl/bristol/edinburgh）不在名单 → list_status='不在认可名单'（红标，与 /position 的 not_on_list 口径一致）

## 三个页面

| 页面 | 内容 | 秀肌肉点 |
|------|------|---------|
| index.html | nav → hero(渐变强调词) → 四格输入(校名/均分/方向/雅思可选) → 当场验证条(谢菲) → 结果列表(四态徽章行: 官方蓝/参考黄/不在名单红/案例积累中灰+waitlist) → 方法论与院校查询入口卡 → 免责页脚 | 谢菲 2891 校当场验证、反例、waitlist 钩子 |
| school.html | 输入中国大学 → 全景表：每所英国校的名单状态+分数线+出处链接 | 3433 条官方名单全景 |
| methodology.html | 数据来源（四源条数+官网链接）、三级徽章含义、反推方法论预告、免责声明 | 透明即获客，可被引用传播 |

**话术红线（沿用 MVP-0/1 验收口径）**：官方=精确数字+蓝标；aggregator=黄标+"建议核对官网"；case_inferred 只出区间；样本不足显示"案例积累中"绝不硬出数；每页页脚免责声明；所有数字带可点出处。

## 错误处理

- 校名未识别：422 → 前端显示"未识别院校"+输入全称提示（不静默）
- API 异常/超时：前端 toast "服务暂时不可用，稍后再试"
- 无数据学校：显示"案例积累中"+waitlist 表单，不留空白

## 测试与验收

- pytest：/school-ladder TDD 单测；现有 72 测试零退
- 冒烟：三页面 curl 200 + 关键文案在场；北极星链路（江苏大学→谢菲 75 官方/UCL 不在名单）
- 响应式：375px / 1280px 两档人工过查（浏览器）
- 话术红线 UI 审查：四态徽章逐态截图核对

## 范围边界（明确不做）

- 反推线（案例 P10/等渗管线）——被 1p3a Cloudflare cookie 与别名顾问抽检（H3）阻塞，独立排期
- 对话式 LLM、PS/签证、澳洲港新、用户账号体系
- React 工程化、Redis、CDN
