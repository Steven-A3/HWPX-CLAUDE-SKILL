#!/usr/bin/env python3
"""
Table Consistency Validator & Auto-Fixer for HWPX files.

Validates and fixes rowCnt/cellAddr/rowAddr attributes in HWPX table XML.
Hancom Office rejects files where these values are inconsistent.

All operations work on raw XML bytes (strings) — no etree serialization.
Modifications use regex substitution to preserve original XML formatting.

Validation Rules:
  - rowCnt == actual count of <hp:tr> elements
  - rowAddr == row_idx (0-based)
  - colAddr == logical grid column (0-based), accounting for:
    - colSpan: each cell occupies colSpan columns horizontally
    - rowSpan: cells from earlier rows with rowSpan > 1 occupy columns
      in subsequent rows, which must be skipped
"""

import re

from . import _parser


class TableValidationError:
    """A single validation error in a table."""
    __slots__ = ('table_index', 'field', 'expected', 'actual', 'context')

    def __init__(self, table_index, field, expected, actual, context=''):
        self.table_index = table_index
        self.field = field
        self.expected = expected
        self.actual = actual
        self.context = context

    def __repr__(self):
        return (f"TableValidationError(table={self.table_index}, "
                f"{self.field}: expected={self.expected}, actual={self.actual}"
                f"{', ' + self.context if self.context else ''})")


def _extract_col_count(table_xml):
    """Extract colCnt from table attributes."""
    m = re.search(r'colCnt="(\d+)"', table_xml)
    return int(m.group(1)) if m else None


def _extract_row_count_attr(table_xml):
    """Extract rowCnt from table attributes."""
    m = re.search(r'rowCnt="(\d+)"', table_xml)
    return int(m.group(1)) if m else None


def _extract_cell_metadata_suffix(cell_xml):
    """Extract the metadata suffix of a cell (after the last </hp:subList>).

    In HWPX, each <hp:tc> has this structure:
      <hp:tc ...>
        <hp:subList>...content (may include nested tables)...</hp:subList>
        <hp:cellAddr .../> ← metadata suffix starts here
        <hp:cellSpan .../>
        <hp:cellSz .../>
        <hp:cellMargin .../>
      </hp:tc>

    By extracting only the suffix after the last </hp:subList>, we avoid
    matching <hp:cellSpan> from nested tables inside the cell content.

    Args:
        cell_xml: Raw XML of a single <hp:tc>...</hp:tc>.

    Returns:
        The metadata suffix string, or the full cell_xml if no
        </hp:subList> is found (graceful fallback).
    """
    last_sublist_close = cell_xml.rfind('</hp:subList>')
    if last_sublist_close != -1:
        return cell_xml[last_sublist_close:]
    return cell_xml


def _extract_col_span(cell_xml):
    """Extract colSpan value from a cell's <hp:cellSpan> element.

    In HWPX, every <hp:tc> contains <hp:cellSpan colSpan="N" rowSpan="M"/>.
    Non-merged cells have colSpan="1". Merged cells have colSpan > 1,
    indicating how many logical grid columns the cell spans.

    Searches only in the cell's metadata suffix (after the last
    </hp:subList>) to avoid matching nested tables' cellSpan elements.

    Args:
        cell_xml: Raw XML string of a single <hp:tc>...</hp:tc>.

    Returns:
        Integer colSpan value (defaults to 1 if not found).
    """
    suffix = _extract_cell_metadata_suffix(cell_xml)
    m = re.search(r'<hp:cellSpan\b[^/]*colSpan="(\d+)"', suffix)
    return int(m.group(1)) if m else 1


def _extract_row_span(cell_xml):
    """Extract rowSpan value from a cell's <hp:cellSpan> element.

    Searches only in the cell's metadata suffix to avoid nested tables.

    Args:
        cell_xml: Raw XML string of a single <hp:tc>...</hp:tc>.

    Returns:
        Integer rowSpan value (defaults to 1 if not found).
    """
    suffix = _extract_cell_metadata_suffix(cell_xml)
    m = re.search(r'<hp:cellSpan\b[^/]*rowSpan="(\d+)"', suffix)
    return int(m.group(1)) if m else 1


def _extract_cell_addrs_by_row(table_xml):
    """Extract cellAddr elements grouped by row from a table.

    Uses _parser.find_direct_rows() and _parser.find_direct_cells() for
    proper depth tracking, which correctly handles:
      - Nested tables (cells within sub-tables are skipped)
      - Merged cells (rows with fewer cells than colCnt)
      - Both attribute orderings (colAddr/rowAddr and rowAddr/colAddr)

    Returns list of lists: one list per row, each containing
    (colAddr, rowAddr, colSpan, rowSpan, abs_start, abs_end) tuples where:
      - colAddr, rowAddr: current values in the XML
      - colSpan: number of logical grid columns this cell spans
      - rowSpan: number of logical grid rows this cell spans
      - abs_start, abs_end: offsets relative to table_xml
    """
    rows = _parser.find_direct_rows(table_xml)
    all_row_addrs = []

    for row_start, row_end in rows:
        row_xml = table_xml[row_start:row_end]
        cells = _parser.find_direct_cells(row_xml)
        row_addrs = []

        for cell_start, cell_end in cells:
            cell_xml = row_xml[cell_start:cell_end]
            # Find <hp:cellAddr> within this cell
            m = re.search(r'<hp:cellAddr\s+([^/]*)/>', cell_xml)
            if not m:
                m = re.search(r'<hp:cellAddr\s+([^>]*)>', cell_xml)
            if m:
                fragment = m.group(0)
                col_m = re.search(r'colAddr="(\d+)"', fragment)
                row_m = re.search(r'rowAddr="(\d+)"', fragment)
                if col_m and row_m:
                    # Calculate absolute position in table_xml
                    abs_start = row_start + cell_start + m.start()
                    abs_end = row_start + cell_start + m.end()
                    col_span = _extract_col_span(cell_xml)
                    row_span = _extract_row_span(cell_xml)
                    row_addrs.append((
                        int(col_m.group(1)),
                        int(row_m.group(1)),
                        col_span,
                        row_span,
                        abs_start,
                        abs_end,
                    ))

        all_row_addrs.append(row_addrs)

    return all_row_addrs


def _build_occupied_sets(rows_addrs):
    """Build occupied column sets for ALL rows in a single forward pass.

    Returns a list of sets, one per row.  Each set contains column indices
    occupied by rowSpan cells from previous rows.

    Complexity is O(R * C) overall — call this once and index the result
    rather than computing per-row sets individually.

    Uses the *expected* colAddr (computed with the same occupation logic)
    rather than the XML's current colAddr, so this is self-consistent
    even when the XML values are wrong.

    Args:
        rows_addrs: Output of _extract_cell_addrs_by_row() — list of lists
            of 6-tuples (colAddr, rowAddr, colSpan, rowSpan, abs_start, abs_end).

    Returns:
        List of sets, one per row. occupied_sets[i] is the set of column
        indices occupied by rowSpan cells from rows before i.
    """
    num_rows = len(rows_addrs)
    occupied_sets = [set() for _ in range(num_rows)]

    for prev_idx in range(num_rows):
        occupied = occupied_sets[prev_idx]
        logical_col = 0
        for _, _, col_span, row_span, _, _ in rows_addrs[prev_idx]:
            while logical_col in occupied:
                logical_col += 1
            if row_span > 1:
                for future_row in range(prev_idx + 1, min(prev_idx + row_span, num_rows)):
                    for c in range(logical_col, logical_col + col_span):
                        occupied_sets[future_row].add(c)
            logical_col += col_span

    return occupied_sets


def validate_table(table_xml):
    """Validate a single table's rowCnt, cellAddr, and rowAddr consistency.

    Handles merged cells correctly by validating per-row rather than
    assuming a flat colCnt cells per row. Also accounts for rowSpan:
    cells in subsequent rows must skip columns occupied by rowSpan
    cells from earlier rows.

    Args:
        table_xml: Raw XML string of a single <hp:tbl>...</hp:tbl> element.

    Returns:
        List of TableValidationError objects. Empty list means valid.
    """
    errors = []

    row_cnt_attr = _extract_row_count_attr(table_xml)
    col_cnt = _extract_col_count(table_xml)
    actual_rows = _parser.count_direct_rows(table_xml)

    if row_cnt_attr is not None and row_cnt_attr != actual_rows:
        errors.append(TableValidationError(
            0, 'rowCnt', actual_rows, row_cnt_attr,
            f'colCnt={col_cnt}'))

    if col_cnt is not None:
        rows_addrs = _extract_cell_addrs_by_row(table_xml)
        occupied_sets = _build_occupied_sets(rows_addrs)
        for row_idx, row_addrs in enumerate(rows_addrs):
            occupied = occupied_sets[row_idx]
            logical_col = 0
            for col_addr, row_addr, col_span, row_span, _, _ in row_addrs:
                # Skip columns occupied by rowSpan from above
                while logical_col in occupied:
                    logical_col += 1
                if row_addr != row_idx:
                    errors.append(TableValidationError(
                        0, 'rowAddr', row_idx, row_addr,
                        f'row {row_idx}, colAddr={col_addr}'))
                if col_addr != logical_col:
                    errors.append(TableValidationError(
                        0, 'colAddr', logical_col, col_addr,
                        f'row {row_idx}, rowAddr={row_addr}, '
                        f'colSpan={col_span}, rowSpan={row_span}'))
                logical_col += col_span

    return errors


def fix_table(table_xml):
    """Fix rowCnt, cellAddr, and rowAddr in a single table.

    Recalculates:
      - rowCnt to match actual <hp:tr> count
      - rowAddr to match actual row index (0, 1, 2, ...)
      - colAddr to match logical grid position using colSpan AND rowSpan

    Handles merged cells correctly:
      - colSpan: reads <hp:cellSpan colSpan="N"/> to know how many grid
        columns each cell spans horizontally.
      - rowSpan: reads <hp:cellSpan rowSpan="N"/> to know how many grid
        rows each cell spans vertically. Cells in subsequent rows skip
        columns occupied by rowSpan cells from above.

    Example for colCnt=3 with rowSpan:
      Row 0: Cell A (colSpan=1, rowSpan=2) → colAddr=0
             Cell B (colSpan=2, rowSpan=1) → colAddr=1
      Row 1: Cell C (colSpan=1, rowSpan=1) → colAddr=1  (col 0 occupied by A)
             Cell D (colSpan=1, rowSpan=1) → colAddr=2

    Args:
        table_xml: Raw XML string of a <hp:tbl>...</hp:tbl>.

    Returns:
        Fixed XML string.
    """
    actual_rows = _parser.count_direct_rows(table_xml)
    col_cnt = _extract_col_count(table_xml)
    result = table_xml

    # Fix rowCnt attribute in the outermost <hp:tbl> opening tag only
    # (find the first '>' to limit replacement scope to the opening tag)
    first_close = result.find('>')
    if first_close != -1:
        opening = result[:first_close + 1]
        rest = result[first_close + 1:]
        opening = re.sub(r'(rowCnt=")(\d+)(")', rf'\g<1>{actual_rows}\3', opening, count=1)
        result = opening + rest

    if col_cnt is None:
        return result

    # Fix cellAddr values — use colSpan and rowSpan for grid positions
    rows_addrs = _extract_cell_addrs_by_row(result)
    occupied_sets = _build_occupied_sets(rows_addrs)
    corrections = []

    for row_idx, row_addrs in enumerate(rows_addrs):
        occupied = occupied_sets[row_idx]
        logical_col = 0
        for old_col, old_row, col_span, row_span, start, end in row_addrs:
            # Skip columns occupied by rowSpan from above
            while logical_col in occupied:
                logical_col += 1
            new_fragment = (f'<hp:cellAddr colAddr="{logical_col}" '
                            f'rowAddr="{row_idx}"/>')
            corrections.append((start, end, new_fragment))
            logical_col += col_span

    # Apply corrections in reverse order to preserve offsets
    for start, end, new_fragment in reversed(corrections):
        result = result[:start] + new_fragment + result[end:]

    return result


def validate_all_tables(section_bytes):
    """Validate all tables in a section XML string.

    Args:
        section_bytes: Raw XML string of a complete section.

    Returns:
        List of TableValidationError objects with table_index set.
    """
    tables = _parser.find_tables(section_bytes)
    all_errors = []
    for idx, (start, end, tbl_xml) in enumerate(tables):
        errors = validate_table(tbl_xml)
        for err in errors:
            err.table_index = idx
        all_errors.extend(errors)
    return all_errors


def fix_all_tables(section_bytes):
    """Fix all tables in a section XML string.

    Args:
        section_bytes: Raw XML string of a complete section.

    Returns:
        Fixed XML string with all tables corrected.
    """
    tables = _parser.find_tables(section_bytes)
    if not tables:
        return section_bytes

    result = section_bytes
    for start, end, tbl_xml in reversed(tables):
        fixed = fix_table(tbl_xml)
        if fixed != tbl_xml:
            result = result[:start] + fixed + result[end:]

    return result
