#!/usr/bin/env python3
"""
Byte-Preserving HWPX Editor.

Modifies HWPX file content while preserving original XML byte formatting.
All edits use str.replace() or regex on raw XML bytes — never DOM serialization.

CONSTRAINT: etree.tostring() is NEVER used. All modifications are string
operations on the original XML bytes. This prevents Hancom Office from
detecting the file as corrupted due to XML reformatting.

VALIDATION: After modifications, validate_output() can be called to verify
the result is still well-formed XML. This uses ET.fromstring() (read-only)
and never serializes.
"""

import re
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from . import zip_handler
from . import table_fixer
from . import xml_templates
from . import _parser


# ============================================================================
# Output Validation
# ============================================================================

def validate_output(section_bytes):
    """Validate that modified section XML is still well-formed.

    This is a safety net that catches structural XML errors introduced
    by string surgery (mismatched tags, broken attributes, etc.).
    Uses ET.fromstring() — read-only, never serializes.

    Args:
        section_bytes: Raw XML string after modification.

    Returns:
        True if well-formed.

    Raises:
        ValueError: If XML is malformed, with details.
    """
    return _parser.validate_wellformed(section_bytes)


# ============================================================================
# Text Replacement
# ============================================================================

def replace_text(section_bytes, old_text, new_text, max_count=0):
    """Replace text content within <hp:t> tags, preserving XML structure.

    Only replaces text inside <hp:t>old_text</hp:t> patterns.
    Does NOT touch XML tags, attributes, or structure.

    Args:
        section_bytes: Raw XML string of a section.
        old_text: Raw text to find (not XML-escaped — escaping is handled
            internally). For example, pass 'A & B' not 'A &amp; B'.
        new_text: Replacement text (will be XML-escaped).
        max_count: Max replacements (0 = unlimited).

    Returns:
        Modified XML string.
    """
    escaped_new = xml_escape(new_text)
    escaped_old = re.escape(xml_escape(old_text))

    pattern = re.compile(r'(<hp:t>)(' + escaped_old + r')(</hp:t>)')
    if max_count > 0:
        return pattern.sub(rf'\g<1>{escaped_new}\3', section_bytes, count=max_count)
    return pattern.sub(rf'\g<1>{escaped_new}\3', section_bytes)


def replace_text_in_cell(section_bytes, row_addr, col_addr, new_text,
                          table_index=0):
    """Replace text in a specific table cell identified by row/col address.

    Handles both attribute orderings in cellAddr (colAddr/rowAddr and
    rowAddr/colAddr).

    Args:
        section_bytes: Raw XML string.
        row_addr: Target row address (0-based).
        col_addr: Target column address (0-based).
        new_text: New text content.
        table_index: Which table (0-based) if section has multiple.

    Returns:
        Modified XML string, or original if cell not found.
    """
    tables = _parser.find_tables(section_bytes)
    if table_index >= len(tables):
        return section_bytes

    tbl_start, tbl_end, tbl_xml = tables[table_index]

    # Find all direct rows, then cells within each row
    rows = _parser.find_direct_rows(tbl_xml)

    for row_start, row_end in rows:
        row_xml = tbl_xml[row_start:row_end]
        cells = _parser.find_direct_cells(row_xml)

        for cell_start, cell_end in cells:
            cell_xml = row_xml[cell_start:cell_end]

            # Match cellAddr with either attribute order
            addr_m = re.search(
                rf'<hp:cellAddr\s+(?:'
                rf'colAddr="{col_addr}"\s+rowAddr="{row_addr}"'
                rf'|rowAddr="{row_addr}"\s+colAddr="{col_addr}")',
                cell_xml)
            if not addr_m:
                continue

            # Found the target cell — replace first <hp:t> content
            new_cell = re.sub(
                r'<hp:t>[^<]*</hp:t>',
                f'<hp:t>{xml_escape(new_text)}</hp:t>',
                cell_xml, count=1)

            if new_cell != cell_xml:
                # Reconstruct: cell offsets are relative to row, row to table
                new_row = row_xml[:cell_start] + new_cell + row_xml[cell_end:]
                new_tbl = tbl_xml[:row_start] + new_row + tbl_xml[row_end:]
                return section_bytes[:tbl_start] + new_tbl + section_bytes[tbl_end:]

    return section_bytes


# ============================================================================
# Paragraph Operations
# ============================================================================

def insert_paragraph_after(section_bytes, anchor_index, new_para_xml):
    """Insert a new paragraph after the paragraph at anchor_index.

    Args:
        section_bytes: Raw XML string of a section.
        anchor_index: 0-based index of the paragraph after which to insert.
        new_para_xml: Complete <hp:p>...</hp:p> XML string to insert.

    Returns:
        Modified XML string, or original if anchor not found.
    """
    paragraphs = _parser.find_top_level_paragraphs(section_bytes)
    if anchor_index >= len(paragraphs):
        return section_bytes

    _, anchor_end = paragraphs[anchor_index]
    return section_bytes[:anchor_end] + new_para_xml + section_bytes[anchor_end:]


def insert_paragraph_before(section_bytes, anchor_index, new_para_xml):
    """Insert a new paragraph before the paragraph at anchor_index.

    Args:
        section_bytes: Raw XML string of a section.
        anchor_index: 0-based index of the paragraph before which to insert.
        new_para_xml: Complete <hp:p>...</hp:p> XML string.

    Returns:
        Modified XML string, or original if anchor not found.
    """
    paragraphs = _parser.find_top_level_paragraphs(section_bytes)
    if anchor_index >= len(paragraphs):
        return section_bytes

    anchor_start, _ = paragraphs[anchor_index]
    return section_bytes[:anchor_start] + new_para_xml + section_bytes[anchor_start:]


def delete_paragraph(section_bytes, para_index):
    """Delete a paragraph by index.

    Args:
        section_bytes: Raw XML string.
        para_index: 0-based index of the paragraph to remove.

    Returns:
        Modified XML string, or original if index out of range.
    """
    paragraphs = _parser.find_top_level_paragraphs(section_bytes)
    if para_index >= len(paragraphs):
        return section_bytes

    start, end = paragraphs[para_index]
    return section_bytes[:start] + section_bytes[end:]


def replace_paragraph(section_bytes, para_index, new_para_xml):
    """Replace a paragraph at the given index.

    Args:
        section_bytes: Raw XML string.
        para_index: 0-based index of the paragraph to replace.
        new_para_xml: Replacement <hp:p>...</hp:p> XML.

    Returns:
        Modified XML string, or original if index out of range.
    """
    paragraphs = _parser.find_top_level_paragraphs(section_bytes)
    if para_index >= len(paragraphs):
        return section_bytes

    start, end = paragraphs[para_index]
    return section_bytes[:start] + new_para_xml + section_bytes[end:]


# ============================================================================
# Table Row Operations
# ============================================================================

def insert_table_row(section_bytes, table_index, row_xml, position=-1):
    """Insert a new row into a table.

    Args:
        section_bytes: Raw XML string.
        table_index: 0-based table index in the section.
        row_xml: Complete <hp:tr>...</hp:tr> XML string.
        position: Row position (0-based, -1 = append at end).

    Returns:
        Modified XML string with table_fixer applied automatically.
    """
    tables = _parser.find_tables(section_bytes)
    if table_index >= len(tables):
        return section_bytes

    tbl_start, tbl_end, tbl_xml = tables[table_index]

    if position == -1:
        close_pos = tbl_xml.rfind('</hp:tbl>')
        if close_pos == -1:
            return section_bytes
        new_tbl = tbl_xml[:close_pos] + row_xml + tbl_xml[close_pos:]
    else:
        rows = _parser.find_direct_rows(tbl_xml)
        if position >= len(rows):
            close_pos = tbl_xml.rfind('</hp:tbl>')
            new_tbl = tbl_xml[:close_pos] + row_xml + tbl_xml[close_pos:]
        else:
            row_start, _ = rows[position]
            new_tbl = tbl_xml[:row_start] + row_xml + tbl_xml[row_start:]

    # Auto-fix table consistency
    new_tbl = table_fixer.fix_table(new_tbl)

    return section_bytes[:tbl_start] + new_tbl + section_bytes[tbl_end:]


def delete_table_row(section_bytes, table_index, row_index):
    """Delete a row from a table.

    Args:
        section_bytes: Raw XML string.
        table_index: 0-based table index.
        row_index: 0-based row index to delete.

    Returns:
        Modified XML string with table_fixer applied.
    """
    tables = _parser.find_tables(section_bytes)
    if table_index >= len(tables):
        return section_bytes

    tbl_start, tbl_end, tbl_xml = tables[table_index]
    rows = _parser.find_direct_rows(tbl_xml)

    if row_index >= len(rows):
        return section_bytes

    row_start, row_end = rows[row_index]
    new_tbl = tbl_xml[:row_start] + tbl_xml[row_end:]

    # Auto-fix table consistency
    new_tbl = table_fixer.fix_table(new_tbl)

    return section_bytes[:tbl_start] + new_tbl + section_bytes[tbl_end:]


# ============================================================================
# Section-Level Operations
# ============================================================================

def update_section(hwpx_path, section_name, modifier_fn, output_path=None,
                    validate=True):
    """Apply a modifier function to a section and repackage the HWPX.

    The modifier function receives the raw XML string and returns
    the modified XML string. It should use only string operations.

    Args:
        hwpx_path: Path to the source .hwpx file.
        section_name: Entry name (e.g. 'Contents/section1.xml').
        modifier_fn: Callable(xml_string) -> modified_xml_string.
        output_path: Output path (defaults to overwriting hwpx_path).
        validate: If True (default), validates both input and output XML
            are well-formed. Catches malformed input before parsing and
            structural errors introduced by string surgery.

    Returns:
        Path to the output file.

    Raises:
        KeyError: If section_name is not found in the archive.
        ValueError: If validate=True and input or output XML is malformed.
    """
    hwpx_path = Path(hwpx_path)
    if output_path is None:
        output_path = hwpx_path
    output_path = Path(output_path)

    info = zip_handler.read_hwpx_zip(hwpx_path)
    original = info.get_text(section_name)
    if original is None:
        raise KeyError(f"Section '{section_name}' not found in {hwpx_path}")

    if validate:
        _parser.validate_wellformed(original)

    modified = modifier_fn(original)

    if validate:
        _parser.validate_wellformed(modified)

    info.set_text(section_name, modified)
    zip_handler.write_hwpx_zip(info, output_path)

    return output_path


def update_sections(hwpx_path, modifications, output_path=None, validate=True):
    """Apply multiple section modifications in a single repackage.

    Args:
        hwpx_path: Path to the source .hwpx file.
        modifications: Dict of {section_name: modifier_fn}.
        output_path: Output path (defaults to overwriting hwpx_path).
        validate: If True (default), validates input and output XML
            for each section.

    Raises:
        KeyError: If any section_name is not found in the archive.
        ValueError: If validate=True and any input or output XML is malformed.

    Returns:
        Path to the output file.
    """
    hwpx_path = Path(hwpx_path)
    if output_path is None:
        output_path = hwpx_path
    output_path = Path(output_path)

    info = zip_handler.read_hwpx_zip(hwpx_path)

    for section_name, modifier_fn in modifications.items():
        original = info.get_text(section_name)
        if original is None:
            raise KeyError(f"Section '{section_name}' not found in {hwpx_path}")
        if validate:
            _parser.validate_wellformed(original)
        modified = modifier_fn(original)
        if validate:
            _parser.validate_wellformed(modified)
        info.set_text(section_name, modified)

    zip_handler.write_hwpx_zip(info, output_path)
    return output_path


# ============================================================================
# Convenience: Template-Based Insertion
# ============================================================================

def insert_paragraph_from_template(section_bytes, anchor_index, template_index,
                                    text, charPrIDRef=None, paraPrIDRef=None):
    """Extract a paragraph template and insert a new paragraph after anchor.

    Combines xml_templates.extract_paragraph_template() with
    insert_paragraph_after() for a single-call workflow.

    Args:
        section_bytes: Raw XML string.
        anchor_index: Insert after this paragraph index.
        template_index: Index of the paragraph to use as template.
        text: Text for the new paragraph.
        charPrIDRef: Optional charPrIDRef override.
        paraPrIDRef: Optional paraPrIDRef override.

    Returns:
        Modified XML string, or original if template extraction fails.
    """
    tmpl = xml_templates.extract_paragraph_template(section_bytes, template_index)
    if tmpl is None:
        return section_bytes

    new_para = xml_templates.render_paragraph(
        tmpl['template'], text,
        charPrIDRef=charPrIDRef or tmpl['charPrIDRef'],
        paraPrIDRef=paraPrIDRef or tmpl['paraPrIDRef'])

    return insert_paragraph_after(section_bytes, anchor_index, new_para)


def insert_table_row_from_template(section_bytes, table_index, row_data,
                                    position=-1, use_header=False):
    """Extract a row template from an existing table and insert a new row.

    Args:
        section_bytes: Raw XML string.
        table_index: Which table to modify.
        row_data: List of cell text values.
        position: Row position (-1 = append).
        use_header: If True, use header cell template; else use body cell.

    Returns:
        Modified XML string.
    """
    tmpl = xml_templates.extract_table_template(section_bytes, table_index)
    if tmpl is None:
        return section_bytes

    cell_tmpl = tmpl['header_cell'] if use_header else tmpl['body_cell']
    if cell_tmpl is None:
        return section_bytes

    # Determine row_addr based on current row count
    tables = _parser.find_tables(section_bytes)
    if table_index >= len(tables):
        return section_bytes

    _, _, tbl_xml = tables[table_index]
    existing_rows = _parser.count_direct_rows(tbl_xml)
    row_addr = existing_rows if position == -1 else position

    row_xml = xml_templates.render_table_row(
        cell_tmpl, row_data, row_addr, tmpl['col_count'])

    return insert_table_row(section_bytes, table_index, row_xml, position)
