#!/usr/bin/env python3
"""Tests for bold keyword runs (docs/superpowers/specs/2026-05-29-bold-keyword-runs-design.md)."""
import os, re, sys, json, zipfile, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import generate_hwpx as G

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(SKILL_DIR, "assets", "template.hwpx")


class TestBoldWidth(unittest.TestCase):
    def test_hangul_width_weight_invariant(self):
        # Korean syllables occupy a fixed em square regardless of weight.
        self.assertEqual(G._char_width('가', 1500, bold=False),
                         G._char_width('가', 1500, bold=True))

    def test_proportional_width_widened_by_bold(self):
        # ASCII letters/digits are proportional; bold must be wider.
        self.assertGreater(G._char_width('A', 1500, bold=True),
                           G._char_width('A', 1500, bold=False))

    def test_default_bold_false_unchanged(self):
        # Backward compat: the 2-arg call is identical to the old behavior.
        self.assertEqual(G._char_width('A', 1500), int(1500 * 0.50))

    def test_segmented_line_count_matches_string_when_no_bold(self):
        text = "올해 목표 달성률은 전년 대비 크게 상승하여 목표치를 초과 달성했다 " * 2
        segs = [(text, False)]
        self.assertEqual(G._segmented_line_count(segs, 1500),
                         G.estimate_line_count(text, 1500))

    def test_segmented_line_count_bold_latin_not_fewer(self):
        latin = "performance metric exceeded baseline target " * 3
        normal = G._segmented_line_count([(latin, False)], 1500)
        bold = G._segmented_line_count([(latin, True)], 1500)
        self.assertGreaterEqual(bold, normal)


if __name__ == "__main__":
    unittest.main()
