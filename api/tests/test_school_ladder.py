"""
TDD test suite for GET /school-ladder endpoint.
6 test cases covering the panoramic school ladder contract.
"""
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from api import main
from api.main import app, LIST_GATED_SCHOOLS

client = TestClient(app)

# ---------------------------------------------------------------------------
# FAKE DATA
# ---------------------------------------------------------------------------

FAKE_TIER = {"cn_uni_id": "jiangsu_univ", "tier_label": "双非", "name_zh": "江苏大学"}

# Full universe of 3 UK universities (tests use small set for speed)
FAKE_UK_UNIS = [
    {"uk_uni_id": "ucl",       "name_zh": "伦敦大学学院",   "qs_rank": 9},
    {"uk_uni_id": "sheffield", "name_zh": "谢菲尔德大学",   "qs_rank": 92},
    {"uk_uni_id": "bristol",   "name_zh": "布里斯托大学",   "qs_rank": 55},
    {"uk_uni_id": "edinburgh", "name_zh": "爱丁堡大学",     "qs_rank": 27},
    {"uk_uni_id": "manchester","name_zh": "曼彻斯特大学",   "qs_rank": 35},
]

# stg official list rows (sheffield arwu-tier1 + bristol accepted)
FAKE_LIST_ROWS = [
    {
        "uk_uni_id":    "sheffield",
        "cn_uni_id":    "jiangsu_univ",
        "band":         "arwu-tier1",
        "min_avg_score": 70.0,                  # band_min_score (stg 逐校线)
        "source_type":  "official_web",
        "source_url":   "https://sheffield.ac.uk/official",
    },
    {
        "uk_uni_id":    "bristol",
        "cn_uni_id":    "jiangsu_univ",
        "band":         "accepted",
        "min_avg_score": None,
        "source_type":  "official_web",
        "source_url":   "https://bristol.ac.uk/official",
    },
]

# mart match rows – tier-level scores
FAKE_MART_ROWS = [
    {
        "uk_uni_id":     "manchester",
        "name_zh":       "曼彻斯特大学",
        "qs_rank":       35,
        "cn_tier":       "双非",
        "subject_group": "通用",
        "min_avg_score": 82.0,
        "source_type":   "aggregator",
        "source_url":    "https://www.testdaily.cn/64451/",
        "confidence":    "low",
        "ielts_overall": 6.5,
    },
    {
        "uk_uni_id":     "ucl",
        "name_zh":       "伦敦大学学院",
        "qs_rank":       9,
        "cn_tier":       "双非",
        "subject_group": "通用",
        "min_avg_score": 90.0,
        "source_type":   "official_web",
        "source_url":    "https://www.ucl.ac.uk/x",
        "confidence":    "high",
        "ielts_overall": 7.0,
    },
    {
        "uk_uni_id":     "sheffield",
        "name_zh":       "谢菲尔德大学",
        "qs_rank":       92,
        "cn_tier":       "双非",
        "subject_group": "通用",
        "min_avg_score": 75.0,                  # mart tier 线 (北极星: 江苏大学×sheffield=75.0)
        "source_type":   "official_web",
        "source_url":    "https://sheffield.ac.uk/mart",
        "confidence":    "high",
        "ielts_overall": 6.5,
    },
]


# ---------------------------------------------------------------------------
# Test 1: 全景正常路径
# ---------------------------------------------------------------------------

def test_ladder_panorama_normal(monkeypatch):
    """
    200; sheffield → min_avg_score=75/band_min_score=70/"arwu-tier1" in list_status/official_web;
    bristol → 名单内(accepted) 且 min_avg_score null;
    qs 升序; aggregator 行 source_url 非空.
    """
    monkeypatch.setattr(main, "resolve_cn_university", lambda name: FAKE_TIER)
    monkeypatch.setattr(main, "query_uk_universities",       lambda: FAKE_UK_UNIS)
    monkeypatch.setattr(main, "query_official_list_rows",    lambda cid: FAKE_LIST_ROWS)
    monkeypatch.setattr(main, "query_match_rows",            lambda tier, grp: FAKE_MART_ROWS)

    resp = client.get("/school-ladder", params={"school": "江苏大学"})
    assert resp.status_code == 200

    body = resp.json()
    assert "cn_university" in body
    assert "schools" in body
    assert "disclaimer" in body
    assert "不构成录取承诺" in body["disclaimer"]

    rows = {r["uk_uni_id"]: r for r in body["schools"]}

    # sheffield: 北极星断言
    sh = rows["sheffield"]
    assert sh["min_avg_score"] == 75.0,         f"expected 75.0 got {sh['min_avg_score']}"
    assert sh["band_min_score"] == 70.0,        f"expected 70.0 got {sh['band_min_score']}"
    assert "arwu-tier1" in sh["list_status"],   f"expected arwu-tier1 in {sh['list_status']}"
    assert sh["source_type"] == "official_web", f"expected official_web got {sh['source_type']}"

    # bristol: 名单内 + min_avg_score null
    br = rows["bristol"]
    assert br["list_status"].startswith("名单内"), f"expected 名单内 got {br['list_status']}"
    assert br["min_avg_score"] is None,         f"expected null got {br['min_avg_score']}"

    # qs_rank 升序 (nulls last)
    qs_vals = [r["qs_rank"] for r in body["schools"] if r["qs_rank"] is not None]
    assert qs_vals == sorted(qs_vals), f"qs_rank not ascending: {qs_vals}"

    # aggregator 行 source_url 非空
    man = rows["manchester"]
    assert man["source_url"], "aggregator source_url should be non-empty"

    # 9 字段全在
    required = {"uk_uni_id", "name_zh", "qs_rank", "list_status", "band_min_score",
                "min_avg_score", "source_type", "source_url", "ielts_overall"}
    assert required.issubset(sh.keys()), f"missing fields: {required - sh.keys()}"


# ---------------------------------------------------------------------------
# Test 2: 未识别校名 → 422
# ---------------------------------------------------------------------------

def test_ladder_unknown_school_422(monkeypatch):
    """422 + detail 含'未识别' + candidates"""
    monkeypatch.setattr(main, "resolve_cn_university",   lambda name: None)
    monkeypatch.setattr(main, "suggest_cn_universities", lambda name: ["江苏大学", "江苏师范大学"])

    resp = client.get("/school-ladder", params={"school": "霍格沃茨"})
    assert resp.status_code == 422

    detail = resp.json()["detail"]
    assert "未识别" in detail["msg"], f"expected '未识别' in {detail}"
    assert "candidates" in detail,  f"expected candidates key in {detail}"


# ---------------------------------------------------------------------------
# Test 3: 门控校不在名单 → 行仍在但 list_status="不在认可名单"
# ---------------------------------------------------------------------------

def test_ladder_gated_school_not_on_list(monkeypatch):
    """
    ucl 无 stg 行 → 行仍存在于全景（区别 /position 剔除），list_status="不在认可名单"
    """
    # list rows 不含 ucl
    list_rows_no_ucl = [r for r in FAKE_LIST_ROWS if r["uk_uni_id"] != "ucl"]

    monkeypatch.setattr(main, "resolve_cn_university",   lambda name: FAKE_TIER)
    monkeypatch.setattr(main, "query_uk_universities",       lambda: FAKE_UK_UNIS)
    monkeypatch.setattr(main, "query_official_list_rows",    lambda cid: list_rows_no_ucl)
    monkeypatch.setattr(main, "query_match_rows",            lambda tier, grp: FAKE_MART_ROWS)

    resp = client.get("/school-ladder", params={"school": "江苏大学"})
    assert resp.status_code == 200

    body = resp.json()
    rows = {r["uk_uni_id"]: r for r in body["schools"]}

    assert "ucl" in rows, "ucl must appear in panoramic view even if not on list"
    assert rows["ucl"]["list_status"] == "不在认可名单", \
        f"expected '不在认可名单' got {rows['ucl']['list_status']}"


# ---------------------------------------------------------------------------
# Test 4: sheffield band=see-additional → 个案审核
# ---------------------------------------------------------------------------

def test_ladder_sheffield_see_additional(monkeypatch):
    """
    band=see-additional → list_status='个案审核', band_min_score=null, mart线 min_avg_score 仍透出
    """
    list_rows_see_add = [
        {
            "uk_uni_id":    "sheffield",
            "cn_uni_id":    "jiangsu_univ",
            "band":         "see-additional",
            "min_avg_score": None,              # see-additional 无 band 分数
            "source_type":  "official_web",
            "source_url":   "https://sheffield.ac.uk/official",
        },
    ]

    monkeypatch.setattr(main, "resolve_cn_university",   lambda name: FAKE_TIER)
    monkeypatch.setattr(main, "query_uk_universities",       lambda: FAKE_UK_UNIS)
    monkeypatch.setattr(main, "query_official_list_rows",    lambda cid: list_rows_see_add)
    monkeypatch.setattr(main, "query_match_rows",            lambda tier, grp: FAKE_MART_ROWS)

    resp = client.get("/school-ladder", params={"school": "江苏大学"})
    assert resp.status_code == 200

    rows = {r["uk_uni_id"]: r for r in resp.json()["schools"]}
    sh = rows["sheffield"]

    assert sh["list_status"] == "个案审核",  f"expected '个案审核' got {sh['list_status']}"
    assert sh["band_min_score"] is None,     f"expected null band_min_score got {sh['band_min_score']}"
    # mart tier 线仍透出
    assert sh["min_avg_score"] == 75.0,      f"expected mart line 75.0 got {sh['min_avg_score']}"


# ---------------------------------------------------------------------------
# Test 5: 非门控校 → 有分数线
# ---------------------------------------------------------------------------

def test_ladder_unlisted_uk_school(monkeypatch):
    """
    manchester 不是 LIST_GATED_SCHOOLS → list_status='有分数线', 不误判为'不在认可名单'
    """
    monkeypatch.setattr(main, "resolve_cn_university",   lambda name: FAKE_TIER)
    monkeypatch.setattr(main, "query_uk_universities",       lambda: FAKE_UK_UNIS)
    monkeypatch.setattr(main, "query_official_list_rows",    lambda cid: FAKE_LIST_ROWS)
    monkeypatch.setattr(main, "query_match_rows",            lambda tier, grp: FAKE_MART_ROWS)

    resp = client.get("/school-ladder", params={"school": "江苏大学"})
    assert resp.status_code == 200

    rows = {r["uk_uni_id"]: r for r in resp.json()["schools"]}
    man = rows["manchester"]

    assert man["list_status"] == "有分数线",           f"got {man['list_status']}"
    assert man["list_status"] != "不在认可名单",       "non-gated school must not be red-flagged"


# ---------------------------------------------------------------------------
# Test 6: LIST_GATED_SCHOOLS 常量不变
# ---------------------------------------------------------------------------

def test_ladder_gated_set_unchanged():
    """LIST_GATED_SCHOOLS must equal {'ucl', 'bristol', 'edinburgh'}"""
    assert LIST_GATED_SCHOOLS == {"ucl", "bristol", "edinburgh"}, \
        f"unexpected gated set: {LIST_GATED_SCHOOLS}"


# ---------------------------------------------------------------------------
# Test 7 (I-1): sheffield 不在 stg 名单时应回落通用规则而非硬写"未收录"
# ---------------------------------------------------------------------------

def test_ladder_sheffield_not_in_list_falls_back(monkeypatch):
    """
    西交大类: sheffield 不在 stg 名单但 mart 有 tier 线 (75/official) →
    list_status 必须是 "有分数线"，min_avg_score=75.0，band_min_score=None。
    不能出现 "未收录" 且仍透传 mart 线的矛盾状态。
    """
    # stg 不含 sheffield 行（只含 bristol）
    list_rows_no_sheffield = [r for r in FAKE_LIST_ROWS if r["uk_uni_id"] != "sheffield"]

    monkeypatch.setattr(main, "resolve_cn_university",    lambda name: FAKE_TIER)
    monkeypatch.setattr(main, "query_uk_universities",    lambda: FAKE_UK_UNIS)
    monkeypatch.setattr(main, "query_official_list_rows", lambda cid: list_rows_no_sheffield)
    # FAKE_MART_ROWS 含 sheffield(75.0/official_web)
    monkeypatch.setattr(main, "query_match_rows",         lambda tier, grp: FAKE_MART_ROWS)

    resp = client.get("/school-ladder", params={"school": "江苏大学"})
    assert resp.status_code == 200

    rows = {r["uk_uni_id"]: r for r in resp.json()["schools"]}
    sh = rows["sheffield"]

    assert sh["list_status"] == "有分数线", \
        f"sheffield 无 stg 行但 mart 有线，期望 '有分数线'，实际: {sh['list_status']}"
    assert sh["min_avg_score"] == 75.0, \
        f"min_avg_score 期望 75.0，实际: {sh['min_avg_score']}"
    assert sh["band_min_score"] is None, \
        f"band_min_score 应为 null，实际: {sh['band_min_score']}"
