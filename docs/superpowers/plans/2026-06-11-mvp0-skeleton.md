# MVP-0「内测骨架版」实施计划（W1-2）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复三个存量爬虫 bug，建立英联邦 raw 层 schema，上线功能 4（雅思 gap）与功能 3（专业对口规则版）两个内测 API，跑通"输入背景→结构化输出+来源标注"骨架。

**Architecture:** 爬虫解析函数抽成可单测的纯函数模块；DDL 迁移脚本扩展 raw 层；dbt 新增 `models/uk/` 支线（seed 驱动的两张维表）；FastAPI 薄查表层。雅思要求 MVP-0 用人工核实的 seed（10 校），Top30 爬虫留给 MVP-1。

**Tech Stack:** Python 3.10+ / pytest / psycopg2 / dbt-postgres / FastAPI / Postgres(docker, port 5433)

**环境约定:** 数据库 DSN 与 `run-pipeline.sh` 一致：`host=localhost port=5433 dbname=warehouse user=postgres password=postgres`。dbt 在 `dbt_liuxue/` 目录运行，profile 名 `liuxue`。

---

### Task 1: 测试基建 + 修复 parse_gpa 钳制脏值 bug

**Files:**
- Create: `crawlers/tests/__init__.py`（空文件）
- Create: `crawlers/tests/test_parsers.py`
- Modify: `crawlers/sync_1point3acres.py:202-207`

当前 bug：`return v if 0 < v <= 4.0 or 0 < v <= 100 else min(v, 4.0)` —— `0 < v <= 100` 覆盖了前一个条件，else 只在 v>100 时触发，把 `3.8/4.0` 这类文本中误抓的 `3.84.0`、或 `985` 这类脏值钳成 `4.0`，制造假 4.0 制数据。

- [ ] **Step 1: 写失败测试**

```python
# crawlers/tests/test_parsers.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sync_1point3acres import parse_gpa


class TestParseGpa:
    def test_normal_4scale(self):
        assert parse_gpa("3.8/4.0") == 3.8

    def test_normal_percent(self):
        assert parse_gpa("88.5") == 88.5

    def test_garbage_over_100_returns_none(self):
        # bug 回归：>100 的脏值必须返回 None，不能钳成 4.0
        assert parse_gpa("985") is None

    def test_empty(self):
        assert parse_gpa("") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/zp/work/guoji-agent/crawlers && python -m pytest tests/test_parsers.py -v`
Expected: `test_garbage_over_100_returns_none` FAIL（返回 4.0 而非 None）

- [ ] **Step 3: 修复实现**

```python
# crawlers/sync_1point3acres.py — 替换 parse_gpa 全函数
def parse_gpa(text: str) -> float | None:
    m = re.search(r"(\d+\.?\d*)", text)
    if m:
        v = float(m.group(1))
        return v if 0 < v <= 100 else None   # >100 是脏值，raw 层不做制式换算
    return None
```

- [ ] **Step 4: 运行确认通过**

Run: `cd /home/zp/work/guoji-agent/crawlers && python -m pytest tests/test_parsers.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add crawlers/tests/ crawlers/sync_1point3acres.py
git commit -m "fix: parse_gpa 不再把超100脏值钳成假4.0制数据"
```

---

### Task 2: 共享 decision 归一模块（修子串误判 + 识别 con/uncon offer）

**Files:**
- Create: `crawlers/normalize.py`
- Test: `crawlers/tests/test_normalize.py`

两个爬虫各自用 `"ad" in dr` 子串匹配（1p3a L155 / gter L131），"grad"/"madrid" 会误判成 Offer；且都不识别英联邦的 Conditional/Unconditional。DRY：抽成共享函数。

- [ ] **Step 1: 写失败测试**

```python
# crawlers/tests/test_normalize.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from normalize import normalize_decision


class TestNormalizeDecision:
    def test_ad_word(self):
        assert normalize_decision("AD小奖") == ("Offer", None)

    def test_offer(self):
        assert normalize_decision("Offer") == ("Offer", None)

    def test_grad_not_misjudged(self):
        # bug 回归："graduate" 含 "ad" 子串但不是 Offer
        assert normalize_decision("graduate program info") == ("Other", None)

    def test_conditional(self):
        assert normalize_decision("Conditional Offer") == ("Offer", "Conditional")
        assert normalize_decision("con offer 雅思还差0.5") == ("Offer", "Conditional")
        assert normalize_decision("有条件录取") == ("Offer", "Conditional")

    def test_unconditional_checked_before_con(self):
        # "uncon" 含 "con" 子串，必须先判 uncon
        assert normalize_decision("Unconditional Offer") == ("Offer", "Unconditional")
        assert normalize_decision("uncon了") == ("Offer", "Unconditional")

    def test_rejected(self):
        assert normalize_decision("Rejected") == ("Rejected", None)
        assert normalize_decision("拒信") == ("Rejected", None)

    def test_waitlist_interview_other(self):
        assert normalize_decision("WL") == ("Waitlist", None)
        assert normalize_decision("interview invite") == ("Interview", None)
        assert normalize_decision("") == ("Other", None)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/zp/work/guoji-agent/crawlers && python -m pytest tests/test_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'normalize'`

- [ ] **Step 3: 实现**

```python
# crawlers/normalize.py
"""录取结果归一：两爬虫共享。返回 (decision, decision_detail)。"""
from __future__ import annotations

import re


def normalize_decision(raw: str) -> tuple[str, str | None]:
    dr = (raw or "").strip().lower()
    if not dr:
        return ("Other", None)

    detail = None
    # 顺序敏感：uncon 先于 con（子串包含）
    if "uncon" in dr or "无条件" in dr:
        detail = "Unconditional"
    elif "con" in dr or "条件" in dr:
        detail = "Conditional"

    if "offer" in dr or re.search(r"\bad\b", dr) or detail:
        return ("Offer", detail)
    if "reject" in dr or "rej" in dr or "拒" in dr:
        return ("Rejected", None)
    if "wl" in dr or "wait" in dr:
        return ("Waitlist", None)
    if "interview" in dr or "面试" in dr:
        return ("Interview", None)
    return ("Other", None)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd /home/zp/work/guoji-agent/crawlers && python -m pytest tests/test_normalize.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add crawlers/normalize.py crawlers/tests/test_normalize.py
git commit -m "feat: 共享decision归一模块 — 修子串误判+识别con/uncon offer"
```

---

### Task 3: 雅思小分解析扩展

**Files:**
- Modify: `crawlers/sync_1point3acres.py:218-231`（parse_english）
- Test: `crawlers/tests/test_parsers.py`（追加）

- [ ] **Step 1: 写失败测试（追加到 test_parsers.py）**

```python
from sync_1point3acres import parse_english


class TestParseEnglish:
    def test_toefl_only(self):
        assert parse_english("TOEFL 105") == (105, None, None, None, None, None)

    def test_ielts_total_only(self):
        assert parse_english("IELTS 7.0") == (None, 7.0, None, None, None, None)

    def test_ielts_with_subscores_paren(self):
        # 常见写法 "IELTS 7(6.5)" = 总分7 小分最低6.5 → 总分提取,小分写W(最常见短板)不可靠,只提取总分
        assert parse_english("IELTS 7(6.5)")[1] == 7.0

    def test_ielts_lrws(self):
        toefl, total, l, r, w, s = parse_english("IELTS 7.0 L7R7.5W6S6.5")
        assert (total, l, r, w, s) == (7.0, 7.0, 7.5, 6.0, 6.5)

    def test_ielts_chinese_subscores(self):
        toefl, total, l, r, w, s = parse_english("雅思7 听7读7.5写6说6.5")
        assert (l, r, w, s) == (7.0, 7.5, 6.0, 6.5)

    def test_bare_number_toefl(self):
        assert parse_english("108")[0] == 108
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/zp/work/guoji-agent/crawlers && python -m pytest tests/test_parsers.py -v`
Expected: TestParseEnglish 全部 FAIL（返回值是 2 元组）

- [ ] **Step 3: 实现（替换 parse_english 全函数）**

```python
# crawlers/sync_1point3acres.py
def parse_english(text: str) -> tuple[int | None, float | None, float | None,
                                       float | None, float | None, float | None]:
    """返回 (toefl, ielts_total, ielts_l, ielts_r, ielts_w, ielts_s)"""
    toefl, ielts = None, None
    l = r = w = s = None

    m = re.search(r"TOEFL\s*(\d+)", text, re.IGNORECASE)
    if m:
        toefl = int(m.group(1))
    m = re.search(r"(?:IELTS|雅思)\s*(\d+\.?\d*)", text, re.IGNORECASE)
    if m:
        ielts = float(m.group(1))

    # 小分: L7R7.5W6S6.5 / 听7读7.5写6说6.5
    pairs = {"l": r"[Ll听]\s*(\d\.?\d?)", "r": r"[Rr读]\s*(\d\.?\d?)",
             "w": r"[Ww写]\s*(\d\.?\d?)", "s": r"[Ss说]\s*(\d\.?\d?)"}
    subs = {}
    for key, pat in pairs.items():
        mm = re.search(pat, text)
        if mm:
            v = float(mm.group(1))
            if 3.0 <= v <= 9.0:
                subs[key] = v
    if len(subs) >= 2:   # 至少命中2项才认为是小分写法,防误匹配
        l, r, w, s = subs.get("l"), subs.get("r"), subs.get("w"), subs.get("s")

    if not toefl and not ielts:
        mm = re.search(r"(\d{3})", text)
        if mm and 100 <= int(mm.group(1)) <= 120:
            toefl = int(mm.group(1))
    return toefl, ielts, l, r, w, s
```

注意：`Task 3` 改了返回值元数，`parse_list_page` L135 的调用点同步改：
```python
toefl, ielts, ielts_l, ielts_r, ielts_w, ielts_s = parse_english(english_score)
```
record dict（L174-192）追加四个键：`"ielts_l": ielts_l, "ielts_r": ielts_r, "ielts_w": ielts_w, "ielts_s": ielts_s`（入库列在 Task 5 wiring 时一起加）。

- [ ] **Step 4: 运行确认通过**

Run: `cd /home/zp/work/guoji-agent/crawlers && python -m pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add crawlers/sync_1point3acres.py crawlers/tests/test_parsers.py
git commit -m "feat: parse_english 支持雅思四项小分解析"
```

---

### Task 4: raw 层 DDL 迁移

**Files:**
- Create: `migrations/001_uk_schema.sql`

- [ ] **Step 1: 写迁移脚本**

```sql
-- migrations/001_uk_schema.sql
-- 英联邦支线 raw 层扩展。幂等：可重复执行。

ALTER TABLE raw.liuxue_admissions
    ADD COLUMN IF NOT EXISTS country         TEXT,
    ADD COLUMN IF NOT EXISTS decision_detail TEXT,
    ADD COLUMN IF NOT EXISTS ielts_l         NUMERIC(2,1),
    ADD COLUMN IF NOT EXISTS ielts_r         NUMERIC(2,1),
    ADD COLUMN IF NOT EXISTS ielts_w         NUMERIC(2,1),
    ADD COLUMN IF NOT EXISTS ielts_s         NUMERIC(2,1);

CREATE TABLE IF NOT EXISTS raw.uk_ielts_requirements (
    id            SERIAL PRIMARY KEY,
    uk_school     TEXT NOT NULL,
    profile_level TEXT NOT NULL DEFAULT 'standard',  -- 学校自己的档位原文,如 Standard/Higher
    ielts_overall NUMERIC(2,1) NOT NULL,
    ielts_l       NUMERIC(2,1),
    ielts_r       NUMERIC(2,1),
    ielts_w       NUMERIC(2,1),
    ielts_s       NUMERIC(2,1),
    subject_hint  TEXT,                    -- 该档适用专业说明原文,dbt 层展开到 subject_group
    source_url    TEXT NOT NULL,
    valid_until   DATE,
    verified_at   DATE NOT NULL,
    UNIQUE (uk_school, profile_level)
);
```

- [ ] **Step 2: 执行并验证**

Run: `psql "host=localhost port=5433 dbname=warehouse user=postgres password=postgres" -f migrations/001_uk_schema.sql && psql "host=localhost port=5433 dbname=warehouse user=postgres password=postgres" -c "\d raw.liuxue_admissions" | grep -E "country|decision_detail|ielts_l"`
Expected: 新列出现；再跑一遍脚本无报错（幂等）

- [ ] **Step 3: Commit**

```bash
git add migrations/001_uk_schema.sql
git commit -m "feat: raw层英联邦扩展 — country/decision_detail/雅思小分列+雅思要求表"
```

---

### Task 5: 两爬虫接线（country / decision_detail / 小分入库 + gter 全列修复）

**Files:**
- Modify: `crawlers/sync_1point3acres.py`（UPSERT_SQL L41-50、record、main 入库行、--fid 参数）
- Modify: `crawlers/sync_gter.py`（UPSERT_SQL L39-47、build_record L127-138）

- [ ] **Step 1: 1p3a 接线**

UPSERT_SQL 列清单改为：
```python
UPSERT_SQL = """
INSERT INTO raw.liuxue_admissions
    (school, program, degree, season, year, decision, decision_detail, gpa,
     gre, gre_v, gre_aw, toefl, ielts, ielts_l, ielts_r, ielts_w, ielts_s,
     undergrad_school, undergrad_major, country, comment, source_url, source, crawled_at)
VALUES %s
ON CONFLICT (source_url) DO UPDATE SET
    decision = EXCLUDED.decision,
    decision_detail = EXCLUDED.decision_detail,
    gpa = EXCLUDED.gpa,
    crawled_at = EXCLUDED.crawled_at
"""
```

顶部 import 与 fid 映射：
```python
from normalize import normalize_decision

# fid → (国家, 论坛名)。82=美研版。英联邦版块 fid 上线前用浏览器核实后补充。
FID_COUNTRY = {82: "US"}
```

`parse_args` 加：`p.add_argument("--fid", type=int, default=82, help="版块ID(82=美研)")`；
`FORUM_URL` 改 `f"{BASE_URL}/forum-{{fid}}-{{page}}.html"`，main 里 `url = FORUM_URL.format(fid=args.fid, page=page)`。

decision 块（L152-162）替换为：
```python
            decision, decision_detail = normalize_decision(result_info)
```
record dict 加 `"decision_detail": decision_detail, "country": FID_COUNTRY.get(args.fid)`（args 需传入 parse_list_page 或在 main 里补 country——选简单的：main 里 `r["country"] = FID_COUNTRY.get(args.fid)`）。

main 入库 rows.append 按新列清单同步扩展（顺序必须与 UPSERT_SQL 完全一致）。

- [ ] **Step 2: gter 接线（修 10 列 bug）**

先核实 API 实际字段：
Run: `cd /home/zp/work/guoji-agent/crawlers && python -c "
import requests
r = requests.get('https://offer.gter.net/api/lists?page=1&limit=3', headers={'User-Agent':'Mozilla/5.0'}, timeout=30)
import json; print(json.dumps(r.json()['data']['data'][0], ensure_ascii=False, indent=2))"`
Expected: 打印一条 item 的全部键。记录是否有 gpa/语言/本科校/地区类字段（agent 调研判断这些登录可见，大概率没有——没有就只接 decision_detail，其余列入库 NULL）。

UPSERT_SQL 改为与 1p3a 相同的全列清单（两边一致才不会再漏列）。
`build_record` 的 decision 块（L127-138）替换为：
```python
    decision, decision_detail = normalize_decision(item.get("apply_results") or "")
```
return dict 补齐全列（无数据的填 None）：`"decision_detail": decision_detail, "gpa": None, "gre": None, "gre_v": None, "gre_aw": None, "toefl": None, "ielts": None, "ielts_l": None, "ielts_r": None, "ielts_w": None, "ielts_s": None, "undergrad_school": None, "undergrad_major": None, "country": None`（若 Step 2 发现 API 有这些字段，则解析填入）。
main 的 rows.append 同步扩展。

- [ ] **Step 3: dry-run 验证两爬虫**

Run: `cd /home/zp/work/guoji-agent/crawlers && python sync_gter.py --dry-run --max-pages 2`
Expected: 正常打印记录，无 KeyError；con offer 记录显示 decision=Offer。
Run: `python -m pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 4: 小批量真实入库验证**

Run: `cd /home/zp/work/guoji-agent/crawlers && python sync_gter.py --max-pages 5 && psql "host=localhost port=5433 dbname=warehouse user=postgres password=postgres" -c "SELECT decision, decision_detail, count(*) FROM raw.liuxue_admissions WHERE source='gter' GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10"`
Expected: 出现 decision_detail='Conditional'/'Unconditional' 的行（寄托英联邦 offer 多，con offer 常见）

- [ ] **Step 5: Commit**

```bash
git add crawlers/sync_1point3acres.py crawlers/sync_gter.py
git commit -m "fix: gter全列入库+两爬虫接入decision归一/小分/country"
```

---

### Task 6: dbt 英联邦支线基建（sources 补登 + seeds 两张维表）

**Files:**
- Modify: `dbt_liuxue/models/staging/_sources.yml`
- Modify: `dbt_liuxue/dbt_project.yml`
- Create: `dbt_liuxue/seeds/dim_uk_university.csv`
- Create: `dbt_liuxue/seeds/dim_major_mapping.csv`
- Create: `dbt_liuxue/seeds/properties.yml`

- [ ] **Step 1: _sources.yml 追加（蓝图点名的"第一坑"）**

在现有 `tables:` 下追加：
```yaml
      - name: liuxue_admissions
        description: 一亩三分地+寄托 中文站录取案例（英联邦反推核心源）
        columns:
          - name: school
          - name: program
          - name: degree
          - name: decision
          - name: decision_detail
          - name: gpa
          - name: ielts
          - name: ielts_l
          - name: ielts_r
          - name: ielts_w
          - name: ielts_s
          - name: undergrad_school
          - name: undergrad_major
          - name: country
          - name: source
          - name: source_url
      - name: uk_ielts_requirements
        description: 英国大学雅思要求（官方采集）
```

- [ ] **Step 2: dbt_project.yml 加 uk 支线与 seeds 配置**

```yaml
# models: 节追加（与 staging 同级缩进，放 liuxue_warehouse: 下）
    uk:
      staging:
        +materialized: view
      mart:
        +materialized: table

# 文件末尾追加顶级节
seeds:
  liuxue_warehouse:
    +schema: public
```

- [ ] **Step 3: dim_uk_university seed（Top30，QS 排名按 2026 版填写后核实）**

```csv
uk_uni_id,name_en,name_zh,qs_rank,list_is_public,banding_scheme
oxford,University of Oxford,牛津大学,4,false,tier-985-211-other
cambridge,University of Cambridge,剑桥大学,6,false,tier-985-211-other
imperial,Imperial College London,帝国理工学院,2,false,none-published
ucl,University College London,伦敦大学学院,9,true,list-in-out
lse,London School of Economics,伦敦政治经济学院,50,false,none-published
edinburgh,University of Edinburgh,爱丁堡大学,27,true,priority-band-ABCD
manchester,University of Manchester,曼彻斯特大学,35,false,internal-list
kcl,King's College London,伦敦国王学院,31,false,internal-list
bristol,University of Bristol,布里斯托大学,51,true,accepted-list
warwick,University of Warwick,华威大学,69,false,four-tier
glasgow,University of Glasgow,格拉斯哥大学,79,false,internal-list
leeds,University of Leeds,利兹大学,86,false,internal-list
southampton,University of Southampton,南安普顿大学,80,false,internal-list
sheffield,University of Sheffield,谢菲尔德大学,92,true,arwu-four-tier
birmingham,University of Birmingham,伯明翰大学,76,false,internal-list
nottingham,University of Nottingham,诺丁汉大学,97,false,internal-list
durham,Durham University,杜伦大学,89,false,internal-list
york,University of York,约克大学,146,false,none-published
newcastle,Newcastle University,纽卡斯尔大学,129,false,internal-list
liverpool,University of Liverpool,利物浦大学,165,false,internal-list
exeter,University of Exeter,埃克塞特大学,169,false,internal-list
bath,University of Bath,巴斯大学,150,false,internal-list
cardiff,Cardiff University,卡迪夫大学,186,false,internal-list
qmul,Queen Mary University of London,伦敦玛丽女王大学,120,false,internal-list
lancaster,Lancaster University,兰卡斯特大学,141,false,internal-list
st_andrews,University of St Andrews,圣安德鲁斯大学,104,false,none-published
loughborough,Loughborough University,拉夫堡大学,212,false,internal-list
leicester,University of Leicester,莱斯特大学,272,false,internal-list
reading,University of Reading,雷丁大学,异常值核实,false,internal-list
sussex,University of Sussex,萨塞克斯大学,246,false,internal-list
```
执行时逐行核实 qs_rank（来源 topuniversities.com），`reading` 行的排名占位必须替换为真实值。

- [ ] **Step 4: dim_major_mapping seed（核心 24 行起步，标 reviewed=false 待顾问 H1 扩展）**

```csv
src_major_category,tgt_subject_group,fit_level,required_prereqs,note,reviewed
计算机类,CS与数据,对口,,本科CS/软工直申,false
数学统计类,CS与数据,可转,编程基础;数据结构,需课程描述佐证,false
电子电气类,CS与数据,可转,编程基础,EE转CS英国接受度高,false
机械自动化类,CS与数据,可转,编程基础;数学,部分校仅收转换课程,false
文科类,CS与数据,不可转,,可申conversion course另议,false
计算机类,工科,对口,,,false
电子电气类,工科,对口,,,false
机械自动化类,工科,对口,,,false
土木建筑类,工科,对口,,,false
数学统计类,商科金融,可转,,金融数学/金工友好,false
经济金融类,商科金融,对口,,,false
管理类,商科金融,对口,,纯管理转金融部分校卡量化课,false
文科类,商科金融,可转,数学基础,管理/市场方向可,false
计算机类,商科金融,可转,,商业分析/金科友好,false
经济金融类,社科,对口,,,false
文科类,社科,对口,,,false
文科类,传媒,对口,,,false
管理类,传媒,可转,,营销传播方向,false
文科类,教育,对口,,,false
理科类,教育,可转,,学科教学方向,false
理科类,理科,对口,,,false
数学统计类,理科,对口,,,false
法学类,法律,对口,,,false
文科类,法律,可转,,部分LLM收非法本,false
```

- [ ] **Step 5: seeds/properties.yml（schema 测试）**

```yaml
version: 2
seeds:
  - name: dim_uk_university
    columns:
      - name: uk_uni_id
        tests: [unique, not_null]
  - name: dim_major_mapping
    columns:
      - name: fit_level
        tests:
          - accepted_values:
              values: ['对口', '可转', '不可转']
```

- [ ] **Step 6: 跑 seed + 测试**

Run: `cd /home/zp/work/guoji-agent/dbt_liuxue && dbt seed && dbt test --select dim_uk_university dim_major_mapping`
Expected: seed 2 张表落库，tests 全 PASS

- [ ] **Step 7: Commit**

```bash
git add dbt_liuxue/models/staging/_sources.yml dbt_liuxue/dbt_project.yml dbt_liuxue/seeds/
git commit -m "feat: dbt英联邦支线基建 — sources补登liuxue_admissions+两张seed维表"
```

---

### Task 7: 雅思要求 seed（10 校人工核实版）+ dim_ielts_requirement 模型

**Files:**
- Create: `dbt_liuxue/seeds/uk_ielts_seed.csv`
- Create: `dbt_liuxue/models/uk/staging/stg_uk_ielts_requirements.sql`
- Create: `dbt_liuxue/models/uk/staging/_uk_models.yml`

- [ ] **Step 1: 人工核实并填写 seed（这一步是数据采集，必须逐条开官网核对）**

逐校访问官网 English language requirements 页，按下面格式填写。**source_url 必填官网原页，verified_at 填核对当日**。覆盖 10 校：manchester, edinburgh, ucl, bristol, sheffield, kcl, warwick, glasgow, leeds, southampton。每校至少 standard 一档，有 higher 档的填两行。

```csv
uk_uni_id,profile_level,ielts_overall,ielts_l,ielts_r,ielts_w,ielts_s,subject_hint,source_url,verified_at,valid_until
manchester,standard,6.5,6.0,6.0,6.0,6.0,多数理工科,https://www.manchester.ac.uk/study/international/admissions/language-requirements/,2026-06-12,2027-09-01
manchester,higher,7.0,6.5,6.5,6.5,6.5,商学院/人文,https://www.manchester.ac.uk/study/international/admissions/language-requirements/,2026-06-12,2027-09-01
```
（其余 8 校同格式补全——数值以官网当日实查为准，**计划中不预填未核实数字**。）

- [ ] **Step 2: staging 模型**

```sql
-- dbt_liuxue/models/uk/staging/stg_uk_ielts_requirements.sql
SELECT
    uk_uni_id,
    profile_level,
    ielts_overall, ielts_l, ielts_r, ielts_w, ielts_s,
    subject_hint,
    source_url,
    verified_at,
    valid_until,
    (valid_until < CURRENT_DATE) AS is_stale
FROM {{ ref('uk_ielts_seed') }}
```

- [ ] **Step 3: 模型测试**

```yaml
# dbt_liuxue/models/uk/staging/_uk_models.yml
version: 2
models:
  - name: stg_uk_ielts_requirements
    columns:
      - name: ielts_overall
        tests: [not_null]
      - name: source_url
        tests: [not_null]
```

- [ ] **Step 4: 运行验证**

Run: `cd /home/zp/work/guoji-agent/dbt_liuxue && dbt seed --select uk_ielts_seed && dbt run --select stg_uk_ielts_requirements && dbt test --select stg_uk_ielts_requirements`
Expected: PASS；`psql ... -c "SELECT count(*) FROM stg_uk_ielts_requirements"` ≥ 10

- [ ] **Step 5: Commit**

```bash
git add dbt_liuxue/seeds/uk_ielts_seed.csv dbt_liuxue/models/uk/
git commit -m "feat: 雅思要求seed(10校官网核实)+staging模型"
```

---

### Task 8: FastAPI 骨架 + /ielts-gap 端点

**Files:**
- Create: `api/__init__.py`（空）
- Create: `api/db.py`
- Create: `api/main.py`
- Test: `api/tests/test_ielts_gap.py`
- Create: `api/requirements.txt`（`fastapi\nuvicorn\npsycopg2-binary\nhttpx\npytest`）

- [ ] **Step 1: 写失败测试**

```python
# api/tests/test_ielts_gap.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from api import main
from api.main import app

client = TestClient(app)

FAKE_REQ = [{
    "uk_uni_id": "manchester", "profile_level": "standard",
    "ielts_overall": 6.5, "ielts_l": 6.0, "ielts_r": 6.0,
    "ielts_w": 6.0, "ielts_s": 6.0,
    "source_url": "https://example.org", "verified_at": "2026-06-12",
    "is_stale": False,
}]


def test_gap_subscore_short(monkeypatch):
    monkeypatch.setattr(main, "query_ielts_req", lambda uni: FAKE_REQ)
    resp = client.get("/ielts-gap", params={
        "uk_uni_id": "manchester",
        "overall": 7.0, "l": 6.5, "r": 6.5, "w": 5.5, "s": 6.0})
    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["gaps"]["overall"] == 0          # 7.0 >= 6.5 达标
    assert body["gaps"]["w"] == 0.5              # 写作差 0.5 —— 核心场景
    assert body["passed"] is False
    assert body["source_url"]                    # 来源必须透出


def test_unknown_school_404(monkeypatch):
    monkeypatch.setattr(main, "query_ielts_req", lambda uni: [])
    resp = client.get("/ielts-gap", params={"uk_uni_id": "hogwarts", "overall": 7.0})
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/zp/work/guoji-agent && python -m pytest api/tests/test_ielts_gap.py -v`
Expected: FAIL（main 不存在）

- [ ] **Step 3: 实现**

```python
# api/db.py
import os
import psycopg2
import psycopg2.extras

DSN = os.environ.get("WAREHOUSE_DSN",
    "host=localhost port=5433 dbname=warehouse user=postgres password=postgres")


def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    with psycopg2.connect(DSN) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
```

```python
# api/main.py
from fastapi import FastAPI, HTTPException

from api.db import fetch_all

app = FastAPI(title="英联邦留学选校 API", version="0.1.0")


def query_ielts_req(uk_uni_id: str) -> list[dict]:
    return fetch_all(
        "SELECT * FROM stg_uk_ielts_requirements WHERE uk_uni_id = %s", (uk_uni_id,))


@app.get("/ielts-gap")
def ielts_gap(uk_uni_id: str, overall: float,
              l: float | None = None, r: float | None = None,
              w: float | None = None, s: float | None = None):
    reqs = query_ielts_req(uk_uni_id)
    if not reqs:
        raise HTTPException(404, detail=f"未收录 {uk_uni_id} 的雅思要求")
    student = {"overall": overall, "l": l, "r": r, "w": w, "s": s}
    out = []
    for req in reqs:
        gaps, passed = {}, True
        for k, col in [("overall", "ielts_overall"), ("l", "ielts_l"),
                       ("r", "ielts_r"), ("w", "ielts_w"), ("s", "ielts_s")]:
            need = req.get(col)
            have = student.get(k)
            if need is None:
                continue
            if have is None:
                gaps[k] = None        # 学生未提供该项
                continue
            gap = round(max(0.0, float(need) - float(have)), 1)
            gaps[k] = gap
            if gap > 0:
                passed = False
        out.append({
            "uk_uni_id": req["uk_uni_id"],
            "profile_level": req["profile_level"],
            "requirement": {c: req.get(c) for c in
                            ("ielts_overall", "ielts_l", "ielts_r", "ielts_w", "ielts_s")},
            "gaps": gaps,
            "passed": passed,
            "source_url": req["source_url"],       # 话术红线: 来源必须透出
            "verified_at": str(req["verified_at"]),
            "stale": bool(req.get("is_stale")),
        })
    return out
```

- [ ] **Step 4: 运行确认通过**

Run: `cd /home/zp/work/guoji-agent && python -m pytest api/tests/ -v`
Expected: 2 passed

- [ ] **Step 5: 起服务冒烟（真实 DB）**

Run: `cd /home/zp/work/guoji-agent && uvicorn api.main:app --port 8800 & sleep 2 && curl -s "http://localhost:8800/ielts-gap?uk_uni_id=manchester&overall=7.0&w=5.5" | head -c 500; kill %1`
Expected: 返回 JSON，含 gaps.w=0.5、source_url

- [ ] **Step 6: Commit**

```bash
git add api/
git commit -m "feat: FastAPI骨架+/ielts-gap端点 — 小分卡线检测+来源透出"
```

---

### Task 9: /major-fit 端点

**Files:**
- Modify: `api/main.py`
- Test: `api/tests/test_major_fit.py`

- [ ] **Step 1: 写失败测试**

```python
# api/tests/test_major_fit.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from api import main
from api.main import app

client = TestClient(app)

FAKE_RULES = [
    {"src_major_category": "数学统计类", "tgt_subject_group": "CS与数据",
     "fit_level": "可转", "required_prereqs": "编程基础;数据结构",
     "note": "需课程描述佐证", "reviewed": False},
]


def test_match_keyword(monkeypatch):
    monkeypatch.setattr(main, "query_major_rules", lambda: FAKE_RULES)
    resp = client.post("/major-fit", json={
        "undergrad_major": "应用统计", "tgt_subject_group": "CS与数据"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fit_level"] == "可转"
    assert "编程基础" in body["required_prereqs"]
    assert body["reviewed"] is False     # 未经顾问复核必须透出


def test_no_match_returns_candidates(monkeypatch):
    monkeypatch.setattr(main, "query_major_rules", lambda: FAKE_RULES)
    resp = client.post("/major-fit", json={
        "undergrad_major": "口腔医学", "tgt_subject_group": "CS与数据"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fit_level"] == "待人工确认"   # 架构决策: 不在线LLM即时判
    assert isinstance(body["candidates"], list)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest api/tests/test_major_fit.py -v`
Expected: FAIL（端点不存在）

- [ ] **Step 3: 实现（追加到 api/main.py）**

```python
from pydantic import BaseModel

# 本科专业关键词 → 大类。与 seeds/dim_major_mapping.csv 的 src_major_category 对齐。
MAJOR_KEYWORDS = {
    "计算机类": ["计算机", "软件", "computer", "software", "cs", "信息安全", "物联网"],
    "数学统计类": ["数学", "统计", "math", "statistic", "精算"],
    "电子电气类": ["电子", "电气", "通信", "微电子", "ee", "electronic"],
    "机械自动化类": ["机械", "自动化", "机电", "车辆", "mechanical"],
    "土木建筑类": ["土木", "建筑", "civil", "工程管理"],
    "经济金融类": ["经济", "金融", "finance", "econom", "国贸", "投资"],
    "管理类": ["管理", "工商", "市场营销", "会计", "business", "management"],
    "文科类": ["英语", "汉语", "历史", "哲学", "新闻", "翻译", "文学"],
    "理科类": ["物理", "化学", "生物", "材料", "环境"],
    "法学类": ["法学", "法律", "law"],
}


def query_major_rules() -> list[dict]:
    return fetch_all("SELECT * FROM dim_major_mapping")


def classify_major(raw: str) -> str | None:
    low = raw.lower()
    for cat, kws in MAJOR_KEYWORDS.items():
        if any(kw in low for kw in kws):
            return cat
    return None


class MajorFitIn(BaseModel):
    undergrad_major: str
    tgt_subject_group: str


@app.post("/major-fit")
def major_fit(body: MajorFitIn):
    cat = classify_major(body.undergrad_major)
    rules = query_major_rules()
    if cat:
        for rule in rules:
            if (rule["src_major_category"] == cat
                    and rule["tgt_subject_group"] == body.tgt_subject_group):
                return {
                    "src_major_category": cat,
                    "fit_level": rule["fit_level"],
                    "required_prereqs": rule.get("required_prereqs") or "",
                    "note": rule.get("note") or "",
                    "reviewed": bool(rule.get("reviewed")),
                }
    # 架构决策: 未命中规则表返回"待人工确认"+候选，不在线 LLM 即时判
    return {
        "src_major_category": cat,
        "fit_level": "待人工确认",
        "candidates": sorted(MAJOR_KEYWORDS.keys()),
        "note": "请从候选大类中确认你的本科专业归属",
        "reviewed": False,
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest api/tests/ -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add api/main.py api/tests/test_major_fit.py
git commit -m "feat: /major-fit端点 — 规则表查询+未命中候选确认"
```

---

### Task 10: run-pipeline.sh 接入 uk 子命令

**Files:**
- Modify: `run-pipeline.sh`

- [ ] **Step 1: 在 `run_dbt()` 之后加函数，case 里注册**

```bash
# ── uk: 英联邦支线 ──────────────────────────────────────────────────────
run_uk() {
    ensure_db
    ensure_dbt_profile
    log "执行英联邦支线: migration → seed → dbt uk模型 → 测试"
    psql "$DB_DSN" -f "$SCRIPT_DIR/migrations/001_uk_schema.sql"
    cd "$SCRIPT_DIR/dbt_liuxue"
    dbt seed --select dim_uk_university dim_major_mapping uk_ielts_seed
    dbt run --select models/uk
    dbt test --select models/uk dim_uk_university dim_major_mapping
    log "英联邦支线完成"
}
```
case 中加 `uk) run_uk ;;`，用法提示同步更新。

- [ ] **Step 2: 全链路验证**

Run: `./run-pipeline.sh uk`
Expected: migration 幂等通过、seed 3 张、uk 模型 run+test 全 PASS

- [ ] **Step 3: Commit**

```bash
git add run-pipeline.sh
git commit -m "feat: run-pipeline.sh 增加 uk 子命令"
```

---

### Task 11: 内测验收（MVP-0 门禁）

**Files:**
- Create: `docs/superpowers/plans/mvp0-acceptance.md`（验收记录）

- [ ] **Step 1: 雅思抽检（发布门禁：错误率 ≤3%）**

10 校 seed 共 N 行，逐行开 source_url 对照官网四项小分，记录到验收文档表格：`行 | 官网值 | seed值 | 是否一致`。不一致 >0 行 → 修 seed 重跑 `dbt seed`。

- [ ] **Step 2: 全量测试 + 管线绿**

Run: `cd /home/zp/work/guoji-agent && python -m pytest crawlers/tests api/tests -v && ./run-pipeline.sh uk`
Expected: 全 PASS

- [ ] **Step 3: 顾问试用脚本**

验收文档中附 5 个标准用例 curl 命令（含"总分够写作差0.5"核心场景），交顾问试用并回收反馈到同一文档。

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/mvp0-acceptance.md
git commit -m "docs: MVP-0 内测验收记录"
```
