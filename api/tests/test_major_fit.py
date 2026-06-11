import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from api import main
from api.main import app

client = TestClient(app)

FAKE_RULES = [
    {"src_major_category": "数学统计类", "tgt_subject_group": "CS与数据",
     "fit_level": "可转", "required_prereqs": "编程基础;数据结构",
     "note": "需课程描述佐证", "reviewed": False},
]


def test_match_keyword(monkeypatch):
    monkeypatch.setattr(main, "query_major_rules", lambda: FAKE_RULES)
    resp = client.post("/major-fit", json={
        "undergrad_major": "应用统计", "tgt_subject_group": "CS与数据"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fit_level"] == "可转"
    assert "编程基础" in body["required_prereqs"]
    assert body["reviewed"] is False     # 未经顾问复核必须透出


def test_no_match_returns_candidates(monkeypatch):
    monkeypatch.setattr(main, "query_major_rules", lambda: FAKE_RULES)
    resp = client.post("/major-fit", json={
        "undergrad_major": "口腔医学", "tgt_subject_group": "CS与数据"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fit_level"] == "待人工确认"   # 架构决策: 不在线LLM即时判
    assert isinstance(body["candidates"], list)


def test_english_major_no_cs_substring_misjudge(monkeypatch):
    # "Economics"含"cs"子串、"engineering"含"ee"子串——不得误归计算机/电气类
    monkeypatch.setattr(main, "query_major_rules", lambda: [])
    from api.main import classify_major
    assert classify_major("Economics") == "经济金融类"      # econom 长关键词命中
    assert classify_major("engineering") != "电子电气类"    # ee 词边界不命中
