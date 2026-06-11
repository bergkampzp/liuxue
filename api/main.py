import re
import json

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from rapidfuzz import fuzz, process

from api.db import fetch_all, execute

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


LIST_GATED_SCHOOLS = {"ucl", "bristol", "edinburgh"}  # 有官方in/out名单的校(sheffield全量分档不卡名单)


def query_list_membership(cn_uni_id: str) -> set[str]:
    """该本科校出现在哪些英国校的官方名单里"""
    rows = fetch_all(
        "SELECT DISTINCT uk_uni_id FROM stg_uk_official_lists WHERE cn_uni_id = %s",
        (cn_uni_id,))
    return {r["uk_uni_id"] for r in rows}


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
    membership = query_list_membership(uni["cn_uni_id"])
    schools = []
    not_on_list = []
    for row in rows:
        # 有官方in/out名单的校：不在名单内则移入not_on_list，不参与冲/匹/保/不建议
        if row["uk_uni_id"] in LIST_GATED_SCHOOLS and row["uk_uni_id"] not in membership:
            not_on_list.append({
                "uk_uni_id": row["uk_uni_id"],
                "name_zh": row["name_zh"],
                "note": "你的本科院校不在该校官方认可名单,通常不予考虑",
                "source_url": row["source_url"],
            })
            continue
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
        "not_on_list": not_on_list,
        "major_fit": major_fit,
        "waitlist_hint": "曼大/KCL等校精确线即将上线，可在 /waitlist 留邮箱",
    }


def query_uk_universities() -> list[dict]:
    """全量 dim_uk_university，30 行（qs_rank 升序 null 殿后由端点排序）"""
    return fetch_all("SELECT uk_uni_id, name_zh, qs_rank FROM dim_uk_university")


def query_official_list_rows(cn_uni_id: str) -> list[dict]:
    """本科校在 stg_uk_official_lists 中的所有命中行（≤4校）"""
    return fetch_all(
        "SELECT uk_uni_id, cn_uni_id, band, min_avg_score, source_url "
        "FROM stg_uk_official_lists WHERE cn_uni_id = %s",
        (cn_uni_id,))


def suggest_cn_universities(name: str) -> list[str]:
    """模糊匹配候选校名，fuzz≥60 取前 3"""
    all_rows = fetch_all("SELECT name_zh FROM dim_cn_university")
    names = [r["name_zh"] for r in all_rows]
    results = process.extract(name, names, scorer=fuzz.ratio, limit=10)
    return [r[0] for r in results if r[1] >= 60][:3]


def synth_row(dim_row: dict, stg_hits: dict, mart_hits: dict) -> dict:
    """
    纯函数：不查库。
    dim_row   : {uk_uni_id, name_zh, qs_rank}
    stg_hits  : dict[uk_uni_id -> stg list row]
    mart_hits : dict[uk_uni_id -> mart match row]
    返回 9 字段行（契约字段）。
    """
    uid = dim_row["uk_uni_id"]
    stg = stg_hits.get(uid)
    mart = mart_hits.get(uid)

    # ---- list_status & band_min_score ----
    if uid == "sheffield":
        if stg:
            band = stg.get("band") or ""
            arwu_bands = {"arwu-tier1", "arwu-tier2", "arwu-tier3", "arwu-tier4"}
            special_bands = {"see-additional", "gpa-scale"}
            if band in arwu_bands:
                list_status = f"名单内({band})"
                band_min_score = float(stg["min_avg_score"]) if stg.get("min_avg_score") is not None else None
            elif band in special_bands:
                list_status = "个案审核"
                band_min_score = None
            else:
                list_status = f"名单内({band})" if band else "有分数线"
                band_min_score = float(stg["min_avg_score"]) if stg.get("min_avg_score") is not None else None
        else:
            list_status = "未收录"
            band_min_score = None
    elif uid in LIST_GATED_SCHOOLS:
        if stg:
            band = stg.get("band") or ""
            list_status = f"名单内({band})" if band else "名单内"
            band_min_score = None
        else:
            list_status = "不在认可名单"
            band_min_score = None
    else:
        # 其余校: mart 命中 → 有分数线; 否则 → 未收录
        if mart:
            list_status = "有分数线"
        else:
            list_status = "未收录"
        band_min_score = None

    # ---- min_avg_score: 一律取 mart tier 线 ----
    min_avg_score = float(mart["min_avg_score"]) if mart and mart.get("min_avg_score") is not None else None

    # ---- source_type / source_url: 名单出处优先(stg)，无则mart，无则null ----
    # stg 表无 source_type 列，名单行一律视为 official_web
    if stg:
        source_type = stg.get("source_type") or "official_web"
        source_url = stg.get("source_url") or (mart.get("source_url") if mart else None)
    elif mart:
        source_type = mart.get("source_type")
        source_url = mart.get("source_url")
    else:
        source_type = None
        source_url = None

    ielts_overall = float(mart["ielts_overall"]) if mart and mart.get("ielts_overall") is not None else None

    return {
        "uk_uni_id":      uid,
        "name_zh":        dim_row["name_zh"],
        "qs_rank":        dim_row.get("qs_rank"),
        "list_status":    list_status,
        "band_min_score": band_min_score,
        "min_avg_score":  min_avg_score,
        "source_type":    source_type,
        "source_url":     source_url,
        "ielts_overall":  ielts_overall,
    }


@app.get("/school-ladder")
def school_ladder(school: str):
    uni = resolve_cn_university(school)
    if uni is None:
        candidates = suggest_cn_universities(school)
        raise HTTPException(422, detail={
            "msg": f"未识别本科院校'{school}'，请确认校名",
            "hint": "尝试输入全称，如'江苏大学'",
            "candidates": candidates,
        })

    # 固定 3 查询防 N+1
    all_unis = query_uk_universities()
    list_rows = query_official_list_rows(uni["cn_uni_id"])
    mart_rows = query_match_rows(uni["tier_label"], "通用")

    # 建索引
    stg_hits = {r["uk_uni_id"]: r for r in list_rows}
    mart_hits = {r["uk_uni_id"]: r for r in mart_rows}

    # Python 合成
    schools = [synth_row(d, stg_hits, mart_hits) for d in all_unis]

    # qs_rank 升序 null 殿后
    schools.sort(key=lambda x: (x["qs_rank"] is None, x["qs_rank"] or 9999))

    return {
        "cn_university": uni,
        "schools": schools,
        "disclaimer": "分数线为入学门槛参考，不构成录取承诺；名单与分数以校方当年官网为准",
    }


def insert_waitlist(email: str, uk_uni_id: str | None, profile: dict | None):
    execute("INSERT INTO raw.waitlist_leads (email, uk_uni_id, profile_json) VALUES (%s,%s,%s)",
            (email, uk_uni_id, json.dumps(profile or {}, ensure_ascii=False)))


class WaitlistIn(BaseModel):
    email: EmailStr
    uk_uni_id: str | None = None
    profile: dict | None = None


@app.post("/waitlist")
def waitlist(body: WaitlistIn):
    insert_waitlist(body.email, body.uk_uni_id, body.profile)
    return {"ok": True, "msg": "已登记，上线后第一时间通知你"}
