"""录取结果归一：两爬虫共享。返回 (decision, decision_detail)。"""
from __future__ import annotations

import re


def normalize_decision(raw: str) -> tuple[str, str | None]:
    dr = (raw or "").strip().lower()
    if not dr:
        return ("Other", None)

    detail = None
    # 顺序敏感：uncon 先于 con（子串包含）
    if re.search(r"\buncon", dr, re.ASCII) or "无条件" in dr:
        detail = "Unconditional"
    elif re.search(r"\bcon(?:ditional)?\b", dr, re.ASCII) or "条件" in dr:
        detail = "Conditional"

    # Reject判断必须在 detail 短路之前：拒信含"条件"不得误判为 Offer
    if "reject" in dr or "rej" in dr or "拒" in dr:
        return ("Rejected", None)
    if "offer" in dr or re.search(r"\bad\b", dr, re.ASCII) or detail:
        return ("Offer", detail)
    # re.ASCII: 中文不算\w，使 \b 在中英混排处(如"AD小奖")正确成立
    if re.search(r"\bwl\b", dr, re.ASCII) or "wait" in dr:
        return ("Waitlist", None)
    if "interview" in dr or "面试" in dr:
        return ("Interview", None)
    return ("Other", None)
