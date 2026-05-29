#!/usr/bin/env python3
"""Regression tests for:
  - The dropped 붙임/참고 title bug (inject_appendix_labels single-run cell)
  - The empty-appendix-title guard (hard error)
  - 본문 + 붙임 document structure with the MS_YOON template
  - Marker-based body detection (styleIDRef != "15" templates)

These lock in the behavior described in
docs/superpowers/specs/2026-05-27-ms-yoon-template-and-appendix-title-design.md
"""

import os
import re
import sys
import tempfile
import zipfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import generate_hwpx as G

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(SKILL_DIR, "assets", "template.hwpx")


def _appendix_bar_cells(section_xml):
    """Return {colAddr: [text,...]} for the first 1x3 appendix bar table."""
    m = (re.search(r'<hp:tbl\b[^>]*colCnt="3"[^>]*rowCnt="1"[^>]*>.*?</hp:tbl>',
                   section_xml, re.DOTALL)
         or re.search(r'<hp:tbl\b[^>]*rowCnt="1"[^>]*colCnt="3"[^>]*>.*?</hp:tbl>',
                      section_xml, re.DOTALL))
    if not m:
        return {}
    out = {}
    for tc in re.finditer(r'<hp:tc\b[^>]*>(.*?)</hp:tc>', m.group(0), re.DOTALL):
        body = tc.group(1)
        addr = re.search(r'<hp:cellAddr colAddr="(\d+)"', body)
        texts = re.findall(r'<hp:t>([^<]*)</hp:t>', body)
        if addr:
            out[int(addr.group(1))] = texts
    return out


def _make_appendix_skeleton(title_runs):
    """Build a minimal appendix-bar paragraph (1x3 table).

    ``title_runs``: list of (charPrIDRef, text) tuples for the title cell
    (col 2) so we can exercise both single-run and two-run title cells.
    """
    title_cell_runs = "".join(
        f'<hp:run charPrIDRef="{cp}"><hp:t>{t}</hp:t></hp:run>' for cp, t in title_runs
    )
    return (
        '<hp:p id="0" paraPrIDRef="16" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        '<hp:run charPrIDRef="23">'
        '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
        '</hp:run>'
        '<hp:run charPrIDRef="23">'
        '<hp:tbl id="111" zOrder="3" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
        'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="1" '
        'rowCnt="1" colCnt="3" cellSpacing="0" borderFillIDRef="3" noAdjust="0">'
        '<hp:sz width="48159" widthRelTo="ABSOLUTE" height="2831" heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:tr>'
        # col 0 : tab label
        '<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="14">'
        '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
        'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        '<hp:p id="1" paraPrIDRef="17" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        '<hp:run charPrIDRef="7"><hp:t>붙임1</hp:t></hp:run></hp:p></hp:subList>'
        '<hp:cellAddr colAddr="0" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        '<hp:cellSz width="5968" height="2831"/><hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc>'
        # col 1 : separator (empty)
        '<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="10">'
        '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
        'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        '<hp:p id="2" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        '<hp:run charPrIDRef="4"/></hp:p></hp:subList>'
        '<hp:cellAddr colAddr="1" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        '<hp:cellSz width="565" height="2831"/><hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc>'
        # col 2 : title
        '<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="11">'
        '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
        'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        '<hp:p id="3" paraPrIDRef="15" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'{title_cell_runs}</hp:p></hp:subList>'
        '<hp:cellAddr colAddr="2" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        '<hp:cellSz width="41626" height="2831"/><hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc>'
        '</hp:tr></hp:tbl></hp:run>'
        '<hp:run charPrIDRef="23"><hp:t/></hp:run>'
        '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="2831" textheight="2831" '
        'baseline="2406" spacing="300" horzpos="0" horzsize="48188" flags="393216"/></hp:linesegarray>'
        '</hp:p>'
    )


class TestInjectAppendixLabelsSingleRun(unittest.TestCase):
    """The title cell in real templates (old + MS_YOON) has a SINGLE combined
    <hp:t> run. The injector must still place the title there (not a bare space).
    """

    def test_single_run_title_injected(self):
        skeleton = _make_appendix_skeleton([("5", " 분과별 세부기능(안)")])
        out = G.inject_appendix_labels(skeleton, "붙임", "사업 안건별 현황 조사")
        self.assertIsNotNone(out, "injection should succeed")
        cells = _appendix_bar_cells(out)
        joined = "".join(cells.get(2, []))
        self.assertIn("사업 안건별 현황 조사", joined,
                      f"title text must be present in col-2; got {cells.get(2)!r}")
        self.assertNotEqual(joined.strip(), "",
                            "col-2 must not collapse to a bare space")
        self.assertEqual(cells.get(0), ["붙임"], "tab label must be injected")

    def test_two_run_title_injected(self):
        # space-run + title-run (synthetic two-run cell) must also work
        skeleton = _make_appendix_skeleton([("23", " "), ("5", "OLD TITLE")])
        out = G.inject_appendix_labels(skeleton, "참고1", "새 제목")
        self.assertIsNotNone(out)
        cells = _appendix_bar_cells(out)
        joined = "".join(cells.get(2, []))
        self.assertIn("새 제목", joined, f"got {cells.get(2)!r}")
        self.assertNotIn("OLD TITLE", joined, "stale template title must be replaced")
        self.assertEqual(cells.get(0), ["참고1"])


class TestEmptyAppendixTitleGuard(unittest.TestCase):
    """An appendix section with no appendix_title is a hard error."""

    def _config(self, appendix_title):
        return {
            "title": "테스트 보고서",
            "date": "26.05.27.",
            "department": "전략기획팀",
            "include_cover": False,
            "sections": [
                {"type": "body", "title_bar": "본문",
                 "content": [{"type": "heading", "text": "개요"}]},
                {"type": "appendix", "title_bar": "붙임",
                 "appendix_title": appendix_title,
                 "content": [{"type": "bullet", "text": "내용"}]},
            ],
        }

    def test_empty_title_raises(self):
        out = tempfile.mktemp(suffix=".hwpx")
        try:
            with self.assertRaises(ValueError):
                G.generate_hwpx(self._config(""), out, template_path=TEMPLATE)
        finally:
            if os.path.exists(out):
                os.unlink(out)

    def test_whitespace_title_raises(self):
        out = tempfile.mktemp(suffix=".hwpx")
        try:
            with self.assertRaises(ValueError):
                G.generate_hwpx(self._config("   "), out, template_path=TEMPLATE)
        finally:
            if os.path.exists(out):
                os.unlink(out)


class TestBodyPlusAppendixStructure(unittest.TestCase):
    """End-to-end: a 본문 + 붙임 document fills the 붙임 title correctly."""

    def setUp(self):
        self.config = {
            "title": "(재)이노베이션아카데미 Codyssey 활용 사업 추진 계획(안)",
            "date": "24. 6. 11.(화)",
            "department": "이노베이션아카데미",
            "include_cover": False,
            "sections": [
                {"type": "body", "title_bar": "Codyssey 활용 사업 추진 계획(안)",
                 "content": [
                     {"type": "heading", "text": "추진 배경"},
                     {"type": "bullet", "text": "사업 준비 단계"},
                     {"type": "dash", "text": "역량 집결 및 동력 확보"},
                     {"type": "star", "text": "24년 교육생 미선발"},
                     {"type": "table", "caption": "추진 현황",
                      "headers": ["구분", "내용"], "rows": [["1월", "착수"]]},
                 ]},
                {"type": "appendix", "title_bar": "붙임",
                 "appendix_title": "사업 안건별 현황 조사",
                 "content": [
                     {"type": "heading", "text": "SW중심대학"},
                     {"type": "bullet", "text": "전국 58개 SW중심대학"},
                 ]},
            ],
        }

    def _generate(self):
        out = tempfile.mktemp(suffix=".hwpx")
        G.generate_hwpx(self.config, out, template_path=TEMPLATE)
        sections = {}
        with zipfile.ZipFile(out, "r") as z:
            for n in z.namelist():
                if re.match(r"Contents/section\d+\.xml", n):
                    sections[n] = z.read(n).decode("utf-8")
            header = z.read("Contents/header.xml").decode("utf-8")
        os.unlink(out)
        return sections, header

    def test_appendix_title_is_filled(self):
        sections, _ = self._generate()
        # find the section that has the 붙임 bar
        found = None
        for name, xml in sections.items():
            cells = _appendix_bar_cells(xml)
            if cells.get(0) == ["붙임"]:
                found = cells
                break
        self.assertIsNotNone(found, "a 붙임 bar must exist in output")
        self.assertIn("사업 안건별 현황 조사", "".join(found.get(2, [])),
                      f"붙임 title must be filled; got {found.get(2)!r}")

    def test_uses_ms_yoon_fonts(self):
        _, header = self._generate()
        self.assertIn("HY헤드라인M", header,
                      "MS_YOON template fonts must be present in header.xml")


class TestMarkerBasedBodyDetection(unittest.TestCase):
    """Body detection must work when headings do NOT use styleIDRef='15'."""

    def test_count_body_headings_by_marker(self):
        xml = (
            '<hs:sec>'
            '<hp:p paraPrIDRef="74" styleIDRef="14"><hp:run charPrIDRef="253">'
            '<hp:t>□</hp:t></hp:run><hp:run charPrIDRef="2"><hp:t> 추진 배경</hp:t></hp:run>'
            '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1500" '
            'textheight="1500" baseline="1275" spacing="900" horzpos="0" horzsize="48188" flags="393216"/></hp:linesegarray></hp:p>'
            '<hp:p paraPrIDRef="41" styleIDRef="0"><hp:run charPrIDRef="22">'
            '<hp:t> ㅇ 내용</hp:t></hp:run>'
            '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1500" '
            'textheight="1500" baseline="1275" spacing="900" horzpos="0" horzsize="48188" flags="393216"/></hp:linesegarray></hp:p>'
            '<hp:p paraPrIDRef="74" styleIDRef="14"><hp:run charPrIDRef="253">'
            '<hp:t>□</hp:t></hp:run><hp:run charPrIDRef="2"><hp:t> 향후 계획</hp:t></hp:run>'
            '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1500" '
            'textheight="1500" baseline="1275" spacing="900" horzpos="0" horzsize="48188" flags="393216"/></hp:linesegarray></hp:p>'
            '</hs:sec>'
        )
        self.assertEqual(G._count_body_headings(xml), 2,
                         "should count 2 □ headings regardless of styleIDRef")


if __name__ == "__main__":
    unittest.main()
