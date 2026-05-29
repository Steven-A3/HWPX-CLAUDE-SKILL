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


if __name__ == "__main__":
    unittest.main()
