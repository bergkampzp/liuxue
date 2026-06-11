#!/usr/bin/env python3
"""
normalize_cases.py — 案例校名归一管线

读 raw.liuxue_admissions.undergrad_school（DISTINCT 非空） → 三级匹配：
  1. exact：与 dim_cn_university.name_zh / name_en 精确比较
  2. alias：与 cn_university_alias.alias 精确比较
  3. fuzzy：rapidfuzz partial_ratio >= 92（高闸，归一错误会污染 tier 进而污染线）

结果 UPSERT 到 raw.case_school_map：
  - 命中行：cn_uni_id 非空，method=exact/alias/fuzzy，confidence=1.0/1.0/0.92
  - 未命中行：cn_uni_id=NULL，method=NULL，confidence=NULL（待人工复核）

用法:
    python normalize_cases.py                       # 正常归一+写库
    python normalize_cases.py --dry-run             # 只跑匹配，不写库
    python normalize_cases.py --export-review PATH  # 额外导出未归一+fuzzy 行 CSV（H3 工作包原料）
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
from typing import Optional

import psycopg2
import psycopg2.extras
from rapidfuzz import fuzz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("normalize_cases")

DEFAULT_DSN = os.environ.get(
    "WAREHOUSE_DSN",
    "host=localhost port=5432 dbname=warehouse user=postgres password=postgres",
)

FUZZY_THRESHOLD = 92  # partial_ratio 高闸（比 API 的 85 更严）


# ---------------------------------------------------------------------------
# 核心纯函数 — 可被单元测试直接调用，无 DB 依赖
# ---------------------------------------------------------------------------

def match_school(
    name: str,
    dim_rows: list[dict],
    alias_rows: list[dict],
) -> tuple[Optional[str], Optional[str], Optional[float]]:
    """
    三级匹配校名，返回 (cn_uni_id, method, confidence)。
    未命中返回 (None, None, None)。

    参数:
        name       — 原始校名字符串
        dim_rows   — list of dict，每行含 cn_uni_id / name_zh / name_en
        alias_rows — list of dict，每行含 alias / cn_uni_id
    """
    name_stripped = name.strip()

    # 1. 精确匹配 dim 中文 / 英文
    for row in dim_rows:
        if name_stripped == row["name_zh"] or name_stripped == row["name_en"]:
            return row["cn_uni_id"], "exact", 1.0

    # 2. 别名精确匹配
    for row in alias_rows:
        if name_stripped == row["alias"]:
            return row["cn_uni_id"], "alias", 1.0

    # 3. rapidfuzz partial_ratio >= 92（高闸）
    # 守卫：独立学院（含"学院"）不得 fuzzy 配到母体（无"学院"）
    # 原因：金陵学院事故 — partial_ratio('东南大学成贤学院','东南大学')=100
    #      但独立学院与母体是不同档位（三本 vs 985/211），误配污染 tier → 污染反推线
    # 例外：精确级/别名级不受影响（独立学院若应归一，正道是在维表/别名表中定义）
    if '学院' in name_stripped:
        # 名称含"学院" → 只接受候选也含"学院"的模糊匹配
        best_score = 0.0
        best_id: Optional[str] = None
        for row in dim_rows:
            for candidate in (row["name_zh"], row["name_en"]):
                if not candidate or '学院' not in candidate:
                    # 候选无"学院" → 跳过（防误配）
                    continue
                score = fuzz.partial_ratio(name_stripped, candidate)
                if score > best_score:
                    best_score = score
                    best_id = row["cn_uni_id"]
    else:
        # 正常校名（无"学院"）→ 不受守卫影响
        best_score = 0.0
        best_id: Optional[str] = None
        for row in dim_rows:
            for candidate in (row["name_zh"], row["name_en"]):
                if not candidate:
                    continue
                score = fuzz.partial_ratio(name_stripped, candidate)
                if score > best_score:
                    best_score = score
                    best_id = row["cn_uni_id"]

    if best_score >= FUZZY_THRESHOLD:
        return best_id, "fuzzy", 0.92

    return None, None, None


# ---------------------------------------------------------------------------
# DB 层
# ---------------------------------------------------------------------------

def fetch_all(conn, query: str) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query)
        return [dict(r) for r in cur.fetchall()]


def load_dim(conn) -> tuple[list[dict], list[dict]]:
    dim_rows = fetch_all(conn, "SELECT cn_uni_id, name_zh, name_en FROM dim_cn_university")
    alias_rows = fetch_all(conn, "SELECT alias, cn_uni_id FROM cn_university_alias")
    return dim_rows, alias_rows


def load_school_names(conn) -> list[str]:
    rows = fetch_all(
        conn,
        "SELECT DISTINCT undergrad_school FROM raw.liuxue_admissions "
        "WHERE undergrad_school IS NOT NULL AND undergrad_school <> ''",
    )
    return [r["undergrad_school"] for r in rows]


UPSERT_SQL = """
INSERT INTO raw.case_school_map
    (undergrad_school_raw, cn_uni_id, method, confidence)
VALUES (%(raw)s, %(cn_uni_id)s, %(method)s, %(confidence)s)
ON CONFLICT (undergrad_school_raw) DO UPDATE SET
    cn_uni_id  = EXCLUDED.cn_uni_id,
    method     = EXCLUDED.method,
    confidence = EXCLUDED.confidence
"""


def upsert_results(conn, results: list[dict]) -> None:
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, UPSERT_SQL, results)
    conn.commit()


# ---------------------------------------------------------------------------
# 导出 CSV（H3 工作包原料）
# ---------------------------------------------------------------------------

def export_review_csv(results: list[dict], path: str) -> None:
    """
    导出未归一行（cn_uni_id IS NULL）和 fuzzy 命中行（带建议值与分数）。
    """
    review_rows = [
        r for r in results
        if r["cn_uni_id"] is None or r["method"] == "fuzzy"
    ]
    if not review_rows:
        log.info("无需复核行，跳过导出")
        return

    fieldnames = ["undergrad_school_raw", "cn_uni_id", "method", "confidence", "review_note"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in review_rows:
            writer.writerow({
                "undergrad_school_raw": r["raw"],
                "cn_uni_id": r["cn_uni_id"] or "",
                "method": r["method"] or "unmatched",
                "confidence": r["confidence"] or "",
                "review_note": "fuzzy建议，请人工确认" if r["method"] == "fuzzy" else "未命中，请补充",
            })
    log.info("已导出 %d 行复核 CSV → %s", len(review_rows), path)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    conn = psycopg2.connect(DEFAULT_DSN)
    try:
        dim_rows, alias_rows = load_dim(conn)
        log.info("加载维表：dim %d 行，alias %d 行", len(dim_rows), len(alias_rows))

        school_names = load_school_names(conn)
        if not school_names:
            log.info("0 个待归一校名（undergrad_school 全为 NULL 或表为空），跳过归一步骤")
            return

        log.info("待归一校名：%d 个", len(school_names))

        results: list[dict] = []
        cnt = {"exact": 0, "alias": 0, "fuzzy": 0, "unmatched": 0}

        for name in school_names:
            cn_uni_id, method, confidence = match_school(name, dim_rows, alias_rows)
            results.append({
                "raw": name,
                "cn_uni_id": cn_uni_id,
                "method": method,
                "confidence": confidence,
            })
            cnt[method or "unmatched"] += 1

        log.info(
            "匹配结果：exact=%d alias=%d fuzzy=%d 未命中=%d",
            cnt["exact"], cnt["alias"], cnt["fuzzy"], cnt["unmatched"],
        )

        if args.export_review:
            export_review_csv(results, args.export_review)

        if args.dry_run:
            log.info("--dry-run 模式，不写入数据库")
            return

        upsert_results(conn, results)
        log.info("UPSERT 完成：%d 行写入 raw.case_school_map", len(results))

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="案例校名归一管线")
    p.add_argument("--dry-run", action="store_true", help="只跑匹配，不写入数据库")
    p.add_argument(
        "--export-review",
        metavar="PATH",
        default=None,
        help="导出未归一行 + fuzzy 行 CSV（H3 工作包原料）",
    )
    return p.parse_args()


if __name__ == "__main__":
    run(parse_args())
