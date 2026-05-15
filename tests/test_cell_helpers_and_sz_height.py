#!/usr/bin/env python3
"""Tests for the new in-cell helpers and the table sz-height invariant.

These tests exercise the lessons from production (Rules 14-17 in SKILL.md):
  - `<hp:sz height>` must equal sum of col-0 cellSz heights (Rule 14)
  - In-cell linesegs use flags=393216 (Rule 15)
  - Empty-cell text injection requires subList swap (Rule 16)
  - Cell-content helpers (find_cell, set_cell_text, append_to_cell_subList,
    replace_cell_subList) form the toolkit for Rule 17's R-style pattern
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import modify_hwpx, table_fixer


# ---------------------------------------------------------------------------
# Synthetic table fixtures (minimal HWPX-shaped XML)
# ---------------------------------------------------------------------------

def _build_table(row_heights, col_count=2, sz_height=None):
    """Build a minimal <hp:tbl> with the given row heights.

    Each row has ``col_count`` cells. Col 0 of each row carries the row's
    cellSz height (used by table_fixer to compute sz.height).
    """
    if sz_height is None:
        sz_height = sum(row_heights)
    rows_xml = ""
    for r, h in enumerate(row_heights):
        cells_xml = ""
        for c in range(col_count):
            cells_xml += (
                f'<hp:tc><hp:subList>'
                f'<hp:p id="2147483648" paraPrIDRef="0" styleIDRef="0">'
                f'<hp:run charPrIDRef="0"><hp:t>r{r}c{c}</hp:t></hp:run>'
                f'</hp:p></hp:subList>'
                f'<hp:cellAddr colAddr="{c}" rowAddr="{r}"/>'
                f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
                f'<hp:cellSz width="2000" height="{h}"/>'
                f'<hp:cellMargin left="0" right="0" top="0" bottom="0"/>'
                f'</hp:tc>'
            )
        rows_xml += f'<hp:tr>{cells_xml}</hp:tr>'
    return (
        f'<hp:tbl id="0" rowCnt="{len(row_heights)}" colCnt="{col_count}">'
        f'<hp:sz width="4000" widthRelTo="ABSOLUTE" height="{sz_height}" '
        f'heightRelTo="ABSOLUTE" protect="0"/>'
        f'{rows_xml}'
        f'</hp:tbl>'
    )


# ===========================================================================
# Table sz.height (Rule 14)
# ===========================================================================

class TestTableSzHeight(unittest.TestCase):
    """Table <hp:sz height> must equal sum of col-0 cellSz row heights."""

    def test_validate_detects_sz_height_mismatch(self):
        # Build a table where sz.height intentionally doesn't match cellSz sum
        tbl = _build_table([1000, 2000, 3000], sz_height=5000)  # actual sum = 6000
        errors = table_fixer.validate_table(tbl)
        sz_errors = [e for e in errors if e.field == 'sz.height']
        self.assertEqual(len(sz_errors), 1, "expected one sz.height error")
        self.assertEqual(sz_errors[0].expected, 6000)
        self.assertEqual(sz_errors[0].actual, 5000)

    def test_validate_passes_when_sz_height_matches(self):
        tbl = _build_table([1000, 2000, 3000])  # sz.height defaults to sum
        errors = table_fixer.validate_table(tbl)
        sz_errors = [e for e in errors if e.field == 'sz.height']
        self.assertEqual(sz_errors, [])

    def test_fix_updates_sz_height_to_sum(self):
        tbl = _build_table([1000, 2000, 3000], sz_height=5000)
        fixed = table_fixer.fix_table(tbl)
        # After fix, sz.height should equal sum = 6000
        m = re.search(
            r'<hp:sz\s+width="\d+"\s+widthRelTo="ABSOLUTE"\s+height="(\d+)"',
            fixed)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), 6000)

    def test_fix_after_row_addition_updates_sz_height(self):
        """End-to-end: append a row via modify_hwpx and confirm sz.height updates."""
        # Start with 2-row table (sz.height = 3000)
        tbl = _build_table([1000, 2000])
        section = f'<hs:sec>{tbl}</hs:sec>'

        # Manually add a new <hp:tr> at the end + bump rowCnt
        new_row = (
            '<hp:tr>'
            '<hp:tc><hp:subList>'
            '<hp:p id="2147483648" paraPrIDRef="0" styleIDRef="0">'
            '<hp:run charPrIDRef="0"><hp:t>r2c0</hp:t></hp:run></hp:p>'
            '</hp:subList>'
            '<hp:cellAddr colAddr="0" rowAddr="2"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/>'
            '<hp:cellSz width="2000" height="2500"/>'
            '<hp:cellMargin left="0" right="0" top="0" bottom="0"/></hp:tc>'
            '<hp:tc><hp:subList>'
            '<hp:p id="2147483648" paraPrIDRef="0" styleIDRef="0">'
            '<hp:run charPrIDRef="0"><hp:t>r2c1</hp:t></hp:run></hp:p>'
            '</hp:subList>'
            '<hp:cellAddr colAddr="1" rowAddr="2"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/>'
            '<hp:cellSz width="2000" height="2500"/>'
            '<hp:cellMargin left="0" right="0" top="0" bottom="0"/></hp:tc>'
            '</hp:tr>'
        )
        # Append before </hp:tbl>
        section_with_row = section.replace('</hp:tbl>', new_row + '</hp:tbl>')
        # Bump rowCnt manually
        section_with_row = re.sub(r'rowCnt="2"', 'rowCnt="3"',
                                    section_with_row, count=1)

        # Run fix_all_tables — should auto-update sz.height
        fixed = table_fixer.fix_all_tables(section_with_row)
        m = re.search(
            r'<hp:sz\s+width="\d+"\s+widthRelTo="ABSOLUTE"\s+height="(\d+)"',
            fixed)
        self.assertEqual(int(m.group(1)), 1000 + 2000 + 2500,
            "sz.height should equal new col-0 cellSz sum")


# ===========================================================================
# find_cell + set_cell_text (Rule 16: empty-cell subList swap)
# ===========================================================================

class TestFindCellAndSetText(unittest.TestCase):
    """find_cell + set_cell_text behaviors."""

    def test_find_cell_returns_correct_cell(self):
        tbl = _build_table([1000, 1000], col_count=2)
        cell = modify_hwpx.find_cell(tbl, col=0, row=1)
        self.assertIsNotNone(cell)
        _, _, body = cell
        self.assertIn('rowAddr="1"', body)
        self.assertIn('colAddr="0"', body)
        self.assertIn('<hp:t>r1c0</hp:t>', body)

    def test_find_cell_returns_none_for_missing(self):
        tbl = _build_table([1000])
        self.assertIsNone(modify_hwpx.find_cell(tbl, col=9, row=9))

    def test_set_cell_text_on_filled_cell(self):
        tbl = _build_table([1000])
        new_tbl, changed = modify_hwpx.set_cell_text(tbl, col=0, row=0,
                                                       new_text="NEW")
        self.assertTrue(changed)
        self.assertIn('<hp:t>NEW</hp:t>', new_tbl)
        self.assertNotIn('<hp:t>r0c0</hp:t>', new_tbl)

    def test_set_cell_text_xml_escaping(self):
        """Text with XML-special chars must be escaped."""
        tbl = _build_table([1000])
        new_tbl, _ = modify_hwpx.set_cell_text(tbl, col=0, row=0,
                                                 new_text="a & b < c > d")
        self.assertIn('<hp:t>a &amp; b &lt; c &gt; d</hp:t>', new_tbl)

    def test_set_cell_text_on_empty_cell_with_template(self):
        """Empty cells should swap subList using filled_cell_template."""
        # Build a table with one empty cell + one filled cell
        filled_cell = (
            '<hp:tc><hp:subList>'
            '<hp:p id="0" paraPrIDRef="9" styleIDRef="0">'
            '<hp:run charPrIDRef="99"><hp:t>FILLED</hp:t></hp:run></hp:p>'
            '</hp:subList>'
            '<hp:cellAddr colAddr="0" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/>'
            '<hp:cellSz width="2000" height="1000"/>'
            '<hp:cellMargin left="0" right="0" top="0" bottom="0"/></hp:tc>'
        )
        empty_cell = (
            '<hp:tc><hp:subList>'
            '<hp:p id="0" paraPrIDRef="5" styleIDRef="0">'
            '<hp:run charPrIDRef="100"/></hp:p>'
            '</hp:subList>'
            '<hp:cellAddr colAddr="1" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/>'
            '<hp:cellSz width="2000" height="1000"/>'
            '<hp:cellMargin left="0" right="0" top="0" bottom="0"/></hp:tc>'
        )
        para = f'<hp:tbl rowCnt="1" colCnt="2"><hp:tr>{filled_cell}{empty_cell}</hp:tr></hp:tbl>'

        # Set empty cell's text using filled cell as template
        filled_body = modify_hwpx.find_cell(para, 0, 0)[2]
        new_para, changed = modify_hwpx.set_cell_text(
            para, col=1, row=0, new_text="NOW FILLED",
            filled_cell_template=filled_body)
        self.assertTrue(changed)
        # The empty cell should now use paraPr=9 (filled template's), not 5
        # (its own empty-cell paraPr)
        new_empty = modify_hwpx.find_cell(new_para, 1, 0)[2]
        self.assertIn('paraPrIDRef="9"', new_empty,
            "empty cell should inherit filled cell's paraPr")
        self.assertIn('charPrIDRef="99"', new_empty)
        self.assertIn('<hp:t>NOW FILLED</hp:t>', new_empty)


# ===========================================================================
# append_to_cell_subList + replace_cell_subList (Rule 15: in-cell flags=393216)
# ===========================================================================

class TestCellSubListHelpers(unittest.TestCase):
    """append_to_cell_subList and replace_cell_subList must use flags=393216
    for ALL linesegs (the in-cell convention)."""

    def _build_para_with_cell(self):
        tbl = _build_table([2000], col_count=1)
        # Wrap in a paragraph (mimic the real structure where a table is
        # inside a paragraph that contains the table).
        return ('<hp:p id="0" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0">'
                + tbl + '<hp:t/></hp:run></hp:p>')

    def test_append_uses_flags_393216(self):
        para = self._build_para_with_cell()
        result = modify_hwpx.append_to_cell_subList(
            para, col=0, row=0,
            new_lines=["첫 줄", "둘째 줄", "셋째 줄"])
        # Extract just the cell, then the appended <hp:p>s (everything after
        # the original r0c0 paragraph)
        cell = modify_hwpx.find_cell(result, 0, 0)
        cell_body = cell[2]
        # Get the appended <hp:t> entries
        appended_texts = re.findall(r'<hp:t>(ㅇ [^<]*)</hp:t>', cell_body)
        self.assertEqual(len(appended_texts), 3)
        self.assertIn("ㅇ 첫 줄", appended_texts)
        # Confirm all linesegs in the appended paragraphs use flags=393216
        # (find linesegs that come AFTER the first existing <hp:t>r0c0)
        after_orig = cell_body.split('<hp:t>r0c0</hp:t>', 1)[1]
        new_flags = re.findall(r'flags="(\d+)"', after_orig)
        self.assertTrue(all(f == '393216' for f in new_flags),
            f"in-cell linesegs must use 393216, got: {new_flags}")

    def test_replace_uses_flags_393216(self):
        para = self._build_para_with_cell()
        result = modify_hwpx.replace_cell_subList(
            para, col=0, row=0,
            new_lines=["완전 교체 1", "완전 교체 2"])
        cell_body = modify_hwpx.find_cell(result, 0, 0)[2]
        # Original r0c0 text should be gone
        self.assertNotIn('<hp:t>r0c0</hp:t>', cell_body)
        # All linesegs must use flags=393216
        flags = re.findall(r'flags="(\d+)"', cell_body)
        self.assertTrue(flags)
        self.assertTrue(all(f == '393216' for f in flags),
            f"in-cell linesegs must all use 393216, got: {flags}")

    def test_append_preserves_existing_paragraphs(self):
        """append_to_cell_subList must keep existing <hp:p>s, only add new ones at end."""
        para = self._build_para_with_cell()
        result = modify_hwpx.append_to_cell_subList(
            para, col=0, row=0, new_lines=["새 줄"])
        cell_body = modify_hwpx.find_cell(result, 0, 0)[2]
        # Original r0c0 must still be there
        self.assertIn('<hp:t>r0c0</hp:t>', cell_body)
        # And the new line is also there
        self.assertIn('<hp:t>ㅇ 새 줄</hp:t>', cell_body)
        # Order: original comes BEFORE the new
        self.assertLess(cell_body.index('r0c0'), cell_body.index('새 줄'))

    def test_replace_drops_existing_paragraphs(self):
        para = self._build_para_with_cell()
        result = modify_hwpx.replace_cell_subList(
            para, col=0, row=0, new_lines=["오직 이것만"])
        cell_body = modify_hwpx.find_cell(result, 0, 0)[2]
        self.assertNotIn('r0c0', cell_body)
        self.assertIn('<hp:t>ㅇ 오직 이것만</hp:t>', cell_body)

    def test_helpers_set_vertpos_zero(self):
        """All new linesegs should use vertpos=0 (Hancom recomputes)."""
        para = self._build_para_with_cell()
        result = modify_hwpx.append_to_cell_subList(
            para, col=0, row=0, new_lines=["a", "b"])
        cell_body = modify_hwpx.find_cell(result, 0, 0)[2]
        after_orig = cell_body.split('<hp:t>r0c0</hp:t>', 1)[1]
        vertpos_values = re.findall(r'vertpos="(\d+)"', after_orig)
        self.assertTrue(vertpos_values)
        self.assertTrue(all(v == '0' for v in vertpos_values),
            f"new in-cell linesegs should use vertpos=0, got: {vertpos_values}")

    def test_in_cell_lineseg_flags_constant(self):
        """The IN_CELL_LINESEG_FLAGS constant is the documented value."""
        self.assertEqual(modify_hwpx.IN_CELL_LINESEG_FLAGS, 393216)


if __name__ == "__main__":
    unittest.main()
