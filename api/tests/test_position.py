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
