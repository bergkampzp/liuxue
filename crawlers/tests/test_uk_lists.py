"""
test_uk_lists.py — 官方名单爬虫单元测试

fixtures 使用快照中截取的真实 HTML 片段（两列 table / 单列 table）
或真实 PDF 文本行（爱丁堡）
"""
import pytest
from sync_uk_official_lists import parse_ucl, parse_bristol, parse_edinburgh_pdf


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


# ---------------------------------------------------------------------------
# Edinburgh fixture — 摘自真实 PDF 文本行
# 结构：主名单（band='priority-list'）+ Appendix 1 法学院 + Appendix 2 艺术学院
# ---------------------------------------------------------------------------

# 模拟真实 PDF 解析出的文本：包含页码行、注释行、多行校名注释，以及两个 Appendix
EDINBURGH_SAMPLE_LINES = [
    "Priority List of Chinese universities",
    "Note: where a university which is not on the 985/211 list has one or more World Class Disciplines,",
    "designated by the China Ministry of Education, we may require your degree to be in a World Class",
    "Discipline. More information is given in notes alongside your university listing below.",
    "Appendix 1 provides details of Law Schools in China which are included as priority universities for",
    "entry to Law degrees, and some other disciplines.",
    "Appendix 2 provides details of Art Schools in China which are included as priority universities for",
    "entry to Art and Design degrees.",
    "Air Force Medical University (formerly known as Fourth Military Medical University)",
    "Anhui University",
    "Beijing Foreign Studies University",
    "Fudan University",
    "Tsinghua University",
    "Capital Normal University (For programmes in the College of Science and Engineering and in the",
    "College of Medicine and Veterinary Medicine, the undergraduate degree must be in a World Class",
    "Discipline that is relevant to the chosen postgraduate programme. World Class Discipline is:",
    "Mathematics)",
    "Priority List of Chinese universities – October 2024 1",
    "Peking University",
    "Priority List of Chinese universities – October 2024 5",
    "Appendix 1 – Chinese Law Schools (considered for entry to Law degrees and some other",
    "relevant degrees)",
    "Beihang University",
    "East China University of Political Science and Law (ECUPL)",
    "Appendix 2 – Chinese Art Colleges (considered for entry to Art and Design degrees only)",
    "Guangzhou Academy of Fine Arts",
    "Nanjing University of the Arts",
    "Priority List of Chinese universities – October 2024 9",
]


class TestParseEdinburgh:
    def _parse(self):
        return parse_edinburgh_pdf(EDINBURGH_SAMPLE_LINES)

    def test_returns_list(self):
        result = self._parse()
        assert isinstance(result, list)

    def test_main_list_university_present(self):
        result = self._parse()
        names = [r["cn_name_raw"] for r in result]
        assert "Fudan University" in names
        assert "Tsinghua University" in names
        assert "Peking University" in names

    def test_main_list_band_is_priority_list(self):
        result = self._parse()
        fudan = [r for r in result if r["cn_name_raw"] == "Fudan University"]
        assert fudan and fudan[0]["band"] == "priority-list"

    def test_appendix1_law_school_present(self):
        result = self._parse()
        names = [r["cn_name_raw"] for r in result]
        assert "East China University of Political Science and Law (ECUPL)" in names

    def test_appendix1_band_is_law_school(self):
        result = self._parse()
        ecupl = [r for r in result if "Political Science and Law (ECUPL)" in r["cn_name_raw"]]
        assert ecupl and ecupl[0]["band"] == "law-school"

    def test_appendix2_art_college_present(self):
        result = self._parse()
        names = [r["cn_name_raw"] for r in result]
        assert "Guangzhou Academy of Fine Arts" in names

    def test_appendix2_band_is_art_college(self):
        result = self._parse()
        art = [r for r in result if r["cn_name_raw"] == "Guangzhou Academy of Fine Arts"]
        assert art and art[0]["band"] == "art-college"

    def test_skips_page_headers_and_footers(self):
        result = self._parse()
        names = [r["cn_name_raw"] for r in result]
        assert not any("Priority List of Chinese universities" in n for n in names)

    def test_skips_note_lines(self):
        result = self._parse()
        names = [r["cn_name_raw"] for r in result]
        assert not any(n.startswith("Note:") for n in names)

    def test_multiline_name_collapsed(self):
        # "Capital Normal University (For programmes ... Mathematics)" is multi-line
        result = self._parse()
        names = [r["cn_name_raw"] for r in result]
        capital_normal = [n for n in names if "Capital Normal University" in n]
        assert capital_normal, "Capital Normal University should be present"
        # Should be a single record (not split across multiple)
        assert len(capital_normal) == 1

    def test_uk_uni_id_is_edinburgh(self):
        result = self._parse()
        for r in result:
            assert r["uk_uni_id"] == "edinburgh"

    def test_min_avg_score_is_none(self):
        result = self._parse()
        for r in result:
            assert r["min_avg_score"] is None

    def test_record_has_required_keys(self):
        result = self._parse()
        required = {"uk_uni_id", "cn_name_raw", "band", "min_avg_score"}
        for r in result:
            assert required.issubset(r.keys())

    def test_at_least_5_records_from_sample(self):
        result = self._parse()
        # sample has: Air Force Medical, Anhui, Beijing Foreign Studies, Fudan, Tsinghua,
        # Capital Normal, Peking (main) + Beihang, ECUPL (law) + Guangzhou, Nanjing Arts (art)
        assert len(result) >= 10

    def test_no_duplicates(self):
        result = self._parse()
        keys = [(r["uk_uni_id"], r["cn_name_raw"], r["band"]) for r in result]
        assert len(keys) == len(set(keys))
