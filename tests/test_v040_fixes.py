#!/usr/bin/env python3
"""Tests for v0.4.0 fixes:
  Fix 1: Nested table cellSpan — metadata suffix extraction
  Fix 2: rowSpan occupation grid — correct colAddr across spanning rows
  Fix 3: Unclosed CDATA/comment detection signal
"""

import sys
import os
import unittest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import _parser
from scripts import table_fixer


# ============================================================================
# Fix 1: Nested table cellSpan — metadata suffix extraction
# ============================================================================

class TestNestedTableCellSpan(unittest.TestCase):
    """Fix 1: _extract_col_span and _extract_row_span must NOT match
    nested tables' <hp:cellSpan> elements. They should only read the
    outer cell's own metadata suffix (after the last </hp:subList>).
    """

    def _make_cell_with_nested_table(self, outer_col_span, outer_row_span,
                                      inner_col_span=1, inner_row_span=1):
        """Build a <hp:tc> with a nested table whose cellSpan differs."""
        return (
            f'<hp:tc>'
            f'<hp:subList>'
            f'<hp:tbl colCnt="2" rowCnt="1">'
            f'<hp:tr><hp:tc>'
            f'<hp:subList><hp:p><hp:t>inner</hp:t></hp:p></hp:subList>'
            f'<hp:cellAddr colAddr="0" rowAddr="0"/>'
            f'<hp:cellSpan colSpan="{inner_col_span}" rowSpan="{inner_row_span}"/>'
            f'<hp:cellSz/><hp:cellMargin/>'
            f'</hp:tc></hp:tr>'
            f'</hp:tbl>'
            f'</hp:subList>'
            f'<hp:cellAddr colAddr="0" rowAddr="0"/>'
            f'<hp:cellSpan colSpan="{outer_col_span}" rowSpan="{outer_row_span}"/>'
            f'<hp:cellSz/><hp:cellMargin/>'
            f'</hp:tc>'
        )

    def test_col_span_reads_outer_not_inner(self):
        """colSpan=2 on outer, colSpan=1 on inner → must return 2."""
        cell = self._make_cell_with_nested_table(
            outer_col_span=2, outer_row_span=1,
            inner_col_span=1, inner_row_span=1)
        self.assertEqual(table_fixer._extract_col_span(cell), 2)

    def test_row_span_reads_outer_not_inner(self):
        """rowSpan=3 on outer, rowSpan=1 on inner → must return 3."""
        cell = self._make_cell_with_nested_table(
            outer_col_span=1, outer_row_span=3,
            inner_col_span=1, inner_row_span=1)
        self.assertEqual(table_fixer._extract_row_span(cell), 3)

    def test_inner_larger_than_outer(self):
        """Inner has colSpan=5, outer has colSpan=2 → must return 2."""
        cell = self._make_cell_with_nested_table(
            outer_col_span=2, outer_row_span=1,
            inner_col_span=5, inner_row_span=4)
        self.assertEqual(table_fixer._extract_col_span(cell), 2)
        self.assertEqual(table_fixer._extract_row_span(cell), 1)

    def test_no_sublist_falls_back_to_full_cell(self):
        """Cell without </hp:subList> — fallback to full cell search."""
        cell = ('<hp:tc>'
                '<hp:cellAddr colAddr="0" rowAddr="0"/>'
                '<hp:cellSpan colSpan="3" rowSpan="2"/>'
                '</hp:tc>')
        self.assertEqual(table_fixer._extract_col_span(cell), 3)
        self.assertEqual(table_fixer._extract_row_span(cell), 2)


# ============================================================================
# Fix 2: rowSpan occupation grid
# ============================================================================

class TestRowSpanOccupationGrid(unittest.TestCase):
    """Fix 2: fix_table() and validate_table() must account for rowSpan
    when assigning/validating colAddr values.
    """

    def _make_table(self, col_cnt, rows):
        """Build a table XML from row specifications.

        Args:
            col_cnt: Number of logical columns.
            rows: List of lists of (col_span, row_span, text) tuples.
                  cellAddr values are set to (0, 0) — intentionally wrong
                  so fix_table() must correct them.
        """
        parts = [f'<hp:tbl colCnt="{col_cnt}" rowCnt="{len(rows)}">']
        for row in rows:
            parts.append('<hp:tr>')
            for cs, rs, text in row:
                parts.append(
                    f'<hp:tc>'
                    f'<hp:subList><hp:p><hp:t>{text}</hp:t></hp:p></hp:subList>'
                    f'<hp:cellAddr colAddr="0" rowAddr="0"/>'
                    f'<hp:cellSpan colSpan="{cs}" rowSpan="{rs}"/>'
                    f'<hp:cellSz/><hp:cellMargin/>'
                    f'</hp:tc>'
                )
            parts.append('</hp:tr>')
        parts.append('</hp:tbl>')
        return ''.join(parts)

    def _extract_cell_addrs(self, table_xml):
        """Extract all (colAddr, rowAddr) pairs from fixed table XML."""
        import re
        return re.findall(
            r'<hp:cellAddr colAddr="(\d+)" rowAddr="(\d+)"',
            table_xml)

    def test_no_rowspan_unchanged(self):
        """3×2 table with no rowSpan — colAddr should be sequential."""
        tbl = self._make_table(3, [
            [(1, 1, 'A'), (1, 1, 'B'), (1, 1, 'C')],
            [(1, 1, 'D'), (1, 1, 'E'), (1, 1, 'F')],
        ])
        fixed = table_fixer.fix_table(tbl)
        addrs = self._extract_cell_addrs(fixed)
        self.assertEqual(addrs, [
            ('0', '0'), ('1', '0'), ('2', '0'),  # Row 0
            ('0', '1'), ('1', '1'), ('2', '1'),  # Row 1
        ])

    def test_rowspan_2_first_column(self):
        """Cell A in row 0, col 0 has rowSpan=2.
        Row 1 has 2 cells that should occupy cols 1 and 2.

        Grid (colCnt=3):
        ┌─────┬─────┬─────┐
        │  A  │  B  │  C  │   Row 0: A(rs=2), B, C
        │(rs2)│     │     │
        ├─────┼─────┼─────┤
        │     │  D  │  E  │   Row 1: D(col=1), E(col=2)
        └─────┴─────┴─────┘
        """
        tbl = self._make_table(3, [
            [(1, 2, 'A'), (1, 1, 'B'), (1, 1, 'C')],
            [(1, 1, 'D'), (1, 1, 'E')],
        ])
        fixed = table_fixer.fix_table(tbl)
        addrs = self._extract_cell_addrs(fixed)
        self.assertEqual(addrs, [
            ('0', '0'), ('1', '0'), ('2', '0'),  # Row 0
            ('1', '1'), ('2', '1'),                # Row 1 (col 0 occupied by A)
        ])

    def test_rowspan_2_middle_column(self):
        """Cell B in row 0, col 1 has rowSpan=2.
        Row 1 has 2 cells at cols 0 and 2.

        Grid (colCnt=3):
        ┌─────┬─────┬─────┐
        │  A  │  B  │  C  │   Row 0: A, B(rs=2), C
        │     │(rs2)│     │
        ├─────┼─────┼─────┤
        │  D  │     │  E  │   Row 1: D(col=0), E(col=2)
        └─────┴─────┴─────┘
        """
        tbl = self._make_table(3, [
            [(1, 1, 'A'), (1, 2, 'B'), (1, 1, 'C')],
            [(1, 1, 'D'), (1, 1, 'E')],
        ])
        fixed = table_fixer.fix_table(tbl)
        addrs = self._extract_cell_addrs(fixed)
        self.assertEqual(addrs, [
            ('0', '0'), ('1', '0'), ('2', '0'),  # Row 0
            ('0', '1'), ('2', '1'),                # Row 1 (col 1 occupied by B)
        ])

    def test_rowspan_plus_colspan(self):
        """Cell A spans 2 columns AND 2 rows.

        Grid (colCnt=3):
        ┌───────────┬─────┐
        │     A     │  B  │   Row 0: A(cs=2,rs=2), B
        │(cs2,rs2)  │     │
        ├───────────┼─────┤
        │           │  C  │   Row 1: C(col=2)
        └───────────┴─────┘
        """
        tbl = self._make_table(3, [
            [(2, 2, 'A'), (1, 1, 'B')],
            [(1, 1, 'C')],
        ])
        fixed = table_fixer.fix_table(tbl)
        addrs = self._extract_cell_addrs(fixed)
        self.assertEqual(addrs, [
            ('0', '0'), ('2', '0'),  # Row 0: A at 0 (spans 0-1), B at 2
            ('2', '1'),               # Row 1: C at 2 (cols 0-1 occupied by A)
        ])

    def test_rowspan_3_cascading(self):
        """Cell spans 3 rows, affecting rows 1 and 2.

        Grid (colCnt=2):
        ┌─────┬─────┐
        │  A  │  B  │   Row 0: A(rs=3), B
        │(rs3)│     │
        ├─────┼─────┤
        │     │  C  │   Row 1: C(col=1)
        ├─────┼─────┤
        │     │  D  │   Row 2: D(col=1)
        └─────┴─────┘
        """
        tbl = self._make_table(2, [
            [(1, 3, 'A'), (1, 1, 'B')],
            [(1, 1, 'C')],
            [(1, 1, 'D')],
        ])
        fixed = table_fixer.fix_table(tbl)
        addrs = self._extract_cell_addrs(fixed)
        self.assertEqual(addrs, [
            ('0', '0'), ('1', '0'),  # Row 0
            ('1', '1'),              # Row 1 (col 0 occupied)
            ('1', '2'),              # Row 2 (col 0 still occupied)
        ])

    def test_multiple_rowspans(self):
        """Two cells with rowSpan in the same row.

        Grid (colCnt=3):
        ┌─────┬─────┬─────┐
        │  A  │  B  │  C  │   Row 0: A(rs=2), B, C(rs=2)
        │(rs2)│     │(rs2)│
        ├─────┼─────┼─────┤
        │     │  D  │     │   Row 1: D(col=1)
        └─────┴─────┴─────┘
        """
        tbl = self._make_table(3, [
            [(1, 2, 'A'), (1, 1, 'B'), (1, 2, 'C')],
            [(1, 1, 'D')],
        ])
        fixed = table_fixer.fix_table(tbl)
        addrs = self._extract_cell_addrs(fixed)
        self.assertEqual(addrs, [
            ('0', '0'), ('1', '0'), ('2', '0'),  # Row 0
            ('1', '1'),                            # Row 1 (cols 0,2 occupied)
        ])

    def test_validate_detects_wrong_colspan_with_rowspan(self):
        """Validator should detect wrong colAddr when rowSpan is present."""
        # Manually build a table with wrong colAddr for row 1
        tbl = (
            '<hp:tbl colCnt="3" rowCnt="2">'
            '<hp:tr>'
            '<hp:tc><hp:subList><hp:p><hp:t>A</hp:t></hp:p></hp:subList>'
            '<hp:cellAddr colAddr="0" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="2"/><hp:cellSz/><hp:cellMargin/></hp:tc>'
            '<hp:tc><hp:subList><hp:p><hp:t>B</hp:t></hp:p></hp:subList>'
            '<hp:cellAddr colAddr="1" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz/><hp:cellMargin/></hp:tc>'
            '<hp:tc><hp:subList><hp:p><hp:t>C</hp:t></hp:p></hp:subList>'
            '<hp:cellAddr colAddr="2" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz/><hp:cellMargin/></hp:tc>'
            '</hp:tr>'
            '<hp:tr>'
            # WRONG: colAddr=0 but should be 1 (col 0 occupied by A's rowSpan)
            '<hp:tc><hp:subList><hp:p><hp:t>D</hp:t></hp:p></hp:subList>'
            '<hp:cellAddr colAddr="0" rowAddr="1"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz/><hp:cellMargin/></hp:tc>'
            '<hp:tc><hp:subList><hp:p><hp:t>E</hp:t></hp:p></hp:subList>'
            '<hp:cellAddr colAddr="1" rowAddr="1"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz/><hp:cellMargin/></hp:tc>'
            '</hp:tr>'
            '</hp:tbl>'
        )
        errors = table_fixer.validate_table(tbl)
        # Should detect at least the wrong colAddr for D and E
        col_errors = [e for e in errors if e.field == 'colAddr']
        self.assertGreaterEqual(len(col_errors), 1,
                                f"Expected colAddr errors, got: {errors}")

    def test_fix_then_validate_clean(self):
        """After fix_table, validate_table should return no errors."""
        tbl = self._make_table(3, [
            [(1, 2, 'A'), (1, 1, 'B'), (1, 1, 'C')],
            [(1, 1, 'D'), (1, 1, 'E')],
        ])
        fixed = table_fixer.fix_table(tbl)
        errors = table_fixer.validate_table(fixed)
        self.assertEqual(errors, [],
                         f"Errors after fix: {errors}")


# ============================================================================
# Fix 3: Unclosed CDATA/comment detection
# ============================================================================

class TestUnclosedConstructDetection(unittest.TestCase):
    """Fix 3: check_for_unclosed_constructs() provides explicit signal
    when CDATA or comments are unclosed, which would cause silent
    element loss in the parser.
    """

    def test_no_issues_clean_xml(self):
        """Normal XML with no CDATA or comments → empty list."""
        xml = '<root><hp:p><hp:t>hello</hp:t></hp:p></root>'
        self.assertEqual(_parser.check_for_unclosed_constructs(xml), [])

    def test_closed_cdata_no_issues(self):
        """Properly closed CDATA → empty list."""
        xml = '<root><hp:t><![CDATA[some data]]></hp:t></root>'
        self.assertEqual(_parser.check_for_unclosed_constructs(xml), [])

    def test_closed_comment_no_issues(self):
        """Properly closed comment → empty list."""
        xml = '<root><!-- a comment --><hp:p/></root>'
        self.assertEqual(_parser.check_for_unclosed_constructs(xml), [])

    def test_unclosed_cdata_detected(self):
        """Unclosed CDATA → reported with position."""
        xml = '<root><hp:t><![CDATA[never closed</hp:t></root>'
        issues = _parser.check_for_unclosed_constructs(xml)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['type'], 'CDATA')
        self.assertEqual(issues[0]['position'], xml.index('<![CDATA['))

    def test_unclosed_comment_detected(self):
        """Unclosed comment → reported with position."""
        xml = '<root><!-- never closed <hp:p/></root>'
        issues = _parser.check_for_unclosed_constructs(xml)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['type'], 'comment')
        self.assertEqual(issues[0]['position'], xml.index('<!--'))

    def test_parser_produces_fewer_elements_with_unclosed_cdata(self):
        """Demonstrate the truncation: unclosed CDATA causes element loss."""
        # 3 paragraphs, but CDATA opens in the first and never closes
        xml = ('<root>'
               '<hp:p><hp:t><![CDATA[unclosed</hp:t></hp:p>'
               '<hp:p><hp:t>second</hp:t></hp:p>'
               '<hp:p><hp:t>third</hp:t></hp:p>'
               '</root>')
        # Parser should find fewer paragraphs (truncation)
        paras = _parser.find_top_level_paragraphs(xml)
        self.assertLess(len(paras), 3,
                        "Expected fewer than 3 paragraphs due to unclosed CDATA")
        # But check_for_unclosed_constructs signals the problem
        issues = _parser.check_for_unclosed_constructs(xml)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['type'], 'CDATA')

    def test_multiple_cdata_first_closed_second_unclosed(self):
        """First CDATA closed, second unclosed → only second reported."""
        xml = '<root><![CDATA[ok]]>text<![CDATA[not closed</root>'
        issues = _parser.check_for_unclosed_constructs(xml)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['type'], 'CDATA')
        # Position should be the second CDATA
        self.assertGreater(issues[0]['position'], 0)


# ============================================================================
# Integration: fix_all_tables with rowSpan
# ============================================================================

class TestFixAllTablesRowSpan(unittest.TestCase):
    """Integration test: fix_all_tables handles rowSpan in section XML."""

    def test_fix_all_tables_with_rowspan(self):
        """Section with a rowSpan table — fix_all_tables corrects colAddr."""
        section = (
            '<?xml version="1.0"?>'
            '<hp:sec>'
            '<hp:p><hp:t>before</hp:t></hp:p>'
            '<hp:tbl colCnt="2" rowCnt="2">'
            '<hp:tr>'
            '<hp:tc><hp:subList><hp:p><hp:t>A</hp:t></hp:p></hp:subList>'
            '<hp:cellAddr colAddr="0" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="2"/><hp:cellSz/><hp:cellMargin/></hp:tc>'
            '<hp:tc><hp:subList><hp:p><hp:t>B</hp:t></hp:p></hp:subList>'
            '<hp:cellAddr colAddr="0" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz/><hp:cellMargin/></hp:tc>'
            '</hp:tr>'
            '<hp:tr>'
            '<hp:tc><hp:subList><hp:p><hp:t>C</hp:t></hp:p></hp:subList>'
            '<hp:cellAddr colAddr="0" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz/><hp:cellMargin/></hp:tc>'
            '</hp:tr>'
            '</hp:tbl>'
            '<hp:p><hp:t>after</hp:t></hp:p>'
            '</hp:sec>'
        )
        fixed = table_fixer.fix_all_tables(section)

        import re
        addrs = re.findall(
            r'<hp:cellAddr colAddr="(\d+)" rowAddr="(\d+)"', fixed)
        # Row 0: A at col 0, B at col 1
        # Row 1: C at col 1 (col 0 occupied by A's rowSpan)
        self.assertEqual(addrs, [
            ('0', '0'), ('1', '0'),  # Row 0
            ('1', '1'),               # Row 1
        ])


# ============================================================================
# Existing functionality regression tests
# ============================================================================

class TestColSpanOnlyRegression(unittest.TestCase):
    """Ensure colSpan-only tables still work correctly with the new code."""

    def test_colspan_2_first_cell(self):
        """Row with colSpan=2 on first cell, no rowSpan anywhere."""
        tbl = (
            '<hp:tbl colCnt="3" rowCnt="2">'
            '<hp:tr>'
            '<hp:tc><hp:subList><hp:p><hp:t>AB</hp:t></hp:p></hp:subList>'
            '<hp:cellAddr colAddr="0" rowAddr="0"/>'
            '<hp:cellSpan colSpan="2" rowSpan="1"/><hp:cellSz/><hp:cellMargin/></hp:tc>'
            '<hp:tc><hp:subList><hp:p><hp:t>C</hp:t></hp:p></hp:subList>'
            '<hp:cellAddr colAddr="0" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz/><hp:cellMargin/></hp:tc>'
            '</hp:tr>'
            '<hp:tr>'
            '<hp:tc><hp:subList><hp:p><hp:t>D</hp:t></hp:p></hp:subList>'
            '<hp:cellAddr colAddr="0" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz/><hp:cellMargin/></hp:tc>'
            '<hp:tc><hp:subList><hp:p><hp:t>E</hp:t></hp:p></hp:subList>'
            '<hp:cellAddr colAddr="0" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz/><hp:cellMargin/></hp:tc>'
            '<hp:tc><hp:subList><hp:p><hp:t>F</hp:t></hp:p></hp:subList>'
            '<hp:cellAddr colAddr="0" rowAddr="0"/>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz/><hp:cellMargin/></hp:tc>'
            '</hp:tr>'
            '</hp:tbl>'
        )
        fixed = table_fixer.fix_table(tbl)
        import re
        addrs = re.findall(
            r'<hp:cellAddr colAddr="(\d+)" rowAddr="(\d+)"', fixed)
        self.assertEqual(addrs, [
            ('0', '0'), ('2', '0'),              # Row 0: AB at 0 (cs=2), C at 2
            ('0', '1'), ('1', '1'), ('2', '1'),  # Row 1: D, E, F
        ])


# ============================================================================
# Page number presence test
# ============================================================================

class TestPageNumberPresence(unittest.TestCase):
    """Verify generated HWPX contains <hp:pageNum> in body section."""

    def test_body_section_has_page_number(self):
        """Generated body section XML must contain bottom-center page number."""
        import tempfile, zipfile
        from scripts.generate_hwpx import generate_hwpx

        config = {
            'title': 'Page Number Test',
            'date': '2026.01.01.',
            'department': 'Test',
            'sections': [{
                'type': 'body',
                'title': 'Section',
                'content': [{'type': 'paragraph', 'text': 'Test.'}]
            }]
        }
        out = tempfile.mktemp(suffix='.hwpx')
        template = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'assets', 'template.hwpx')
        try:
            generate_hwpx(config, out, template_path=template)
            with zipfile.ZipFile(out, 'r') as z:
                xml = z.read('Contents/section0.xml').decode('utf-8')
            self.assertIn('<hp:pageNum pos="BOTTOM_CENTER"', xml)
        finally:
            if os.path.exists(out):
                os.unlink(out)


if __name__ == '__main__':
    unittest.main()
