#!/usr/bin/env python3
"""
build_review_pack.py — 幂等生成顾问工作包三张 CSV

输出到 docs/review-pack/：
  H1-专业映射复核表.csv     — dim_major_mapping 24行 + 26行扩展草案
  H3-校名归一抽检表.csv     — normalize_cases --export-review 输出（当前无数据则说明行）
  H7-反推线sanity表.csv     — raw.uk_entry_line_case 全量（当前无数据则说明行）

用法:
    python3 scripts/build_review_pack.py
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
DEFAULT_DSN = os.environ.get(
    "WAREHOUSE_DSN",
    "host=localhost port=5432 dbname=warehouse user=postgres password=postgres",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "docs" / "review-pack"

# ---------------------------------------------------------------------------
# H1 扩展草案（26 行）
# 高频转专业组合建议，status=draft，reviewed=false
# ---------------------------------------------------------------------------
H1_DRAFT_ROWS = [
    # (src_major_category, tgt_subject_group, fit_level, required_prereqs, note)
    ("医学类",      "CS与数据",    "不可转",  "",                  "医学背景与CS相距甚远；conversion course 极少被顶校接受"),
    ("医学类",      "公共卫生",    "对口",    "",                  "MPH/MScPH 对口；流行病学背景尤佳"),
    ("医学类",      "社科",        "可转",    "",                  "医学社会学/医学人类学方向可申，需说明动机"),
    ("护理类",      "社科",        "可转",    "",                  "公共卫生政策/健康社会学方向；部分校接受护理背景"),
    ("经济金融类",  "CS与数据",    "可转",    "编程基础;数学",     "金融科技/数据分析方向；需提供编程课证明"),
    ("计算机类",    "法律",        "可转",    "",                  "LLM科技法/知识产权方向；部分院校明确欢迎CS背景"),
    ("数学统计类",  "工科",        "可转",    "基础工程课",        "统计/运筹学方向；部分工程项目认可数学背景"),
    ("电子电气类",  "商科金融",    "可转",    "",                  "金融工程/量化方向；EE数学底子被认可"),
    ("土木建筑类",  "商科金融",    "可转",    "",                  "房地产金融/基础设施投融资方向"),
    ("理科类",      "CS与数据",    "可转",    "编程基础",          "物理/化学/生物→数据科学；需课程描述含编程"),
    ("理科类",      "商科金融",    "可转",    "数学基础",          "统计/数据分析路线；金融数学方向友好"),
    ("管理类",      "社科",        "对口",    "",                  "公共管理/社会政策方向直申"),
    ("管理类",      "教育",        "可转",    "",                  "教育管理/高等教育政策方向"),
    ("文科类",      "法律",        "可转",    "",                  "已有映射，此为draft补充确认；部分LLM收非法本"),
    ("外语类",      "教育",        "对口",    "",                  "TESOL/对外汉语教学方向直申"),
    ("外语类",      "传媒",        "对口",    "",                  "跨文化传播/国际新闻方向对口"),
    ("艺术设计类",  "传媒",        "可转",    "",                  "视觉传播/数字媒体方向；作品集权重大"),
    ("艺术设计类",  "教育",        "可转",    "",                  "艺术教育方向；部分院校专门设 Art & Design Education"),
    ("法学类",      "社科",        "对口",    "",                  "法社会学/犯罪学方向；英国 LLM/MSc Law 均接受"),
    ("计算机类",    "理科",        "可转",    "",                  "计算数学/计算物理方向；视具体项目"),
    ("机械自动化类","理科",        "可转",    "",                  "工程物理/材料方向，看项目偏重"),
    ("土木建筑类",  "理科",        "可转",    "环境科学基础",      "环境工程/地球科学方向；draft供顾问判断，fit_level存疑"),
    ("经济金融类",  "教育",        "可转",    "",                  "教育经济学/政策评估方向；部分 Education Policy 项目欢迎"),
    ("护理类",      "教育",        "可转",    "",                  "医学教育/护理教育方向；小众但存在"),
    ("理科类",      "工科",        "可转",    "基础工程课",        "化工/环境工程方向；理工边界模糊，draft"),
    ("文科类",      "商科金融",    "可转",    "数学基础",          "已有映射，此行作为alt fit_level草案——部分校更严格，供复核"),
]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def get_conn():
    return psycopg2.connect(DEFAULT_DSN)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# H1 — 专业映射复核表
# ---------------------------------------------------------------------------

def build_h1(conn) -> int:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # 1. 读 dim_major_mapping 24 行
    cur.execute("""
        SELECT
            src_major_category,
            tgt_subject_group,
            fit_level,
            COALESCE(required_prereqs, '') AS required_prereqs,
            COALESCE(note, '') AS note,
            reviewed
        FROM public.dim_major_mapping
        ORDER BY src_major_category, tgt_subject_group
    """)
    existing_rows = cur.fetchall()

    # 2. 查 int_uk_cases_tagged 共现统计（(src大类 × tgt subject_group)）
    # int_uk_cases_tagged 列：undergrad_major → 需映射到 src_major_category
    # 当前 0 行，全部返回"暂无案例"
    cur.execute("SELECT COUNT(*) AS cnt FROM public.int_uk_cases_tagged")
    total_cases = cur.fetchone()["cnt"]

    # 构造共现 dict：key=(src_major_category, tgt_subject_group) -> {n_cases, offer_rate}
    cooccur: dict[tuple, dict] = {}
    if total_cases > 0:
        cur.execute("""
            SELECT
                subject_group AS tgt,
                COUNT(*) AS n_cases,
                ROUND(
                    SUM(CASE WHEN decision = 'Offer' THEN 1 ELSE 0 END)::numeric
                    / NULLIF(COUNT(*), 0) * 100, 1
                ) AS offer_rate_pct
            FROM public.int_uk_cases_tagged
            GROUP BY subject_group
        """)
        # 注：int_uk_cases_tagged 没有 src_major_category 列（只有 subject_group）
        # 所以我们做 tgt 级别统计，key 只用 tgt 填充
        for row in cur.fetchall():
            cooccur[row["tgt"]] = {
                "n_cases": row["n_cases"],
                "offer_rate": f"{row['offer_rate_pct']}%",
            }

    # 3. 组装 H1 行
    fieldnames = [
        "src_major_category", "tgt_subject_group", "fit_level",
        "required_prereqs", "note", "reviewed",
        "n_cases", "offer_rate",
        "裁决", "修改值", "备注", "status",
    ]

    rows: list[dict] = []

    # 现有 24 行
    for r in existing_rows:
        tgt = r["tgt_subject_group"]
        if total_cases > 0 and tgt in cooccur:
            n_cases = cooccur[tgt]["n_cases"]
            offer_rate = cooccur[tgt]["offer_rate"]
        else:
            n_cases = "暂无案例"
            offer_rate = "暂无案例"

        rows.append({
            "src_major_category": r["src_major_category"],
            "tgt_subject_group":  r["tgt_subject_group"],
            "fit_level":          r["fit_level"],
            "required_prereqs":   r["required_prereqs"],
            "note":               r["note"],
            "reviewed":           str(r["reviewed"]).lower(),
            "n_cases":            n_cases,
            "offer_rate":         offer_rate,
            "裁决":               "",
            "修改值":             "",
            "备注":               "",
            "status":             "existing",
        })

    # 扩展草案 26 行
    for (src, tgt, fit, prereqs, note_text) in H1_DRAFT_ROWS:
        tgt_key = tgt
        if total_cases > 0 and tgt_key in cooccur:
            n_cases = cooccur[tgt_key]["n_cases"]
            offer_rate = cooccur[tgt_key]["offer_rate"]
        else:
            n_cases = "暂无案例"
            offer_rate = "暂无案例"

        rows.append({
            "src_major_category": src,
            "tgt_subject_group":  tgt,
            "fit_level":          fit,
            "required_prereqs":   prereqs,
            "note":               note_text,
            "reviewed":           "false",
            "n_cases":            n_cases,
            "offer_rate":         offer_rate,
            "裁决":               "",
            "修改值":             "",
            "备注":               "",
            "status":             "draft",
        })

    out_path = OUTPUT_DIR / "H1-专业映射复核表.csv"
    return write_csv(out_path, fieldnames, rows)


# ---------------------------------------------------------------------------
# H3 — 校名归一抽检表
# ---------------------------------------------------------------------------

def build_h3(conn) -> int:
    """
    尝试读 raw.case_school_map 的未归一 + fuzzy 行。
    当前 0 行（1p3a 数据未接入），输出一行说明记录。
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    fieldnames = [
        "undergrad_school_raw", "suggested_cn_uni_id", "match_method",
        "match_confidence", "reviewed", "裁决_确认cn_uni_id", "备注",
    ]

    # 尝试查 case_school_map
    try:
        cur.execute("""
            SELECT
                undergrad_school_raw,
                COALESCE(cn_uni_id, '') AS suggested_cn_uni_id,
                COALESCE(method, '') AS match_method,
                COALESCE(confidence::text, '') AS match_confidence,
                reviewed
            FROM raw.case_school_map
            WHERE cn_uni_id IS NULL OR method = 'fuzzy'
            ORDER BY undergrad_school_raw
        """)
        pending_rows = cur.fetchall()
    except Exception:
        conn.rollback()
        pending_rows = []

    if pending_rows:
        rows = [
            {
                "undergrad_school_raw":    r["undergrad_school_raw"],
                "suggested_cn_uni_id":     r["suggested_cn_uni_id"],
                "match_method":            r["match_method"],
                "match_confidence":        r["match_confidence"],
                "reviewed":                str(r["reviewed"]).lower(),
                "裁决_确认cn_uni_id":      "",
                "备注":                    "",
            }
            for r in pending_rows
        ]
    else:
        # 说明行
        rows = [
            {
                "undergrad_school_raw":    "【说明】当前无待归一校名",
                "suggested_cn_uni_id":     "1p3a 数据未接入；数据到达后重跑 python3 scripts/build_review_pack.py 自动填充",
                "match_method":            "N/A",
                "match_confidence":        "N/A",
                "reviewed":                "N/A",
                "裁决_确认cn_uni_id":      "",
                "备注":                    "回流路径：确认行追加到 dbt_liuxue/seeds/cn_university_alias.csv",
            }
        ]

    out_path = OUTPUT_DIR / "H3-校名归一抽检表.csv"
    return write_csv(out_path, fieldnames, rows)


# ---------------------------------------------------------------------------
# H7 — 反推线 sanity 表
# ---------------------------------------------------------------------------

def build_h7(conn) -> int:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    fieldnames = [
        "id", "uk_uni_id", "subject_group", "cn_tier",
        "line_low", "line_high", "line_iso50",
        "sample_n", "offer_n", "reject_n",
        "confidence", "method", "fallback_level", "year_range", "note",
        "sanity_像话", "sanity_不像话", "sanity_存疑", "审核备注",
    ]

    cur.execute("""
        SELECT
            id, uk_uni_id, subject_group, cn_tier,
            line_low, line_high, line_iso50,
            sample_n, offer_n, reject_n,
            confidence, method, fallback_level, year_range, note
        FROM raw.uk_entry_line_case
        ORDER BY uk_uni_id, subject_group, cn_tier
    """)
    data_rows = cur.fetchall()

    if data_rows:
        rows = [
            {
                "id":             r["id"],
                "uk_uni_id":      r["uk_uni_id"],
                "subject_group":  r["subject_group"],
                "cn_tier":        r["cn_tier"],
                "line_low":       r["line_low"] if r["line_low"] is not None else "",
                "line_high":      r["line_high"] if r["line_high"] is not None else "",
                "line_iso50":     r["line_iso50"] if r["line_iso50"] is not None else "",
                "sample_n":       r["sample_n"] if r["sample_n"] is not None else "",
                "offer_n":        r["offer_n"] if r["offer_n"] is not None else "",
                "reject_n":       r["reject_n"] if r["reject_n"] is not None else "",
                "confidence":     r["confidence"] if r["confidence"] else "",
                "method":         r["method"] if r["method"] else "",
                "fallback_level": r["fallback_level"],
                "year_range":     r["year_range"] if r["year_range"] else "",
                "note":           r["note"] if r["note"] else "",
                "sanity_像话":    "",
                "sanity_不像话":  "",
                "sanity_存疑":    "",
                "审核备注":       "",
            }
            for r in data_rows
        ]
    else:
        # 说明行
        rows = [
            {
                "id":             "【说明】当前无反推线数据",
                "uk_uni_id":      "1p3a 数据未接入",
                "subject_group":  "数据到达并运行 ./run-pipeline.sh case 后重跑 python3 scripts/build_review_pack.py 自动填充",
                "cn_tier":        "N/A",
                "line_low":       "N/A",
                "line_high":      "N/A",
                "line_iso50":     "N/A",
                "sample_n":       "N/A",
                "offer_n":        "N/A",
                "reject_n":       "N/A",
                "confidence":     "N/A",
                "method":         "N/A",
                "fallback_level": "N/A",
                "year_range":     "N/A",
                "note":           "红线：H7未经顾问签字确认，case反推线不得接入web/API（见 methodology 承诺）",
                "sanity_像话":    "",
                "sanity_不像话":  "",
                "sanity_存疑":    "",
                "审核备注":       "",
            }
        ]

    out_path = OUTPUT_DIR / "H7-反推线sanity表.csv"
    return write_csv(out_path, fieldnames, rows)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    print(f"[build_review_pack] 输出目录: {OUTPUT_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_conn()
    try:
        n_h1 = build_h1(conn)
        print(f"  H1-专业映射复核表.csv  — {n_h1} 行（含24现有+26草案）")

        n_h3 = build_h3(conn)
        print(f"  H3-校名归一抽检表.csv  — {n_h3} 行")

        n_h7 = build_h7(conn)
        print(f"  H7-反推线sanity表.csv  — {n_h7} 行")

    finally:
        conn.close()

    print("[build_review_pack] 完成。")


if __name__ == "__main__":
    main()
