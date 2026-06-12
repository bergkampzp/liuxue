import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from api import main
from api.main import app

client = TestClient(app)

FAKE_ROWS = [
    {"uk_uni_id": "manchester", "name_zh": "曼彻斯特大学", "qs_rank": 35,
     "subject_group": "通用", "cn_tier": "双非", "min_avg_score": 82.0,
     "source_type": "aggregator", "source_url": "https://www.testdaily.cn/64451/",
     "confidence": "low", "ielts_overall": 6.5, "ielts_l": 6.0, "ielts_r": 6.0,
     "ielts_w": 6.0, "ielts_s": 6.0, "ielts_source_url": "https://example.org"},
    {"uk_uni_id": "ucl", "name_zh": "伦敦大学学院", "qs_rank": 9,
     "subject_group": "通用", "cn_tier": "双非", "min_avg_score": 90.0,
     "source_type": "official_web", "source_url": "https://www.ucl.ac.uk/x",
     "confidence": "high", "ielts_overall": 7.0, "ielts_l": 6.5, "ielts_r": 6.5,
     "ielts_w": 6.5, "ielts_s": 6.5, "ielts_source_url": "https://example.org"},
]
FAKE_TIER = {"cn_uni_id": "jiangsu_univ", "tier_label": "双非", "name_zh": "江苏大学"}


def test_position_buckets(monkeypatch):
    monkeypatch.setattr(main, "query_match_rows", lambda tier, group: FAKE_ROWS)
    monkeypatch.setattr(main, "resolve_cn_university", lambda name: FAKE_TIER)
    monkeypatch.setattr(main, "query_list_membership", lambda cid: {"ucl"})  # 在名单内,保持原断言
    monkeypatch.setattr(main, "query_official_list_rows", lambda cid: [])   # 无逐校线，走tier聚合
    resp = client.post("/position", json={
        "undergrad_school": "江苏大学", "avg_score": 84.0,
        "undergrad_major": "软件工程", "tgt_subject_group": "通用",
        "ielts_overall": 6.5, "ielts_w": 6.0})
    assert resp.status_code == 200
    body = resp.json()
    bucket = {r["uk_uni_id"]: r["tier"] for r in body["schools"]}
    assert bucket["manchester"] == "保"     # gap=+2
    assert bucket["ucl"] == "不建议"        # gap=-6
    man = next(r for r in body["schools"] if r["uk_uni_id"] == "manchester")
    assert "参考线" in man["explanation"]   # aggregator 话术红线
    assert man["source_url"]
    assert body["major_fit"] is not None    # 功能3嵌入: 软件工程→计算机类 应有判定


def test_unknown_school_422(monkeypatch):
    monkeypatch.setattr(main, "resolve_cn_university", lambda name: None)
    resp = client.post("/position", json={
        "undergrad_school": "霍格沃茨", "avg_score": 84.0,
        "undergrad_major": "魔法", "tgt_subject_group": "通用",
        "ielts_overall": 6.5})
    assert resp.status_code == 422


def test_list_gated_school_excluded(monkeypatch):
    """江苏大学不在 UCL 84校名单内 → ucl 不进冲/匹/保, 进 not_on_list"""
    monkeypatch.setattr(main, "query_match_rows", lambda t, g: FAKE_ROWS)
    monkeypatch.setattr(main, "resolve_cn_university", lambda n: FAKE_TIER)
    monkeypatch.setattr(main, "query_list_membership", lambda cid: set())  # 不在任何名单
    monkeypatch.setattr(main, "query_official_list_rows", lambda cid: [])
    resp = client.post("/position", json={
        "undergrad_school": "江苏大学", "avg_score": 84.0,
        "undergrad_major": "软件工程", "tgt_subject_group": "通用",
        "ielts_overall": 6.5})
    assert resp.status_code == 200
    body = resp.json()
    assert "ucl" not in {r["uk_uni_id"] for r in body["schools"]}
    assert any(r["uk_uni_id"] == "ucl" for r in body["not_on_list"])


# --- 新增：逐校精确线覆盖 tier 聚合线 ---

FAKE_ROWS_WITH_SHEFFIELD = [
    {"uk_uni_id": "sheffield", "name_zh": "谢菲尔德大学", "qs_rank": 111,
     "subject_group": "通用", "cn_tier": "双非", "min_avg_score": 85.0,
     "source_type": "aggregator", "source_url": "https://example.org/tier",
     "confidence": "low", "ielts_overall": 6.5, "ielts_l": None, "ielts_r": None,
     "ielts_w": None, "ielts_s": None, "ielts_source_url": None},
]

FAKE_OFFICIAL_ROWS_SHEFFIELD = [
    {"uk_uni_id": "sheffield", "cn_uni_id": "jiangsu_univ",
     "band": "arwu-tier1", "min_avg_score": 70.0,
     "source_url": "https://www.sheffield.ac.uk/study/international/china"},
]


def test_exact_line_overrides_tier_aggregation(monkeypatch):
    """谢菲对江苏大学有逐校公开线 70 → 应用 70，不用 tier 聚合线 85。
    source_type 也应变为 official_web，confidence=high。"""
    monkeypatch.setattr(main, "query_match_rows", lambda t, g: FAKE_ROWS_WITH_SHEFFIELD)
    monkeypatch.setattr(main, "resolve_cn_university", lambda n: FAKE_TIER)
    monkeypatch.setattr(main, "query_list_membership", lambda cid: set())
    monkeypatch.setattr(main, "query_official_list_rows",
                        lambda cid: FAKE_OFFICIAL_ROWS_SHEFFIELD)
    resp = client.post("/position", json={
        "undergrad_school": "江苏大学", "avg_score": 82.0,
        "undergrad_major": "软件工程", "tgt_subject_group": "通用"})
    assert resp.status_code == 200
    body = resp.json()
    sh = next((r for r in body["schools"] if r["uk_uni_id"] == "sheffield"), None)
    assert sh is not None, "谢菲应出现在 schools 列表"
    assert sh["min_avg_score"] == 70.0, \
        f"应用逐校精确线 70，实得 {sh['min_avg_score']}"
    assert sh["source_type"] == "official_web", \
        f"逐校线应标记 official_web，实得 {sh['source_type']}"
    assert sh["confidence"] == "high"
    assert "逐校分档" in sh["explanation"], "explanation 应体现'逐校分档'"
