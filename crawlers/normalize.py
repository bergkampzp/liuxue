"""录取结果归一：两爬虫共享。返回 (decision, decision_detail)。"""
from __future__ import annotations

import re


def normalize_decision(raw: str) -> tuple[str, str | None]:
    dr = (raw or "").strip().lower()
    if not dr:
        return ("Other", None)

    detail = None
    # 顺序敏感：uncon 先于 con（子串包含）
    if "uncon" in dr or "无条件" in dr:
        detail = "Unconditional"
    elif "con" in dr or "条件" in dr:
        detail = "Conditional"

    if "offer" in dr or re.search(r"\bad\b", dr, re.ASCII) or detail:
        return ("Offer", detail)
    if "reject" in dr or "rej" in dr or "拒" in dr:
        return ("Rejected", None)
    if "wl" in dr or "wait" in dr:
        return ("Waitlist", None)
    if "interview" in dr or "面试" in dr:
        return ("Interview", None)
    return ("Other", None)
