# 留学 AI 中介 — 数据爬取与选校引擎方案

> 版本 V1.0 | 2026-06-10
> 联合输出：@产品经理 + @技术架构师

---

## 一、竞品调研摘要

### 1.1 ApplyBoard — 当前最成熟的留学 AI 平台

通过实际注册走完 ApplyBoard 的 9 步 profile 表单，确认其选校匹配的核心输入维度：

| 步骤 | 字段 | 具体选项 |
|:---|:---|:---|
| 1 | 目标国家 | Canada, UK, USA, Australia, Germany, Ireland |
| 2 | 入学时间 | Fall / Winter / Spring-Summer, Year 2026-2032 |
| 3 | 学术背景 | 最高学历 (Grade12→Doctoral 共9档) + 平均成绩 (Scale 1-100) |
| 4 | 专业方向 | 搜索式输入，最多选 10 个。搜索 "CS" 出现 12 个子方向 |
| 5 | 目标学位 | Master's / Bachelor's / College Diploma（可多选） |
| 6-9 | 推测 | 语言成绩/预算/其他偏好/个人信息 |

**关键发现**：
- 用 "Scale 1-100" 而非 GPA 作为统一成绩标尺 → 自动做各国成绩换算
- "Built-in quality checks give ~95% application success rate" → 申请材料有 AI 审核
- 150,000+ 项目、1,500+ 院校、AI-guided search

### 1.2 GradCafe — 最大的公开录取数据库

直接查看了 GradCafe 的搜索结果页，958K+ 条录取记录。每条包含：

```
Row structure:
  School: "Columbia University"
  Program: "Statistics Masters"
  Decision: "Accepted on Nov 06" / "Rejected on Jun 09"
  Details: "Fall 2026 | International | GRE 163 | GRE V 145 | GRE AW 3.50 | GPA 3.64"
  Comment: free text (optional, user-submitted notes)
```

**可提取的结构化字段**：

| 字段 | 格式 | 示例 |
|:---|:---|:---|
| school | string | "Columbia University" |
| program | string | "Statistics Masters" / "Computer Science PhD" |
| season | enum | Fall / Spring / Summer |
| year | int | 2026 |
| nationality | enum | International / American / Other |
| decision | enum | Accepted / Rejected / Waitlisted / Interview |
| decision_date | date | "Nov 06" |
| gpa | float | 3.64 |
| gre_q | int | 163 |
| gre_v | int | 145 |
| gre_aw | float | 3.50 |
| comment | text | free-text notes |

### 1.3 竞品能力对比

| 能力 | ApplyBoard | GradCafe | 再来人 | 新东方 | **我们做** |
|:---|:---:|:---:|:---:|:---:|:---:|
| 选校匹配 | ✅ AI引导 | ✅ 众包案例 | ✅ 数据驱动 | ⚠️ 人工为主 | ✅ RAG+向量检索 |
| 录取数据库 | ❌ 不公开 | ✅ 958K条 | ⚠️ 内部 | ⚠️ 内部 | ✅ 爬取+中介案例 |
| 申请质量检查 | ✅ 内置 | ❌ | ❌ | ❌ | ✅ 规则+LLM |
| 文书助手 | ❌ | ❌ | ⚠️ 人工 | ⚠️ 人工 | ✅ LLM生成 |
| 知识库问答 | ❌ | ❌ | ❌ | ❌ | ✅ RAG |
| 开放数据 | ❌ | ⚠️ 无API | ❌ | ❌ | ✅ 自建爬虫 |

---

## 二、数据爬取方案

### 2.1 爬虫架构（复用 trade 项目模式）

trade 项目中有成熟的爬虫模式可复用。以 `sync_btc_prices.py` 为标准模板：

```python
#!/usr/bin/env python3
"""sync_gradcafe.py — GradCafe 录取案例 → PostgreSQL

用法:
    python sync_gradcafe.py                    # 增量同步
    python sync_gradcafe.py --full             # 全量爬取
    python sync_gradcafe.py --dry-run          # 预览不写入
"""
from __future__ import annotations
import argparse, logging, os
from datetime import datetime
import psycopg2, psycopg2.extras
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
DEFAULT_DSN = os.environ.get("LIUXUE_DB_DSN", "host=localhost port=5433 dbname=liuxue user=postgres")

UPSERT_SQL = """
    INSERT INTO raw.gradcafe_admissions (
        school, program, season, year, nationality, decision, decision_date,
        gpa, gre_q, gre_v, gre_aw, comment, source_url, crawled_at
    ) VALUES %s
    ON CONFLICT (source_url) DO UPDATE SET
        decision = EXCLUDED.decision,
        crawled_at = EXCLUDED.crawled_at
"""
```

### 2.2 三只爬虫规划

| 爬虫 | 目标 | 数据量 | 技术方案 | 优先级 |
|:---|:---|:---|:---|:---:|
| **sync_gradcafe.py** | GradCafe 录取案例 | 958K+ 条 | `requests` + `BeautifulSoup`/HTML解析 | ⭐⭐⭐ P0 |
| **sync_universities.py** | 大学官网录取要求 | Top 200 校 | `requests` + LLM 结构化提取 | ⭐⭐⭐ P0 |
| **sync_rankings.py** | QS/THE/US News 排名 | ~200 条/榜 | 爬取公开排名页 + JSON 解析 | ⭐⭐ P1 |

### 2.3 GradCafe 爬取细节

GradCafe 搜索结果页是 HTML 表格，没有强反爬：

```
https://www.thegradcafe.com/survey?q=Computer+Science&page=1
```

每页约 25 条，958K 条 ÷ 25 ≈ 38,000 页。全量爬取策略：

```python
def fetch_page(query: str, page: int) -> list[dict]:
    url = f"https://www.thegradcafe.com/survey?q={query}&page={page}"
    resp = requests.get(url, headers={"User-Agent": "..."}, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    
    results = []
    for row in soup.select("table tr"):
        # 提取 school, program, decision, gpa, gre 等字段
        ...
    
    return results
```

**反爬策略**：
- 每次请求间隔 2-3 秒
- User-Agent 轮换
- 只爬需要专业的子集（如 CS/EE/Data Science/Finance），而非全量
- 增量模式：记录 last_crawled 时间，只取新增记录

### 2.4 大学官网爬取

每个大学的录取要求页面格式不同，不适合传统爬虫。方案：

```
爬虫获取原始 HTML → LLM 提取结构化 JSON → 写入数据库
```

示例 LLM prompt：
```
从以下大学官网页面提取录取要求，输出 JSON:
{
  "university": "UC Berkeley",
  "program": "M.Eng in EECS",
  "gpa_min": 3.0,
  "gpa_competitive": 3.7,
  "toefl_min": 90,
  "gre_required": false,
  "deadline_fall": "2025-12-15",
  "prerequisites": ["Data Structures", "Algorithms", ...],
  "tuition": 35000
}

页面内容：{crawled_html}
```

---

## 三、人工经验录入方案

### 3.1 为什么还需要人

网络上能爬到的都是"显性知识"（录取数据、排名、官方要求），但有大量"隐性知识"只在从业者脑中：

| 隐性知识 | 为什么重要 | 如何获取 |
|:---|:---|:---|
| 某校某专业今年扩招 | 直接影响录取概率 | 中介每年与招生办沟通 |
| "这个学校虽然排名不高，但 CS 很强" | 选校策略核心信息 | 中介经验积累 |
| 文书中哪些"雷"不能踩 | 决定申请成败 | 中介看到大量失败案例 |
| 签证面签的真实问题 | 网上题库过时 | 中介积累最新反馈 |

### 3.2 访谈 → 结构化知识的流程

```
Step 1: 访谈录音
  与 2-3 位从业 5 年+ 的留学顾问做 1-2 小时访谈
  话题: 选校策略 / 文书套路 / 避坑指南 / 面签题库

Step 2: 录音转文字
  Whisper / 火山引擎 ASR

Step 3: LLM 提取结构化知识
  Prompt 示例:
  "从以下留学顾问访谈记录中提取所有可操作的知识点，
   每一条包括: {分类, 知识点, 适用国家, 适用专业, 可靠度(1-5)}"

Step 4: 人工校验
  顾问确认提取的知识点是否正确

Step 5: 导入知识库
  写入 PostgreSQL + 向量化存入 ChromaDB
```

### 3.3 结构化知识模板

```json
{
  "id": "exp_001",
  "category": "选校策略",
  "knowledge": "UC 系学校越来越看重 diversity statement，建议每个申请人都认真写",
  "country": "us",
  "majors": ["cs", "ee", "ds"],
  "reliability": 4,
  "source": "顾问Zhang-访谈-20260610",
  "expires": "2027-06-01"
}
```

---

## 四、数据库设计

### 4.1 表结构（参考 trade 项目的 PostgreSQL 模式）

```sql
-- Schema: raw — 原始爬取数据
CREATE SCHEMA IF NOT EXISTS raw;

-- GradCafe 录取案例
CREATE TABLE raw.gradcafe_admissions (
    id              BIGSERIAL PRIMARY KEY,
    school          TEXT NOT NULL,
    program         TEXT NOT NULL,
    degree          TEXT,           -- Masters / PhD / Bachelors
    season          TEXT,           -- Fall / Spring / Summer
    year            INTEGER,
    nationality     TEXT,           -- International / American
    decision        TEXT,           -- Accepted / Rejected / Waitlisted
    decision_date   DATE,
    gpa             FLOAT,
    gre_q           INTEGER,
    gre_v           INTEGER,
    gre_aw          FLOAT,
    toefl           INTEGER,
    comment         TEXT,
    source_url      TEXT UNIQUE,
    crawled_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 大学信息
CREATE TABLE raw.universities (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    country         TEXT,
    qs_rank         INTEGER,
    the_rank        INTEGER,
    usnews_rank     INTEGER,
    website         TEXT,
    crawled_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 专业/项目录取要求
CREATE TABLE raw.program_requirements (
    id              BIGSERIAL PRIMARY KEY,
    university_id   BIGINT REFERENCES raw.universities(id),
    program_name    TEXT NOT NULL,
    degree          TEXT,
    gpa_min         FLOAT,
    gpa_competitive FLOAT,
    toefl_min       INTEGER,
    ielts_min       FLOAT,
    gre_required    BOOLEAN DEFAULT TRUE,
    deadline_fall   DATE,
    deadline_spring DATE,
    tuition         INTEGER,        -- USD per year
    prerequisites   TEXT[],
    source_url      TEXT,
    crawled_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Schema: curated — 人工经验 + LLM 提炼后的结构化知识
CREATE SCHEMA IF NOT EXISTS curated;

-- 顾问经验知识库
CREATE TABLE curated.advisorkb (
    id              BIGSERIAL PRIMARY KEY,
    category        TEXT,           -- 选校/文书/签证/行前
    knowledge       TEXT NOT NULL,
    country         TEXT,
    majors          TEXT[],
    reliability     INTEGER DEFAULT 3,  -- 1-5
    source          TEXT,
    expires         DATE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 文书模板与范例
CREATE TABLE curated.essay_templates (
    id              BIGSERIAL PRIMARY KEY,
    essay_type      TEXT,           -- PS / SOP / Diversity / Why School
    country         TEXT,
    major           TEXT,
    title           TEXT,
    content         TEXT,
    analysis        TEXT,           -- LLM 生成的范文分析
    source          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 面签题库
CREATE TABLE curated.visa_questions (
    id              BIGSERIAL PRIMARY KEY,
    country         TEXT,           -- us / uk / ca / au
    question        TEXT NOT NULL,
    suggested_answer TEXT,
    tips            TEXT,
    category        TEXT,           -- 资金/学习计划/归国/背景
    frequency       INTEGER DEFAULT 0,  -- 出现频次
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 索引
CREATE INDEX ON raw.gradcafe_admissions (school, program);
CREATE INDEX ON raw.gradcafe_admissions (gpa);
CREATE INDEX ON raw.gradcafe_admissions (decision);
CREATE INDEX ON curated.advisorkb (category, country);
CREATE INDEX ON curated.visa_questions (country, category);
```

### 4.2 与学校教师评价系统的数据协同

```sql
-- 学生画像表（与教师评价系统共享）
CREATE TABLE shared.student_profiles (
    id              BIGSERIAL PRIMARY KEY,
    student_name    TEXT,           -- 可选脱敏
    gpa             FLOAT,
    ib_score        INTEGER,        -- IB 预估分
    ap_scores       JSONB,          -- {"Calculus BC": 5, "Physics C": 4}
    toefl           INTEGER,
    ielts           FLOAT,
    sat             INTEGER,
    activities      TEXT[],         -- 竞赛/社团/科研
    target_countries TEXT[],        -- 意向国家
    target_majors   TEXT[],         -- 意向专业
    budget          INTEGER,        -- 年预算(万元)
    source          TEXT DEFAULT 'teacher_eval_system'
);
```

---

## 五、选校引擎实现方案

### 5.1 技术架构

```
学生 Profile 输入
  ↓
① 向量检索 (ChromaDB)
  → 从 GradCafe 案例中找到最相似的 200 条录取记录
  → 从 adviserkb 中找到匹配的经验知识
  ↓
② 规则过滤
  → GPA/语言不满足硬门槛的学校直接排除
  → 预算超出的学校标注但保留
  ↓
③ LLM 综合判断
  → 输入: 学生 Profile + 匹配的案例 + 大学录取要求 + 顾问经验
  → 输出: 冲/匹/保三档建议 + 每所学校的具体理由
```

### 5.2 向量化策略

```python
# 将每条 GradCafe 案例向量化，用于相似度检索
def vectorize_case(case: dict) -> str:
    """将案例转为可向量化的文本"""
    return f"""
    School: {case['school']}
    Program: {case['program']}
    GPA: {case.get('gpa', 'N/A')}
    GRE Q: {case.get('gre_q', 'N/A')}
    GRE V: {case.get('gre_v', 'N/A')}
    Decision: {case['decision']}
    Season: {case['season']} {case['year']}
    """

# 存储到 ChromaDB
import chromadb
client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_or_create_collection("gradcafe_cases")

for case in cases:
    collection.add(
        documents=[vectorize_case(case)],
        metadatas=[{"school": case["school"], "decision": case["decision"], "gpa": case["gpa"]}],
        ids=[str(case["id"])]
    )
```

### 5.3 选校 Prompt 示例

```
你是一位有 10 年经验的留学顾问。根据以下信息给出选校建议：

## 学生信息
GPA: 3.6/4.0
托福: 105
GRE: 未考（计划考）
专业方向: Computer Science, Data Science
意向国家: 美国, 加拿大
预算: 50 万/年

## 相似案例（从 GradCafe 检索的 10 条匹配记录）
[类似 GPA 3.5-3.7 + TOEFL 100-108 + CS 的录取/拒绝案例]

## 顾问经验
[从 adviserkb 检索到的相关知识点]

## 大学录取要求
[从 program_requirements 表检索的 30 所目标学校要求]

请输出：
1. 冲刺校（3 所）— 每所附概率估计和理由
2. 匹配校（4 所）— 每所附匹配点
3. 保底校（3 所）— 每所附确认点
4. 是否需要再刷语言/GRE
5. 需要注意的风险点
```

---

## 六、启动计划

### 6.1 Phase 1: 数据筑基（2-3 周）

| 周 | 任务 | 产出 | 可复用 trade 项目模式 |
|:---|:---|:---|:---|
| W1 | GradCafe 爬虫开发 | `sync_gradcafe.py` 可运行，导入 5000+ 条案例 | ✅ sync_btc_prices.py 模式 |
| W1 | 大学排名爬取 | `sync_rankings.py`，Top 200 大学信息入库 | ✅ sync_openbb.py 模式 |
| W2 | LLM 提取大学录取要求 | 30 所目标校的结构化要求 | 新开发 |
| W2 | 数据库搭建 | PostgreSQL Schema 创建完毕 | ✅ 复用 DDL 模式 |
| W3 | 中介顾问访谈 | 2-3 次访谈 → 50+ 条经验知识点 | 新流程 |
| W3 | 建立 ChromaDB 向量库 | GradCafe 案例 + adviserkb 全部向量化 | 新开发 |

### 6.2 Phase 2: 选校引擎 MVP（2 周）

| 周 | 任务 | 产出 |
|:---|:---|:---|
| W4 | 选校 RAG 管线 | 向量检索 + 规则过滤 + LLM 综合判断 → 可运行 |
| W4 | 知识库问答 | 基于 adviserkb + 大学信息的 RAG 问答 |
| W5 | Web 界面 | 学生 profile 输入 → 选校建议输出 → 可演示 |

### 6.3 需要的外部资源

| 资源 | 来源 | 获取方式 |
|:---|:---|:---|
| 中介顾问访谈 | 用户提到"做留学中介的朋友" | 约 2-3 次 1 小时访谈 |
| 脱敏录取案例（50-200 条） | 中介朋友 | Excel export |
| 文书范例（10-20 篇） | 中介朋友 + 网络 | 文件分享 |
| GradCafe 数据 | 公开网站 | 爬虫自动获取 |

---

> **文档维护**：@产品经理 + @技术架构师
> **可复用资产**：`~/work/trade` 项目的 `sync_*.py` 爬虫模式、PostgreSQL Schema 设计模式
> **最后更新**：2026-06-10
