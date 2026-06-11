"""
test_uk_lists.py — 官方名单爬虫单元测试

fixtures 使用快照中截取的真实 HTML 片段（两列 table / 单列 table）
"""
import pytest
from sync_uk_official_lists import parse_ucl, parse_bristol


# ---------------------------------------------------------------------------
# UCL fixture — 摘自快照：dl.accordion > dd > table，两列布局
# ---------------------------------------------------------------------------
UCL_SAMPLE_HTML = """
<table border="1" cellpadding="1" cellspacing="1">
  <tbody>
    <tr>
      <td class="xl66"><span>Beihang University (formerly Beijing University of Aeronautics &amp; Astronautics)</span></td>
      <td class="xl66"><span>North China Electric Power University / Huabei Electric Power University</span></td>
    </tr>
    <tr>
      <td class="xl66"><span>Beijing Foreign Studies University</span></td>
      <td class="xl66"><span>Northeast Forestry University</span></td>
    </tr>
    <tr>
      <td class="xl66"><span>Fudan University</span></td>
      <td class="xl66"><span>Tsinghua University</span></td>
    </tr>
    <tr>
      <td class="xl65"><span>Nanhang Jincheng College (independent college of Nanjing University of Aeronautics and Astronautics) **</span></td>
      <td class="xl67"><span>Zhengzhou University**</span></td>
    </tr>
    <tr>
      <td class="xl66"><span>Nankai University</span></td>
      <td class="xl68"> </td>
    </tr>
  </tbody>
</table>
"""


class TestParseUcl:
    def test_returns_list(self):
        result = parse_ucl(UCL_SAMPLE_HTML)
        assert isinstance(result, list)

    def test_parses_both_columns(self):
        result = parse_ucl(UCL_SAMPLE_HTML)
        names = [r["cn_name_raw"] for r in result]
        assert "Beihang University (formerly Beijing University of Aeronautics & Astronautics)" in names
        assert "North China Electric Power University / Huabei Electric Power University" in names

    def test_skips_whitespace_only_cells(self):
        result = parse_ucl(UCL_SAMPLE_HTML)
        names = [r["cn_name_raw"] for r in result]
        # The last row has a whitespace-only second cell — should not appear
        assert "" not in names
        assert " " not in names

    def test_band_is_in_list(self):
        result = parse_ucl(UCL_SAMPLE_HTML)
        for r in result:
            assert r["band"] == "in-list"

    def test_uk_uni_id_is_ucl(self):
        result = parse_ucl(UCL_SAMPLE_HTML)
        for r in result:
            assert r["uk_uni_id"] == "ucl"

    def test_record_has_required_keys(self):
        result = parse_ucl(UCL_SAMPLE_HTML)
        required = {"uk_uni_id", "cn_name_raw", "band", "min_avg_score"}
        for r in result:
            assert required.issubset(r.keys())

    def test_count_from_sample(self):
        # 5 rows × 2 cols = 10 cells, minus 1 blank = 9 names
        result = parse_ucl(UCL_SAMPLE_HTML)
        assert len(result) == 9


# ---------------------------------------------------------------------------
# Bristol fixture — 摘自快照：单列 table，th="University name" + td 行
# ---------------------------------------------------------------------------
BRISTOL_SAMPLE_HTML = """
<table>
  <thead>
    <tr><th>University name</th></tr>
  </thead>
  <tbody>
    <tr><td>Anhui Agricultural University</td></tr>
    <tr><td>Anhui Medical University</td></tr>
    <tr><td>Anhui Normal University</td></tr>
    <tr><td>Fudan University</td></tr>
    <tr><td>Anhui University of Finance and Economics (Specialist institution: Programme limitations may apply)</td></tr>
  </tbody>
</table>
"""


class TestParseBristol:
    def test_returns_list(self):
        result = parse_bristol(BRISTOL_SAMPLE_HTML)
        assert isinstance(result, list)

    def test_parses_university_names(self):
        result = parse_bristol(BRISTOL_SAMPLE_HTML)
        names = [r["cn_name_raw"] for r in result]
        assert "Anhui Agricultural University" in names
        assert "Fudan University" in names

    def test_count_from_sample(self):
        result = parse_bristol(BRISTOL_SAMPLE_HTML)
        assert len(result) == 5

    def test_band_is_accepted(self):
        result = parse_bristol(BRISTOL_SAMPLE_HTML)
        for r in result:
            assert r["band"] == "accepted"

    def test_uk_uni_id_is_bristol(self):
        result = parse_bristol(BRISTOL_SAMPLE_HTML)
        for r in result:
            assert r["uk_uni_id"] == "bristol"

    def test_record_has_required_keys(self):
        result = parse_bristol(BRISTOL_SAMPLE_HTML)
        required = {"uk_uni_id", "cn_name_raw", "band", "min_avg_score"}
        for r in result:
            assert required.issubset(r.keys())

    def test_skips_header_row(self):
        result = parse_bristol(BRISTOL_SAMPLE_HTML)
        names = [r["cn_name_raw"] for r in result]
        assert "University name" not in names
