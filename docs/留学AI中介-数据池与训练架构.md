# 留学 AI 中介 — 数据池与训练架构

> 版本 V1.0 | 2026-06-10
> 复用 `~/work/trade` 项目的成熟数据平台模式
> 联合输出：@产品经理 + @技术架构师

---

## 一、trade 项目数据平台架构总结

### 1.1 四层数据架构

trade 项目的量化数据平台采用标准的 **四层数据仓库** 模式：

```
┌──────────────────────────────────────────────────────┐
│                   Layer 4: API 服务层                  │
│  FastAPI routes → /quant/factors, /quant/macro,       │
│  /quant/sync, /quant/skills                           │
│  背景异步任务 (ApiBG)                                  │
├──────────────────────────────────────────────────────┤
│                   Layer 3: Mart 应用层                 │
│  mart_factor_scoreboard (因子评分板)                   │
│  mart_factor_ic (IC分析: 因子→收益相关性)              │
│  mart_factor_correlation (因子间相关性矩阵)            │
│  mart_hourly_signals (每小时信号汇总)                  │
│  宏观信号检查 (rule-based signal definitions)          │
├──────────────────────────────────────────────────────┤
│            Layer 2: dbt 转换层 (3子层)                  │
│  staging (view): stg_ohlcv — 原始数据薄封装            │
│  intermediate (table): int_hourly_returns,             │
│     int_macro_hourly, int_sentiment_hourly             │
│  features (table): RSI, Momentum, Volatility,          │
│     Amihud, Bollinger, MFI, VIX, CPI, DXY, PMI ...     │
├──────────────────────────────────────────────────────┤
│                  Layer 1: Raw 原始层                    │
│  quant_raw.macro_indicators (series_id/date/value)     │
│  quant_raw_cn.financial_metrics (A股财务)              │
│  raw tables for OHLCV, news, documents                  │
└──────────────────────────────────────────────────────┘
```

### 1.2 核心设计模式

#### 模式 1: 标准化同步脚本

每个数据源一个独立 Python 脚本，遵循统一模板：

```python
# sync_xxx.py — 标准模板
import argparse, logging, psycopg2, requests

UPSERT_SQL = """
    INSERT INTO target_table (...) VALUES %s
    ON CONFLICT (key) DO UPDATE SET ... = EXCLUDED...
"""

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()

def fetch_data() -> list[dict]: ...
def upsert(conn, rows): ...

def main():
    args = parse_args()
    rows = fetch_data()
    if not args.dry_run:
        with psycopg2.connect(DSN) as conn:
            upsert(conn, rows)
```

#### 模式 2: dbt 分层转换

```
raw tables (PostgreSQL)
    ↓ staging: view (schema alignment, thin wrapper)
    ↓ intermediate: table (joins, cleaning, time alignment)
    ↓ features: table (computed factors — RSI, momentum, MACD...)
    ↓ mart: table (aggregation — IC, correlation matrix, scoreboard)
```

dbt_project.yml 配置：
```yaml
models:
  quant_warehouse:
    staging:       +materialized: view     # 轻量，随时刷新
    intermediate:  +materialized: table    # 物化，加速下游
    features:      +materialized: table    # 物化，多表复用
    mart:          +materialized: table    # 物化，API 查询用
```

#### 模式 3: 三级因子研究回路 (Tier System)

```
Phase 1: 因子注册 (YAML registry)
    factors.yml → factor_registry.py 加载
    ↓
Phase 2: 三级筛选 (Tier 1→2→3)
    Tier 1: IC 过滤
      条件: IC_mean > 0.005 AND IC_IR > 0.3
      含义: 因子与未来收益有统计显著的正相关
    Tier 2: 相关性过滤
      条件: max_corr_with_accepted < 0.7
      含义: 与已接受的因子不过度相关（避免冗余）
    Tier 3: 回测验证
      条件: Sharpe > 1.0 AND Max_DD < 15%
      含义: 实际交易中有正期望 + 可控回撤
    ↓
Phase 3: 结果记录
    quant.mart_factor_scoreboard (每个因子每轮的打分)
```

#### 模式 4: 宏观信号检测系统

```python
_MACRO_SIGNAL_DEFS = [
    {
        "id": "cpi_turning",
        "label_zh": "CPI 拐头回落",
        "check": lambda rows: {
            "status": "confirmed" if value < 3.0 else "watching" if value < 3.5 else "off",
            "value": f"{value:.1f}%",
            "detail": f"核心PCE {value:.1f}%{' (确认拐头)' if confirmed else ''}"
        }
    },
    # ... 5个信号定义
]
```

特点：每个信号是独立的 lambda/function，输入原始值 → 输出 `{status, value, detail}`。

#### 模式 5: ChromaDB 知识库

```python
# ingest_documents.py — 文档→chunks→embeddings→ChromaDB
from sentence_transformers import SentenceTransformer
import chromadb

model = SentenceTransformer("all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path="./chromadb")

# 文档分块 → 向量化 → 存储
chunks = split_text(document, chunk_size=500, overlap=100)
embeddings = model.encode(chunks)
collection.add(documents=chunks, embeddings=embeddings, metadatas=[...], ids=[...])
```

---

## 二、留学 AI 数据池架构（复用 trade 模式）

### 2.1 整体架构

```
┌──────────────────────────────────────────────────────────┐
│                    Layer 4: AI 应用层                       │
│  选校引擎 (RAG)  │  文书助手 (LLM)  │  知识库问答 (RAG)    │
│  面签模拟 (对话)  │  时间线管理 (规则)  │  材料审核 (规则)   │
│  FastAPI routes: /api/match, /api/essay, /api/qa...      │
├──────────────────────────────────────────────────────────┤
│                   Layer 3: Mart 分析层                      │
│  mart.school_admission_stats (学校-专业录取统计)            │
│  mart.student_match_scores (学生-学校匹配分)                │
│  mart.admission_patterns (录取模式: GPA阈值/标化相关性)     │
│  curated.signal_definitions (申请信号: 安全性/匹配度/风险)  │
├──────────────────────────────────────────────────────────┤
│               Layer 2: dbt 转换层 (3子层)                   │
│  staging: stg_gradcafe — 爬虫数据薄封装                     │
│  intermediate: int_admissions_ranked (按校/专业聚合)        │
│  features: feat_gpa_threshold, feat_acceptance_rate,       │
│     feat_gre_correlation, feat_major_competition...        │
├──────────────────────────────────────────────────────────┤
│                  Layer 1: Raw 原始层                         │
│  raw.gradcafe_admissions (958K+ 条录取案例)                │
│  raw.universities (Top 200 校排名)                         │
│  raw.program_requirements (各校各专业录取要求)              │
│  curated.advisorkb (顾问经验知识库)                         │
│  curated.essay_templates (文书模板库)                       │
│  curated.visa_questions (面签题库)                          │
└──────────────────────────────────────────────────────────┘
```

### 2.2 与 trade 项目的模式对应

| trade 项目 | 留学 AI | 复用内容 |
|:---|:---|:---|
| `sync_btc_prices.py` | `sync_gradcafe.py` | argparse + psycopg2 upsert + --dry-run |
| `sync_openbb.py` | `sync_rankings.py` | API 调用 → 结构化入库 |
| `sync_fedwatch.py` | `sync_universities.py` | 爬取 HTML → 解析 → 入库 |
| `quant_raw.macro_indicators` | `raw.gradcafe_admissions` | series_id/date/value 的宽表模式 |
| `factors.yml` | `admission_factors.yml` | YAML 注册 + factor_registry.py 加载 |
| dbt models (4层) | dbt models (4层) | 完全复用分层物料化策略 |
| Tier 1→2→3 研究回路 | **Admission Tier 1→2→3** | 复制三级筛选框架 |
| `_MACRO_SIGNAL_DEFS` | `_ADMISSION_SIGNAL_DEFS` | lambda check → {status, value, detail} |
| `ingest_documents.py` → ChromaDB | `ingest_advisorkb.py` → ChromaDB | 文档分块→向量化→RAG |
| `mart_factor_scoreboard` | `mart.admission_school_stats` | 评分板模式 |
| FastAPI + ApiBG | FastAPI + ApiBG | 完全复用 API 框架 |

---

## 三、三级 Admission 研究回路

### 3.1 回路设计（参考 factor research loop）

```python
# admission_research_loop.py

"""
留学选校因子研究回路。

Phase 1: 加载学校/专业注册表 (admission_factors.yml)
Phase 2: 三级筛选
    Tier 1: 录取相关性过滤
        条件: 某特征(如GPA)与该专业录取率的相关性 > 0.3
        含义: 该特征对录取有显著预测力
    Tier 2: 交叉相关性过滤
        条件: max_corr_with_other_factors < 0.8
        含义: 避免冗余特征（如 GPA 和班级排名高度相关取其一）
    Tier 3: 预测准确率验证
        条件: 基于案例库回测的录取/拒绝预测准确率 > 70%
        含义: 模型在实际案例上有可接受的预测力

Phase 3: 结果写入 mart.admission_factor_scoreboard
"""
```

### 3.2 录取信号定义（参考 macro signals）

```python
_ADMISSION_SIGNAL_DEFS = [
    {
        "id": "gpa_safety",
        "label_zh": "GPA 安全边际",
        "description_zh": "学生GPA距该校该专业录取中位数GPA的差值",
        "check": lambda student, school_stats: {
            "status": "safe" if student.gpa >= school_stats.gpa_median + 0.2
                 else "match" if student.gpa >= school_stats.gpa_median - 0.1
                 else "reach",
            "value": f"+{student.gpa - school_stats.gpa_median:.2f}",
            "detail": f"该校录取中位GPA {school_stats.gpa_median}，你高出{student.gpa - school_stats.gpa_median:.2f}"
        }
    },
    {
        "id": "gre_necessity",
        "label_zh": "GRE 必要性",
        "check": lambda student, school_stats: {
            "status": "optional" if school_stats.gre_required == False
                 else "recommended" if student.gre_q and student.gre_q >= school_stats.gre_q_median - 5
                 else "required_and_weak",
            "value": f"Q{student.gre_q or '未考'} vs 中位{school_stats.gre_q_median}",
            ...
        }
    },
    # ... 更多信号
]
```

### 3.3 选校信号 vs 量化信号对照

| trade 模式 | 留学 AI 对应 | 说明 |
|:---|:---|:---|
| IC (信息系数) | 特征-录取相关性 | GPA/标化/活动 vs 录取结果 |
| IR (信息比率) | 特征稳定性 | 该特征在不同年份/申请季的稳定性 |
| 因子相关性矩阵 | 学生特征相关性 | GPA vs 班级排名、IB vs AP 换算 |
| 回测验证 | 案例库回测 | 用 GradCafe 历史数据验证预测准确率 |
| 宏观信号 | 录取信号 | GPA安全边际、GRE必要性、专业竞争度 |

---

## 四、dbt 模型设计

### 4.1 目录结构

```
dbt_liuxue/
├── dbt_project.yml
└── models/
    ├── staging/
    │   └── stg_gradcafe_admissions.sql    # 清洗 GradCafe 数据
    │   └── stg_universities.sql           # 大学信息清洗
    │   └── stg_program_requirements.sql   # 录取要求清洗
    ├── intermediate/
    │   └── int_admissions_ranked.sql      # 按校/专业聚合，添加排名
    │   └── int_student_profiles.sql       # 学生画像（来自教师评价系统）
    ├── features/
    │   └── feat_gpa_threshold.sql         # 各校各专业 GPA 录取阈值
    │   └── feat_acceptance_rate.sql       # 各校各专业录取率
    │   └── feat_gre_correlation.sql       # GRE 与录取的相关性
    │   └── feat_seasonality.sql           # 申请季差异（Fall vs Spring）
    │   └── feat_nationality_bias.sql      # 国际生 vs 本地生录取差异
    └── mart/
        └── mart_school_admission_stats.sql # 学校-专业录取统计汇总
        └── mart_student_match_scores.sql   # 学生与学校匹配分
        └── mart_admission_patterns.sql     # 录取模式识别
```

### 4.2 核心 dbt SQL 示例

**stg_gradcafe_admissions.sql** — staging 层（薄封装）：
```sql
SELECT
    id,
    school,
    program,
    CASE
        WHEN program ILIKE '%phd%' OR program ILIKE '%doctor%' THEN 'PhD'
        WHEN program ILIKE '%master%' OR program ILIKE '%ms %' THEN 'Masters'
        WHEN program ILIKE '%bachelor%' OR program ILIKE '%bs %' THEN 'Bachelors'
        ELSE 'Other'
    END AS degree,
    season,
    year,
    nationality,
    CASE WHEN decision ILIKE '%accept%' THEN 'Accepted'
         WHEN decision ILIKE '%reject%' THEN 'Rejected'
         WHEN decision ILIKE '%wait%' THEN 'Waitlisted'
         ELSE 'Other'
    END AS decision,
    gpa,
    gre_q, gre_v, gre_aw,
    crawled_at
FROM {{ source('raw', 'gradcafe_admissions') }}
WHERE gpa IS NOT NULL
  AND gpa > 0 AND gpa <= 4.0
```

**feat_gpa_threshold.sql** — 特征层（计算各校 GPA 阈值）：
```sql
WITH stats AS (
    SELECT
        school, program, degree,
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY gpa) AS gpa_p25,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY gpa) AS gpa_median,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY gpa) AS gpa_p75,
        COUNT(*) FILTER (WHERE decision = 'Accepted') AS accepted_count,
        COUNT(*) AS total_count
    FROM {{ ref('stg_gradcafe_admissions') }}
    GROUP BY school, program, degree
    HAVING COUNT(*) >= 10  -- 最少10条案例才算有效
)
SELECT
    *,
    CASE
        WHEN accepted_count::float / total_count > 0.7 THEN 'Low Competition'
        WHEN accepted_count::float / total_count > 0.4 THEN 'Moderate'
        ELSE 'High Competition'
    END AS competition_level
FROM stats
```

**mart_school_admission_stats.sql** — Mart 层（汇总输出给 API）：
```sql
SELECT
    s.school,
    s.program,
    s.degree,
    s.gpa_p25, s.gpa_median, s.gpa_p75,
    s.competition_level,
    r.qs_rank, r.the_rank, r.usnews_rank,
    s.total_count AS sample_size
FROM {{ ref('feat_gpa_threshold') }} s
LEFT JOIN {{ ref('stg_universities') }} r ON s.school = r.name
WHERE s.total_count >= 10
ORDER BY r.qs_rank NULLS LAST, s.gpa_median DESC
```

---

## 五、端到端数据流

### 5.1 从爬虫到 AI 应用的完整链路

```
Step 1: 爬取 (Crawl)
  sync_gradcafe.py ──→ raw.gradcafe_admissions
  sync_rankings.py ──→ raw.universities
  sync_universities.py ──→ raw.program_requirements (LLM提取)

Step 2: 转换 (Transform)
  dbt run ──→ staging → intermediate → features → mart
  
Step 3: 向量化 (Embed)
  ingest_admissions.py ──→ ChromaDB (录取案例向量库)
  ingest_advisorkb.py ──→ ChromaDB (顾问知识向量库)

Step 4: 信号定义 (Signal)
  admission_factors.yml ──→ factor_registry.py 加载
  admission_signal_defs.py ──→ lambda check 函数

Step 5: 研究回路 (Research)
  admission_research_loop.py ──→ Tier 1→2→3 筛选
  ──→ mart.admission_factor_scoreboard

Step 6: AI 应用 (Application)
  FastAPI routes:
    POST /api/match    → 输入学生profile → 选校建议
    POST /api/essay    → 文书生成
    GET /api/qa?q=...  → 知识库问答
    每条请求内部:
      ① ChromaDB 向量检索 (召回相似案例)
      ② mart 统计查询 (获取录取阈值)
      ③ 信号检查 (GPA安全边际等)
      ④ LLM 综合判断 → 输出结果
```

### 5.2 同步 cron 配置

```bash
# 每周一凌晨 2:00 — GradCafe 增量同步
0 2 * * 1  cd ~/work/guoji-agent && python crawlers/sync_gradcafe.py

# 每月1号 — 大学排名更新
0 3 1 * *  cd ~/work/guoji-agent && python crawlers/sync_rankings.py

# 每两周 — 大学录取要求更新
0 4 1,15 * * cd ~/work/guoji-agent && python crawlers/sync_universities.py

# 每天早上 6:00 — dbt 转换
0 6 * * *  cd ~/work/guoji-agent/dbt_liuxue && dbt run

# 每周 — 研究回路运行
0 5 * * 1  cd ~/work/guoji-agent && python research/admission_research_loop.py
```

---

## 六、启动清单

### 6.1 基础设施（复用 trade 项目模式，1-2天搭建）

| 任务 | 复用来源 | 工作量 |
|:---|:---|:---:|
| PostgreSQL 数据库 + Schema | trade 项目的 DDL 模式 | 0.5天 |
| dbt 项目初始化 (`dbt init`) | `dbt_project.yml` 模板 | 0.5天 |
| ChromaDB 部署 | `ingest_documents.py` 模式 | 0.5天 |
| FastAPI 基础框架 | `api_quant.py` + `sync_routes.py` | 0.5天 |

### 6.2 数据爬取（第1周）

| 任务 | 输出 |
|:---|:---|
| `sync_gradcafe.py` | 首批 5000 条 CS/DS 专业录取案例入库 |
| `sync_rankings.py` | Top 200 大学排名入库 |
| `sync_universities.py` + LLM 提取 | 30 所目标校录取要求结构化 |

### 6.3 dbt 与训练（第2周）

| 任务 | 输出 |
|:---|:---|
| dbt models 开发 (staging→features→mart) | 可运行的 `dbt run` |
| Tier 1 录取相关性分析 | 哪些特征对录取有预测力 |
| ChromaDB 向量库构建 | 案例 + 知识向量化完成 |
| 顾问访谈数据录入 | 50+ 条经验知识点入库 |

### 6.4 AI 应用层（第3周）

| 任务 | 输出 |
|:---|:---|
| 选校引擎 API (`POST /api/match`) | 学生 profile → 选校建议 |
| 知识库问答 API (`GET /api/qa`) | RAG 问答可用 |
| Web 界面试点 | 可演示的选校辅助工具 |

---

> **文档维护**：@产品经理 + @技术架构师
> **复用了 trade 项目的**：全部 5 个核心模式（同步脚本/dbt分层/Tier研究/信号系统/ChromaDB）
> **最后更新**：2026-06-10
