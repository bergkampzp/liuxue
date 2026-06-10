from fastapi import FastAPI, HTTPException

from api.db import fetch_all

app = FastAPI(title="英联邦留学选校 API", version="0.1.0")


def query_ielts_req(uk_uni_id: str) -> list[dict]:
    return fetch_all(
        "SELECT * FROM stg_uk_ielts_requirements WHERE uk_uni_id = %s", (uk_uni_id,))


@app.get("/ielts-gap")
def ielts_gap(uk_uni_id: str, overall: float,
              l: float | None = None, r: float | None = None,
              w: float | None = None, s: float | None = None):
    reqs = query_ielts_req(uk_uni_id)
    if not reqs:
        raise HTTPException(404, detail=f"未收录 {uk_uni_id} 的雅思要求")
    student = {"overall": overall, "l": l, "r": r, "w": w, "s": s}
    out = []
    for req in reqs:
        gaps, passed = {}, True
        for k, col in [("overall", "ielts_overall"), ("l", "ielts_l"),
                       ("r", "ielts_r"), ("w", "ielts_w"), ("s", "ielts_s")]:
            need = req.get(col)
            have = student.get(k)
            if need is None:
                continue
            if have is None:
                gaps[k] = None        # 学生未提供该项
                continue
            gap = round(max(0.0, float(need) - float(have)), 1)
            gaps[k] = gap
            if gap > 0:
                passed = False
        out.append({
            "uk_uni_id": req["uk_uni_id"],
            "profile_level": req["profile_level"],
            "requirement": {c: req.get(c) for c in
                            ("ielts_overall", "ielts_l", "ielts_r", "ielts_w", "ielts_s")},
            "gaps": gaps,
            "passed": passed,
            "source_url": req["source_url"],       # 话术红线: 来源必须透出
            "verified_at": str(req["verified_at"]),
            "stale": bool(req.get("is_stale")),
        })
    return out
