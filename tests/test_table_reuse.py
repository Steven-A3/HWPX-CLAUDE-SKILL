#!/usr/bin/env python3
"""Tests for template table reuse (docs/superpowers/specs/2026-05-29-table-reuse-and-gaejosik-design.md)."""
import os, re, sys, json, zipfile, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import generate_hwpx as G

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(SKILL_DIR, "assets", "template.hwpx")


class TestColumnWidths(unittest.TestCase):
    def test_widths_sum_to_total(self):
        w = G._compute_column_widths(["연도", "구분"], [["2023년", "SW중심대학"]], 1200, 40000)
        self.assertEqual(sum(w), 40000)
        self.assertEqual(len(w), 2)

    def test_long_content_column_is_wider(self):
        w = G._compute_column_widths(
            ["구분", "내용"],
            [["A", "교육생 미선발에 따른 자체 주력사업 부재를 코디세이 사업으로 전환"]],
            1200, 40000)
        self.assertGreater(w[1], w[0])

    def test_min_width_floor(self):
        w = G._compute_column_widths(["a","b","c","d"], [["1","2","3","4"]], 1200, 4000)
        self.assertTrue(all(c >= G.MIN_COL_WIDTH for c in w))

    def test_single_column(self):
        w = G._compute_column_widths(["제목"], [["내용"]], 1200, 47000)
        self.assertEqual(w, [47000])

    def test_three_column_exact_sum_with_rounding(self):
        # 3 columns with uneven content must still sum EXACTLY to total_width
        w = G._compute_column_widths(
            ["짧음", "보통 길이의 항목", "아주 길고 자세한 설명이 들어가는 칸"],
            [["A", "BB", "CCC"]], 1200, 47001)  # odd total to exercise rounding
        self.assertEqual(sum(w), 47001)
        self.assertEqual(len(w), 3)

    def test_degenerate_overflow_is_accepted(self):
        # When the floor can't fit, sum is allowed to exceed total_width (documented contract)
        w = G._compute_column_widths(["a","b","c","d","e","f","g","h"],
                                     [["1","2","3","4","5","6","7","8"]], 1200, 4000)
        self.assertGreater(sum(w), 4000)
        self.assertTrue(all(c >= G.MIN_COL_WIDTH for c in w))

    def test_feasible_long_plus_short_sums_exactly(self):
        # one long column + several short ones (a common 개조식 shape) must still
        # sum EXACTLY to total_width (regression for the overshoot bug)
        headers = ["설명" * 100, "a", "b", "c", "d", "e"]
        rows = [["내용", "1", "2", "3", "4", "5"]]
        w = G._compute_column_widths(headers, rows, 1200, 48964)
        self.assertEqual(sum(w), 48964)
        self.assertTrue(all(c >= G.MIN_COL_WIDTH for c in w))

    def test_long_column_gets_most_width(self):
        w = G._compute_column_widths(["설명" * 100, "a", "b"], [["x", "y", "z"]], 1200, 48964)
        self.assertEqual(max(range(3), key=lambda j: w[j]), 0)  # the long col is widest


class TestRichCellExtractor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        zipfile.ZipFile(TEMPLATE).extractall(self.tmp.name)
        body, _ = G._detect_template_sections(self.tmp.name)
        bx = open(body, encoding="utf-8").read()
        paras, _ = G._extract_all_top_level_paragraphs(bx)
        attrs = [G._extract_para_attrs(p) for p in paras]
        self.tbl = next(paras[i] for i, a in enumerate(attrs)
                        if a['has_tbl'] and not a['has_colpr'])

    def test_rich_cells_have_geometry(self):
        cells = G._extract_table_cells_rich(self.tbl)
        self.assertGreater(len(cells), 1)
        for c in cells:
            for k in ("rowAddr", "colAddr", "bf", "charPr", "paraPr",
                      "width", "height", "valign", "margin", "spanned"):
                self.assertIn(k, c)
        # value correctness on the header row (catches silent regex defaults)
        r0 = sorted((c for c in cells if c["rowAddr"] == 0), key=lambda x: x["colAddr"])
        self.assertTrue(r0)
        for c in r0:
            self.assertGreater(c["width"], 0)          # real cellSz width
            self.assertNotEqual(c["bf"], "1")          # real border fill, not default
            self.assertNotEqual(c["charPr"], "0")      # real run charPr, not default
            self.assertIn(c["valign"], ("CENTER", "TOP", "BOTTOM"))
            self.assertEqual(set(c["margin"]), {"left", "right", "top", "bottom"})


class TestTableProfile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        zipfile.ZipFile(TEMPLATE).extractall(self.tmp.name)
        self.tdir = self.tmp.name
        self.body, _ = G._detect_template_sections(self.tdir)
        self.header_xml = open(os.path.join(self.tdir, "Contents", "header.xml"), encoding="utf-8").read()

    def test_catalog_has_common_col_counts_and_shape(self):
        bx = open(self.body, encoding="utf-8").read()
        cat = G._build_table_profile_catalog(bx, self.header_xml)
        self.assertTrue(cat)  # non-empty
        prof = next(iter(cat.values()))
        for k in ("total_width", "cell_margin", "header_h", "body_h", "row_h",
                  "header", "first", "interior", "last"):
            self.assertIn(k, prof)
        ncols = len(prof["header"])
        for role in ("header", "first", "interior", "last"):
            self.assertEqual(len(prof[role]), ncols)
            self.assertTrue(all("bf" in c and "charPr" in c for c in prof[role]))

    def test_header_distinct_corner_fills(self):
        bx = open(self.body, encoding="utf-8").read()
        cat = G._build_table_profile_catalog(bx, self.header_xml)
        multi = [p for p in cat.values() if len(p["header"]) >= 3]
        self.assertTrue(multi)
        p = multi[0]
        bfs = [c["bf"] for c in p["header"]]
        self.assertNotEqual(bfs[0], bfs[-1])  # left corner != right corner


class TestStyleMapTableProfiles(unittest.TestCase):
    def test_default_has_empty_table_profiles(self):
        self.assertIn("table_profiles", G.DEFAULT_STYLE_MAP)
        self.assertEqual(G.DEFAULT_STYLE_MAP["table_profiles"], {})

    def test_build_populates_table_profiles(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        zipfile.ZipFile(TEMPLATE).extractall(os.path.join(tmp.name, "t"))
        sm = G.build_style_map_from_template(os.path.join(tmp.name, "t"))
        self.assertIn("table_profiles", sm)
        self.assertTrue(sm["table_profiles"])  # non-empty for the bundled template
        for ncols, prof in sm["table_profiles"].items():
            self.assertEqual(len(prof["header"]), int(ncols))


class TestProfileDrivenTable(unittest.TestCase):
    def _sm(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        zipfile.ZipFile(TEMPLATE).extractall(os.path.join(tmp.name, "t"))
        return G.build_style_map_from_template(os.path.join(tmp.name, "t"))

    def test_uses_profile_border_fills(self):
        sm = self._sm()
        ncols = int(sorted(sm["table_profiles"], key=int)[0])
        prof = sm["table_profiles"][str(ncols)]
        headers = [f"H{i}" for i in range(ncols)]
        rows = [[f"r{r}c{c}" for c in range(ncols)] for r in range(3)]
        xml, _ = G.data_table_xml(headers, rows, sm)
        header_tr = re.search(r'<hp:tr>(.*?)</hp:tr>', xml, re.DOTALL).group(1)
        hdr_cell_bfs = re.findall(r'<hp:tc\b[^>]*borderFillIDRef="(\d+)"', header_tr)
        self.assertEqual(hdr_cell_bfs, [c["bf"] for c in prof["header"]])

    def test_last_row_uses_last_profile_fill(self):
        sm = self._sm()
        ncols = int(sorted(sm["table_profiles"], key=int)[0])
        prof = sm["table_profiles"][str(ncols)]
        headers = [f"H{i}" for i in range(ncols)]
        rows = [[f"r{r}c{c}" for c in range(ncols)] for r in range(4)]
        xml, _ = G.data_table_xml(headers, rows, sm)
        last_fill = prof["last"][0]["bf"]
        self.assertIn(last_fill, xml)

    def test_widths_sum_to_profile_total(self):
        sm = self._sm()
        ncols = int(sorted(sm["table_profiles"], key=int)[0])
        prof = sm["table_profiles"][str(ncols)]
        headers = [f"H{i}" for i in range(ncols)]
        rows = [[f"r{r}c{c}" for c in range(ncols)] for r in range(2)]
        xml, _ = G.data_table_xml(headers, rows, sm)
        widths = [int(w) for w in re.findall(r'<hp:cellSz width="(\d+)"', xml)]
        self.assertEqual(sum(widths[:ncols]), prof["total_width"])

    def test_fallback_when_no_profile(self):
        sm = self._sm()
        present = {int(k) for k in sm["table_profiles"]}
        ncols = next(c for c in range(2, 40) if c not in present)
        headers = [f"H{i}" for i in range(ncols)]
        rows = [[f"r{c}" for c in range(ncols)]]
        xml, vs = G.data_table_xml(headers, rows, sm)   # must not raise
        self.assertIn("<hp:tbl", xml)

    def test_table_height_equals_row_height_sum(self):
        sm = self._sm()
        ncols = int(sorted(sm["table_profiles"], key=int)[0])
        headers = [f"H{i}" for i in range(ncols)]
        rows = [[f"r{r}c{c}" for c in range(ncols)] for r in range(3)]
        xml, _ = G.data_table_xml(headers, rows, sm)
        # geometry must be self-consistent: table height == sum of per-row heights
        # (Hancom trusts our geometry; it does not recalc).
        heights = [int(h) for h in re.findall(r'<hp:cellSz width="\d+" height="(\d+)"', xml)]
        per_row = heights[0::ncols]            # first cell of each row
        tbl_h = int(re.search(r'<hp:sz width="\d+" widthRelTo="ABSOLUTE" height="(\d+)"', xml).group(1))
        self.assertEqual(sum(per_row), tbl_h)

    def test_single_body_row_uses_last_profile(self):
        sm = self._sm()
        ncols = int(sorted(sm["table_profiles"], key=int)[0])
        prof = sm["table_profiles"][str(ncols)]
        headers = [f"H{i}" for i in range(ncols)]
        rows = [[f"c{c}" for c in range(ncols)]]   # R == 1
        xml, _ = G.data_table_xml(headers, rows, sm)
        trs = re.findall(r'<hp:tr>(.*?)</hp:tr>', xml, re.DOTALL)
        body_fills = re.findall(r'borderFillIDRef="(\d+)"', trs[-1])
        self.assertEqual(body_fills, [c["bf"] for c in prof["last"]])

    def test_row_height_uses_margin_for_wrapping(self):
        # wider margins -> narrower inner width -> more wrapped lines -> taller row.
        # (regression: _row_height must use the profile margin, not a literal 1022)
        narrow = G._row_height(["가" * 40], [10000], 1200, 2048,
                               {"left": 510, "right": 510, "top": 141, "bottom": 141})
        wide = G._row_height(["가" * 40], [10000], 1200, 2048,
                             {"left": 3000, "right": 3000, "top": 141, "bottom": 141})
        self.assertGreater(wide, narrow)


class TestEndToEndTable(unittest.TestCase):
    def test_generated_doc_table_matches_template_fills(self):
        sm = json.load(open(os.path.join(SKILL_DIR, "assets", "default_styles.json")))["style_map"]
        ncols = int(sorted(sm["table_profiles"], key=int)[0])
        headers = [f"항목{i}" for i in range(ncols)]
        rows = [[f"행{r}열{c}" for c in range(ncols)] for r in range(3)]
        config = {"include_cover": False, "sections": [{
            "type": "body", "title_bar": "표 양식 점검",
            "content": [
                {"type": "heading", "text": "표 점검"},
                {"type": "table", "caption": "샘플", "headers": headers, "rows": rows},
            ]}]}
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        out = os.path.join(tmp.name, "t.hwpx")
        G.generate_hwpx(config, out)
        self.assertTrue(zipfile.is_zipfile(out))
        with zipfile.ZipFile(out) as zf:
            secs = sorted(n for n in zf.namelist() if re.search(r'section\d+\.xml$', n))
            body = "".join(zf.read(n).decode("utf-8") for n in secs)
        m = re.search(r'<hp:tbl[^>]*colCnt="%d"' % ncols, body)
        self.assertIsNotNone(m, "generated table with expected colCnt not found")
        # confirm the profile path actually rendered all N columns in this table
        tbl_slice = body[m.start():m.start() + 20000]
        first_tr = re.search(r'<hp:tr>(.*?)</hp:tr>', tbl_slice, re.DOTALL).group(1)
        self.assertEqual(len(re.findall(r'<hp:tc\b', first_tr)), ncols,
                         "header row should render exactly ncols cells")


if __name__ == "__main__":
    unittest.main()
