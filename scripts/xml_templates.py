#!/usr/bin/env python3
"""
XML Template Extraction & String Substitution for HWPX files.

Extracts XML patterns from existing HWPX content to use as templates,
then renders new elements by string substitution. This ensures generated
XML exactly matches the original format (whitespace, attribute order, etc.).

CONSTRAINT: etree.tostring() is NEVER used. Templates are raw strings,
and rendering uses str.format() / str.replace() for value injection.
"""

import re
from xml.sax.saxutils import escape as xml_escape

from . import _parser


# ============================================================================
# Paragraph Templates
# ============================================================================

def extract_paragraph_template(section_bytes, para_index=0):
    """Extract a paragraph from section XML as a reusable template.

    Finds the paragraph at the given index and replaces its text content,
    charPrIDRef, and paraPrIDRef with placeholders.

    Args:
        section_bytes: Raw XML string of a section.
        para_index: 0-based index of the paragraph to extract.

    Returns:
        dict with:
          'raw': original paragraph XML
          'template': paragraph XML with placeholders:
            {TEXT} — text content
            {CHAR_PR_ID} — charPrIDRef of the main run
            {PARA_PR_ID} — paraPrIDRef of the paragraph
          'charPrIDRef': original charPrIDRef
          'paraPrIDRef': original paraPrIDRef
        Returns None if paragraph not found.
    """
    paragraphs = _parser.find_top_level_paragraphs(section_bytes)
    if para_index >= len(paragraphs):
        return None

    start, end = paragraphs[para_index]
    raw = section_bytes[start:end]

    para_pr_m = re.search(r'paraPrIDRef="(\d+)"', raw)
    char_pr_m = re.search(r'charPrIDRef="(\d+)"', raw)
    para_pr = para_pr_m.group(1) if para_pr_m else '0'
    char_pr = char_pr_m.group(1) if char_pr_m else '0'

    template = raw
    template = re.sub(r'<hp:t>[^<]*</hp:t>', '<hp:t>{TEXT}</hp:t>', template, count=1)
    template = re.sub(r'(paraPrIDRef=")' + re.escape(para_pr) + '"',
                      r'\g<1>{PARA_PR_ID}"', template, count=1)
    template = re.sub(r'(charPrIDRef=")' + re.escape(char_pr) + '"',
                      r'\g<1>{CHAR_PR_ID}"', template, count=1)

    return {
        'raw': raw,
        'template': template,
        'charPrIDRef': char_pr,
        'paraPrIDRef': para_pr,
    }


def extract_paragraph_by_pattern(section_bytes, text_pattern):
    """Extract the first paragraph containing text matching a regex pattern.

    Args:
        section_bytes: Raw XML string of a section.
        text_pattern: Regex pattern to match against <hp:t> content.

    Returns:
        Same dict as extract_paragraph_template, or None if not found.
    """
    paragraphs = _parser.find_top_level_paragraphs(section_bytes)
    compiled = re.compile(text_pattern)

    for idx, (start, end) in enumerate(paragraphs):
        para_xml = section_bytes[start:end]
        texts = re.findall(r'<hp:t>([^<]*)</hp:t>', para_xml)
        if any(compiled.search(t) for t in texts):
            return extract_paragraph_template(section_bytes, idx)

    return None


def render_paragraph(template, text, charPrIDRef=None, paraPrIDRef=None):
    """Render a paragraph template with given values.

    Args:
        template: Template string with {TEXT}, {CHAR_PR_ID}, {PARA_PR_ID}.
        text: Text content (will be XML-escaped).
        charPrIDRef: Optional charPrIDRef override.
        paraPrIDRef: Optional paraPrIDRef override.

    Returns:
        Rendered XML string.
    """
    result = template
    result = result.replace('{TEXT}', xml_escape(text))
    if charPrIDRef is not None:
        result = result.replace('{CHAR_PR_ID}', str(charPrIDRef))
    if paraPrIDRef is not None:
        result = result.replace('{PARA_PR_ID}', str(paraPrIDRef))
    return result


# ============================================================================
# Table Templates
# ============================================================================

def extract_table_template(section_bytes, table_index=0):
    """Extract a table from section XML as a reusable template.

    Creates templates for:
      - The table wrapper (with row/column count placeholders)
      - A header cell template
      - A body cell template

    Args:
        section_bytes: Raw XML string of a section.
        table_index: 0-based index of the table to extract.

    Returns:
        dict with:
          'raw': original table XML
          'header_cell': template for a header row cell
          'body_cell': template for a body row cell
          'table_open': table opening tag with {ROW_CNT}, {COL_CNT} placeholders
          'table_close': table closing elements
          'col_count': original column count
          'row_count': original row count
        Returns None if table not found.
    """
    tables = _parser.find_tables(section_bytes)
    if table_index >= len(tables):
        return None

    start, end, tbl_xml = tables[table_index]

    row_m = re.search(r'rowCnt="(\d+)"', tbl_xml)
    col_m = re.search(r'colCnt="(\d+)"', tbl_xml)
    row_cnt = int(row_m.group(1)) if row_m else 0
    col_cnt = int(col_m.group(1)) if col_m else 0

    # Extract table opening (everything before first <hp:tr>)
    rows = _parser.find_direct_rows(tbl_xml)
    if not rows:
        return None
    tr_start = rows[0][0]

    table_open = tbl_xml[:tr_start]
    table_open = re.sub(r'rowCnt="\d+"', 'rowCnt="{ROW_CNT}"', table_open)
    table_open = re.sub(r'colCnt="\d+"', 'colCnt="{COL_CNT}"', table_open)

    # First row = header template
    header_row_xml = tbl_xml[rows[0][0]:rows[0][1]]
    header_cell = _extract_first_cell_template(header_row_xml)

    # Second row = body template (fallback to header)
    body_cell = None
    if len(rows) > 1:
        body_row_xml = tbl_xml[rows[1][0]:rows[1][1]]
        body_cell = _extract_first_cell_template(body_row_xml)
    if body_cell is None:
        body_cell = header_cell

    return {
        'raw': tbl_xml,
        'header_cell': header_cell,
        'body_cell': body_cell,
        'table_open': table_open,
        'table_close': '</hp:tbl>',
        'col_count': col_cnt,
        'row_count': row_cnt,
    }


def render_table_row(cell_template, cells, row_addr, col_count=None):
    """Render a table row from a cell template and cell data.

    Args:
        cell_template: Cell template string with placeholders.
        cells: List of text values for each cell.
        row_addr: Row address (0-based).
        col_count: Number of columns (defaults to len(cells)).

    Returns:
        Rendered <hp:tr>...</hp:tr> XML string.
    """
    if col_count is None:
        col_count = len(cells)

    row_cells = ''
    for col_idx, text in enumerate(cells):
        cell = cell_template
        cell = cell.replace('{TEXT}', xml_escape(str(text)))
        cell = cell.replace('{COL_ADDR}', str(col_idx))
        cell = cell.replace('{ROW_ADDR}', str(row_addr))
        row_cells += cell

    return f'<hp:tr>{row_cells}</hp:tr>'


def render_table(table_template, headers, rows):
    """Render a complete table from a template.

    Args:
        table_template: Dict from extract_table_template().
        headers: List of header cell text values.
        rows: List of lists of body cell text values.

    Returns:
        Rendered table XML string.
    """
    total_rows = 1 + len(rows)
    col_count = len(headers)

    table_open = table_template['table_open']
    table_open = table_open.replace('{ROW_CNT}', str(total_rows))
    table_open = table_open.replace('{COL_CNT}', str(col_count))

    header_html = render_table_row(
        table_template['header_cell'], headers, 0, col_count)

    body_html = ''
    for r_idx, row in enumerate(rows):
        body_html += render_table_row(
            table_template['body_cell'], row, r_idx + 1, col_count)

    return table_open + header_html + body_html + table_template['table_close']


# ============================================================================
# Run Templates
# ============================================================================

def extract_run_template(paragraph_xml, run_index=0):
    """Extract a <hp:run> element as a template.

    Args:
        paragraph_xml: Raw XML of a paragraph.
        run_index: 0-based index of the run to extract.

    Returns:
        dict with 'raw', 'template' (with {TEXT}, {CHAR_PR_ID}), 'charPrIDRef'.
        Returns None if not found.
    """
    runs = list(re.finditer(
        r'(<hp:run\s+charPrIDRef="(\d+)"[^>]*>)(.*?)(</hp:run>)',
        paragraph_xml, re.DOTALL))

    if run_index >= len(runs):
        return None

    m = runs[run_index]
    raw = m.group(0)
    char_pr = m.group(2)

    template = raw
    template = re.sub(r'<hp:t>[^<]*</hp:t>', '<hp:t>{TEXT}</hp:t>', template, count=1)
    template = re.sub(r'(charPrIDRef=")' + re.escape(char_pr) + '"',
                      r'\g<1>{CHAR_PR_ID}"', template, count=1)

    return {
        'raw': raw,
        'template': template,
        'charPrIDRef': char_pr,
    }


def render_run(template, text, charPrIDRef=None):
    """Render a run template.

    Args:
        template: Template string with {TEXT}, {CHAR_PR_ID}.
        text: Text content (will be XML-escaped).
        charPrIDRef: Optional override.

    Returns:
        Rendered XML string.
    """
    result = template
    result = result.replace('{TEXT}', xml_escape(text))
    if charPrIDRef is not None:
        result = result.replace('{CHAR_PR_ID}', str(charPrIDRef))
    return result


# ============================================================================
# Internal Helpers
# ============================================================================

def _extract_first_cell_template(row_xml):
    """Extract the first <hp:tc> from a row as a template.

    Uses depth-tracking to correctly handle cells containing nested tables.
    Replaces text, colAddr, and rowAddr with placeholders.
    """
    cells = _parser.find_direct_cells(row_xml)
    if not cells:
        return None

    start, end = cells[0]
    cell = row_xml[start:end]

    # Replace text
    cell = re.sub(r'<hp:t>[^<]*</hp:t>', '<hp:t>{TEXT}</hp:t>', cell, count=1)
    # Replace colAddr (handle both attribute orderings)
    cell = re.sub(r'(colAddr=")(\d+)(")', r'\g<1>{COL_ADDR}\3', cell, count=1)
    # Replace rowAddr
    cell = re.sub(r'(rowAddr=")(\d+)(")', r'\g<1>{ROW_ADDR}\3', cell, count=1)

    return cell
