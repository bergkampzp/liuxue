"""
等渗反推拟合脚本 — 按 (uk_uni_id × subject_group × cn_tier) 分组，
对每格执行等渗回归估计录取分界线并写入 raw.uk_entry_line_case。

警告：未经 H7 顾问复核不得接入 API / web 端。
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from typing import Any

import numpy as np
from sklearn.isotonic import IsotonicRegression


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def weighted_percentile(values: list[float], weights: list[float], pct: float) -> float:
    """加权分位数（累积权重法，确定性）。
    pct: 0-100
    """
    if not values:
        raise ValueError("values 不能为空")
    arr = np.array(values, dtype=float)
    wgt = np.array(weights, dtype=float)
    # 按值升序排列
    sort_idx = np.argsort(arr)
    arr = arr[sort_idx]
    wgt = wgt[sort_idx]
    cum_wgt = np.cumsum(wgt)
    total = cum_wgt[-1]
    target = pct / 100.0 * total
    # 找到第一个累积权重 >= target 的位置
    idx = np.searchsorted(cum_wgt, target)
    idx = int(min(idx, len(arr) - 1))
    return float(arr[idx])


def _find_iso50(ir: IsotonicRegression, grid: np.ndarray) -> float | None:
    """在网格上扫描，返回使等渗预测 >= 0.5 的最小分数。"""
    preds = ir.predict(grid)
    candidates = grid[preds >= 0.5]
    if len(candidates) == 0:
        return None
    return float(candidates[0])


# ---------------------------------------------------------------------------
# 核心纯函数
# ---------------------------------------------------------------------------

def fit_cell(
    offers: list[float],
    rejects: list[float],
    offer_weights: list[float],
) -> dict[str, Any] | None:
    """拟合单个 (uk_uni_id, subject_group, tier) 格子。

    Parameters
    ----------
    offers:         录取样本分数
    rejects:        拒绝样本分数
    offer_weights:  offer 样本权重（与 offers 等长），reject 固定权重 1.0

    Returns
    -------
    dict 或 None（n < 5 时返回 None）
    """
    n = len(offers) + len(rejects)
    if n < 5:
        return None

    offer_n = len(offers)
    reject_n = len(rejects)

    # ---- 全拒格（无 offer）→ 不崩，返回语义明确的结果 ----
    if not offers:
        return {
            "line_low": None,
            "line_high": None,
            "line_iso50": None,
            "confidence": "low",
            "method": "all_reject",
            "note": f"样本内全拒，门槛高于可观测分数范围(最高拒信 {max(rejects)})",
            "sample_n": n,
            "offer_n": 0,
            "reject_n": reject_n,
        }

    # ---- 全 offer 无拒 → 只给下界 ----
    if not rejects:
        line_low = weighted_percentile(offers, offer_weights, 10)
        return {
            "line_low": line_low,
            "line_high": None,
            "line_iso50": None,
            "confidence": "low",
            "method": "lower_bound",
            "note": "无拒信样本，线低估或高估，仅供参考",
            "sample_n": n,
            "offer_n": offer_n,
            "reject_n": 0,
        }

    # ---- 等渗拟合（5 <= n < 30 or n >= 30）----
    # 构建训练集
    x_all = np.array(offers + rejects, dtype=float)
    y_all = np.array([1.0] * offer_n + [0.0] * reject_n, dtype=float)
    w_all = np.array(list(offer_weights) + [1.0] * reject_n, dtype=float)

    ir = IsotonicRegression(increasing=True, out_of_bounds="clip")
    ir.fit(x_all, y_all, sample_weight=w_all)

    grid = np.arange(60.0, 95.5, 0.5)
    line_iso50 = _find_iso50(ir, grid)
    _iso50_undetectable = line_iso50 is None  # 曲线在整个网格未达 0.5（拒信主导或全录）

    line_low_p = weighted_percentile(offers, offer_weights, 10)
    line_high_p = weighted_percentile(offers, offer_weights, 25)

    if n >= 30:
        # Bootstrap CI（200 次）
        rng = np.random.default_rng(42)
        iso50_samples = []
        for _ in range(200):
            idx = rng.integers(0, n, size=n)
            x_b = x_all[idx]
            y_b = y_all[idx]
            w_b = w_all[idx]
            try:
                ir_b = IsotonicRegression(increasing=True, out_of_bounds="clip")
                ir_b.fit(x_b, y_b, sample_weight=w_b)
                val = _find_iso50(ir_b, grid)
                if val is not None:
                    iso50_samples.append(val)
            except Exception:
                continue
        if len(iso50_samples) >= 20:
            line_low = float(np.percentile(iso50_samples, 2.5))
            line_high = float(np.percentile(iso50_samples, 97.5))
        else:
            # bootstrap 样本不足，退回 P10/P25
            line_low = line_low_p
            line_high = line_high_p
        confidence = "high"
        method = "isotonic+bootstrap"
    else:
        line_low = line_low_p
        line_high = line_high_p
        confidence = "medium"
        method = "isotonic+p10p25"

    note = None
    if _iso50_undetectable:
        # 等渗曲线在可观测范围内未达 50%，门槛可能高于可观测范围
        # 不使用端点兜底（60 或 95）——方向不确定，留 None 更诚实
        note = "等渗曲线未达50%，门槛或高于可观测范围"
        confidence = "low"

    return {
        "line_low": line_low,
        "line_high": line_high,
        "line_iso50": line_iso50,
        "confidence": confidence,
        "method": method,
        "note": note,
        "sample_n": n,
        "offer_n": offer_n,
        "reject_n": reject_n,
    }


# ---------------------------------------------------------------------------
# 置信降档辅助
# ---------------------------------------------------------------------------

_CONFIDENCE_ORDER = ["high", "medium", "low"]


def _downgrade(confidence: str, steps: int = 1) -> str:
    idx = _CONFIDENCE_ORDER.index(confidence) if confidence in _CONFIDENCE_ORDER else 2
    return _CONFIDENCE_ORDER[min(idx + steps, 2)]


# ---------------------------------------------------------------------------
# 分组 + 四级回退
# ---------------------------------------------------------------------------

def fit_all(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对 int_uk_cases_tagged 的行 dict 列表执行分组拟合 + 四级回退。

    每行 dict 字段：
        uk_uni_id / subject_group / tier_label / avg_score_pct /
        decision / score_scale_inferred / year
    """
    # 只保留 Offer / Rejected 行
    valid_rows = [r for r in rows if r.get("decision") in ("Offer", "Rejected")]

    # 按 (uk_uni_id, subject_group, tier_label) 分组
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in valid_rows:
        key = (r["uk_uni_id"], r["subject_group"], r["tier_label"])
        groups[key].append(r)

    results: list[dict[str, Any]] = []

    def _extract_offers_rejects(row_list: list[dict]):
        offers, rejects, offer_weights = [], [], []
        for r in row_list:
            score = r.get("avg_score_pct")
            if score is None:
                continue
            w = 0.5 if r.get("score_scale_inferred") else 1.0
            if r["decision"] == "Offer":
                offers.append(float(score))
                offer_weights.append(w)
            else:
                rejects.append(float(score))
        return offers, rejects, offer_weights

    def _year_range(row_list: list[dict]) -> str:
        years = [r["year"] for r in row_list if r.get("year")]
        if not years:
            return "unknown"
        return f"{min(years)}-{max(years)}"

    processed_keys: set[tuple] = set()

    for (uk_uni_id, subject_group, tier_label), row_list in groups.items():
        key = (uk_uni_id, subject_group, tier_label)
        # 已被回退合并写入 → 跳过，避免重复输出
        if key in processed_keys:
            continue

        # 0 级：原格
        offers, rejects, weights = _extract_offers_rejects(row_list)
        cell = fit_cell(offers, rejects, weights)
        if cell is not None:
            cell.update({
                "uk_uni_id": uk_uni_id,
                "subject_group": subject_group,
                "tier_label": tier_label,
                "fallback_level": 0,
                "year_range": _year_range(row_list),
            })
            results.append(cell)
            processed_keys.add((uk_uni_id, subject_group, tier_label))
            continue

        # 1 级：放宽年份（本版 year 本就不过滤 → 跳过）

        # 2 级：subject_group 并到 '通用'
        # 收集同 (uk_uni_id, tier_label) 下所有行（不限 subject_group）
        generic_key = (uk_uni_id, "通用", tier_label)
        if generic_key not in processed_keys:
            sibling_rows = []
            for (u, s, t), rlist in groups.items():
                if u == uk_uni_id and t == tier_label:
                    sibling_rows.extend(rlist)
            offers2, rejects2, weights2 = _extract_offers_rejects(sibling_rows)
            cell2 = fit_cell(offers2, rejects2, weights2)
            if cell2 is not None:
                # 每回退 1 级降一档 confidence
                cell2["confidence"] = _downgrade(cell2["confidence"], steps=1)
                cell2.update({
                    "uk_uni_id": uk_uni_id,
                    "subject_group": "通用",
                    "tier_label": tier_label,
                    "fallback_level": 2,
                    "year_range": _year_range(sibling_rows),
                })
                results.append(cell2)
                processed_keys.add(generic_key)
                continue

        # 3 级：tier 合并双非一本二本（本版 tier 无细分 → 跳过）

        # 放弃
        # 不输出此格

    return results


# ---------------------------------------------------------------------------
# main — 读 DB → 拟合 → 写回
# ---------------------------------------------------------------------------

def main():
    import psycopg2
    import psycopg2.extras

    dsn = os.environ.get(
        "WAREHOUSE_DSN",
        "host=localhost port=5432 dbname=warehouse user=postgres password=postgres",
    )

    conn = psycopg2.connect(dsn)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # 读 int_uk_cases_tagged
    try:
        cur.execute("""
            SELECT
                uk_uni_id,
                subject_group,
                tier_label,
                avg_score_pct,
                decision,
                score_scale_inferred,
                year
            FROM int_uk_cases_tagged
            ORDER BY uk_uni_id, subject_group, tier_label
        """)
        rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"读 int_uk_cases_tagged 失败（可能表不存在）: {e}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    if not rows:
        print("样本不足，0 格出线")
        conn.close()
        return

    results = fit_all(rows)

    # TRUNCATE + 批量 INSERT
    cur.execute("TRUNCATE raw.uk_entry_line_case")

    insert_sql = """
        INSERT INTO raw.uk_entry_line_case
            (uk_uni_id, subject_group, cn_tier, line_low, line_high, line_iso50,
             sample_n, offer_n, reject_n, confidence, method, fallback_level,
             year_range, note)
        VALUES
            (%(uk_uni_id)s, %(subject_group)s, %(tier_label)s,
             %(line_low)s, %(line_high)s, %(line_iso50)s,
             %(sample_n)s, %(offer_n)s, %(reject_n)s,
             %(confidence)s, %(method)s, %(fallback_level)s,
             %(year_range)s, %(note)s)
        ON CONFLICT (uk_uni_id, subject_group, cn_tier) DO UPDATE SET
            line_low       = EXCLUDED.line_low,
            line_high      = EXCLUDED.line_high,
            line_iso50     = EXCLUDED.line_iso50,
            sample_n       = EXCLUDED.sample_n,
            offer_n        = EXCLUDED.offer_n,
            reject_n       = EXCLUDED.reject_n,
            confidence     = EXCLUDED.confidence,
            method         = EXCLUDED.method,
            fallback_level = EXCLUDED.fallback_level,
            year_range     = EXCLUDED.year_range,
            note           = EXCLUDED.note
    """
    if results:
        psycopg2.extras.execute_batch(cur, insert_sql, results)

    conn.commit()

    # 产量统计
    by_conf: dict[str, int] = defaultdict(int)
    for r in results:
        by_conf[r["confidence"]] += 1

    total = len(results)
    print(f"拟合完成：共 {total} 格出线")
    for conf in ["high", "medium", "low"]:
        if by_conf[conf]:
            print(f"  {conf}: {by_conf[conf]} 格")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
