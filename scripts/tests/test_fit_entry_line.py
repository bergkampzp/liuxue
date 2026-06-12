"""
TDD 夹具用例 — fit_cell / fit_all 纯函数测试（不连 DB）
按统计规格锁定：等渗反推 + 四级回退 + 置信标注
"""
import pytest


# ---------------------------------------------------------------------------
# Case 1: n < 5 → None
# ---------------------------------------------------------------------------
def test_fit_cell_too_few_samples():
    from fit_uk_entry_line import fit_cell

    result = fit_cell(offers=[80.0, 85.0], rejects=[70.0], offer_weights=[1.0, 1.0])
    assert result is None, "n=3 应返回 None"


def test_fit_cell_exactly_four_returns_none():
    from fit_uk_entry_line import fit_cell

    result = fit_cell(
        offers=[80.0, 82.0], rejects=[70.0, 72.0], offer_weights=[1.0, 1.0]
    )
    assert result is None, "n=4 应返回 None"


# ---------------------------------------------------------------------------
# Case 2: 全 offer 无拒（n=8）→ lower_bound / low / note含"或高估" / line_low==加权P10
# ---------------------------------------------------------------------------
def test_fit_cell_all_offers_no_rejects():
    from fit_uk_entry_line import fit_cell

    offers = [75.0, 78.0, 80.0, 82.0, 84.0, 86.0, 88.0, 90.0]
    weights = [1.0] * 8
    result = fit_cell(offers=offers, rejects=[], offer_weights=weights)

    assert result is not None
    assert result["method"] == "lower_bound"
    assert result["confidence"] == "low"
    assert "或高估" in result.get("note", "")
    assert result["line_high"] is None
    assert result["line_iso50"] is None
    # 加权P10 of [75,78,80,82,84,86,88,90]（等权）≈ 75 + 0.1*(90-75) = 76.5
    # 用 numpy 精确值断言在合理区间即可
    assert 75.0 <= result["line_low"] <= 78.5, f"line_low={result['line_low']} 超出预期区间"


# ---------------------------------------------------------------------------
# Case 3: n=12 偏序可分（offers 80-88, rejects 70-78）→ iso50 ∈ (78,80] / medium / line_low<=line_high
# ---------------------------------------------------------------------------
def test_fit_cell_medium_isotonic():
    from fit_uk_entry_line import fit_cell

    offers = [80.0, 81.5, 83.0, 84.5, 86.0, 87.5, 88.0]
    rejects = [70.0, 71.5, 73.0, 75.0, 78.0]
    weights = [1.0] * 7
    result = fit_cell(offers=offers, rejects=rejects, offer_weights=weights)

    assert result is not None
    assert result["confidence"] == "medium"
    assert result["method"] == "isotonic+p10p25"
    assert 78.0 < result["line_iso50"] <= 80.5, f"line_iso50={result['line_iso50']} 不在 (78,80.5]"
    assert result["line_low"] <= result["line_high"]
    assert result["sample_n"] == 12
    assert result["offer_n"] == 7
    assert result["reject_n"] == 5


# ---------------------------------------------------------------------------
# Case 4: n=40 → high + line_low < line_iso50 < line_high（bootstrap CI 包含点估计）
# ---------------------------------------------------------------------------
def test_fit_cell_high_confidence_bootstrap():
    from fit_uk_entry_line import fit_cell
    import random

    rng = random.Random(42)
    offers = [rng.uniform(78, 92) for _ in range(25)]
    rejects = [rng.uniform(60, 82) for _ in range(15)]
    weights = [1.0] * 25

    result = fit_cell(offers=offers, rejects=rejects, offer_weights=weights)

    assert result is not None
    assert result["confidence"] == "high"
    assert result["method"] == "isotonic+bootstrap"
    assert result["sample_n"] == 40
    # CI 包含点估计（line_low < line_iso50 < line_high，严格不等式对 200 次 bootstrap 稳健）
    assert result["line_low"] < result["line_iso50"], (
        f"CI 下界 {result['line_low']} 应 < 点估计 {result['line_iso50']}"
    )
    assert result["line_iso50"] < result["line_high"], (
        f"点估计 {result['line_iso50']} 应 < CI 上界 {result['line_high']}"
    )


# ---------------------------------------------------------------------------
# Case 5: 权重生效 — 高分组权重 0.5 时加权 P10/P25 向低分偏移
#   构造：offers = [80]*5 + [90]*5，全权 1.0 vs 90 的权重 0.5
#   全权1: 均分 85, 加权P25 应在 ~80; 90降权: 加权P25 也应 ≤ 82
#   关键断言：高分降权后的加权 P25 <= 全权时的加权 P25（偏移≥0）
# ---------------------------------------------------------------------------
def test_fit_cell_weights_affect_quantiles():
    from fit_uk_entry_line import fit_cell, weighted_percentile

    scores = [80.0] * 5 + [90.0] * 5
    weights_equal = [1.0] * 10
    weights_downscale_high = [1.0] * 5 + [0.5] * 5  # 90 的权重减半

    p25_equal = weighted_percentile(scores, weights_equal, 25)
    p25_downscaled = weighted_percentile(scores, weights_downscale_high, 25)

    # 高分降权 → 加权 P25 应 <= 等权 P25（偏向低分一侧）
    assert p25_downscaled <= p25_equal, (
        f"高分降权后 P25={p25_downscaled} 应 <= 等权 P25={p25_equal}"
    )

    # 额外验证：全权样本的加权 P10 在 [80, 81]（10 个等权点，P10 约 80.9）
    p10_equal = weighted_percentile(scores, weights_equal, 10)
    assert 80.0 <= p10_equal <= 82.0, f"P10={p10_equal} 超出预期"


# ---------------------------------------------------------------------------
# Case 6: 噪声不崩 — offers/rejects 交叠乱序 → 返回 dict 且 60 <= line_iso50 <= 95
# ---------------------------------------------------------------------------
def test_fit_cell_overlapping_noisy_returns_valid():
    from fit_uk_entry_line import fit_cell

    # 交叠乱序：offer 和 reject 混在同一分数区间
    offers = [70.0, 85.0, 72.0, 88.0, 75.0, 91.0, 68.0, 80.0, 66.0, 83.0]
    rejects = [72.0, 86.0, 69.0, 90.0, 75.0, 80.0, 65.0, 88.0, 78.0, 83.0]
    weights = [1.0] * 10

    result = fit_cell(offers=offers, rejects=rejects, offer_weights=weights)

    assert result is not None, "交叠样本不应崩溃返回 None（n=20>=5）"
    assert isinstance(result, dict)
    assert 60.0 <= result["line_iso50"] <= 95.0, f"line_iso50={result['line_iso50']} 超出合法范围"


# ---------------------------------------------------------------------------
# Case 7: fit_all 分组 + 回退 — 两格各 3 行不足 5 → 2级合并'通用'后 n=6 出线
#   fallback_level==2 且 confidence 降档（medium 降 low，或 low 保持 low）
# ---------------------------------------------------------------------------
def test_fit_all_fallback_to_generic_subject():
    from fit_uk_entry_line import fit_all

    # 两格 (uni_a, CS与数据, 985) 和 (uni_a, 商科金融, 985)，各 3 行（不足 5）
    # 合并到 subject_group='通用' 后共 6 行（offer 4 + reject 2，可出线）
    rows = []
    # CS组：2 offer 1 reject
    for score in [82.0, 84.0]:
        rows.append({
            "uk_uni_id": "imperial",
            "subject_group": "CS与数据",
            "tier_label": "985",
            "avg_score_pct": score,
            "decision": "Offer",
            "score_scale_inferred": False,
            "year": 2023,
        })
    rows.append({
        "uk_uni_id": "imperial",
        "subject_group": "CS与数据",
        "tier_label": "985",
        "avg_score_pct": 72.0,
        "decision": "Rejected",
        "score_scale_inferred": False,
        "year": 2023,
    })
    # 商科组：2 offer 1 reject
    for score in [80.0, 85.0]:
        rows.append({
            "uk_uni_id": "imperial",
            "subject_group": "商科金融",
            "tier_label": "985",
            "avg_score_pct": score,
            "decision": "Offer",
            "score_scale_inferred": False,
            "year": 2023,
        })
    rows.append({
        "uk_uni_id": "imperial",
        "subject_group": "商科金融",
        "tier_label": "985",
        "avg_score_pct": 70.0,
        "decision": "Rejected",
        "score_scale_inferred": False,
        "year": 2023,
    })

    results = fit_all(rows)

    # 应出线（fallback 到 '通用' 后 n=6）
    assert len(results) >= 1, "回退后应有至少 1 格出线"

    # 找到回退出的格子
    fallback_results = [r for r in results if r.get("fallback_level", 0) > 0]
    assert len(fallback_results) >= 1, "应有 fallback_level > 0 的格子"

    for r in fallback_results:
        assert r["fallback_level"] == 2, f"本版有效回退应为 level 2，得 {r['fallback_level']}"
        assert r["subject_group"] == "通用", f"回退格子 subject_group 应为'通用'，得 {r['subject_group']}"
        # confidence 应 <= medium（每回退降一档）
        assert r["confidence"] in ("low", "medium"), (
            f"回退后 confidence={r['confidence']} 不应为 high"
        )


# ---------------------------------------------------------------------------
# Case 8: 全拒格（C1 回归）— 不崩，返回"高于可观测范围"语义
# ---------------------------------------------------------------------------
def test_all_reject_cell_no_crash():
    from fit_uk_entry_line import fit_cell

    r = fit_cell([], [70, 72, 75, 78, 80], [])
    assert r is not None, "全拒格不应崩溃返回 None"
    assert r["line_low"] is None and r["line_iso50"] is None, (
        f"全拒格 line_low/iso50 应为 None，得 {r['line_low']}/{r['line_iso50']}"
    )
    assert r["confidence"] == "low", f"全拒格 confidence 应为 low，得 {r['confidence']}"
    assert "全拒" in (r.get("note") or ""), f"note 应含'全拒'，得 {r.get('note')}"
    assert r["offer_n"] == 0 and r["reject_n"] == 5, (
        f"offer_n={r['offer_n']}, reject_n={r['reject_n']}"
    )


# ---------------------------------------------------------------------------
# Case 9: 拒信主导格（C2 回归）— iso50 不得给 60 地板值
# ---------------------------------------------------------------------------
def test_reject_dominated_iso50_not_floor():
    from fit_uk_entry_line import fit_cell

    # 2 offer @ 70/72 vs 6 rejects @ 75-92 — 拒信主导，曲线在95仍<0.5
    r = fit_cell([70.0, 72.0], [75, 78, 82, 85, 88, 92], [1.0, 1.0])
    assert r is not None
    # iso50 应为 None（曲线未达50%），或至少 >= 72（不低于最高offer分）
    assert r["line_iso50"] is None or r["line_iso50"] >= 72, (
        f"拒信主导格 iso50 不得给地板值 60，得 {r['line_iso50']}"
    )
    if r["line_iso50"] is None:
        assert r["confidence"] == "low", (
            f"iso50=None 时 confidence 应降为 low，得 {r['confidence']}"
        )


# ---------------------------------------------------------------------------
# Case 10: I3 回归 — fit_all 重复键检测 + 输入序无关性
# ---------------------------------------------------------------------------
def test_fit_all_no_duplicate_keys_order_independent():
    from fit_uk_entry_line import fit_all

    def _make_rows(cs_first: bool):
        cs_rows = [
            {"uk_uni_id": "ucl", "subject_group": "CS与数据", "tier_label": "985",
             "avg_score_pct": s, "decision": d, "score_scale_inferred": False, "year": 2023}
            for s, d in [(82.0, "Offer"), (84.0, "Offer"), (86.0, "Offer")]
        ]
        generic_rows = [
            {"uk_uni_id": "ucl", "subject_group": "通用", "tier_label": "985",
             "avg_score_pct": s, "decision": d, "score_scale_inferred": False, "year": 2023}
            for s, d in [(75.0, "Offer"), (78.0, "Offer"), (80.0, "Offer"),
                         (70.0, "Rejected"), (68.0, "Rejected"), (65.0, "Rejected")]
        ]
        return cs_rows + generic_rows if cs_first else generic_rows + cs_rows

    res_a = fit_all(_make_rows(cs_first=True))
    res_b = fit_all(_make_rows(cs_first=False))

    def keys(res):
        return [(r["uk_uni_id"], r["subject_group"], r["tier_label"]) for r in res]

    keys_a = keys(res_a)
    keys_b = keys(res_b)
    assert len(keys_a) == len(set(keys_a)), f"输入序A有重复键: {keys_a}"
    assert len(keys_b) == len(set(keys_b)), f"输入序B有重复键: {keys_b}"

    # 输入序无关：键集合相同
    assert set(keys_a) == set(keys_b), (
        f"输入序影响输出键集合:\nA={sorted(keys_a)}\nB={sorted(keys_b)}"
    )
