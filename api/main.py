from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from api.db import fetch_all

app = FastAPI(title="英联邦留学选校 API", version="0.1.0")

# 本科专业关键词 → 大类。与 seeds/dim_major_mapping.csv 的 src_major_category 对齐。
MAJOR_KEYWORDS = {
    "计算机类": ["计算机", "软件", "computer", "software", "cs", "信息安全", "物联网"],
    "数学统计类": ["数学", "统计", "math", "statistic", "精算"],
    "电子电气类": ["电子", "电气", "通信", "微电子", "ee", "electronic"],
    "机械自动化类": ["机械", "自动化", "机电", "车辆", "mechanical"],
    "土木建筑类": ["土木", "建筑", "civil", "工程管理"],
    "经济金融类": ["经济", "金融", "finance", "econom", "国贸", "投资"],
    "管理类": ["管理", "工商", "市场营销", "会计", "business", "management"],
    "文科类": ["英语", "汉语", "历史", "哲学", "新闻", "翻译", "文学"],
    "理科类": ["物理", "化学", "生物", "材料", "环境"],
    "法学类": ["法学", "法律", "law"],
}


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


def query_major_rules() -> list[dict]:
    return fetch_all("SELECT * FROM dim_major_mapping")


def classify_major(raw: str) -> str | None:
    low = raw.lower()
    for cat, kws in MAJOR_KEYWORDS.items():
        if any(kw in low for kw in kws):
            return cat
    return None


class MajorFitIn(BaseModel):
    undergrad_major: str
    tgt_subject_group: str


@app.post("/major-fit")
def major_fit(body: MajorFitIn):
    cat = classify_major(body.undergrad_major)
    rules = query_major_rules()
    if cat:
        for rule in rules:
            if (rule["src_major_category"] == cat
                    and rule["tgt_subject_group"] == body.tgt_subject_group):
                return {
                    "src_major_category": cat,
                    "fit_level": rule["fit_level"],
                    "required_prereqs": rule.get("required_prereqs") or "",
                    "note": rule.get("note") or "",
                    "reviewed": bool(rule.get("reviewed")),
                }
    # 架构决策: 未命中规则表返回"待人工确认"+候选，不在线 LLM 即时判
    return {
        "src_major_category": cat,
        "fit_level": "待人工确认",
        "candidates": sorted(MAJOR_KEYWORDS.keys()),
        "note": "请从候选大类中确认你的本科专业归属",
        "reviewed": False,
    }
