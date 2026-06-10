import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from api import main
from api.main import app

client = TestClient(app)

FAKE_REQ = [{
    "uk_uni_id": "manchester", "profile_level": "standard",
    "ielts_overall": 6.5, "ielts_l": 6.0, "ielts_r": 6.0,
    "ielts_w": 6.0, "ielts_s": 6.0,
    "source_url": "https://example.org", "verified_at": "2026-06-12",
    "is_stale": False,
}]


def test_gap_subscore_short(monkeypatch):
    monkeypatch.setattr(main, "query_ielts_req", lambda uni: FAKE_REQ)
    resp = client.get("/ielts-gap", params={
        "uk_uni_id": "manchester",
        "overall": 7.0, "l": 6.5, "r": 6.5, "w": 5.5, "s": 6.0})
    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["gaps"]["overall"] == 0          # 7.0 >= 6.5 达标
    assert body["gaps"]["w"] == 0.5              # 写作差 0.5 —— 核心场景
    assert body["passed"] is False
    assert body["source_url"]                    # 来源必须透出


def test_unknown_school_404(monkeypatch):
    monkeypatch.setattr(main, "query_ielts_req", lambda uni: [])
    resp = client.get("/ielts-gap", params={"uk_uni_id": "hogwarts", "overall": 7.0})
    assert resp.status_code == 404
