#!/usr/bin/env python3
"""
sync_gter.py — 寄托天下 (offer.gter.net) 录取数据爬虫

爬取 offer.gter.net 的公开 REST API 数据，写入 warehouse.raw.liuxue_admissions

API: GET https://offer.gter.net/api/lists?page={n}&limit=20
详情: GET https://offer.gter.net/details/{hashId} (SSR HTML, 含公共字段)

用法:
    python sync_gter.py                        # 增量爬取
    python sync_gter.py --full                 # 全量爬取（所有页）
    python sync_gter.py --max-pages 100        # 限制页数
    python sync_gter.py --dry-run              # 只爬不写入
"""
from __future__ import annotations

import argparse, logging, os, re, time
from datetime import datetime, timezone
from typing import Any

import psycopg2, psycopg2.extras
import requests
from bs4 import BeautifulSoup

from normalize import normalize_decision

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sync_gter")

GTER_API = "https://offer.gter.net/api/lists"
GTER_DETAIL = "https://offer.gter.net/details"
DEFAULT_DSN = os.environ.get("WAREHOUSE_DSN",
    "host=localhost port=5432 dbname=warehouse user=postgres password=postgres")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
PAGE_SIZE = 20

UPSERT_SQL = """
INSERT INTO raw.liuxue_admissions
    (school, program, degree, season, year, decision, decision_detail, gpa,
     gre, gre_v, gre_aw, toefl, ielts, ielts_l, ielts_r, ielts_w, ielts_s,
     undergrad_school, undergrad_major, country, comment, source_url, source, crawled_at)
VALUES %s
ON CONFLICT (source_url) DO UPDATE SET
    decision = EXCLUDED.decision,
    decision_detail = EXCLUDED.decision_detail,
    comment = EXCLUDED.comment,
    gpa = EXCLUDED.gpa,
    crawled_at = EXCLUDED.crawled_at
"""


def parse_args():
    p = argparse.ArgumentParser(description="寄托天下录取数据爬虫")
    p.add_argument("--full", action="store_true", help="全量爬取（所有页）")
    p.add_argument("--max-pages", type=int, default=None, help="最大页数")
    p.add_argument("--limit", type=int, default=None, help="最大记录数")
    p.add_argument("--dry-run", action="store_true", help="只爬不写入")
    return p.parse_args()


def fetch_page(page: int) -> list[dict]:
    """通过公开 API 获取一页数据"""
    try:
        resp = requests.get(f"{GTER_API}?page={page}&limit={PAGE_SIZE}",
                            headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            return []
        return data["data"]["data"]
    except Exception as e:
        log.warning("Page %d 失败: %s", page, e)
        return []


def build_record(item: dict) -> dict:
    """从 API item 构建一条记录"""
    school = (item.get("schoolname") or "").strip()
    # 清理学校名（去掉中文括号前缀如"（ISEP）"）
    school = re.sub(r"^[（(][^）)]*[）)]\s*", "", school).strip()
    if not school:
        school = item.get("title", "").split("-")[-1].strip() if "-" in item.get("title", "") else ""

    program = (item.get("professional") or item.get("project") or "").strip()

    degree_raw = (item.get("degree") or "").strip()
    degree = "Other"
    if degree_raw:
        dl = degree_raw.lower()
        if "phd" in dl or "ph" in dl or "doctor" in dl:
            degree = "PhD"
        elif "master" in dl or "msc" in dl or "ms " in dl or "ma" in dl or "meng" in dl or "mba" in dl or "llm" in dl:
            degree = "Masters"
        elif "bach" in dl or "bs" in dl or "ba" in dl or "undergrad" in dl:
            degree = "Bachelors"

    # 解析学期 semester
    semester = item.get("semester") or ""
    season, year = None, None
    m = re.search(r"(Fall|Spring|Summer|Winter|25|26|27|28|29)\s*(\d{2,4})?", semester)
    if m:
        g1 = m.group(1)
        if g1.isdigit():
            year = 2000 + int(g1) if int(g1) < 50 else int(g1)
        else:
            season = g1
    # 也匹配纯年份格式如 "26Fall"
    m2 = re.search(r"(\d{2})(Fall|Spring|Summer|Winter)", semester)
    if m2:
        year = 2000 + int(m2.group(1))
        season = m2.group(2)

    decision, decision_detail = normalize_decision(item.get("apply_results") or "")

    return {
        "school": school,
        "program": program[:200] if program else None,
        "degree": degree,
        "season": season,
        "year": year,
        "decision": decision,
        "decision_detail": decision_detail,
        "gpa": None,
        "gre": None,
        "gre_v": None,
        "gre_aw": None,
        "toefl": None,
        "ielts": None,
        "ielts_l": None,
        "ielts_r": None,
        "ielts_w": None,
        "ielts_s": None,
        "undergrad_school": None,
        "undergrad_major": None,
        "country": None,
        "comment": (item.get("message") or "")[:500],
        "source_url": item.get("url", ""),
        "source": "gter",
    }


def main():
    args = parse_args()

    # 先查总记录数
    first_page = fetch_page(1)
    if not first_page:
        log.error("无法获取 API 数据，退出")
        return

    # 计算需爬多少页（API 返回了 total）
    r = requests.get(f"{GTER_API}?page=1&limit=1", headers=HEADERS, timeout=15)
    total_count = r.json()["data"]["count"]
    log.info("API 总记录数: %d", total_count)

    max_pages = args.max_pages
    if args.full:
        max_pages = (total_count // PAGE_SIZE) + 1
    elif args.max_pages is None:
        max_pages = 200  # 默认 200 页 ≈ 4000 条

    # 增量模式：检查已有 source_url 去重
    existing_urls = set()
    if not args.dry_run and not args.full:
        with psycopg2.connect(DEFAULT_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT source_url FROM raw.liuxue_admissions WHERE source='gter'")
                existing_urls = {r[0] for r in cur.fetchall()}
        log.info("数据库已有 %d 条 GTER 记录", len(existing_urls))

    total_new = 0
    total_skipped = 0

    for page in range(1, max_pages + 1):
        items = fetch_page(page)
        if not items:
            log.info("第 %d 页无数据，结束爬取", page)
            break

        records = [build_record(item) for item in items]

        if not args.dry_run:
            # 去重
            new_records = [r for r in records if r["source_url"] not in existing_urls]
            skipped = len(records) - len(new_records)
            total_skipped += skipped

            if new_records:
                now = datetime.now(timezone.utc)
                rows = []
                for r in new_records:
                    rows.append((
                        r["school"], r["program"], r["degree"],
                        r["season"], r["year"], r["decision"], r.get("decision_detail"),
                        r.get("gpa"), r.get("gre"), r.get("gre_v"), r.get("gre_aw"),
                        r.get("toefl"), r.get("ielts"),
                        r.get("ielts_l"), r.get("ielts_r"), r.get("ielts_w"), r.get("ielts_s"),
                        r.get("undergrad_school"), r.get("undergrad_major"), r.get("country"),
                        r.get("comment"), r["source_url"],
                        "gter", now,
                    ))
                with psycopg2.connect(DEFAULT_DSN) as conn:
                    with conn.cursor() as cur:
                        psycopg2.extras.execute_values(cur, UPSERT_SQL, rows)
                    conn.commit()
                total_new += len(rows)
                # 记录已写入的 URL
                for r in new_records:
                    existing_urls.add(r["source_url"])

            log.info("第 %d 页: %d 新 + %d 跳过 (累计 %d 新)",
                     page, len(new_records), skipped, total_new)
        else:
            total_new += len(records)
            log.info("第 %d 页: 预览 %d 条", page, len(records))
            if page <= 2:
                for r in records[:2]:
                    log.info("  %s | %s | %s", r["school"][:35], r["degree"], r["decision"])

        time.sleep(1.0)

    log.info("=" * 50)
    log.info("完成！新增 %d 条, 跳过 %d 条", total_new, total_skipped)
    if not args.dry_run:
        with psycopg2.connect(DEFAULT_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM raw.liuxue_admissions WHERE source='gter'")
                cnt = cur.fetchone()[0]
        log.info("数据库 GTER 总计: %d 条", cnt)


if __name__ == "__main__":
    main()
