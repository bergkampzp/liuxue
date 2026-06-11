#!/usr/bin/env python3
"""
sync_uk_official_lists.py — UCL & Bristol & Edinburgh 官方中国院校名单爬虫

数据源（静态 HTML）:
  UCL     https://www.ucl.ac.uk/prospective-students/international/china
           → dl.accordion > dd.accordion__description > table（两列布局）
  Bristol https://www.bristol.ac.uk/international/countries/china/accepted-universities-in-china/
           → 单列 table，th="University name" + td 行（303 条）
  Edinburgh https://www.ed.ac.uk/studying/international/postgraduate-entry/asia/china
           → 页面含 PDF 链接，下载并解析文本型 PDF（pdfplumber）

用法:
    python sync_uk_official_lists.py --source ucl
    python sync_uk_official_lists.py --source bristol
    python sync_uk_official_lists.py --source edinburgh
    python sync_uk_official_lists.py --source ucl --dry-run
    python sync_uk_official_lists.py --source ucl --from-snapshot crawlers/snapshots/ucl_china.html
    python sync_uk_official_lists.py --source edinburgh --from-snapshot crawlers/snapshots/edinburgh_priority_list.pdf
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

import psycopg2
import psycopg2.extras
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sync_uk_official_lists")

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
UCL_URL = "https://www.ucl.ac.uk/prospective-students/international/china"
BRISTOL_URL = "https://www.bristol.ac.uk/international/countries/china/accepted-universities-in-china/"
EDINBURGH_URL = "https://www.ed.ac.uk/studying/international/postgraduate-entry/asia/china"
EDINBURGH_PDF_BASE = "https://www.ed.ac.uk"
SHEFFIELD_URL = "https://www.sheffield.ac.uk/international/entry-requirements/china"
SHEFFIELD_RANKING_URL = "https://www.sheffield.ac.uk/international/entry-requirements/china/ranking-list"
EDINBURGH_SNAPSHOT_PDF = os.path.join(
    os.path.dirname(__file__), "snapshots", "edinburgh_priority_list.pdf"
)

DEFAULT_DSN = os.environ.get(
    "WAREHOUSE_DSN",
    "host=localhost port=5432 dbname=warehouse user=postgres password=postgres",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.5",
}

# 熔断阈值：解析结果低于此数则拒绝写入
MIN_RECORDS = 20

UPSERT_SQL = """
INSERT INTO raw.uk_official_lists
    (uk_uni_id, cn_name_raw, band, min_avg_score, source_url, fetched_at)
VALUES %s
ON CONFLICT (uk_uni_id, cn_name_raw, band) DO UPDATE SET
    fetched_at = EXCLUDED.fetched_at
"""


# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------
def parse_ucl(html: str) -> list[dict[str, Any]]:
    """
    解析 UCL 中国院校名单。

    DOM 结构：
      dl.accordion > dd.accordion__description > table > tbody > tr > td × 2
    两列布局，每行两所院校，空白单元格跳过。
    返回 list[{uk_uni_id, cn_name_raw, band, min_avg_score}]
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        log.warning("UCL: 未找到 table 元素")
        return []

    records: list[dict[str, Any]] = []
    for row in table.find_all("tr"):
        for cell in row.find_all("td"):
            name = cell.get_text(separator=" ", strip=True)
            # 跳过空白格
            if not name or not name.strip():
                continue
            records.append(
                {
                    "uk_uni_id": "ucl",
                    "cn_name_raw": name.strip(),
                    "band": "in-list",
                    "min_avg_score": None,
                }
            )
    log.info("UCL: 解析到 %d 条", len(records))
    return records


def parse_bristol(html: str) -> list[dict[str, Any]]:
    """
    解析 Bristol 中国接受院校名单。

    DOM 结构：
      单列 table，第一行 th="University name"，后续 td 每行一所院校。
    返回 list[{uk_uni_id, cn_name_raw, band, min_avg_score}]
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        log.warning("Bristol: 未找到 table 元素")
        return []

    records: list[dict[str, Any]] = []
    for row in table.find_all("tr"):
        # 跳过 th 行（表头）
        if row.find("th"):
            continue
        cells = row.find_all("td")
        if not cells:
            continue
        name = cells[0].get_text(strip=True)
        if not name:
            continue
        records.append(
            {
                "uk_uni_id": "bristol",
                "cn_name_raw": name,
                "band": "accepted",
                "min_avg_score": None,
            }
        )
    log.info("Bristol: 解析到 %d 条", len(records))
    return records


def parse_edinburgh_pdf(lines: list[str]) -> list[dict[str, Any]]:
    """
    解析 Edinburgh Priority List PDF 提取出的文本行列表。

    PDF 结构（October 2024，9页）：
      - 页面标题行：匹配 r'^Priority List of Chinese universities'
      - 注释段落行（Note:/designated by/.../entry to ...）：跳过
      - 主名单：从第一所院校起，到 "Appendix 1" 前（band='priority-list'）
      - Appendix 1 — 法学院（band='law-school'）
      - Appendix 2 — 艺术学院（band='art-college'）

    多行校名（校名后跟括号注释跨行）：通过括号计数合并为单条记录。

    接受 list[str]（已按行拆分的 PDF 文本），便于单元测试注入 fixture。
    """
    # ---- 跳过规则（非校名行） ----
    SKIP_RE = re.compile(
        r"^Priority List of Chinese universities"
        r"|^Note:"
        r"|^designated by"
        r"|^Discipline\."
        r"|^Discipline that is relevant"
        r"|^Appendix \d+ provides"
        r"|^entry to (Law|Art)"
        r"|^relevant degrees\)"
        r"|^College of (Medicine|Science)"
        r"|^the College of"
        r"|^\(For programmes"
        r"|^and in the College"
        r"|^in the College"
        r"|^must be in"
        r"|^be in a World Class"
        r"|^degree must be in"
        r"|^undergraduate degree must"
        r"|^postgraduate programme\."
        r"|^programme\."
        r"|^World Class Discipline"
        r"|^Class Discipline"
        r"|^is relevant"
        r"|^that is relevant"
    )

    # 三个段落的 band 标签
    SECTION_MAIN = "priority-list"
    SECTION_LAW = "law-school"
    SECTION_ART = "art-college"

    current_section = SECTION_MAIN
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    pending: list[str] = []   # 多行校名缓冲

    def flush_pending() -> None:
        """将 pending 缓冲合并为一条记录写入 records"""
        if not pending:
            return
        name = " ".join(pending).strip()
        pending.clear()
        if not name:
            return
        key = (name, current_section)
        if key in seen:
            return
        seen.add(key)
        records.append(
            {
                "uk_uni_id": "edinburgh",
                "cn_name_raw": name,
                "band": current_section,
                "min_avg_score": None,
            }
        )

    # 括号深度计数：用于判断多行注释是否结束
    open_parens = 0

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # ---- 检测 Appendix 节标题 ----
        if re.match(r"^Appendix 1\s*[–—-]", line):
            flush_pending()
            current_section = SECTION_LAW
            continue
        if re.match(r"^Appendix 2\s*[–—-]", line):
            flush_pending()
            current_section = SECTION_ART
            continue

        # ---- 跳过非校名行（在没有待积累校名时） ----
        if open_parens == 0 and SKIP_RE.match(line):
            continue

        # ---- 追加到当前校名缓冲 ----
        pending.append(line)
        open_parens += line.count("(") - line.count(")")

        # 括号已闭合（= 0）：可以 flush
        if open_parens <= 0:
            open_parens = 0
            flush_pending()

    flush_pending()
    log.info("Edinburgh: 解析到 %d 条 (main/law/art)", len(records))
    return records


def parse_sheffield(html: str) -> list[dict[str, Any]]:
    """
    解析 Sheffield 中国院校分档名单。

    数据源：https://www.sheffield.ac.uk/international/entry-requirements/china/ranking-list
    DOM 结构：
      单个 table，列顺序：
        0: Name of Institution (English)
        1: Name of Institution (Chinese)
        2: Grade Equivalent to UK 2:1  → 用于确定 band
        3: Grade Equivalent to UK 2:2
        4: Additional Information

    Band 映射（按页面 ARWU 分档表）：
      70%  → arwu-tier1  (ARWU Top 100 + 985/211/双一流)
      75%  → arwu-tier2  (ARWU 101-300)
      80%  → arwu-tier3  (ARWU 301-500)
      85%  → arwu-tier4  (ARWU 501+ / 其他院校)
      见附加信息        → see-additional (专科升本等)
      GPA/CGPA 制      → gpa-scale

    返回 list[{uk_uni_id, cn_name_raw, band, min_avg_score}]
    其中 min_avg_score 为 UK 2:1 对应百分制成绩（整数）或 None。
    """
    GRADE_BAND: dict[str, tuple[str, int | None]] = {
        "70%": ("arwu-tier1", 70),
        "75%": ("arwu-tier2", 75),
        "80%": ("arwu-tier3", 80),
        "85%": ("arwu-tier4", 85),
        "2.1": ("arwu-tier1", 70),  # 少数按 2.1 标注，对应 tier1
    }

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        log.warning("Sheffield: 未找到 table 元素")
        return []

    rows = table.find_all("tr")
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for row in rows[1:]:  # 跳过表头行
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        eng_name = cells[0].get_text(separator=" ", strip=True)
        grade_21 = cells[2].get_text(strip=True)

        if not eng_name:
            continue

        # 确定 band 和分数
        if grade_21 in GRADE_BAND:
            band, score = GRADE_BAND[grade_21]
        elif grade_21.startswith("CGPA") or grade_21.startswith("GPA"):
            band, score = "gpa-scale", None
        else:
            # "See additional information" / "Please See additional information" 等
            band, score = "see-additional", None

        # 去重：官网源存在少量重复行（同一院校出现两次）
        key = (eng_name, band)
        if key in seen:
            log.debug("Sheffield: 跳过重复行 %s | %s", eng_name, band)
            continue
        seen.add(key)

        records.append(
            {
                "uk_uni_id": "sheffield",
                "cn_name_raw": eng_name,  # 主存英文名（官网以英文为主键）
                "band": band,
                "min_avg_score": score,
            }
        )

    log.info("Sheffield: 解析到 %d 条（arwu-tier1/2/3/4 + see-additional + gpa-scale）", len(records))
    return records


def fetch_edinburgh_pdf(snapshot_path: str | None = None) -> tuple[str, list[str]]:
    """
    获取爱丁堡 Priority List PDF 并提取文本行。

    优先使用 snapshot_path；否则：
      1. 从 EDINBURGH_URL 页面抓取 HTML，找到 PDF 链接
      2. 下载 PDF 到 EDINBURGH_SNAPSHOT_PDF 归档
      3. 用 pdfplumber 提取文本行

    返回 (source_url, lines)
    """
    try:
        import pdfplumber
    except ImportError:
        log.error("pdfplumber 未安装，请 pip install pdfplumber")
        sys.exit(1)

    if snapshot_path:
        pdf_path = snapshot_path
        source_url = EDINBURGH_URL  # 快照模式下使用官方页面 URL，不暴露本地路径
    else:
        # Step 1: 抓取页面，找 PDF 链接
        log.info("GET %s", EDINBURGH_URL)
        resp = requests.get(EDINBURGH_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text

        match = re.search(r'href="(/[^"]*priority[^"]*\.pdf)"', html, re.IGNORECASE)
        if not match:
            log.error("Edinburgh: 页面未找到 Priority List PDF 链接，请检查页面结构")
            sys.exit(1)

        pdf_rel = match.group(1)
        pdf_url = EDINBURGH_PDF_BASE + pdf_rel
        source_url = pdf_url

        # Step 2: 下载 PDF
        log.info("下载 PDF: %s", pdf_url)
        pdf_resp = requests.get(pdf_url, headers=HEADERS, timeout=60)
        pdf_resp.raise_for_status()

        os.makedirs(os.path.dirname(EDINBURGH_SNAPSHOT_PDF), exist_ok=True)
        with open(EDINBURGH_SNAPSHOT_PDF, "wb") as f:
            f.write(pdf_resp.content)
        log.info("PDF 已保存: %s (%d bytes)", EDINBURGH_SNAPSHOT_PDF, len(pdf_resp.content))

        pdf_path = EDINBURGH_SNAPSHOT_PDF

    # Step 3: 提取文本行
    lines: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        log.info("Edinburgh PDF: %d 页", len(pdf.pages))
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                for line in text.split("\n"):
                    stripped = line.strip()
                    if stripped:
                        lines.append(stripped)

    return source_url, lines


# ---------------------------------------------------------------------------
# 抓取 / 读快照
# ---------------------------------------------------------------------------
def fetch_html(url: str) -> str:
    """从远端 URL 获取 HTML"""
    log.info("GET %s", url)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def load_snapshot(path: str) -> str:
    """从本地快照文件读取 HTML"""
    log.info("读取快照: %s", path)
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 写入数据库
# ---------------------------------------------------------------------------
def upsert_records(records: list[dict[str, Any]], source_url: str) -> int:
    """UPSERT 到 raw.uk_official_lists，返回写入行数"""
    now = datetime.now(timezone.utc)
    rows = [
        (
            r["uk_uni_id"],
            r["cn_name_raw"],
            r["band"],
            r["min_avg_score"],
            source_url,
            now,
        )
        for r in records
    ]
    with psycopg2.connect(DEFAULT_DSN) as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, UPSERT_SQL, rows)
        conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="UCL/Bristol/Edinburgh/Sheffield 官方中国院校名单爬虫")
    p.add_argument(
        "--source",
        choices=["ucl", "bristol", "edinburgh", "sheffield"],
        required=True,
        help="数据源",
    )
    p.add_argument("--dry-run", action="store_true", help="只解析不写入数据库")
    p.add_argument(
        "--from-snapshot",
        metavar="PATH",
        help="离线模式：直接读本地快照文件（跳过 HTTP 请求）。"
             "Edinburgh 传入 PDF 路径；UCL/Bristol 传入 HTML 路径。",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # ---- 爱丁堡：PDF 源，独立处理分支 ----
    if args.source == "edinburgh":
        source_url, lines = fetch_edinburgh_pdf(
            snapshot_path=args.from_snapshot,
        )
        records = parse_edinburgh_pdf(lines)

        if len(records) < MIN_RECORDS:
            log.error(
                "熔断！解析结果仅 %d 条（阈值 %d），PDF 可能改版，终止写入。",
                len(records),
                MIN_RECORDS,
            )
            sys.exit(1)

        log.info("Edinburgh 解析完成，共 %d 条", len(records))

        if args.dry_run:
            log.info("[dry-run] 跳过写入，预览前 5 条：")
            for r in records[:5]:
                log.info("  %s | %s | %s", r["uk_uni_id"], r["band"], r["cn_name_raw"][:60])
            return

        written = upsert_records(records, source_url)
        log.info("已写入 %d 条 → raw.uk_official_lists", written)

        with psycopg2.connect(DEFAULT_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM raw.uk_official_lists WHERE uk_uni_id = %s",
                    ("edinburgh",),
                )
                total = cur.fetchone()[0]
        log.info("数据库 edinburgh 总计: %d 条", total)
        return

    # ---- Sheffield：排名列表页 HTML 源 ----
    if args.source == "sheffield":
        url = SHEFFIELD_RANKING_URL
        parser = parse_sheffield
    # ---- UCL / Bristol：HTML 源 ----
    elif args.source == "ucl":
        url = UCL_URL
        parser = parse_ucl
    else:
        url = BRISTOL_URL
        parser = parse_bristol

    # 获取 HTML
    if args.from_snapshot:
        html = load_snapshot(args.from_snapshot)
    else:
        html = fetch_html(url)

    # 解析
    records = parser(html)

    # 熔断：解析结果过少，拒绝写入
    if len(records) < MIN_RECORDS:
        log.error(
            "熔断！解析结果仅 %d 条（阈值 %d），页面可能已改版或被拦截，终止写入。",
            len(records),
            MIN_RECORDS,
        )
        sys.exit(1)

    log.info("解析完成，共 %d 条", len(records))

    if args.dry_run:
        log.info("[dry-run] 跳过写入，预览前 5 条：")
        for r in records[:5]:
            log.info("  %s | %s | %s", r["uk_uni_id"], r["band"], r["cn_name_raw"][:60])
        return

    # 写入数据库
    written = upsert_records(records, url)
    log.info("已写入 %d 条 → raw.uk_official_lists", written)

    # 验证写入
    with psycopg2.connect(DEFAULT_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM raw.uk_official_lists WHERE uk_uni_id = %s",
                (args.source,),
            )
            total = cur.fetchone()[0]
    log.info("数据库 %s 总计: %d 条", args.source, total)


if __name__ == "__main__":
    main()
