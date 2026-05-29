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


if __name__ == "__main__":
    unittest.main()
