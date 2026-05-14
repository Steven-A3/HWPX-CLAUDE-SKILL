#!/usr/bin/env python3
"""Tests for bullet/box/dash paragraph style alignment with the template.

These tests verify that ``assets/default_styles.json`` and the marker-style
discovery in ``scripts/generate_hwpx.py`` map □/ㅇ/-/* paragraphs to the
template's most-common 165% line-spacing paraPr, and that generated
documents preserve those values.
"""

import json
import os
import re
import sys
import tempfile
import unittest
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import generate_hwpx as gh
from scripts._parser import find_top_level_paragraphs


SKILL_DIR = Path(__file__).parent.parent
TEMPLATE_PATH = SKILL_DIR / "assets" / "template.hwpx"
CACHE_PATH = SKILL_DIR / "assets" / "default_styles.json"


def _read_template_files():
    """Return (header_xml, section0_xml) as decoded strings."""
    with zipfile.ZipFile(TEMPLATE_PATH, 'r') as zf:
        header_xml = zf.read("Contents/header.xml").decode('utf-8')
        section0_xml = zf.read("Contents/section0.xml").decode('utf-8')
    return header_xml, section0_xml


def _parse_paraPr(header_xml, pid):
    """Return a dict of attributes for the given paraPr id, or None."""
    # ``id`` is the first attribute on <hh:paraPr> in the template; anchor to it
    # to avoid matching substrings like ``Grid="1"`` (which contains ``id="``).
    m = re.search(
        rf'<hh:paraPr\s+id="{pid}"[^>]*>.*?</hh:paraPr>',
        header_xml, re.DOTALL)
    if not m:
        return None
    body = m.group(0)
    out = {'id': pid}
    align_m = re.search(r'<hh:align horizontal="(\w+)"', body)
    out['align'] = align_m.group(1) if align_m else None
    out['breakNonLatinWord'] = (
        re.search(r'breakNonLatinWord="(\w+)"', body).group(1)
        if re.search(r'breakNonLatinWord="(\w+)"', body) else None)
    out['default_intent'] = int(
        re.search(r'<hp:default>.*?<hc:intent value="(-?\d+)"', body, re.DOTALL).group(1))
    out['default_left'] = int(
        re.search(r'<hp:default>.*?<hc:left value="(-?\d+)"', body, re.DOTALL).group(1))
    out['default_right'] = int(
        re.search(r'<hp:default>.*?<hc:right value="(-?\d+)"', body, re.DOTALL).group(1))
    out['default_prev'] = int(
        re.search(r'<hp:default>.*?<hc:prev value="(-?\d+)"', body, re.DOTALL).group(1))
    out['default_next'] = int(
        re.search(r'<hp:default>.*?<hc:next value="(-?\d+)"', body, re.DOTALL).group(1))
    ls_m = re.search(
        r'<hp:default>.*?<hh:lineSpacing type="(\w+)" value="(\d+)"', body, re.DOTALL)
    out['ls_type'] = ls_m.group(1) if ls_m else None
    out['ls_value'] = ls_m.group(2) if ls_m else None
    hu_m = re.search(
        r'<hp:case[^>]*HwpUnitChar[^>]*>.*?<hc:intent value="(-?\d+)"', body, re.DOTALL)
    out['hwpunitchar_intent'] = int(hu_m.group(1)) if hu_m else None
    return out


def _all_paraPr_ids(header_xml):
    return set(re.findall(r'<hh:paraPr\s+id="(\d+)"', header_xml))


class TestParaPrExistence(unittest.TestCase):
    """Every paraPr referenced by the style map must exist in header.xml.

    Guards against the old ``heading_end → 28`` bug where the cache pointed at
    a non-existent paraPr.
    """

    def test_marker_paraPrs_exist_in_header(self):
        header_xml, _ = _read_template_files()
        valid = _all_paraPr_ids(header_xml)
        sm = json.loads(CACHE_PATH.read_text())['style_map']
        marker_keys = (
            "heading_marker", "heading_text", "heading_tail", "heading_end",
            "bullet", "bullet_end", "dash", "dash_end",
            "star", "star_end", "note", "paragraph", "paragraph_end",
        )
        for key in marker_keys:
            with self.subTest(key=key):
                _cp, pp = sm[key][0], sm[key][1]
                self.assertIn(pp, valid,
                    f"{key} → paraPr {pp} not found in header.xml")


class TestScreenshotDialogFilter(unittest.TestCase):
    """The user's screenshot shows JUSTIFY / 165% / 0pt margins / hanging indent.

    Filtering header.xml's paraPrs by that exact dialog state must yield
    exactly one match: paraPr 43 (the dominant - dash paraPr). This anchors
    the screenshot identity without depending on the HWPUNIT-to-pt
    conversion.
    """

    def test_screenshot_dialog_state_matches_only_paraPr_43(self):
        header_xml, _ = _read_template_files()
        # The screenshot's HwpUnitChar intent value of -4050 corresponds to
        # the dialog showing 40.5 pt 내어쓰기. Multiple paraPrs share the
        # justify+165%+0margins shape (41, 42, 43, 44) — only paraPr 43 has
        # intent=-4050.
        matches = []
        for pid in sorted(_all_paraPr_ids(header_xml), key=int):
            p = _parse_paraPr(header_xml, pid)
            if not p:
                continue
            if (p['align'] == 'JUSTIFY'
                and p['ls_type'] == 'PERCENT'
                and p['ls_value'] == '165'
                and p['default_left'] == 0
                and p['default_right'] == 0
                and p['default_prev'] == 0
                and p['default_next'] == 0
                and p['hwpunitchar_intent'] == -4050
                and p['breakNonLatinWord'] == 'KEEP_WORD'):
                matches.append(pid)
        self.assertEqual(matches, ['43'],
            "Screenshot dialog state should uniquely identify paraPr 43; "
            f"got: {matches}")


class TestTemplateFrequencyAlignment(unittest.TestCase):
    """The style map's marker paraPrs should be the most common 165% LS
    variants in the template — independent verification that the cache
    matches the template's actual marker frequency, not just my expectations.
    """

    def _bucket_from_template(self):
        header_xml, section0_xml = _read_template_files()
        spans = find_top_level_paragraphs(section0_xml)
        paragraphs = [section0_xml[a:b] for a, b in spans]
        attrs = [gh._extract_para_attrs(p) for p in paragraphs]
        char_cat, para_cat = gh._parse_header_catalogs(
            zipfile_extract_header(TEMPLATE_PATH))
        buckets = gh._classify_paragraphs_by_marker(
            paragraphs, attrs, para_cat, gh.DEFAULT_LINE_SPACING_BAND)
        return buckets

    def test_dash_most_common_paraPr_is_43(self):
        buckets = self._bucket_from_template()
        counts = Counter((pp, cp) for pp, cp, _, _ in buckets["dash"])
        self.assertTrue(counts, "dash bucket should be non-empty")
        top_pair, _n = counts.most_common(1)[0]
        self.assertEqual(top_pair[0], "43",
            f"most common dash paraPr should be 43; got {top_pair}")

    def test_bullet_most_common_paraPr_is_41(self):
        buckets = self._bucket_from_template()
        counts = Counter((pp, cp) for pp, cp, _, _ in buckets["bullet"])
        self.assertTrue(counts, "bullet bucket should be non-empty")
        top_pair, _n = counts.most_common(1)[0]
        self.assertEqual(top_pair[0], "41",
            f"most common bullet paraPr should be 41; got {top_pair}")

    def test_heading_most_common_paraPr_is_40(self):
        buckets = self._bucket_from_template()
        counts = Counter((pp, cp) for pp, cp, _, _ in buckets["heading"])
        self.assertTrue(counts, "heading bucket should be non-empty")
        top_pair, _n = counts.most_common(1)[0]
        self.assertEqual(top_pair[0], "40",
            f"most common heading paraPr should be 40; got {top_pair}")


class TestMarkerParaPrProperties(unittest.TestCase):
    """Each marker's chosen paraPr must have the expected align +
    line-spacing + hanging-indent direction (intent < 0).
    """

    EXPECTED = {
        "heading_marker": ("LEFT",    "165", -7160, -3580),
        "heading_text":   ("LEFT",    "165", -7160, -3580),
        "bullet":         ("JUSTIFY", "165", -6480, -3240),
        "dash":           ("JUSTIFY", "165", -8100, -4050),
    }

    def test_paraPr_properties(self):
        header_xml, _ = _read_template_files()
        sm = json.loads(CACHE_PATH.read_text())['style_map']
        for key, (align, ls, default_intent, hu_intent) in self.EXPECTED.items():
            with self.subTest(key=key):
                pp_id = sm[key][1]
                p = _parse_paraPr(header_xml, pp_id)
                self.assertIsNotNone(p, f"{key} paraPr {pp_id} not found")
                self.assertEqual(p['align'], align, f"{key} align")
                self.assertEqual(p['ls_value'], ls, f"{key} line spacing")
                self.assertEqual(p['default_intent'], default_intent,
                    f"{key} default intent")
                self.assertEqual(p['hwpunitchar_intent'], hu_intent,
                    f"{key} HwpUnitChar intent")
                self.assertEqual(p['default_left'], 0, f"{key} left margin")
                self.assertEqual(p['default_right'], 0, f"{key} right margin")
                self.assertEqual(p['default_prev'], 0, f"{key} prev margin")
                self.assertEqual(p['default_next'], 0, f"{key} next margin")


class TestCacheRegeneratesToSameValues(unittest.TestCase):
    """Deleting and regenerating the cache must produce identical marker
    paraPr/charPr values — guards the "auto-discovery silently overwrites"
    failure mode.
    """

    def test_regen_produces_same_marker_styles(self):
        original = json.loads(CACHE_PATH.read_text())['style_map']

        backup = CACHE_PATH.read_bytes()
        try:
            CACHE_PATH.unlink()
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "out.hwpx"
                config = {"sections": [{"type": "body", "title_bar": "x",
                                        "content": [{"type": "heading", "text": "y"}]}]}
                gh.generate_hwpx(config, out, TEMPLATE_PATH)
            self.assertTrue(CACHE_PATH.exists(),
                "regen should have written default_styles.json")
            regen = json.loads(CACHE_PATH.read_text())['style_map']
            for key in ("heading_marker", "heading_text", "heading_tail",
                        "heading_end", "bullet", "bullet_end",
                        "dash", "dash_end", "star", "star_end"):
                with self.subTest(key=key):
                    self.assertEqual(list(regen[key])[:2], list(original[key])[:2],
                        f"{key} regen should match committed cache")
        finally:
            CACHE_PATH.write_bytes(backup)


class TestGeneratedDocumentParaPrPerMarker(unittest.TestCase):
    """End-to-end: build a document containing one of each marker type and
    assert each paragraph's resolved paraPr (looked up in the OUTPUT's
    trimmed header) has the expected properties (align, line-spacing,
    intent). Raw paraPr IDs are NOT compared because ``trim_unused_styles``
    renumbers IDs in the output.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _generate(self, line_spacing_band=None):
        config = {
            "include_cover": False,
            "sections": [{
                "type": "body",
                "title_bar": "테스트",
                "content": [
                    {"type": "heading", "text": "테스트 헤딩"},
                    {"type": "bullet",  "text": "테스트 불릿"},
                    {"type": "dash",    "text": "테스트 대시"},
                    {"type": "star",    "text": "테스트 스타"},
                ],
            }],
        }
        out = Path(self.tmp.name) / "out.hwpx"
        gh.generate_hwpx(config, out, TEMPLATE_PATH,
                          line_spacing_band=line_spacing_band)
        with zipfile.ZipFile(out, 'r') as zf:
            section_xml = None
            for name in zf.namelist():
                if name.startswith("Contents/section") and name.endswith(".xml"):
                    section_xml = zf.read(name).decode('utf-8')
                    break
            header_xml = zf.read("Contents/header.xml").decode('utf-8')
        self.assertIsNotNone(section_xml, "no section XML in output")
        return section_xml, header_xml

    def _find_paragraph_containing(self, section_xml, needle):
        spans = find_top_level_paragraphs(section_xml)
        for a, b in spans:
            blk = section_xml[a:b]
            texts = re.findall(r'<hp:t>([^<]*)</hp:t>', blk)
            if any(needle in t for t in texts):
                return blk
        return None

    def _paragraph_paraPr_props(self, section_xml, header_xml, needle):
        blk = self._find_paragraph_containing(section_xml, needle)
        self.assertIsNotNone(blk, f"paragraph with {needle!r} not found")
        pp_m = re.search(r'paraPrIDRef="(\d+)"', blk)
        self.assertIsNotNone(pp_m, "paragraph missing paraPrIDRef")
        props = _parse_paraPr(header_xml, pp_m.group(1))
        self.assertIsNotNone(props,
            f"paraPr {pp_m.group(1)} not found in output header.xml")
        return props

    def test_each_marker_resolved_paraPr_properties(self):
        section_xml, header_xml = self._generate()
        # heading (□): LEFT, 165%, hanging indent -3580 HwpUnitChar
        p = self._paragraph_paraPr_props(section_xml, header_xml, "테스트 헤딩")
        self.assertEqual(p['align'], 'LEFT')
        self.assertEqual(p['ls_value'], '165')
        self.assertEqual(p['hwpunitchar_intent'], -3580)
        # bullet (ㅇ): JUSTIFY, 165%, hanging indent -3240
        p = self._paragraph_paraPr_props(section_xml, header_xml, "테스트 불릿")
        self.assertEqual(p['align'], 'JUSTIFY')
        self.assertEqual(p['ls_value'], '165')
        self.assertEqual(p['hwpunitchar_intent'], -3240)
        # dash (-): JUSTIFY, 165%, hanging indent -4050 (screenshot value)
        p = self._paragraph_paraPr_props(section_xml, header_xml, "테스트 대시")
        self.assertEqual(p['align'], 'JUSTIFY')
        self.assertEqual(p['ls_value'], '165')
        self.assertEqual(p['hwpunitchar_intent'], -4050)
        # star (*): LEFT, 155% (the only star paraPr in the template)
        p = self._paragraph_paraPr_props(section_xml, header_xml, "테스트 스타")
        self.assertEqual(p['align'], 'LEFT')
        self.assertEqual(p['ls_value'], '155')

    def test_line_spacing_override_switches_paraPrs(self):
        # --line-spacing 160 should pick a 160% LS paraPr for dash.
        section_xml, header_xml = self._generate(line_spacing_band="160")
        p = self._paragraph_paraPr_props(section_xml, header_xml, "테스트 대시")
        self.assertEqual(p['ls_value'], '160',
            "--line-spacing 160 should produce a 160% LS dash paraPr")
        self.assertEqual(p['align'], 'JUSTIFY')


# --- helper for TestTemplateFrequencyAlignment -----------------------------

def zipfile_extract_header(hwpx_path):
    """Extract Contents/header.xml to a temp file and return its path.

    _parse_header_catalogs takes a file path (uses ET.parse), so we
    materialize header.xml from the zip into a temp file kept alive for
    the duration of the test.
    """
    if not hasattr(zipfile_extract_header, "_cache"):
        tmp = tempfile.NamedTemporaryFile(suffix="-header.xml", delete=False)
        with zipfile.ZipFile(hwpx_path, 'r') as zf:
            tmp.write(zf.read("Contents/header.xml"))
        tmp.close()
        zipfile_extract_header._cache = Path(tmp.name)
    return zipfile_extract_header._cache


if __name__ == "__main__":
    unittest.main()
