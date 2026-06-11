import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from api import main
from api.main import app

client = TestClient(app)


def test_waitlist_saves(monkeypatch):
    saved = {}
    monkeypatch.setattr(main, "insert_waitlist",
                        lambda email, uni, profile: saved.update(
                            {"email": email, "uni": uni}))
    resp = client.post("/waitlist", json={
        "email": "a@b.com", "uk_uni_id": "manchester", "profile": {"avg": 82}})
    assert resp.status_code == 200
    assert saved["email"] == "a@b.com"


def test_bad_email_422():
    resp = client.post("/waitlist", json={"email": "not-an-email"})
    assert resp.status_code == 422
