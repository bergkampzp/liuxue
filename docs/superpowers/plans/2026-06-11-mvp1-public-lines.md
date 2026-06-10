# MVP-1「英国选校定位·公开校先行版」实施计划（W4-6）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 上线首个对外版本：功能 1 降级版（4 所官方公开校精确判定 + 16 校种子参考线 + 冲/匹/保规则层，不等反推），与功能 4 联动，曼大/KCL 数据缺口做成 waitlist 获客钩子。

**Architecture:** 新增中国院校维表（985/211 标签 + 别名）与官方名单爬虫（4 源 4 种采集方式）；dbt `entry_requirement` 统一官方+种子两类线源；`mart_uk_school_match_v1` 算 gap 出冲/匹/保；API `/position` 纯查表 + 模板解释（架构决策：LLM 润色后置）；Streamlit 做最小对外前端。

**Tech Stack:** 同 MVP-0 + pdfplumber + rapidfuzz + streamlit

**前置:** MVP-0 计划全部完成（normalize 模块、001 迁移、dim_uk_university seed、/ielts-gap、run-pipeline uk 子命令均已存在）。

---

### Task 1: DDL 迁移 002（中国院校 / 官方名单 / waitlist 三张表）

**Files:**
- Create: `migrations/002_mvp1_schema.sql`

- [ ] **Step 1: 写迁移**

```sql
-- migrations/002_mvp1_schema.sql  幂等
CREATE TABLE IF NOT EXISTS raw.uk_official_lists (
    id          SERIAL PRIMARY KEY,
    uk_uni_id   TEXT NOT NULL,          -- 对齐 seeds/dim_uk_university.uk_uni_id
    cn_name_raw TEXT NOT NULL,          -- 名单上的中国院校名原文(可能中英混排)
    band        TEXT NOT NULL,          -- in-list / BandA-D / arwu-tier1-4 等,按校原文
    min_avg_score NUMERIC(4,1),         -- 名单页直接标分数线的填,否则NULL
    source_url  TEXT NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL,
    UNIQUE (uk_uni_id, cn_name_raw, band)
);

CREATE TABLE IF NOT EXISTS raw.waitlist_leads (
    id          SERIAL PRIMARY KEY,
    email       TEXT NOT NULL,
    uk_uni_id   TEXT,                   -- 用户想查但缺数据的学校
    profile_json JSONB,                 -- 用户输入的背景(脱敏前先存)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- [ ] **Step 2: 执行验证（幂等跑两遍）**

Run: `psql "host=localhost port=5433 dbname=warehouse user=postgres password=postgres" -f migrations/002_mvp1_schema.sql && psql "host=localhost port=5433 dbname=warehouse user=postgres password=postgres" -f migrations/002_mvp1_schema.sql`
Expected: 两遍均无报错

- [ ] **Step 3: Commit**

```bash
git add migrations/002_mvp1_schema.sql
git commit -m "feat: MVP-1 schema — 官方名单/waitlist表"
```

---

### Task 2: 中国院校维表 seed（985/211 标签 + 别名）

**Files:**
- Create: `dbt_liuxue/seeds/dim_cn_university.csv`
- Create: `dbt_liuxue/seeds/cn_university_alias.csv`
- Modify: `dbt_liuxue/seeds/properties.yml`

- [ ] **Step 1: 985 院校全量 39 行（静态公开事实，直接录入）**

`dim_cn_university.csv` 表头与 985 部分：
```csv
cn_uni_id,name_zh,name_en,is_985,is_211,tier_label
tsinghua,清华大学,Tsinghua University,true,true,985
pku,北京大学,Peking University,true,true,985
fudan,复旦大学,Fudan University,true,true,985
sjtu,上海交通大学,Shanghai Jiao Tong University,true,true,985
zju,浙江大学,Zhejiang University,true,true,985
nju,南京大学,Nanjing University,true,true,985
ustc,中国科学技术大学,USTC,true,true,985
hit,哈尔滨工业大学,Harbin Institute of Technology,true,true,985
xjtu,西安交通大学,Xi'an Jiaotong University,true,true,985
buaa,北京航空航天大学,Beihang University,true,true,985
tongji,同济大学,Tongji University,true,true,985
...（其余 28 所 985 同格式补全，名单以教育部公布为准，录完核对 count=39）
```
211（非 985 的 76 所）与高频双非（先录案例里出现最多的 ~60 所，含江苏大学/深圳大学/南京工业大学等），`tier_label` 取 `211`/`双非`。**录完验证：985=39、211 合计=115。**

- [ ] **Step 2: 别名表（先覆盖高频简称，后续从未归一暂存表回流扩充）**

```csv
alias,cn_uni_id
清华,tsinghua
北大,pku
上交,sjtu
交大,sjtu
浙大,zju
中科大,ustc
哈工大,hit
北航,buaa
电子科大,uestc
成电,uestc
UESTC,uestc
华科,hust
武大,whu
川大,scu
吉大,jlu
```
（同格式扩充到 ≥80 行常见简称。）

- [ ] **Step 3: properties.yml 追加测试**

```yaml
  - name: dim_cn_university
    columns:
      - name: cn_uni_id
        tests: [unique, not_null]
      - name: tier_label
        tests:
          - accepted_values:
              values: ['985', '211', '双非', '海本', '其他']
  - name: cn_university_alias
    columns:
      - name: alias
        tests: [unique, not_null]
```

- [ ] **Step 4: 跑 seed + 验证**

Run: `cd /home/zp/work/guoji-agent/dbt_liuxue && dbt seed --select dim_cn_university cn_university_alias && dbt test --select dim_cn_university cn_university_alias && psql "host=localhost port=5433 dbname=warehouse user=postgres password=postgres" -c "SELECT tier_label, count(*) FROM dim_cn_university GROUP BY 1"`
Expected: tests PASS；985 行数=39

- [ ] **Step 5: Commit**

```bash
git add dbt_liuxue/seeds/
git commit -m "feat: 中国院校维表seed — 985/211标签+别名表"
```

---

### Task 3: 官方名单爬虫 — UCL + Bristol（静态 HTML，先做最容易的两源）

**Files:**
- Create: `crawlers/sync_uk_official_lists.py`
- Test: `crawlers/tests/test_uk_lists.py`

- [ ] **Step 1: 先抓页面快照确认结构（采集类任务必做侦察步）**

Run: `cd /tmp && curl -sL "https://www.ucl.ac.uk/prospective-students/international/china" -o ucl.html && curl -sL "https://www.bristol.ac.uk/international/countries/china/accepted-universities-in-china/" -o bristol.html && grep -c "大学\|University" ucl.html bristol.html`
Expected: 两文件都有大量院校名命中。打开快照确认表格/列表的 CSS 结构，**据实调整 Step 3 的选择器**。

- [ ] **Step 2: 写解析函数失败测试（用快照里截取的真实 HTML 片段做 fixture）**

```python
# crawlers/tests/test_uk_lists.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sync_uk_official_lists import parse_ucl, parse_bristol

# fixture 从 Step 1 快照中截取真实片段（执行时替换为实际结构）
UCL_SNIPPET = """<table><tr><td>Tsinghua University 清华大学</td></tr>
<tr><td>Jiangsu University 江苏大学</td></tr></table>"""


def test_parse_ucl_extracts_rows():
    rows = parse_ucl(UCL_SNIPPET)
    assert {"cn_name_raw": "Tsinghua University 清华大学", "band": "in-list"} in [
        {k: r[k] for k in ("cn_name_raw", "band")} for r in rows]
    assert len(rows) == 2
```

- [ ] **Step 3: 实现爬虫（骨架，选择器按快照核实后定稿）**

```python
# crawlers/sync_uk_official_lists.py
#!/usr/bin/env python3
"""英国大学官方中国院校认可名单爬虫。
用法: python sync_uk_official_lists.py --source ucl [--dry-run]
源: ucl | bristol | edinburgh | sheffield (各源采集方式不同,分task实现)
"""
from __future__ import annotations

import argparse, logging, os
from datetime import datetime, timezone

import psycopg2, psycopg2.extras
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("uk_lists")

DSN = os.environ.get("WAREHOUSE_DSN",
    "host=localhost port=5433 dbname=warehouse user=postgres password=postgres")
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0 Safari/537.36"}

SOURCES = {
    "ucl": "https://www.ucl.ac.uk/prospective-students/international/china",
    "bristol": "https://www.bristol.ac.uk/international/countries/china/accepted-universities-in-china/",
}

UPSERT = """
INSERT INTO raw.uk_official_lists (uk_uni_id, cn_name_raw, band, min_avg_score, source_url, fetched_at)
VALUES %s
ON CONFLICT (uk_uni_id, cn_name_raw, band) DO UPDATE SET fetched_at = EXCLUDED.fetched_at
"""


def parse_ucl(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for td in soup.select("table td"):           # 选择器按快照核实定稿
        name = td.get_text(strip=True)
        if name and ("学" in name or "univ" in name.lower()):
            rows.append({"uk_uni_id": "ucl", "cn_name_raw": name,
                         "band": "in-list", "min_avg_score": None})
    return rows


def parse_bristol(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for td in soup.select("table td"):           # 选择器按快照核实定稿
        name = td.get_text(strip=True)
        if name and ("学" in name or "univ" in name.lower()):
            rows.append({"uk_uni_id": "bristol", "cn_name_raw": name,
                         "band": "accepted", "min_avg_score": None})
    return rows


PARSERS = {"ucl": parse_ucl, "bristol": parse_bristol}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True, choices=list(SOURCES))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    url = SOURCES[args.source]
    html = requests.get(url, headers=HEADERS, timeout=60).text
    rows = PARSERS[args.source](html)
    log.info("%s: 解析出 %d 条", args.source, len(rows))
    if len(rows) < 20:
        log.error("条数异常少(<20)，页面结构可能已变，拒绝写入")
        return

    if args.dry_run:
        for r in rows[:5]:
            log.info("  %s | %s", r["cn_name_raw"][:40], r["band"])
        return

    now = datetime.now(timezone.utc)
    values = [(r["uk_uni_id"], r["cn_name_raw"], r["band"], r["min_avg_score"], url, now)
              for r in rows]
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, UPSERT, values)
        conn.commit()
    log.info("写入完成: %d 条", len(values))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 测试 + dry-run + 真实入库**

Run: `cd /home/zp/work/guoji-agent/crawlers && python -m pytest tests/test_uk_lists.py -v && python sync_uk_official_lists.py --source ucl --dry-run && python sync_uk_official_lists.py --source ucl && python sync_uk_official_lists.py --source bristol`
Expected: 测试 PASS；UCL ~100+ 条、Bristol ~266 条（与调研一致，明显偏少则停下查结构）

- [ ] **Step 5: Commit**

```bash
git add crawlers/sync_uk_official_lists.py crawlers/tests/test_uk_lists.py
git commit -m "feat: 官方名单爬虫 — UCL+Bristol 静态HTML源"
```

---

### Task 4: 官方名单爬虫 — 爱丁堡（PDF Priority List）

**Files:**
- Modify: `crawlers/sync_uk_official_lists.py`

- [ ] **Step 1: 定位并下载 PDF**

Run: `curl -sL "https://www.ed.ac.uk/studying/international/postgraduate-entry/asia/china" | grep -io 'href="[^"]*priority[^"]*pdf"'`
Expected: 拿到 PDF 链接。下载存 `crawlers/snapshots/edinburgh_priority_list.pdf` 归档留证（建目录 + `.gitignore` 不需排除，PDF 入库存证）。

- [ ] **Step 2: 实现 PDF 解析（pdfplumber，按实际表格结构定稿）**

```python
# 追加到 sync_uk_official_lists.py
import pdfplumber

EDINBURGH_PAGE = "https://www.ed.ac.uk/studying/international/postgraduate-entry/asia/china"


def parse_edinburgh_pdf(pdf_path: str) -> list[dict]:
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for line in table:
                    cells = [c.strip() for c in line if c and c.strip()]
                    if len(cells) < 2:
                        continue
                    name, band = cells[0], cells[-1]      # 列序按实际PDF核实
                    if "band" in band.lower() or band in ("A", "B", "C", "D"):
                        rows.append({"uk_uni_id": "edinburgh", "cn_name_raw": name,
                                     "band": f"Band{band[-1]}", "min_avg_score": None})
    return rows
```
`--source edinburgh` 分支：先 requests 抓页面找 PDF 链接 → 下载到 snapshots/ → 调 parse_edinburgh_pdf → 走同一 UPSERT。Band 对应均分线（A 85/B 80 等）不在爬虫硬编码，放 Task 6 的 entry_requirement 模型。

- [ ] **Step 3: dry-run + 入库**

Run: `python sync_uk_official_lists.py --source edinburgh --dry-run && python sync_uk_official_lists.py --source edinburgh`
Expected: 条数 ≥100；抽 5 条人工对照 PDF 原文

- [ ] **Step 4: Commit**

```bash
git add crawlers/sync_uk_official_lists.py crawlers/snapshots/
git commit -m "feat: 官方名单爬虫 — 爱丁堡 Priority List PDF 源"
```

---

### Task 5: 官方名单爬虫 — Sheffield（最高风险源，XHR 优先 / 失败则人工 seed 兜底）

**Files:**
- Modify: `crawlers/sync_uk_official_lists.py` 或 Create: `dbt_liuxue/seeds/sheffield_tiers_seed.csv`

- [ ] **Step 1: 侦察 lookup 工具是否有 JSON 接口**

浏览器打开 `https://www.sheffield.ac.uk/international/entry-requirements/china`，DevTools Network 过滤 XHR，操作一次查询，记录请求 URL/参数。

- [ ] **Step 2: 二选一实现**

有 JSON 接口 → 在爬虫加 `--source sheffield`：requests 枚举 dim_cn_university 校名查询，band 取 ARWU tier1-4。
无接口（或需复杂 JS）→ **不在 MVP-1 死磕**：按官网公开的四档规则（ARWU 排名段→70/75/80/85%）做 `sheffield_tiers_seed.csv`：
```csv
uk_uni_id,band,arwu_min,arwu_max,min_avg_score,source_url,verified_at
sheffield,tier1,1,100,70,https://www.sheffield.ac.uk/international/entry-requirements/china,2026-06-20
sheffield,tier2,101,300,75,https://www.sheffield.ac.uk/international/entry-requirements/china,2026-06-20
sheffield,tier3,301,500,80,https://www.sheffield.ac.uk/international/entry-requirements/china,2026-06-20
sheffield,tier4,501,9999,85,https://www.sheffield.ac.uk/international/entry-requirements/china,2026-06-20
```
（数值执行时按官网当日核实。）此路线需 dim_cn_university 补 `arwu_rank` 列（seed 加列，高频校先填）。

- [ ] **Step 3: 验证 + Commit**

```bash
git add -A crawlers/ dbt_liuxue/seeds/
git commit -m "feat: Sheffield 四档线接入（XHR或规则seed兜底）"
```

---

### Task 6: TestDaily 种子线 + entry_requirement 统一模型

**Files:**
- Create: `dbt_liuxue/seeds/testdaily_lines_seed.csv`
- Create: `dbt_liuxue/models/uk/staging/stg_uk_official_lists.sql`
- Create: `dbt_liuxue/models/uk/mart/entry_requirement.sql`

- [ ] **Step 1: 种子线人工录入（来源 testdaily.cn/64451，全部标低可信待核）**

```csv
uk_uni_id,cn_tier,subject_group,min_avg_score,source_type,source_url,source_year,confidence,valid_until
oxford,985,通用,85,aggregator,https://www.testdaily.cn/64451/,2022,low,2026-09-01
oxford,211,通用,85,aggregator,https://www.testdaily.cn/64451/,2022,low,2026-09-01
oxford,双非,通用,90,aggregator,https://www.testdaily.cn/64451/,2022,low,2026-09-01
manchester,985,通用,80,aggregator,https://www.testdaily.cn/64451/,2022,low,2026-09-01
manchester,211,通用,80,aggregator,https://www.testdaily.cn/64451/,2022,low,2026-09-01
manchester,双非,通用,82,aggregator,https://www.testdaily.cn/64451/,2022,low,2026-09-01
```
（同格式录满 16 校 × 3 档 × 至少"通用"+"商科金融"两大类；逐条对照原文，数值不确定的行宁缺勿录。）

- [ ] **Step 2: staging 名单归一（cn_name_raw → cn_uni_id）**

```sql
-- dbt_liuxue/models/uk/staging/stg_uk_official_lists.sql
WITH raw_lists AS (
    SELECT * FROM {{ source('raw', 'uk_official_lists') }}
),
matched AS (
    SELECT
        l.uk_uni_id, l.cn_name_raw, l.band, l.min_avg_score, l.source_url, l.fetched_at,
        COALESCE(d_zh.cn_uni_id, d_en.cn_uni_id, a.cn_uni_id) AS cn_uni_id
    FROM raw_lists l
    LEFT JOIN {{ ref('dim_cn_university') }} d_zh
        ON l.cn_name_raw ILIKE '%' || d_zh.name_zh || '%'
    LEFT JOIN {{ ref('dim_cn_university') }} d_en
        ON l.cn_name_raw ILIKE '%' || d_en.name_en || '%'
    LEFT JOIN {{ ref('cn_university_alias') }} a
        ON l.cn_name_raw ILIKE '%' || a.alias || '%'
)
SELECT DISTINCT ON (uk_uni_id, cn_name_raw, band) *
FROM matched
```

- [ ] **Step 3: entry_requirement 统一两类线源**

```sql
-- dbt_liuxue/models/uk/mart/entry_requirement.sql
-- 官方名单档 → 均分线的映射常量（执行时按官网核实数值）
WITH official_band_lines AS (
    SELECT * FROM (VALUES
        ('edinburgh', 'BandA', 85.0), ('edinburgh', 'BandB', 80.0),
        ('edinburgh', 'BandC', 85.0), ('edinburgh', 'BandD', 80.0),
        ('ucl',       'in-list', 85.0),
        ('bristol',   'accepted', NULL)          -- Bristol 名单不标分,线靠种子/反推
    ) AS t(uk_uni_id, band, line)
),
official AS (
    SELECT
        o.uk_uni_id,
        '通用' AS subject_group,
        d.tier_label AS cn_tier,
        o.cn_uni_id,
        b.line AS min_avg_score,
        'official_web' AS source_type,
        o.source_url,
        'high' AS confidence
    FROM {{ ref('stg_uk_official_lists') }} o
    JOIN official_band_lines b ON b.uk_uni_id = o.uk_uni_id AND b.band = o.band
    LEFT JOIN {{ ref('dim_cn_university') }} d ON d.cn_uni_id = o.cn_uni_id
),
seed_lines AS (
    SELECT uk_uni_id, subject_group, cn_tier,
           NULL::text AS cn_uni_id,
           min_avg_score, source_type, source_url, confidence
    FROM {{ ref('testdaily_lines_seed') }}
)
SELECT * FROM official
UNION ALL
SELECT * FROM seed_lines s
-- 官方覆盖种子: 同(校,档)官方已有线则种子不出
WHERE NOT EXISTS (
    SELECT 1 FROM official o
    WHERE o.uk_uni_id = s.uk_uni_id AND o.cn_tier = s.cn_tier
      AND o.min_avg_score IS NOT NULL
)
```

- [ ] **Step 4: 运行 + 测试（_uk_models.yml 追加 source_type/confidence not_null 测试）**

Run: `cd /home/zp/work/guoji-agent/dbt_liuxue && dbt seed --select testdaily_lines_seed && dbt run --select models/uk && dbt test --select models/uk && psql "host=localhost port=5433 dbname=warehouse user=postgres password=postgres" -c "SELECT source_type, confidence, count(*) FROM entry_requirement GROUP BY 1,2"`
Expected: official_web=high 与 aggregator=low 两类都有行

- [ ] **Step 5: Commit**

```bash
git add dbt_liuxue/seeds/testdaily_lines_seed.csv dbt_liuxue/models/uk/
git commit -m "feat: entry_requirement — 官方名单线+种子线统一(官方优先)"
```

---

### Task 7: mart_uk_school_match_v1（冲/匹/保 + 雅思联动）

**Files:**
- Create: `dbt_liuxue/models/uk/mart/mart_uk_school_match_v1.sql`

- [ ] **Step 1: 实现**

```sql
-- 每行 = (英国校 × subject_group × cn_tier) 的线 + 元数据,API按学生背景查
SELECT
    e.uk_uni_id,
    u.name_zh,
    u.qs_rank,
    e.subject_group,
    e.cn_tier,
    e.min_avg_score,
    e.source_type,
    e.source_url,
    e.confidence,
    i.ielts_overall, i.ielts_l, i.ielts_r, i.ielts_w, i.ielts_s,
    i.source_url AS ielts_source_url
FROM {{ ref('entry_requirement') }} e
JOIN {{ ref('dim_uk_university') }} u USING (uk_uni_id)
LEFT JOIN {{ ref('stg_uk_ielts_requirements') }} i
    ON i.uk_uni_id = e.uk_uni_id AND i.profile_level = 'standard'
WHERE e.min_avg_score IS NOT NULL
```

- [ ] **Step 2: 运行 + 行数检查**

Run: `dbt run --select mart_uk_school_match_v1 && psql ... -c "SELECT count(DISTINCT uk_uni_id) FROM mart_uk_school_match_v1"`
Expected: ≥15 所学校有线

- [ ] **Step 3: Commit**

```bash
git add dbt_liuxue/models/uk/mart/mart_uk_school_match_v1.sql
git commit -m "feat: mart_uk_school_match_v1 — 选校定位查表层"
```

---

### Task 8: /position 端点（降级版：查表 + gap 规则 + 模板话术）

**Files:**
- Modify: `api/main.py`
- Test: `api/tests/test_position.py`

- [ ] **Step 1: 写失败测试**

```python
# api/tests/test_position.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from api import main
from api.main import app

client = TestClient(app)

FAKE_ROWS = [
    {"uk_uni_id": "manchester", "name_zh": "曼彻斯特大学", "qs_rank": 35,
     "subject_group": "通用", "cn_tier": "双非", "min_avg_score": 82.0,
     "source_type": "aggregator", "source_url": "https://www.testdaily.cn/64451/",
     "confidence": "low", "ielts_overall": 6.5, "ielts_l": 6.0, "ielts_r": 6.0,
     "ielts_w": 6.0, "ielts_s": 6.0, "ielts_source_url": "https://example.org"},
    {"uk_uni_id": "ucl", "name_zh": "伦敦大学学院", "qs_rank": 9,
     "subject_group": "通用", "cn_tier": "双非", "min_avg_score": 90.0,
     "source_type": "official_web", "source_url": "https://www.ucl.ac.uk/...",
     "confidence": "high", "ielts_overall": 7.0, "ielts_l": 6.5, "ielts_r": 6.5,
     "ielts_w": 6.5, "ielts_s": 6.5, "ielts_source_url": "https://example.org"},
]
FAKE_TIER = {"cn_uni_id": "jiangsu", "tier_label": "双非", "name_zh": "江苏大学"}


def _patch(monkeypatch):
    monkeypatch.setattr(main, "query_match_rows", lambda tier, group: FAKE_ROWS)
    monkeypatch.setattr(main, "resolve_cn_university", lambda name: FAKE_TIER)


def test_position_buckets(monkeypatch):
    _patch(monkeypatch)
    resp = client.post("/position", json={
        "undergrad_school": "江苏大学", "avg_score": 84.0,
        "undergrad_major": "软件工程", "tgt_subject_group": "通用",
        "ielts_overall": 6.5, "ielts_w": 6.0})
    assert resp.status_code == 200
    body = resp.json()
    # gap=84-82=+2 → 保 ; gap=84-90=-6 → 不建议
    bucket = {r["uk_uni_id"]: r["tier"] for r in body["schools"]}
    assert bucket["manchester"] == "保"
    assert bucket["ucl"] == "不建议"
    man = next(r for r in body["schools"] if r["uk_uni_id"] == "manchester")
    # 话术红线: aggregator 必须带"参考线"且透出来源
    assert "参考线" in man["explanation"]
    assert man["source_url"]


def test_unknown_school_candidates(monkeypatch):
    monkeypatch.setattr(main, "resolve_cn_university", lambda name: None)
    resp = client.post("/position", json={
        "undergrad_school": "霍格沃茨", "avg_score": 84.0,
        "undergrad_major": "魔法", "tgt_subject_group": "通用",
        "ielts_overall": 6.5})
    assert resp.status_code == 422   # 未归一→明确422+提示,不默默放行
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest api/tests/test_position.py -v`
Expected: FAIL

- [ ] **Step 3: 实现（追加到 api/main.py）**

```python
from rapidfuzz import fuzz, process


def resolve_cn_university(name: str) -> dict | None:
    """校名→维表行: 精确→别名→模糊(≥85分)"""
    rows = fetch_all("""
        SELECT d.cn_uni_id, d.name_zh, d.tier_label FROM dim_cn_university d
        WHERE d.name_zh = %s OR d.name_en ILIKE %s
        UNION
        SELECT d.cn_uni_id, d.name_zh, d.tier_label
        FROM cn_university_alias a JOIN dim_cn_university d USING (cn_uni_id)
        WHERE a.alias = %s
    """, (name, name, name))
    if rows:
        return rows[0]
    all_rows = fetch_all("SELECT cn_uni_id, name_zh, tier_label FROM dim_cn_university")
    best = process.extractOne(name, [r["name_zh"] for r in all_rows], scorer=fuzz.ratio)
    if best and best[1] >= 85:
        return next(r for r in all_rows if r["name_zh"] == best[0])
    return None


def query_match_rows(cn_tier: str, subject_group: str) -> list[dict]:
    return fetch_all("""
        SELECT * FROM mart_uk_school_match_v1
        WHERE cn_tier = %s AND subject_group IN (%s, '通用')
    """, (cn_tier, subject_group))


SOURCE_LABEL = {"official_web": "官方公布门槛", "official_pdf": "官方公布门槛",
                "aggregator": "第三方整理参考线，建议核对官网", "case_inferred": "历史案例估计参考线"}


def bucket_of(gap: float) -> str:
    if gap >= 2:
        return "保"
    if gap >= -2:
        return "匹"
    if gap >= -5:
        return "冲"
    return "不建议"


class PositionIn(BaseModel):
    undergrad_school: str
    avg_score: float
    undergrad_major: str
    tgt_subject_group: str
    ielts_overall: float | None = None
    ielts_l: float | None = None
    ielts_r: float | None = None
    ielts_w: float | None = None
    ielts_s: float | None = None


@app.post("/position")
def position(body: PositionIn):
    uni = resolve_cn_university(body.undergrad_school)
    if uni is None:
        raise HTTPException(422, detail={"msg": "未识别本科院校，请确认校名",
                                         "hint": "尝试输入全称，如'江苏大学'"})
    rows = query_match_rows(uni["tier_label"], body.tgt_subject_group)
    schools, waitlist = [], []
    for row in rows:
        gap = round(body.avg_score - float(row["min_avg_score"]), 1)
        tier = bucket_of(gap)
        # 雅思联动: 任一小分/总分不达标 → 降一档并标注
        ielts_flag = None
        checks = [("总分", body.ielts_overall, row.get("ielts_overall")),
                  ("写作", body.ielts_w, row.get("ielts_w")),
                  ("口语", body.ielts_s, row.get("ielts_s"))]
        for label, have, need in checks:
            if have is not None and need is not None and float(have) < float(need):
                ielts_flag = f"雅思{label}差{round(float(need)-float(have),1)}"
                tier = {"保": "匹", "匹": "冲", "冲": "不建议", "不建议": "不建议"}[tier]
                break
        # 模板话术(架构决策: 模板先行,LLM润色后置)
        explanation = (
            f"{SOURCE_LABEL[row['source_type']]}：{uni['tier_label']}背景约需均分"
            f"{row['min_avg_score']}，你的均分{body.avg_score}（差距{gap:+}）。"
            + (f"{ielts_flag}，按降一档处理。" if ielts_flag else ""))
        if row["source_type"] != "official_web" and "参考线" not in explanation:
            explanation += "（参考线，非录取承诺）"
        schools.append({
            "uk_uni_id": row["uk_uni_id"], "name_zh": row["name_zh"],
            "qs_rank": row["qs_rank"], "tier": tier, "gap": gap,
            "min_avg_score": float(row["min_avg_score"]),
            "source_type": row["source_type"], "source_url": row["source_url"],
            "confidence": row["confidence"], "ielts_flag": ielts_flag,
            "explanation": explanation,
        })
    schools.sort(key=lambda x: (x["qs_rank"] or 999))
    # 功能3嵌入选校流程(非独立入口): 复用 MVP-0 的 classify_major + 规则表
    cat = classify_major(body.undergrad_major)
    major_fit = None
    if cat:
        for rule in query_major_rules():
            if (rule["src_major_category"] == cat
                    and rule["tgt_subject_group"] == body.tgt_subject_group):
                major_fit = {"src_major_category": cat,
                             "fit_level": rule["fit_level"],
                             "required_prereqs": rule.get("required_prereqs") or ""}
                break
    return {"cn_university": uni, "schools": schools, "major_fit": major_fit,
            "waitlist_hint": "曼大/KCL等校精确线即将上线，可在 /waitlist 留邮箱"}
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest api/tests/ -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add api/main.py api/tests/test_position.py
git commit -m "feat: /position降级版 — 查表+gap分档+雅思降档+模板话术"
```

---

### Task 9: /waitlist 留资端点

**Files:**
- Modify: `api/main.py`
- Test: `api/tests/test_waitlist.py`

- [ ] **Step 1: 写失败测试**

```python
# api/tests/test_waitlist.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from api import main
from api.main import app

client = TestClient(app)


def test_waitlist_saves(monkeypatch):
    saved = {}
    monkeypatch.setattr(main, "insert_waitlist",
                        lambda email, uni, profile: saved.update(
                            {"email": email, "uni": uni}))
    resp = client.post("/waitlist", json={
        "email": "a@b.com", "uk_uni_id": "manchester", "profile": {"avg": 82}})
    assert resp.status_code == 200
    assert saved["email"] == "a@b.com"


def test_bad_email_422():
    resp = client.post("/waitlist", json={"email": "not-an-email"})
    assert resp.status_code == 422
```

- [ ] **Step 2: 实现（追加 api/main.py；db.py 加 execute 函数）**

```python
# api/db.py 追加
def execute(sql: str, params: tuple = ()) -> None:
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
```

```python
# api/main.py 追加
import json
from pydantic import EmailStr

from api.db import execute


def insert_waitlist(email: str, uk_uni_id: str | None, profile: dict | None):
    execute("INSERT INTO raw.waitlist_leads (email, uk_uni_id, profile_json) VALUES (%s,%s,%s)",
            (email, uk_uni_id, json.dumps(profile or {}, ensure_ascii=False)))


class WaitlistIn(BaseModel):
    email: EmailStr
    uk_uni_id: str | None = None
    profile: dict | None = None


@app.post("/waitlist")
def waitlist(body: WaitlistIn):
    insert_waitlist(body.email, body.uk_uni_id, body.profile)
    return {"ok": True, "msg": "已登记，上线后第一时间通知你"}
```
（`requirements.txt` 加 `email-validator` `rapidfuzz`。）

- [ ] **Step 3: 测试 + Commit**

Run: `python -m pytest api/tests/ -v` → 全 passed
```bash
git add api/
git commit -m "feat: /waitlist留资端点 — 数据缺口获客钩子"
```

---

### Task 10: Streamlit 对外前端（最小可用版）

**Files:**
- Create: `app_uk_select.py`

- [ ] **Step 1: 实现（直读 API，三类来源徽章话术按红线规范）**

```python
# app_uk_select.py — MVP-1 对外前端。运行: streamlit run app_uk_select.py
import requests
import streamlit as st

API = "http://localhost:8800"
BADGE = {"official_web": "🔵 官方公布", "official_pdf": "🔵 官方公布",
         "aggregator": "🟡 参考线·待核", "case_inferred": "⚪ 案例估计"}

st.set_page_config(page_title="英国选校定位", layout="wide")
st.title("英国选校定位 — 每个数字都有出处")

with st.form("profile"):
    c1, c2, c3 = st.columns(3)
    school = c1.text_input("本科院校", placeholder="如：江苏大学")
    score = c2.number_input("均分(百分制)", 50.0, 100.0, 82.0, 0.5)
    major = c3.text_input("本科专业", placeholder="如：软件工程")
    c4, c5 = st.columns(2)
    group = c4.selectbox("目标方向", ["通用", "商科金融", "CS与数据", "工科", "社科"])
    ielts = c5.number_input("雅思总分(可选)", 0.0, 9.0, 6.5, 0.5)
    submitted = st.form_submit_button("看我能上哪些学校", use_container_width=True)

if submitted:
    r = requests.post(f"{API}/position", json={
        "undergrad_school": school, "avg_score": score, "undergrad_major": major,
        "tgt_subject_group": group, "ielts_overall": ielts or None}, timeout=30)
    if r.status_code == 422:
        st.error(r.json()["detail"]["msg"])
    else:
        data = r.json()
        st.caption(f"识别院校：{data['cn_university']['name_zh']}"
                   f"（{data['cn_university']['tier_label']}）")
        for bucket, emoji in [("冲", "🚀"), ("匹", "🎯"), ("保", "🛡️")]:
            rows = [s for s in data["schools"] if s["tier"] == bucket]
            st.subheader(f"{emoji} {bucket} ({len(rows)})")
            for s in rows:
                with st.container(border=True):
                    st.markdown(f"**{s['name_zh']}** (QS {s['qs_rank']})　"
                                f"{BADGE[s['source_type']]}")
                    st.write(s["explanation"])
                    st.markdown(f"[数据出处]({s['source_url']})")
        st.divider()
        st.info("曼大/KCL 等校精确线即将上线 👇")
        email = st.text_input("留下邮箱，上线第一时间通知你")
        if st.button("登记") and email:
            requests.post(f"{API}/waitlist", json={"email": email}, timeout=10)
            st.success("已登记！")
        st.caption("免责声明：录取结果由学校最终决定，本平台数据用于规划参考。")
```

- [ ] **Step 2: 北极星用例全链路冒烟**

Run: `uvicorn api.main:app --port 8800 & streamlit run app_uk_select.py --server.port 8501 --server.headless true & sleep 5 && curl -s -X POST http://localhost:8800/position -H 'Content-Type: application/json' -d '{"undergrad_school":"江苏大学","avg_score":82,"undergrad_major":"软件工程","tgt_subject_group":"通用","ielts_overall":6.5}' | python -m json.tool | head -40; kill %1 %2`
Expected: 返回 ≥10 所学校，含三类徽章字段；浏览器打开 8501 手动走一遍北极星用例

- [ ] **Step 3: Commit**

```bash
git add app_uk_select.py
git commit -m "feat: Streamlit对外前端 — 北极星用例+三类徽章+waitlist"
```

---

### Task 11: 发布门禁执行（MVP-1 阻断项）

**Files:**
- Create: `docs/superpowers/plans/mvp1-acceptance.md`

- [ ] **Step 1: 公开名单判定抽检（门禁：零错误）**

从 dim_cn_university 随机抽 50 所 × UCL/Bristol/爱丁堡，对照官网名单核 in/out 与档位，记录到验收文档。错 1 个 = 阻断，修数据重验。

- [ ] **Step 2: 种子线逐条复核**

testdaily_lines_seed 每行对照原文，标"采用/剔除/降级"决定。剔除行直接删 seed 重跑。

- [ ] **Step 3: 北极星用例验收**

「双非/82分/软工/通用/雅思6.5」→ 必须返回 ≥10 校、冲匹保每档 ≥2、每行有来源徽章+出处链接、aggregator 行含"参考线"字样。截图存档。

- [ ] **Step 4: 全量回归 + Commit**

Run: `python -m pytest crawlers/tests api/tests -v && ./run-pipeline.sh uk`
```bash
git add docs/superpowers/plans/mvp1-acceptance.md
git commit -m "docs: MVP-1 发布门禁验收记录"
```
