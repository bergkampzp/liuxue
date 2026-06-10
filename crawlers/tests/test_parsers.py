import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sync_1point3acres import parse_gpa


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
