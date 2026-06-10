#!/usr/bin/env python3
"""
sync_gradcafe.py — GradCafe 录取案例爬虫 → PostgreSQL warehouse

爬取 GradCafe (thegradcafe.com) 的公开录取结果，写入目标仓库
raw.gradcafe_admissions 表。遵循 power-v2 数据平台的爬虫模式。

用法:
    python sync_gradcafe.py                          # 增量爬取（默认 500 条）
    python sync_gradcafe.py --full                   # 全量爬取（按专业分批）
    python sync_gradcafe.py --majors "Computer Science,Data Science"  # 指定专业
    python sync_gradcafe.py --max-pages 10           # 限制页数（测试用）
    python sync_gradcafe.py --dry-run                # 只爬不写

数据库:
    目标: dest-postgres:5433/warehouse (Docker 容器, 对齐 power-v2 运维手册)
    表:   raw.gradcafe_admissions

爬虫策略:
    - GradCafe 搜索页是公开 HTML 表格，无需登录
    - 每页约 25 条，请求间隔 2-3 秒避免被封
    - 增量模式: 按 submitted_date DESC 爬取，遇已存在 URL 时停止
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

import psycopg2
import psycopg2.extras
import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("sync_gradcafe")

# ── Config ────────────────────────────────────────────────────────────
GRADCAFE_BASE = "https://www.thegradcafe.com"
GRADCAFE_SEARCH = f"{GRADCAFE_BASE}/survey"

# 数据库连接（对齐 power-v2: dest-postgres:5433/warehouse）
DEFAULT_DSN = os.environ.get(
    "WAREHOUSE_DSN",
    "host=localhost port=5432 dbname=warehouse user=postgres password=postgres",
)

# 默认爬取专业（申请最火的几个方向）
DEFAULT_MAJORS = [
    "Computer Science",
    "Data Science",
    "Electrical Engineering",
    "Statistics",
    "Economics",
    "Finance",
    "Business Analytics",
    "Mechanical Engineering",
]

# 请求头
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── SQL ───────────────────────────────────────────────────────────────

CREATE_SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS raw;
"""

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS raw.gradcafe_admissions (
    id              BIGSERIAL PRIMARY KEY,
    school          TEXT NOT NULL,
    program         TEXT NOT NULL,
    degree          TEXT,
    season          TEXT,
    year            INTEGER,
    nationality     TEXT,
    decision        TEXT,
    decision_date   DATE,
    gpa             FLOAT,
    gre_q           INTEGER,
    gre_v           INTEGER,
    gre_aw          FLOAT,
    toefl           INTEGER,
    comment         TEXT,
    source_url      TEXT UNIQUE,
    major_category  TEXT,
    crawled_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gradcafe_school
    ON raw.gradcafe_admissions (school);
CREATE INDEX IF NOT EXISTS idx_gradcafe_degree_major
    ON raw.gradcafe_admissions (degree, major_category);
CREATE INDEX IF NOT EXISTS idx_gradcafe_decision
    ON raw.gradcafe_admissions (decision);
CREATE INDEX IF NOT EXISTS idx_gradcafe_gpa
    ON raw.gradcafe_admissions (gpa) WHERE gpa IS NOT NULL;
"""

UPSERT_SQL = """
INSERT INTO raw.gradcafe_admissions (
    school, program, degree, season, year,
    nationality, decision, decision_date,
    gpa, gre_q, gre_v, gre_aw, toefl,
    comment, source_url, major_category, crawled_at
) VALUES %s
ON CONFLICT (source_url) DO UPDATE SET
    decision      = EXCLUDED.decision,
    gpa           = EXCLUDED.gpa,
    gre_q         = EXCLUDED.gre_q,
    gre_v         = EXCLUDED.gre_v,
    gre_aw        = EXCLUDED.gre_aw,
    toefl         = EXCLUDED.toefl,
    crawled_at    = EXCLUDED.crawled_at
"""

# ── Arguments ──────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="GradCafe 录取案例爬虫 → warehouse.raw.gradcafe_admissions"
    )
    p.add_argument(
        "--majors",
        type=str,
        default=",".join(DEFAULT_MAJORS),
        help=f"要爬取的专业，逗号分隔（默认: {','.join(DEFAULT_MAJORS[:3])}...）",
    )
    p.add_argument("--full", action="store_true", help="全量爬取（每专业最多 50 页）")
    p.add_argument("--max-pages", type=int, default=5, help="每专业最大页数（默认 5）")
    p.add_argument("--dry-run", action="store_true", help="只爬取不写入数据库")
    p.add_argument("--init-db", action="store_true", help="仅初始化数据库表")
    return p.parse_args()


# ── Database Init ─────────────────────────────────────────────────────

def init_database(dsn: str):
    """创建 raw schema 和 gradcafe_admissions 表。"""
    log.info("初始化数据库...")
    with psycopg2.connect(dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(CREATE_SCHEMA_SQL)
            cur.execute(CREATE_TABLE_SQL)
    log.info("数据库初始化完成")


# ── Parse ─────────────────────────────────────────────────────────────

def parse_admission_row(row_soup: BeautifulSoup) -> dict | None:
    """
    解析搜索结果中的一行录取记录。

    GradCafe 搜索结果每两条 <tr> 组成一条记录：
      <tr> — 摘要行: school, program, date, decision
      <tr> — 详情行: season, nationality, GPA, GRE, TOEFL, comment

    返回 dict 或 None（解析失败）。
    """
    try:
        cells = row_soup.find_all("td")
        if len(cells) < 4:
            return None

        # 提取 school + program
        school_text = cells[0].get_text(strip=True)
        program_text = cells[1].get_text(strip=True) if len(cells) > 1 else ""

        # 提取 decision
        decision_cell = cells[3].get_text(strip=True) if len(cells) > 3 else ""
        decision, decision_date = _parse_decision(decision_cell)

        # 提取详情行（在下一个 tr 中）
        detail_text = ""
        # 尝试从 cells 的后续元素获取
        next_tr = row_soup.find_next_sibling("tr")
        if next_tr:
            detail_text = next_tr.get_text(" ", strip=True)

        # 解析详情
        data = _parse_detail(detail_text)
        data["school"] = school_text
        data["program"] = program_text
        data["decision"] = decision
        data["decision_date"] = decision_date

        # 推断学位
        data["degree"] = _infer_degree(program_text)

        # source_url
        link = cells[0].find("a") if cells[0] else None
        data["source_url"] = (
            GRADCAFE_BASE + link["href"]
            if link and link.get("href")
            else f"{GRADCAFE_SEARCH}?q={school_text}+{program_text}"
        )

        return data if data.get("school") else None

    except Exception as e:
        log.debug("解析行失败: %s", e)
        return None


def _parse_decision(text: str) -> tuple[str, str | None]:
    """解析决策文本：'Accepted on Mar 15' → ('Accepted', '2025-03-15')"""
    text = text.strip()
    for kw in ("Accepted", "Rejected", "Waitlisted", "Interview"):
        if text.lower().startswith(kw.lower()):
            date_str = text[len(kw):].strip()
            date_str = date_str.lstrip("on").strip()
            try:
                parsed = datetime.strptime(date_str, "%b %d")
                return kw, parsed.replace(year=datetime.now().year).strftime("%Y-%m-%d")
            except ValueError:
                return kw, None
    return text, None


def _parse_detail(text: str) -> dict:
    """解析详情文本：'Fall 2026 International GRE 163 GRE V 145 GPA 3.64'"""
    data: dict[str, Any] = {}

    # Season + Year
    m = re.search(r"(Fall|Spring|Summer|Winter)\s+(\d{4})", text)
    if m:
        data["season"] = m.group(1)
        data["year"] = int(m.group(2))

    # Nationality
    if "International" in text:
        data["nationality"] = "International"
    elif "American" in text:
        data["nationality"] = "American"
    elif "Other" in text:
        data["nationality"] = "Other"

    # GPA
    m = re.search(r"GPA\s+(\d+\.?\d*)", text)
    if m:
        data["gpa"] = float(m.group(1))

    # GRE Q
    m = re.search(r"GRE\s+(\d+)", text)
    if m:
        data["gre_q"] = int(m.group(1))

    # GRE V
    m = re.search(r"GRE V\s+(\d+)", text)
    if m:
        data["gre_v"] = int(m.group(1))

    # GRE AW
    m = re.search(r"GRE AW\s+(\d+\.?\d*)", text)
    if m:
        data["gre_aw"] = float(m.group(1))

    # TOEFL
    m = re.search(r"TOEFL\s+(\d+)", text)
    if m:
        data["toefl"] = int(m.group(1))

    # Comment（从第二个 <td> 中可能是评论）
    # 细节文本本身如果在单独的 td 中就是评论
    if text and len(text) > 80 and not re.search(r"GRE|GPA|TOEFL", text):
        data["comment"] = text.strip()

    return data


def _infer_degree(program: str) -> str:
    """从 program 文本推断学位层级。"""
    p = program.lower()
    if "phd" in p or "doctor" in p:
        return "PhD"
    if "master" in p or "ms " in p or "m.eng" in p or "m.a." in p or "mba" in p:
        return "Masters"
    if "bachelor" in p or "b.s." in p or "b.a." in p or "undergrad" in p:
        return "Bachelors"
    return "Other"


# ── Fetch ─────────────────────────────────────────────────────────────

def fetch_page(major: str, page: int) -> list[dict]:
    """获取单个搜索页面的录取结果。"""
    url = f"{GRADCAFE_SEARCH}?q={major}&page={page}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("请求失败 page=%d major=%s: %s", page, major, e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # GradCafe 搜索结果在 table > tbody > tr 中
    # 每两条 tr 组成一条记录
    rows = soup.select("table tr")
    results = []

    i = 0
    while i < len(rows):
        # 跳过 header row
        cells = rows[i].find_all(["th", "td"])
        if not cells or rows[i].find("th"):
            i += 1
            continue

        # 提取该行 + 下一行
        record = parse_admission_row_separate(rows[i], rows[i + 1] if i + 1 < len(rows) else None)
        if record:
            record["major_category"] = major
            results.append(record)
        i += 2  # 跳过详情行

    log.debug("page=%d: 提取 %d 条", page, len(results))
    return results


def parse_admission_row_separate(
    summary_tr: BeautifulSoup, detail_tr: BeautifulSoup | None
) -> dict | None:
    """分别解析摘要行和详情行。"""
    try:
        cells = summary_tr.find_all("td")
        if len(cells) < 4:
            return None

        school = cells[0].get_text(strip=True)
        program = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        decision_text = cells[3].get_text(strip=True) if len(cells) > 3 else ""

        decision, decision_date = _parse_decision(decision_text)
        degree = _infer_degree(program)

        # 提取 source_url
        link = cells[0].find("a") if cells[0] else None
        source_url = (
            GRADCAFE_BASE + link["href"]
            if link and link.get("href")
            else f"{GRADCAFE_SEARCH}?q={school}+{program}"
        )

        # 提取详情
        detail_text = detail_tr.get_text(" ", strip=True) if detail_tr else ""
        details = _parse_detail(detail_text)

        return {
            "school": school,
            "program": program,
            "degree": degree or details.pop("degree", None),
            "season": details.pop("season", None),
            "year": details.pop("year", None),
            "nationality": details.pop("nationality", None),
            "decision": decision,
            "decision_date": decision_date,
            "gpa": details.pop("gpa", None),
            "gre_q": details.pop("gre_q", None),
            "gre_v": details.pop("gre_v", None),
            "gre_aw": details.pop("gre_aw", None),
            "toefl": details.pop("toefl", None),
            "comment": detail_text if len(detail_text) > 50 and not _has_scores(detail_text) else None,
            "source_url": source_url,
        }

    except Exception as e:
        log.debug("parse_admission_row: %s", e)
        return None


def _has_scores(text: str) -> bool:
    """检查文本是否包含标准化考试成绩（作为详情而非评论的标志）。"""
    return bool(re.search(r"(GPA|GRE|TOEFL|IELTS)\s+\d", text))


# ── Upsert ─────────────────────────────────────────────────────────────

def upsert_records(dsn: str, records: list[dict]) -> int:
    """批量 upsert 记录到数据库。"""
    if not records:
        return 0

    now = datetime.now(timezone.utc)
    # 去重 source_url（同一批中可能有重复）
    seen_urls = set()
    rows = []
    for r in records:
        url = r.get("source_url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        rows.append((
            r.get("school"),
            r.get("program"),
            r.get("degree"),
            r.get("season"),
            r.get("year"),
            r.get("nationality"),
            r.get("decision"),
            r.get("decision_date"),
            r.get("gpa"),
            r.get("gre_q"),
            r.get("gre_v"),
            r.get("gre_aw"),
            r.get("toefl"),
            r.get("comment"),
            r["source_url"],
            r.get("major_category"),
            now,
        ))

    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, UPSERT_SQL, rows)
        conn.commit()

    return len(rows)


# ── Main ───────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    # 初始化数据库
    if args.init_db or not args.dry_run:
        init_database(DEFAULT_DSN)
    if args.init_db:
        log.info("数据库初始化完成，退出")
        return

    majors = [m.strip() for m in args.majors.split(",") if m.strip()]
    max_pages = 50 if args.full else args.max_pages

    total_inserted = 0

    for major in majors:
        log.info("开始爬取: %s (最多 %d 页)", major, max_pages)
        major_records = 0

        for page in range(1, max_pages + 1):
            records = fetch_page(major, page)
            if not records:
                log.info("  page=%d: 无结果，该专业爬取完成", page)
                break

            if not args.dry_run:
                n = upsert_records(DEFAULT_DSN, records)
                log.info("  page=%d: 写入 %d 条", page, n)
                major_records += n
            else:
                log.info("  page=%d: 预览 %d 条 (--dry-run)", page, len(records))
                for r in records[:3]:
                    log.info(
                        "    %s | %s | %s | GPA %s",
                        r.get("school", "?")[:40],
                        r.get("program", "?")[:30],
                        r.get("decision", "?"),
                        r.get("gpa", "?"),
                    )
                major_records += len(records)

            time.sleep(2 + (page % 3))  # 2-4 秒间隔

        log.info("  ✓ %s: 共 %d 条", major, major_records)
        total_inserted += major_records

    # 汇总
    if not args.dry_run:
        with psycopg2.connect(DEFAULT_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*), COUNT(DISTINCT school) FROM raw.gradcafe_admissions"
                )
                count, schools = cur.fetchone()
        log.info(
            "========================================"
            "\n  本次新增: %d 条"
            "\n  数据库总计: %d 条, %d 所学校"
            "\n========================================",
            total_inserted,
            count,
            schools,
        )
    else:
        log.info("Dry-run 完成，共预览 %d 条", total_inserted)


if __name__ == "__main__":
    main()
