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


class TestStyleMapBoldKeys(unittest.TestCase):
    def test_default_style_map_has_bold_keys(self):
        for k in ("paragraph_bold", "bullet_bold", "dash_bold",
                  "star_bold", "note_bold"):
            self.assertIn(k, G.DEFAULT_STYLE_MAP)

    def test_build_resolves_paragraph_bold_to_twin(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with zipfile.ZipFile(TEMPLATE) as zf:
            zf.extractall(os.path.join(tmp.name, "t"))
        sm = G.build_style_map_from_template(os.path.join(tmp.name, "t"))
        self.assertIsNotNone(sm)
        # paragraph base (38) has a twin -> resolved id differs from base.
        self.assertIn("paragraph_bold", sm)
        self.assertNotEqual(sm["paragraph_bold"], sm["paragraph"][0])


class TestSegmentedRunBuilder(unittest.TestCase):
    def test_builds_prefix_and_bold_segment(self):
        xml = G._build_segmented_runs(" ", [("올해 ", False), ("목표", True)],
                                      base_cp="38", bold_cp="71", end_cp="33")
        self.assertIn('<hp:run charPrIDRef="38"><hp:t> </hp:t></hp:run>', xml)
        self.assertIn('charPrIDRef="71"><hp:t>목표</hp:t>', xml)
        self.assertTrue(xml.rstrip().endswith('<hp:run charPrIDRef="33"/>'))

    def test_no_end_run_when_none(self):
        xml = G._build_segmented_runs("▷ ", [("주의", True)],
                                      base_cp="38", bold_cp="71", end_cp=None)
        self.assertNotIn('charPrIDRef="None"', xml)


class TestContentItemBold(unittest.TestCase):
    def _sm(self):
        sm = dict(G.DEFAULT_STYLE_MAP)
        sm["paragraph_bold"] = "71"  # force a distinct bold id for assertion
        return sm

    def test_string_paragraph_byte_identical(self):
        sm = self._sm()
        a = G.generate_content_item({"type": "paragraph", "text": "안녕"}, sm, G.VertPosTracker())
        b = G.generate_content_item({"type": "paragraph", "text": "안녕"}, dict(G.DEFAULT_STYLE_MAP), G.VertPosTracker())
        self.assertEqual(a, b)  # string path unchanged regardless of bold key

    def test_array_paragraph_emits_bold_run(self):
        sm = self._sm()
        xml = G.generate_content_item(
            {"type": "paragraph",
             "text": [{"t": "올해 "}, {"t": "목표", "bold": True}, {"t": "달성"}]},
            sm, G.VertPosTracker())
        self.assertIn('charPrIDRef="71"><hp:t>목표</hp:t>', xml)
        # plain text round-trips
        self.assertEqual(G._extract_paragraph_first_text(xml), " 올해 목표달성")

    def test_heading_flattens_array(self):
        sm = self._sm()
        xml = G.generate_content_item(
            {"type": "heading", "text": [{"t": "제목", "bold": True}]},
            sm, G.VertPosTracker())
        self.assertNotIn('charPrIDRef="71"', xml)  # heading ignores bold
        self.assertIn("제목", xml)

    def test_malformed_segment_raises(self):
        with self.assertRaises(ValueError):
            G.generate_content_item(
                {"type": "bullet", "text": [{"bold": True}]},
                self._sm(), G.VertPosTracker(), item_index=2)


class TestPrepScript(unittest.TestCase):
    def _twin_count(self, header):
        return sum(1 for m in re.finditer(r'<hh:charPr id="\d+".*?</hh:charPr>',
                                          header, re.DOTALL) if '<hh:bold' in m.group(0))

    def test_prep_adds_missing_twins_and_is_idempotent(self):
        from scripts import prepare_template_bold_twins as P
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        work = os.path.join(tmp.name, "template.hwpx")
        import shutil; shutil.copy(TEMPLATE, work)

        added1 = P.prepare(work)            # returns list of (style, new_id)
        with zipfile.ZipFile(work) as zf:
            header = zf.read("Contents/header.xml").decode("utf-8")
        # itemCnt matches actual charPr count
        ic = int(re.search(r'<hh:charProperties itemCnt="(\d+)"', header).group(1))
        n = len(re.findall(r'<hh:charPr id="\d+"', header))
        self.assertEqual(ic, n)
        # every body style now resolves to a real twin
        sm = self._build_sm(work)
        for k in ("paragraph_bold", "dash_bold", "star_bold"):
            base = sm[k[:-5]][0] if isinstance(sm[k[:-5]], (list, tuple)) else None
            self.assertNotEqual(sm[k], base)

        added2 = P.prepare(work)            # second run: no-op
        self.assertEqual(added2, [])

    def _build_sm(self, hwpx):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        with zipfile.ZipFile(hwpx) as zf:
            zf.extractall(os.path.join(tmp.name, "t"))
        return G.build_style_map_from_template(os.path.join(tmp.name, "t"))


if __name__ == "__main__":
    unittest.main()
