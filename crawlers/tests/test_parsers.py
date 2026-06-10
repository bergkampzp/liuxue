from sync_1point3acres import parse_gpa, parse_english


class TestParseGpa:
    def test_normal_4scale(self):
        assert parse_gpa("3.8/4.0") == 3.8

    def test_normal_percent(self):
        assert parse_gpa("88.5") == 88.5

    def test_garbage_over_100_returns_none(self):
        # bug 回归：>100 的脏值必须返回 None，不能钳成 4.0
        assert parse_gpa("985") is None

    def test_empty(self):
        assert parse_gpa("") is None


class TestParseEnglish:
    def test_toefl_only(self):
        assert parse_english("TOEFL 105") == (105, None, None, None, None, None)

    def test_ielts_total_only(self):
        assert parse_english("IELTS 7.0") == (None, 7.0, None, None, None, None)

    def test_ielts_with_subscores_paren(self):
        # "IELTS 7(6.5)" = 总分7,括号内小分最低值不可靠 → 只提取总分
        assert parse_english("IELTS 7(6.5)")[1] == 7.0

    def test_ielts_lrws(self):
        toefl, total, l, r, w, s = parse_english("IELTS 7.0 L7R7.5W6S6.5")
        assert (total, l, r, w, s) == (7.0, 7.0, 7.5, 6.0, 6.5)

    def test_ielts_chinese_subscores(self):
        toefl, total, l, r, w, s = parse_english("雅思7 听7读7.5写6说6.5")
        assert (l, r, w, s) == (7.0, 7.5, 6.0, 6.5)

    def test_bare_number_toefl(self):
        assert parse_english("108")[0] == 108
