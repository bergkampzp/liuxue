"""
TDD tests for normalize_cases.py — match_school() pure function

四用例契约（计划 R-T2 钉死）：
  1. 精确中文 → exact 命中
  2. 别名"成电" → alias 命中 uestc
  3. 模糊"电子科技大学(沙河校区)" → fuzzy 命中 uestc（partial_ratio >= 92）
  4. 不命中"剑桥高中" → None
"""
from normalize_cases import match_school


# ---------------------------------------------------------------------------
# 夹具数据（不依赖 DB）
# ---------------------------------------------------------------------------

DIM_ROWS = [
    {"cn_uni_id": "tsinghua", "name_zh": "清华大学",         "name_en": "Tsinghua University"},
    {"cn_uni_id": "pku",      "name_zh": "北京大学",         "name_en": "Peking University"},
    {"cn_uni_id": "uestc",    "name_zh": "电子科技大学",     "name_en": "University of Electronic Science and Technology of China"},
    {"cn_uni_id": "xidian",   "name_zh": "西安电子科技大学", "name_en": "Xidian University"},
    {"cn_uni_id": "hdu",      "name_zh": "杭州电子科技大学", "name_en": "Hangzhou Dianzi University"},
]

ALIAS_ROWS = [
    {"alias": "清华",         "cn_uni_id": "tsinghua"},
    {"alias": "THU",          "cn_uni_id": "tsinghua"},
    {"alias": "清华大学",     "cn_uni_id": "tsinghua"},
    {"alias": "北大",         "cn_uni_id": "pku"},
    {"alias": "PKU",          "cn_uni_id": "pku"},
    {"alias": "成电",         "cn_uni_id": "uestc"},
    {"alias": "电子科大",     "cn_uni_id": "uestc"},
    {"alias": "UESTC",        "cn_uni_id": "uestc"},
    {"alias": "电子科技大学", "cn_uni_id": "uestc"},
]


# ---------------------------------------------------------------------------
# 用例 1：精确中文命中
# ---------------------------------------------------------------------------

class TestExactZhMatch:
    def test_exact_chinese_name_returns_cn_uni_id(self):
        cn_uni_id, method, confidence = match_school("清华大学", DIM_ROWS, ALIAS_ROWS)
        assert cn_uni_id == "tsinghua"

    def test_exact_chinese_method_is_exact(self):
        _, method, _ = match_school("清华大学", DIM_ROWS, ALIAS_ROWS)
        assert method == "exact"

    def test_exact_chinese_confidence_is_1(self):
        _, _, confidence = match_school("清华大学", DIM_ROWS, ALIAS_ROWS)
        assert confidence == 1.0


# ---------------------------------------------------------------------------
# 用例 2：别名命中（"成电" → uestc）
# ---------------------------------------------------------------------------

class TestAliasMatch:
    def test_alias_chengdian_returns_uestc(self):
        cn_uni_id, method, confidence = match_school("成电", DIM_ROWS, ALIAS_ROWS)
        assert cn_uni_id == "uestc"

    def test_alias_method_is_alias(self):
        _, method, _ = match_school("成电", DIM_ROWS, ALIAS_ROWS)
        assert method == "alias"

    def test_alias_confidence_is_1(self):
        _, _, confidence = match_school("成电", DIM_ROWS, ALIAS_ROWS)
        assert confidence == 1.0


# ---------------------------------------------------------------------------
# 用例 3：模糊命中（"电子科技大学(沙河校区)" → uestc，partial_ratio >= 92）
# 高闸不误配：西安电子科技大学 / 杭州电子科技大学不得被选中
# ---------------------------------------------------------------------------

class TestFuzzyMatch:
    def test_fuzzy_campus_variant_returns_uestc(self):
        cn_uni_id, method, confidence = match_school(
            "电子科技大学(沙河校区)", DIM_ROWS, ALIAS_ROWS
        )
        assert cn_uni_id == "uestc"

    def test_fuzzy_method_is_fuzzy(self):
        _, method, _ = match_school("电子科技大学(沙河校区)", DIM_ROWS, ALIAS_ROWS)
        assert method == "fuzzy"

    def test_fuzzy_confidence_is_092(self):
        _, _, confidence = match_school("电子科技大学(沙河校区)", DIM_ROWS, ALIAS_ROWS)
        assert confidence == 0.92


# ---------------------------------------------------------------------------
# 用例 4：不命中（"剑桥高中" → None）
# 高闸保证：不误配任何大学
# ---------------------------------------------------------------------------

class TestNoMatch:
    def test_non_university_returns_none(self):
        cn_uni_id, method, confidence = match_school("剑桥高中", DIM_ROWS, ALIAS_ROWS)
        assert cn_uni_id is None

    def test_no_match_method_is_none(self):
        _, method, _ = match_school("剑桥高中", DIM_ROWS, ALIAS_ROWS)
        assert method is None

    def test_no_match_confidence_is_none(self):
        _, _, confidence = match_school("剑桥高中", DIM_ROWS, ALIAS_ROWS)
        assert confidence is None


# ---------------------------------------------------------------------------
# 用例 5：独立学院不得 fuzzy 误配到母体（回归测试 — 防 tier 污染）
# 金陵学院事故同款：partial_ratio('东南大学成贤学院','东南大学')=100
# 守卫：名称含"学院"而候选不含"学院" → 拒绝 fuzzy 匹配
# ---------------------------------------------------------------------------

class TestIndependentCollegeGuard:
    """
    独立学院（名含"学院"）的 fuzzy 匹配不得指向无"学院"的母体大学。
    否则会污染 tier 分类（独立学院三本，母体是 985/211）。
    """

    def _setup_with_colleges(self):
        """扩展夹具：添加三所独立学院及其母体"""
        dim_with_colleges = [
            {"cn_uni_id": "tsinghua",      "name_zh": "清华大学",           "name_en": "Tsinghua University"},
            {"cn_uni_id": "pku",           "name_zh": "北京大学",           "name_en": "Peking University"},
            {"cn_uni_id": "uestc",         "name_zh": "电子科技大学",       "name_en": "University of Electronic Science and Technology of China"},
            {"cn_uni_id": "xidian",        "name_zh": "西安电子科技大学",   "name_en": "Xidian University"},
            {"cn_uni_id": "hdu",           "name_zh": "杭州电子科技大学",   "name_en": "Hangzhou Dianzi University"},
            # 东南大学 + 独立学院
            {"cn_uni_id": "seu",           "name_zh": "东南大学",           "name_en": "Southeast University"},
            # 浙江大学 + 独立学院
            {"cn_uni_id": "zju",           "name_zh": "浙江大学",           "name_en": "Zhejiang University"},
        ]
        return dim_with_colleges

    def test_independent_college_not_fuzzy_matched_to_parent_its1(self):
        """独立学院"东南大学成贤学院"不应 fuzzy 匹配到母体"东南大学" (partial_ratio=100)"""
        dim = self._setup_with_colleges()
        cn_uni_id, method, confidence = match_school("东南大学成贤学院", dim, ALIAS_ROWS)
        assert cn_uni_id is None, \
            f"Expected None (no match), got cn_uni_id={cn_uni_id} via {method}. " \
            f"独立学院含'学院'不得 fuzzy 配到母体无'学院'的校名"

    def test_independent_college_not_fuzzy_matched_to_parent_its2(self):
        """独立学院"浙江大学城市学院"不应 fuzzy 匹配到母体"浙江大学" (partial_ratio=100)"""
        dim = self._setup_with_colleges()
        cn_uni_id, method, confidence = match_school("浙江大学城市学院", dim, ALIAS_ROWS)
        assert cn_uni_id is None, \
            f"Expected None (no match), got cn_uni_id={cn_uni_id} via {method}. " \
            f"独立学院含'学院'不得 fuzzy 配到母体无'学院'的校名"

    def test_campus_suffix_still_fuzzy_matches(self):
        """
        校区后缀（不是独立学院）应仍能 fuzzy 命中。
        "电子科技大学(沙河校区)" → uestc（含同校校区变体）
        """
        dim = self._setup_with_colleges()
        cn_uni_id, method, confidence = match_school("电子科技大学(沙河校区)", dim, ALIAS_ROWS)
        assert cn_uni_id == "uestc", \
            f"Expected 'uestc', got {cn_uni_id}. " \
            f"同校校区变体应仍能 fuzzy 命中（不含'学院'的校区后缀不受守卫影响）"
        assert method == "fuzzy"
        assert confidence == 0.92
