#!/usr/bin/env python3
"""
sync_1point3acres.py — 一亩三分地录取数据爬虫

爬取一亩三分地研究生申请录取汇报版块 (fid=82) 的结构化数据

⚠️ 一亩三分地有 Cloudflare 防护，需要 residential proxy 或 cookie 绕过。
   本脚本支持两种模式：
   1. cookie 模式：从环境变量 COOKIE_1P3A 获取已有 cookie
   2. Playwright 模式（需要 browserbase 等 residential proxy 环境）

用法:
    python sync_1point3acres.py --cookie "xxxxx"                  # Cookie 模式
    python sync_1point3acres.py --cookie-file /tmp/cookies.txt    # Cookie 文件
    python sync_1point3acres.py --dry-run --cookie "xxxx"         # 预览不写入
"""
from __future__ import annotations

import argparse, logging, os, re, time
from datetime import datetime, timezone
from typing import Any

import psycopg2, psycopg2.extras
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sync_1point3acres")

BASE_URL = "https://www.1point3acres.com/bbs"
FORUM_URL = f"{BASE_URL}/forum-82-{{page}}.html"
DEFAULT_DSN = os.environ.get("WAREHOUSE_DSN",
    "host=localhost port=5432 dbname=warehouse user=postgres password=postgres")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

UPSERT_SQL = """
INSERT INTO raw.liuxue_admissions
    (school, program, degree, season, year, decision, gpa, gre, gre_v, gre_aw,
     toefl, ielts, undergrad_school, undergrad_major, comment, source_url, source, crawled_at)
VALUES %s
ON CONFLICT (source_url) DO UPDATE SET
    decision = EXCLUDED.decision,
    gpa = EXCLUDED.gpa,
    crawled_at = EXCLUDED.crawled_at
"""


def parse_args():
    p = argparse.ArgumentParser(description="一亩三分地录取数据爬虫")
    p.add_argument("--cookie", type=str, default=None, help="Cookie 字符串")
    p.add_argument("--cookie-file", type=str, default=None, help="Cookie 文件路径")
    p.add_argument("--max-pages", type=int, default=100, help="最大页数（默认 100）")
    p.add_argument("--dry-run", action="store_true", help="只爬不写入")
    return p.parse_args()


def build_headers(cookie: str | None = None) -> dict:
    h = HEADERS.copy()
    if cookie:
        h["Cookie"] = cookie
    return h


def parse_list_page(html: str) -> list[dict]:
    """
    解析 Discuz! 论坛列表页的结构化录取数据。

    每条帖子在 <tr id="normalthread_*"> 中。
    结构化数据在 <font> 和 <u> 标签中按固定顺序：
    font[1] = 录取时间
    font[2] = 英语成绩(TOEFL/IELTS)
    font[3] = GRE成绩
    font[4] = 本科专业
    font[5] = GPA
    font[6] = 本科学校
    u/font[1] = 申请季
    u/font[2] = 学位类型 (MS/PhD)
    u/font[3]/b = 录取结果 (AD/Offer/Reject/WL)
    u/font[4]/b = 录取专业
    u/font[5] = 录取学校
    """
    soup = BeautifulSoup(html, "html.parser")
    records = []

    for tr in soup.select("tr[id^=normalthread_]"):
        try:
            fonts = tr.find_all("font")
            us = tr.find_all("u")
            if len(fonts) < 6:
                continue

            # 基本信息
            admit_time = fonts[0].get_text(strip=True)
            english_score = fonts[1].get_text(strip=True)
            gre_score = fonts[2].get_text(strip=True)
            undergrad_major = fonts[3].get_text(strip=True)
            gpa_text = fonts[4].get_text(strip=True)
            undergrad_school = fonts[5].get_text(strip=True)

            # U 标签内的结构化数据
            season_info, degree_info, result_info, major_info, school_info = "", "", "", "", ""
            if len(us) >= 1:
                u_fonts = us[0].find_all("font")
                if len(u_fonts) >= 2:
                    season_info = u_fonts[0].get_text(strip=True)
                    degree_info = u_fonts[1].get_text(strip=True)
                    # 录取结果在 u/font[3]/b
                    if len(u_fonts) >= 3:
                        b_tag = u_fonts[2].find("b")
                        result_info = b_tag.get_text(strip=True) if b_tag else u_fonts[2].get_text(strip=True)
                    else:
                        b_tags = tr.find_all("b")
                        if len(b_tags) >= 1:
                            result_info = b_tags[0].get_text(strip=True)
                    # 录取专业在 u/font[4]/b
                    if len(u_fonts) >= 4:
                        b_tag2 = u_fonts[3].find("b")
                        major_info = b_tag2.get_text(strip=True) if b_tag2 else u_fonts[3].get_text(strip=True)
                    # 录取学校在 u/font[5]
                    if len(u_fonts) >= 5:
                        school_info = u_fonts[4].get_text(strip=True)

            # 帖子标题（可能含学校/专业/结果信息）
            title_el = tr.select_one("a.xst, a.s.xst, th a")
            title = title_el.get_text(strip=True) if title_el else ""

            # 提取数字信息
            gpa = parse_gpa(gpa_text)
            gre = parse_gre(gre_score)
            toefl, ielts = parse_english(english_score)

            # 学位
            degree = "Other"
            if "phd" in degree_info.lower() or "phd" in title.lower():
                degree = "PhD"
            elif "ms" in degree_info.lower() or "master" in degree_info.lower():
                degree = "Masters"
            elif "meng" in degree_info.lower():
                degree = "Masters"

            # 申请季年份
            year = None
            m = re.search(r"(\d{2})(Fall|Spring|Summer)", season_info)
            if m:
                year = 2000 + int(m.group(1))

            # 录取结果标准化
            decision = "Other"
            dr = result_info.lower()
            if "ad" in dr or "offer" in dr:
                decision = "Offer"
            elif "reject" in dr or "rej" in dr:
                decision = "Rejected"
            elif "wl" in dr or "wait" in dr:
                decision = "Waitlist"
            elif "interview" in dr:
                decision = "Interview"

            # source_url
            link = tr.select_one("a.xst, a.s.xst")
            source_url = ""
            if link and link.get("href"):
                href = link["href"]
                source_url = href if href.startswith("http") else f"{BASE_URL}/{href.lstrip('/')}"

            if not school_info and not source_url:
                continue

            record = {
                "school": school_info or None,
                "program": major_info or None,
                "degree": degree,
                "season": season_info,
                "year": year,
                "decision": decision,
                "gpa": gpa,
                "gre": gre,
                "gre_v": None,
                "gre_aw": None,
                "toefl": toefl,
                "ielts": ielts,
                "undergrad_school": undergrad_school or None,
                "undergrad_major": undergrad_major or None,
                "comment": f"{title} | admit_time: {admit_time}" if title else None,
                "source_url": source_url,
                "source": "1point3acres",
            }
            records.append(record)

        except Exception as e:
            log.debug("解析行失败: %s", e)
            continue

    return records


def parse_gpa(text: str) -> float | None:
    m = re.search(r"(\d+\.?\d*)", text)
    if m:
        v = float(m.group(1))
        return v if 0 < v <= 4.0 or 0 < v <= 100 else min(v, 4.0)
    return None


def parse_gre(text: str) -> int | None:
    m = re.search(r"(\d{3})", text)
    if m:
        v = int(m.group(1))
        return v if 260 <= v <= 340 else None
    return None


def parse_english(text: str) -> tuple[int | None, float | None]:
    toefl, ielts = None, None
    m = re.search(r"TOEFL\s*(\d+)", text, re.IGNORECASE)
    if m:
        toefl = int(m.group(1))
    m = re.search(r"IELTS\s*(\d+\.?\d*)", text, re.IGNORECASE)
    if m:
        ielts = float(m.group(1))
    # 也匹配纯数字 100-120 当作 TOEFL
    if not toefl and not ielts:
        m = re.search(r"(\d{3})", text)
        if m and 100 <= int(m.group(1)) <= 120:
            toefl = int(m.group(1))
    return toefl, ielts


def main():
    args = parse_args()

    cookie = args.cookie
    if args.cookie_file:
        with open(args.cookie_file) as f:
            cookie = f.read().strip()

    if not cookie:
        log.warning("没有提供 Cookie！一亩三分地需要 Cloudflare cookie 才能访问。")
        log.warning("请先在浏览器登录 https://www.1point3acres.com/bbs/，")
        log.warning("然后从 DevTools → Application → Cookies 复制完整的 Cookie 字符串")
        log.warning("用法: python sync_1point3acres.py --cookie 'xxx=yyy; aaa=bbb'")
        return

    headers = build_headers(cookie)
    total_new = 0

    for page in range(1, args.max_pages + 1):
        url = FORUM_URL.format(page=page)
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code != 200:
                log.warning("第 %d 页返回 %d，可能 Cookie 过期或 Cloudflare 拦截", page, resp.status_code)
                break
            resp.encoding = 'utf-8'
        except requests.RequestException as e:
            log.warning("第 %d 页请求失败: %s", page, e)
            break

        records = parse_list_page(resp.text)
        if not records:
            log.info("第 %d 页无结构化数据，可能已到尾页", page)
            break

        if not args.dry_run:
            now = datetime.now(timezone.utc)
            rows = []
            for r in records:
                rows.append((
                    r["school"], r["program"], r["degree"],
                    r["season"], r["year"], r["decision"],
                    r["gpa"], r["gre"], r["gre_v"], r["gre_aw"],
                    r["toefl"], r["ielts"],
                    r["undergrad_school"], r["undergrad_major"],
                    r.get("comment"), r["source_url"],
                    "1point3acres", now,
                ))
            with psycopg2.connect(DEFAULT_DSN) as conn:
                with conn.cursor() as cur:
                    psycopg2.extras.execute_values(cur, UPSERT_SQL, rows)
                conn.commit()
            total_new += len(rows)
            log.info("第 %d 页: 写入 %d 条 (累计 %d)", page, len(rows), total_new)
        else:
            total_new += len(records)
            log.info("第 %d 页: 预览 %d 条", page, len(records))
            for r in records[:2]:
                log.info("  %s | %s | GPA %s", r.get("school", "?")[:35], r["decision"], r.get("gpa", "?"))

        time.sleep(3)

    log.info("=" * 50)
    log.info("完成！共 %d 条", total_new)
    if not args.dry_run:
        with psycopg2.connect(DEFAULT_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM raw.liuxue_admissions WHERE source='1point3acres'")
                cnt = cur.fetchone()[0]
        log.info("数据库一亩三分地数据总计: %d 条", cnt)


if __name__ == "__main__":
    main()
