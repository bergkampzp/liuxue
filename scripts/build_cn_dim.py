#!/usr/bin/env python3
"""
build_cn_dim.py — 把 615 所中国大学全量并入 dim_cn_university 维表，并生成简称别名。

幂等可重跑：每次从 /tmp/cn_universities_full.csv（全量）+ 旧 seed（仅取已有 id 映射）
重建 dim_cn_university.csv 与 cn_university_alias.csv。

关键不变量：
  - 985/211 等已有校的 cn_uni_id 必须沿用旧 seed（保护 stg_uk_official_lists 归一、
    北极星 jiangsu_univ 等下游 join），按 name_zh 匹配复用。
  - tier_label: is_985→'985'; elif is_211→'211'; elif is_double_first→'双一流'; else→'双非'
  - alias 唯一（一对一），冲突项剔除并在报告中列出。

用法: python3 scripts/build_cn_dim.py
"""
from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEEDS = ROOT / "dbt_liuxue" / "seeds"
FULL_CSV = Path("/tmp/cn_universities_full.csv")
DIM_CSV = SEEDS / "dim_cn_university.csv"
ALIAS_CSV = SEEDS / "cn_university_alias.csv"

DIM_HEADER = ["cn_uni_id", "name_zh", "name_en", "is_985", "is_211", "tier_label"]
ALIAS_HEADER = ["alias", "cn_uni_id"]


# ── 工具 ──────────────────────────────────────────────────────────────────

def _truthy(v: str) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "t")


def tier_of(is_985: bool, is_211: bool, is_df: bool) -> str:
    if is_985:
        return "985"
    if is_211:
        return "211"
    if is_df:
        return "双一流"
    return "双非"


_STOP_EN = {
    "of", "and", "the", "for", "&", "a", "in", "at", "de",
}


def slug_from_en(name_en: str) -> str:
    """name_en → 小写无空格首字母缩写; 兜底用全名拼接 (无空格无特殊字符)。"""
    name_en = (name_en or "").strip()
    if not name_en:
        return ""
    # 去括号内容（如 (China)）但保留核心词
    name_en = re.sub(r"\([^)]*\)", " ", name_en)
    words = [w for w in re.split(r"[\s\-]+", name_en) if w]
    core = [w for w in words if w.lower() not in _STOP_EN]
    if not core:
        core = words
    # 首字母缩写
    initials = "".join(w[0] for w in core if w[:1].isalpha()).lower()
    initials = re.sub(r"[^a-z0-9]", "", initials)
    if len(initials) >= 2:
        return initials
    # 兜底：核心词全拼接小写
    full = re.sub(r"[^a-z0-9]", "", "".join(core).lower())
    return full or re.sub(r"[^a-z0-9]", "", name_en.lower())


def uniquify(base: str, used: set[str]) -> str:
    base = base or "uni"
    if base not in used:
        return base
    i = 2
    while f"{base}{i}" in used:
        i += 1
    return f"{base}{i}"


# ── 1. dim 构建 ───────────────────────────────────────────────────────────

def load_old_id_map() -> dict[str, str]:
    """旧 seed: name_zh → cn_uni_id（保护已建立 join 关系）。"""
    m: dict[str, str] = {}
    if not DIM_CSV.exists():
        return m
    with DIM_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            zh = (row.get("name_zh") or "").strip()
            cid = (row.get("cn_uni_id") or "").strip()
            if zh and cid:
                m[zh] = cid
    return m


def build_dim(old_id_map: dict[str, str]) -> list[dict]:
    rows: list[dict] = []
    used_ids: set[str] = set()
    seen_zh: set[str] = set()

    with FULL_CSV.open(encoding="utf-8") as f:
        records = list(csv.DictReader(f))

    # Pass 1: 先把沿用旧 id 的校占住 id，保证新校不撞车
    pending: list[dict] = []
    for r in records:
        zh = (r["name_zh"] or "").strip()
        if not zh or zh in seen_zh:
            continue
        seen_zh.add(zh)
        is985 = _truthy(r["is_985"])
        is211 = _truthy(r["is_211"])
        isdf = _truthy(r["is_double_first"])
        rec = {
            "name_zh": zh,
            "name_en": (r["name_en"] or "").strip(),
            "is_985": "true" if is985 else "false",
            "is_211": "true" if is211 else "false",
            "tier_label": tier_of(is985, is211, isdf),
        }
        if zh in old_id_map:
            cid = old_id_map[zh]
            rec["cn_uni_id"] = cid
            used_ids.add(cid)
            rows.append(rec)
        else:
            pending.append(rec)

    # Pass 2: 新校生成唯一 id
    for rec in pending:
        base = slug_from_en(rec["name_en"])
        cid = uniquify(base, used_ids)
        used_ids.add(cid)
        rec["cn_uni_id"] = cid
        rows.append(rec)

    rows.sort(key=lambda x: (
        {"985": 0, "211": 1, "双一流": 2, "双非": 3}.get(x["tier_label"], 9),
        x["cn_uni_id"],
    ))
    return rows


# ── 2. 别名构建 ───────────────────────────────────────────────────────────

def load_existing_aliases() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not ALIAS_CSV.exists():
        return out
    with ALIAS_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            a = (row.get("alias") or "").strip()
            c = (row.get("cn_uni_id") or "").strip()
            if a and c:
                out.append((a, c))
    return out


# 知名度优先级：tier 越高、id 越短越知名（用于冲突时择优）
def fame_rank(tier: str) -> int:
    return {"985": 0, "211": 1, "双一流": 2, "双非": 3}.get(tier, 9)


def gen_short_aliases(zh: str) -> list[str]:
    """从 name_zh 生成候选简称（不含全称本身）。"""
    cands: list[str] = []
    s = zh

    # 去 "中国"/"中华" 前缀 → 形成另一全称变体（如 中国人民大学→人民大学）
    for pfx in ("中国", "中华"):
        if s.startswith(pfx) and len(s) > len(pfx) + 1:
            cands.append(s[len(pfx):])

    if not s.endswith("大学"):
        return cands
    core = s[:-2]  # 去 "大学"
    # 去 "中国"/"中华" 前缀后的核心
    core_np = core
    for pfx in ("中国", "中华"):
        if core_np.startswith(pfx):
            core_np = core_np[len(pfx):]

    # 两字简称：核心词首字 + "大"  （北京大学→北大；郑州大学→郑大；兰州大学→兰大）
    if len(core_np) >= 2:
        cands.append(core_np[0] + "大")
    # 含理工/工业/科技/师范 等的常见缩法：首字 + 学科首字（如 华中科技→华科）
    SUBJ = [("科技", "科"), ("理工", "理工"), ("工业", "工"),
            ("师范", "师大"), ("交通", "交")]
    for kw, suf in SUBJ:
        if kw in core_np:
            head = core_np.split(kw)[0]
            if head:
                cands.append(head[0] + suf)
    return cands


def build_aliases(dim_rows: list[dict]) -> tuple[list[tuple[str, str]], list[dict]]:
    """
    优先级（高→低）：
      1. 现有 seed 别名（人工策展、一对一已稳定，权威）——直接占位，永不被生成别名挤掉
      2. 程序生成简称——仅在该 alias 尚无权威占位时参与；生成项之间若冲突则按知名度择优，
         多目标冲突 -> 全部剔除并报告（避免误指向）
      3. 全称：name_zh 本身不再重复加入 alias 表（已在 dim 命中），但用作冲突歧义判定
    """
    id_to_tier = {r["cn_uni_id"]: r["tier_label"] for r in dim_rows}
    valid_ids = set(id_to_tier)
    zh_rows = [(r["name_zh"], r["cn_uni_id"]) for r in dim_rows]
    fullname_owner = {zh: cid for zh, cid in zh_rows}

    final: list[tuple[str, str]] = []
    conflicts: list[dict] = []

    # ── 1. 权威：现有 seed 别名（去重，首见为准） ──
    authoritative: dict[str, str] = {}
    for a, c in load_existing_aliases():
        a = a.strip()
        if not a or c not in valid_ids:
            continue  # 指向已删 id 的旧别名 -> 丢弃（id 兼容已保证不该发生）
        if a not in authoritative:
            authoritative[a] = c

    # ── 2. 程序生成简称：聚合候选目标 ──
    gen_targets: dict[str, set[str]] = defaultdict(set)
    gen_order: list[str] = []
    for zh, cid in zh_rows:
        for a in gen_short_aliases(zh):
            a = a.strip()
            if not a:
                continue
            if a in authoritative:
                continue  # 已被权威别名占位，生成项让位（不算冲突）
            if a in fullname_owner and fullname_owner[a] != cid:
                continue  # 别名撞上另一所校全称 -> 歧义，跳过
            if a not in gen_targets:
                gen_order.append(a)
            gen_targets[a].add(cid)

    # ── 3. 输出权威别名 ──
    for a, c in authoritative.items():
        final.append((a, c))

    # ── 4. 输出生成别名 ──
    # 无冲突直接收；有冲突时若存在「唯一最知名」(tier 严格高于其余全部)则只保留它，
    # 否则（顶档并列，无法判定）整项剔除并记录。
    for a in gen_order:
        targets = sorted(gen_targets[a])
        if len(targets) == 1:
            final.append((a, targets[0]))
            continue
        ranked = sorted(targets, key=lambda c: (fame_rank(id_to_tier[c]), len(c), c))
        top, second = ranked[0], ranked[1]
        if fame_rank(id_to_tier[top]) < fame_rank(id_to_tier[second]):
            # 唯一最知名（tier 严格更高）→ 保留它，其余作为“已择优”记录
            final.append((a, top))
            conflicts.append({"alias": a, "targets": targets, "kept": top,
                              "resolved": True})
        else:
            conflicts.append({"alias": a, "targets": targets, "kept": None,
                              "resolved": False})

    final.sort(key=lambda x: (x[1], x[0]))
    return final, conflicts


# ── 写出 ──────────────────────────────────────────────────────────────────

def write_csv(path: Path, header: list[str], rows: list[dict] | list[tuple]):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in rows:
            if isinstance(row, dict):
                w.writerow([row[h] for h in header])
            else:
                w.writerow(list(row))


def main() -> int:
    if not FULL_CSV.exists():
        print(f"ERROR: 缺少输入 {FULL_CSV}", file=sys.stderr)
        return 1

    old_id_map = load_old_id_map()
    n_alias_before = len(load_existing_aliases())
    dim_rows = build_dim(old_id_map)

    # 不变量校验：旧校 id 必须沿用
    reused = sum(1 for r in dim_rows if r["name_zh"] in old_id_map
                 and r["cn_uni_id"] == old_id_map[r["name_zh"]])
    drifted = [r["name_zh"] for r in dim_rows
               if r["name_zh"] in old_id_map and r["cn_uni_id"] != old_id_map[r["name_zh"]]]

    alias_rows, conflicts = build_aliases(dim_rows)

    write_csv(DIM_CSV, DIM_HEADER, dim_rows)
    write_csv(ALIAS_CSV, ALIAS_HEADER, alias_rows)

    # ── 报告 ──
    tiers = defaultdict(int)
    for r in dim_rows:
        tiers[r["tier_label"]] += 1
    print("=" * 56)
    print(f"dim_cn_university 总校数: {len(dim_rows)}")
    for t in ("985", "211", "双一流", "双非"):
        print(f"  {t}: {tiers.get(t, 0)}")
    print(f"旧 id 沿用: {reused}/{len(old_id_map)}  漂移: {len(drifted)} {drifted or ''}")
    print(f"别名总数: {len(alias_rows)}（原 {n_alias_before}，新增 {len(alias_rows) - n_alias_before}）")
    resolved = [c for c in conflicts if c.get("resolved")]
    dropped = [c for c in conflicts if not c.get("resolved")]
    print(f"别名冲突: {len(conflicts)}（择优保留 {len(resolved)}，无法判定剔除 {len(dropped)}）")
    for c in resolved:
        print(f"  ⚖ {c['alias']} → 保留 {c['kept']}  (候选 {c['targets']})")
    for c in dropped:
        print(f"  ✗ {c['alias']} → 剔除  (顶档并列 {c['targets']})")
    print("=" * 56)
    if drifted:
        print("WARNING: 检测到旧 id 漂移，下游 join 可能断裂！", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
