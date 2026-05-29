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


class TestSegmentNormalizer(unittest.TestCase):
    def test_string_becomes_single_normal_segment(self):
        self.assertEqual(G._normalize_text_segments("hello"), [("hello", False)])

    def test_array_maps_to_tuples(self):
        text = [{"t": "올해 "}, {"t": "목표", "bold": True}, {"t": "은"}]
        self.assertEqual(G._normalize_text_segments(text),
                         [("올해 ", False), ("목표", True), ("은", False)])

    def test_bold_coerced_to_bool(self):
        self.assertEqual(G._normalize_text_segments([{"t": "x", "bold": 1}]),
                         [("x", True)])

    def test_missing_t_raises_with_index(self):
        with self.assertRaises(ValueError) as cm:
            G._normalize_text_segments([{"bold": True}], item_index=3)
        self.assertIn("3", str(cm.exception))

    def test_non_string_t_raises(self):
        with self.assertRaises(ValueError):
            G._normalize_text_segments([{"t": 5}])

    def test_non_list_non_string_raises(self):
        with self.assertRaises(ValueError):
            G._normalize_text_segments(42)

    def test_plain_text_joins(self):
        segs = [("올해 ", False), ("목표", True), ("은", False)]
        self.assertEqual(G._segments_plain_text(segs), "올해 목표은")


class TestFindBoldTwin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with zipfile.ZipFile(TEMPLATE) as zf:
            zf.extractall(self.tmp.name)
        hp = os.path.join(self.tmp.name, "Contents", "header.xml")
        with open(hp, encoding="utf-8") as f:
            self.header = f.read()

    def tearDown(self):
        self.tmp.cleanup()

    def _has_bold(self, cid):
        m = re.search(r'<hh:charPr id="%s".*?</hh:charPr>' % cid, self.header, re.DOTALL)
        return m is not None and '<hh:bold' in m.group(0)

    def test_exact_twin_found_and_is_true_twin(self):
        # Base 38 (paragraph) has exactly one bold twin (71) in the template.
        twin = G._find_bold_twin(self.header, "38")
        self.assertEqual(twin, "71")
        # The twin must be a TRUE twin: identical to the base except <hh:bold/>.
        base_xml = re.search(r'<hh:charPr id="38".*?</hh:charPr>', self.header, re.DOTALL).group(0)
        twin_xml = re.search(r'<hh:charPr id="%s".*?</hh:charPr>' % twin, self.header, re.DOTALL).group(0)
        self.assertIn('<hh:bold', twin_xml)
        self.assertEqual(G._charpr_canonical(base_xml), G._charpr_canonical(twin_xml))

    def test_no_twin_returns_base(self):
        # A fabricated id with no twin returns the base unchanged.
        self.assertEqual(G._find_bold_twin(self.header, "999999"), "999999")


if __name__ == "__main__":
    unittest.main()
