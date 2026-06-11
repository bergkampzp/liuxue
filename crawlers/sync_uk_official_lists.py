#!/usr/bin/env python3
"""
sync_uk_official_lists.py — UCL & Bristol 官方中国院校名单爬虫

数据源（静态 HTML）:
  UCL     https://www.ucl.ac.uk/prospective-students/international/china
           → dl.accordion > dd.accordion__description > table（两列布局）
  Bristol https://www.bristol.ac.uk/international/countries/china/accepted-universities-in-china/
           → 单列 table，th="University name" + td 行（303 条）

用法:
    python sync_uk_official_lists.py --source ucl
    python sync_uk_official_lists.py --source bristol
    python sync_uk_official_lists.py --source ucl --dry-run
    python sync_uk_official_lists.py --source ucl --from-snapshot crawlers/snapshots/ucl_china.html
"""
from __future__ import annotations

import argparse
import logging
import os
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
    p = argparse.ArgumentParser(description="UCL/Bristol 官方中国院校名单爬虫")
    p.add_argument(
        "--source",
        choices=["ucl", "bristol"],
        required=True,
        help="数据源",
    )
    p.add_argument("--dry-run", action="store_true", help="只解析不写入数据库")
    p.add_argument(
        "--from-snapshot",
        metavar="PATH",
        help="离线模式：直接读本地快照文件（跳过 HTTP 请求）",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # 选择数据源
    if args.source == "ucl":
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
