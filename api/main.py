import re

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from rapidfuzz import fuzz, process

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
        for kw in kws:
            # Short ASCII keywords (≤3 chars, e.g. cs/ee/law) need word boundary
            # to avoid substring false positives (e.g. "cs" in "economics").
            # Long keywords and Chinese keywords use plain substring match.
            if kw.isascii() and len(kw) <= 3:
                if re.search(r'\b' + re.escape(kw) + r'\b', low, re.ASCII):
                    return cat
            else:
                if kw in low:
                    return cat
    return None


def resolve_cn_university(name: str) -> dict | None:
    """校名→维表行: 精确(中/英/别名)→模糊(≥85分)"""
    rows = fetch_all("""
        SELECT d.cn_uni_id, d.name_zh, d.tier_label FROM dim_cn_university d
        WHERE d.name_zh = %s OR lower(d.name_en) = lower(%s)
        UNION
        SELECT d.cn_uni_id, d.name_zh, d.tier_label
        FROM cn_university_alias a JOIN dim_cn_university d USING (cn_uni_id)
        WHERE a.alias = %s
    """, (name, name, name))
    if rows:
        return rows[0]
    all_rows = fetch_all("SELECT cn_uni_id, name_zh, tier_label FROM dim_cn_university")
    best = process.extractOne(name, [r["name_zh"] for r in all_rows], scorer=fuzz.ratio)
    if best and best[1] >= 85:
        return next(r for r in all_rows if r["name_zh"] == best[0])
    return None


def query_match_rows(cn_tier: str, subject_group: str) -> list[dict]:
    return fetch_all("""
        SELECT * FROM mart_uk_school_match_v1
        WHERE cn_tier = %s AND subject_group IN (%s, '通用')
    """, (cn_tier, subject_group))


SOURCE_LABEL = {
    "official_web": "官方公布门槛",
    "official_pdf": "官方公布门槛",
    "aggregator": "第三方整理参考线，建议核对官网",
    "case_inferred": "历史案例估计参考线",
}


def bucket_of(gap: float) -> str:
    if gap >= 2:
        return "保"
    if gap >= -2:
        return "匹"
    if gap >= -5:
        return "冲"
    return "不建议"


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


class PositionIn(BaseModel):
    undergrad_school: str
    avg_score: float
    undergrad_major: str
    tgt_subject_group: str
    ielts_overall: float | None = None
    ielts_l: float | None = None
    ielts_r: float | None = None
    ielts_w: float | None = None
    ielts_s: float | None = None


@app.post("/position")
def position(body: PositionIn):
    uni = resolve_cn_university(body.undergrad_school)
    if uni is None:
        raise HTTPException(422, detail={"msg": "未识别本科院校，请确认校名",
                                         "hint": "尝试输入全称，如'江苏大学'"})
    rows = query_match_rows(uni["tier_label"], body.tgt_subject_group)
    schools = []
    for row in rows:
        gap = round(body.avg_score - float(row["min_avg_score"]), 1)
        tier = bucket_of(gap)
        ielts_flag = None
        checks = [("总分", body.ielts_overall, row.get("ielts_overall")),
                  ("写作", body.ielts_w, row.get("ielts_w")),
                  ("口语", body.ielts_s, row.get("ielts_s"))]
        for label, have, need in checks:
            if have is not None and need is not None and float(have) < float(need):
                ielts_flag = f"雅思{label}差{round(float(need) - float(have), 1)}"
                tier = {"保": "匹", "匹": "冲", "冲": "不建议", "不建议": "不建议"}[tier]
                break
        explanation = (
            f"{SOURCE_LABEL[row['source_type']]}：{uni['tier_label']}背景约需均分"
            f"{row['min_avg_score']}，你的均分{body.avg_score}（差距{gap:+}）。"
            + (f"{ielts_flag}，按降一档处理。" if ielts_flag else ""))
        if row["source_type"] != "official_web" and "参考线" not in explanation:
            explanation += "（参考线，非录取承诺）"
        schools.append({
            "uk_uni_id": row["uk_uni_id"],
            "name_zh": row["name_zh"],
            "qs_rank": row["qs_rank"],
            "tier": tier,
            "gap": gap,
            "min_avg_score": float(row["min_avg_score"]),
            "source_type": row["source_type"],
            "source_url": row["source_url"],
            "confidence": row["confidence"],
            "ielts_flag": ielts_flag,
            "explanation": explanation,
        })
    schools.sort(key=lambda x: (x["qs_rank"] or 999))
    # 功能3嵌入: 复用 MVP-0 的 classify_major + 规则表
    cat = classify_major(body.undergrad_major)
    major_fit = None
    if cat:
        for rule in query_major_rules():
            if (rule["src_major_category"] == cat
                    and rule["tgt_subject_group"] == body.tgt_subject_group):
                major_fit = {
                    "src_major_category": cat,
                    "fit_level": rule["fit_level"],
                    "required_prereqs": rule.get("required_prereqs") or "",
                }
                break
        # 回退: 找不到 (cat × group) 精确行时返回基础判定，保证非 None
        if major_fit is None:
            major_fit = {
                "src_major_category": cat,
                "fit_level": "未知方向",
                "required_prereqs": "",
            }
    return {
        "cn_university": uni,
        "schools": schools,
        "major_fit": major_fit,
        "waitlist_hint": "曼大/KCL等校精确线即将上线，可在 /waitlist 留邮箱",
    }
