#!/usr/bin/env python3
"""
Shared XML parsing helpers for HWPX modules.

All parsers work on raw XML strings using manual depth tracking.
No etree serialization is ever performed.

Safety:
  - CDATA sections are skipped (depth counters frozen inside)
  - XML comments are skipped (depth counters frozen inside)
  - All tag matching verifies next-char is space/>/slash to avoid
    matching partial tag names (e.g. <hp:paraShape vs <hp:p)
"""

import bisect
import re
from xml.etree import ElementTree as ET


# ============================================================================
# Input Validation (read-only — never serializes)
# ============================================================================

def validate_wellformed(xml_string):
    """Validate that XML string is well-formed using stdlib parser.

    This is a READ-ONLY validation pass. It uses ET.fromstring() to verify
    the XML is parseable, but NEVER calls ET.tostring(). The raw string
    is always used for actual operations.

    Args:
        xml_string: Raw XML string to validate.

    Returns:
        True if well-formed.

    Raises:
        ValueError: If XML is malformed, with details about the error.
    """
    try:
        ET.fromstring(xml_string)
        return True
    except ET.ParseError as e:
        raise ValueError(f"Malformed XML input: {e}") from e


def check_for_unclosed_constructs(xml_string):
    """Check for unclosed or malformed CDATA sections and XML comments.

    Detects two categories of problems:

    1. **Unclosed constructs**: A valid ``<![CDATA[`` or ``<!--`` opener
       with no matching closer.  The parser's ``_skip_cdata()`` /
       ``_skip_comment()`` handle these safely (skip to end of string),
       but they cause silent element loss.

    2. **Partial/malformed openers**: Sequences like ``<![CDAT`` or
       ``<!-`` that resemble CDATA/comment openers but are truncated or
       corrupted.  The parser's ``_skip_non_tag()`` does NOT recognise
       these — it treats them as ordinary ``<`` characters.  This is
       harmless in well-formed XML but may indicate file corruption.

    Use this BEFORE parsing to detect truncation risk.  If issues are
    found, the parse results may be incomplete or unreliable.

    Args:
        xml_string: Raw XML string to check.

    Returns:
        List of dicts with keys:
          - 'type': 'CDATA', 'comment', 'partial_CDATA', or
            'partial_comment'
          - 'position': byte offset where the construct starts
        Empty list means no issues found.
    """
    issues = []
    # closed_ranges: sorted list of (start, end) for properly closed
    # CDATA/comment constructs — built in the first pass, reused in the
    # second pass via bisect for O(log n) per-query lookup.
    closed_ranges = []
    # closed_starts: parallel list of start positions for bisect lookup.
    closed_starts = []
    pos = 0
    xml_len = len(xml_string)

    while pos < xml_len:
        # Find earliest CDATA or comment opener
        cdata_pos = xml_string.find('<![CDATA[', pos)
        comment_pos = xml_string.find('<!--', pos)

        # No more openers
        if cdata_pos == -1 and comment_pos == -1:
            break

        # Process whichever comes first
        if cdata_pos != -1 and (comment_pos == -1 or cdata_pos < comment_pos):
            end = xml_string.find(']]>', cdata_pos + 9)
            if end == -1:
                issues.append({'type': 'CDATA', 'position': cdata_pos})
                break  # rest of string is inside unclosed CDATA
            closed_ranges.append((cdata_pos, end + 3))
            closed_starts.append(cdata_pos)
            pos = end + 3
        else:
            end = xml_string.find('-->', comment_pos + 4)
            if end == -1:
                issues.append({'type': 'comment', 'position': comment_pos})
                break  # rest of string is inside unclosed comment
            closed_ranges.append((comment_pos, end + 3))
            closed_starts.append(comment_pos)
            pos = end + 3

    # Second pass: detect partial/malformed openers that _skip_non_tag
    # does NOT recognise.  These are <![...  sequences that don't form a
    # full <![CDATA[ opener or a valid XML conditional section keyword
    # (INCLUDE, IGNORE), and <!- without a second -.
    _PARTIAL_CDATA = re.compile(r'<!\[(?!CDATA\[|INCLUDE\[|IGNORE\[)')
    _PARTIAL_COMMENT = re.compile(r'<!-(?!-)')

    for pattern, issue_type in [(_PARTIAL_CDATA, 'partial_CDATA'),
                                (_PARTIAL_COMMENT, 'partial_comment')]:
        for m in pattern.finditer(xml_string):
            match_pos = m.start()
            # Skip matches that fall inside an unclosed CDATA/comment
            inside = False
            for issue in issues:
                if issue['type'] in ('CDATA', 'comment') and match_pos > issue['position']:
                    inside = True
                    break
            if not inside:
                # O(log n) check against precomputed closed ranges
                if not _is_inside_closed_ranges(closed_starts, closed_ranges, match_pos):
                    issues.append({'type': issue_type, 'position': match_pos})

    # Sort by position for deterministic output
    issues.sort(key=lambda x: x['position'])
    return issues


def _is_inside_closed_ranges(closed_starts, closed_ranges, target_pos):
    """Check if target_pos falls inside any precomputed closed CDATA/comment range.

    Uses bisect for O(log n) lookup instead of rescanning the XML string.

    Args:
        closed_starts: Sorted list of start positions (parallel to closed_ranges).
        closed_ranges: Sorted list of (start, end) tuples for closed constructs.
        target_pos: Position to check.

    Returns:
        True if target_pos is inside any closed range.
    """
    if not closed_starts:
        return False
    # Find the rightmost range whose start <= target_pos
    idx = bisect.bisect_right(closed_starts, target_pos) - 1
    if idx < 0:
        return False
    start, end = closed_ranges[idx]
    return start <= target_pos < end


# ============================================================================
# Safe Position Skipping
# ============================================================================

def _skip_cdata(xml, pos):
    """If pos is at start of a CDATA section, return position after it.

    Returns pos unchanged if not at a CDATA start.
    If CDATA is opened but never closed, returns len(xml) to skip to end —
    this prevents the parser from matching tag-like content inside the
    unclosed CDATA section.
    """
    if xml[pos:pos + 9] == '<![CDATA[':
        end = xml.find(']]>', pos + 9)
        if end != -1:
            return end + 3
        # Unclosed CDATA — treat rest of string as CDATA to be safe
        return len(xml)
    return pos


def _skip_comment(xml, pos):
    """If pos is at start of an XML comment, return position after it.

    Returns pos unchanged if not at a comment start.
    If comment is opened but never closed, returns len(xml) to skip to end —
    same rationale as _skip_cdata.
    """
    if xml[pos:pos + 4] == '<!--':
        end = xml.find('-->', pos + 4)
        if end != -1:
            return end + 3
        # Unclosed comment — treat rest of string as comment to be safe
        return len(xml)
    return pos


def _skip_non_tag(xml, pos):
    """Skip CDATA sections and XML comments at current position.

    Returns new position (may be unchanged if not at CDATA/comment).
    """
    new_pos = _skip_cdata(xml, pos)
    if new_pos != pos:
        return new_pos
    return _skip_comment(xml, pos)


def _skip_section_header(xml):
    """Return byte offset past the ``<hs:sec ...>`` header, or 0 if absent.

    Scanning the section header is unnecessary — it contains only namespace
    declarations and attributes, never child elements like ``<hp:p>`` or
    ``<hp:tbl>``.  Skipping it is defense-in-depth: ``_find_elements``
    already validates tag boundaries, but stripping the header eliminates
    any theoretical false match from namespace URIs.

    The search skips over CDATA sections and XML comments so that a
    ``<hs:sec`` inside a comment is not mistaken for the real header.
    The closing ``>`` search is quote-aware so that ``>`` inside attribute
    values (legal in XML) does not cause a premature split.

    Returns 0 (scan from the start) if ``<hs:sec`` is not found, so this
    is safe to call on any XML fragment.
    """
    xml_len = len(xml)
    pos = 0
    # Phase 1: find '<hs:sec' that is NOT inside a CDATA/comment
    while pos < xml_len:
        new_pos = _skip_non_tag(xml, pos)
        if new_pos != pos:
            pos = new_pos
            continue
        new_pos = _advance_to_lt(xml, pos, xml_len)
        if new_pos != pos:
            pos = new_pos
            continue
        if xml[pos:pos + 7] == '<hs:sec':
            nc = pos + 7
            if nc < xml_len and xml[nc] in (' ', '>'):
                break  # found the real <hs:sec tag
            pos = nc
            continue
        pos += 1
    else:
        return 0  # no <hs:sec found

    # Phase 2: find the closing '>' of this opening tag, skipping
    # '>' characters that appear inside quoted attribute values.
    i = pos + 7  # skip past '<hs:sec'
    while i < xml_len:
        ch = xml[i]
        if ch == '>':
            return i + 1
        if ch in ('"', "'"):
            # Skip to matching close quote
            close = xml.find(ch, i + 1)
            if close == -1:
                return 0  # malformed — unclosed quote, bail out
            i = close + 1
            continue
        i += 1

    return 0  # no closing '>' found


def _advance_to_lt(xml, pos, xml_len):
    """If pos is not at '<', jump forward to the next '<' via str.find().

    Returns pos unchanged if already at '<'. Returns xml_len if no '<' found.
    This avoids character-by-character Python iteration over text content
    between tags, delegating the scan to C-level str.find().
    """
    if pos < xml_len and xml[pos] != '<':
        next_lt = xml.find('<', pos)
        return next_lt if next_lt != -1 else xml_len
    return pos


def find_top_level_paragraphs(section_xml):
    """Find all top-level <hp:p> elements in section XML.

    Uses depth tracking to correctly skip nested <hp:p> inside table cells.
    Skips CDATA sections and XML comments.

    Automatically skips past the ``<hs:sec ...>`` header (if present) so
    the search is scoped to the section body.  Returned offsets are
    relative to the original ``section_xml`` string.

    Args:
        section_xml: Raw XML string (full section or body fragment).

    Returns:
        List of (start, end) tuples — byte offsets into section_xml.
    """
    body_start = _skip_section_header(section_xml)
    body = section_xml[body_start:]
    return [(s + body_start, e + body_start)
            for s, e in _find_elements(body, '<hp:p', '</hp:p>')]


def find_tables(section_xml):
    """Find all top-level <hp:tbl> elements in section XML.

    Automatically skips past the ``<hs:sec ...>`` header (if present) so
    the search is scoped to the section body.  Returned offsets are
    relative to the original ``section_xml`` string, so callers can use
    them directly for substring replacement.

    Args:
        section_xml: Raw XML string (full section or body fragment).

    Returns:
        List of (start, end, xml) tuples where start/end are byte offsets
        into section_xml and xml is section_xml[start:end].
    """
    body_start = _skip_section_header(section_xml)
    body = section_xml[body_start:]
    results = []
    for s, e in _find_elements(body, '<hp:tbl', '</hp:tbl>'):
        results.append((s + body_start, e + body_start, body[s:e]))
    return results


def find_direct_rows(table_xml):
    """Find direct <hp:tr> children of a table (not nested in sub-tables).

    Skips CDATA sections and XML comments. Uses _advance_to_lt() to skip
    past non-tag text content.

    Args:
        table_xml: Raw XML string of a single <hp:tbl>...</hp:tbl>.

    Returns:
        List of (start, end) tuples relative to table_xml.
    """
    rows = []
    tbl_depth = 0
    pos = 0
    xml_len = len(table_xml)

    while pos < xml_len:
        # Skip CDATA and comments
        new_pos = _skip_non_tag(table_xml, pos)
        if new_pos != pos:
            pos = new_pos
            continue
        # Skip text content; re-enter loop so _skip_non_tag checks new pos
        new_pos = _advance_to_lt(table_xml, pos, xml_len)
        if new_pos != pos:
            pos = new_pos
            continue
        if table_xml[pos:pos + 7] == '<hp:tbl':
            nc = pos + 7
            if nc < xml_len and table_xml[nc] in (' ', '>'):
                tbl_depth += 1
            pos += 7
            continue
        if table_xml[pos:pos + 10] == '</hp:tbl>':
            tbl_depth -= 1
            pos += 10
            continue
        if tbl_depth == 1 and table_xml[pos:pos + 6] == '<hp:tr':
            nc = pos + 6
            if nc < xml_len and table_xml[nc] in (' ', '>'):
                tr_start = pos
                tr_end = _find_matching_close(table_xml, pos, '<hp:tr', '</hp:tr>')
                if tr_end != -1:
                    rows.append((tr_start, tr_end))
                    pos = tr_end
                    continue
        pos += 1

    return rows


def find_direct_cells(row_xml):
    """Find direct <hp:tc> children of a table row.

    Uses depth tracking to handle nested tables inside cells.
    Skips CDATA sections and XML comments. Uses _advance_to_lt() to skip
    past non-tag text content.

    Args:
        row_xml: Raw XML string of a single <hp:tr>...</hp:tr>.

    Returns:
        List of (start, end) tuples relative to row_xml.
    """
    cells = []
    tc_depth = 0
    tbl_depth = 0  # track nested tables to skip their cells
    pos = 0
    xml_len = len(row_xml)

    while pos < xml_len:
        # Skip CDATA and comments
        new_pos = _skip_non_tag(row_xml, pos)
        if new_pos != pos:
            pos = new_pos
            continue
        # Skip text content; re-enter loop so _skip_non_tag checks new pos
        new_pos = _advance_to_lt(row_xml, pos, xml_len)
        if new_pos != pos:
            pos = new_pos
            continue
        # Track nested tables
        if row_xml[pos:pos + 7] == '<hp:tbl':
            nc = pos + 7
            if nc < xml_len and row_xml[nc] in (' ', '>'):
                tbl_depth += 1
            pos += 7
            continue
        if row_xml[pos:pos + 10] == '</hp:tbl>':
            tbl_depth -= 1
            pos += 10
            continue
        # Only match cells at the row level (no nested tables)
        if tbl_depth == 0 and row_xml[pos:pos + 6] == '<hp:tc':
            nc = pos + 6
            if nc < xml_len and row_xml[nc] in (' ', '>'):
                tc_start = pos
                tc_end = _find_matching_close(row_xml, pos, '<hp:tc', '</hp:tc>')
                if tc_end != -1:
                    cells.append((tc_start, tc_end))
                    pos = tc_end
                    continue
        pos += 1

    return cells


def count_direct_rows(table_xml):
    """Count direct <hp:tr> children of a table."""
    return len(find_direct_rows(table_xml))


def find_first_row(table_xml):
    """Find the first direct <hp:tr> in a table.

    Args:
        table_xml: Raw XML string of a <hp:tbl>.

    Returns:
        Row XML string, or None if not found.
    """
    rows = find_direct_rows(table_xml)
    if not rows:
        return None
    start, end = rows[0]
    return table_xml[start:end]


# ============================================================================
# Internal helpers
# ============================================================================

def _find_cdata_or_comment_in_range(xml, start, end):
    """Check if a CDATA section or XML comment exists in xml[start:end].

    Uses C-level str.find() for O(n) performance instead of character-by-
    character Python scanning. Returns the position AFTER the CDATA/comment
    if one is found that overlaps or spans past `end`, or None if the range
    is clean.

    Args:
        xml: Full XML string.
        start: Start of range to check.
        end: End of range to check (exclusive).

    Returns:
        Position after the CDATA/comment if found, or None.
    """
    search_pos = start
    while search_pos < end:
        # Find earliest CDATA or comment opener in the range
        cdata_pos = xml.find('<![CDATA[', search_pos, end)
        comment_pos = xml.find('<!--', search_pos, end)

        # No CDATA or comment in range — clean
        if cdata_pos == -1 and comment_pos == -1:
            return None

        # Pick whichever comes first
        if cdata_pos == -1:
            found_pos = comment_pos
        elif comment_pos == -1:
            found_pos = cdata_pos
        else:
            found_pos = min(cdata_pos, comment_pos)

        # Use _skip_non_tag to find the end of this CDATA/comment
        after = _skip_non_tag(xml, found_pos)
        if after > end:
            # The CDATA/comment spans past our candidate tag — skip past it
            return after
        # The CDATA/comment ends before our candidate — continue searching
        search_pos = after

    return None


def _find_elements(xml, open_prefix, close_tag):
    """Find top-level elements matching open_prefix/close_tag with depth tracking.

    Skips CDATA sections and XML comments to prevent false tag matches.

    Args:
        xml: Raw XML string.
        open_prefix: Opening tag prefix (e.g. '<hp:p').
        close_tag: Full closing tag (e.g. '</hp:p>').

    Returns:
        List of (start, end) tuples.
    """
    results = []
    pos = 0
    prefix_len = len(open_prefix)

    while pos < len(xml):
        # Skip CDATA and comments at current position
        new_pos = _skip_non_tag(xml, pos)
        if new_pos != pos:
            pos = new_pos
            continue
        start = xml.find(open_prefix, pos)
        if start == -1:
            break
        # Check if there's a CDATA/comment between pos and start.
        # Uses str.find (C-level) instead of character-by-character scan.
        skip_target = _find_cdata_or_comment_in_range(xml, pos, start)
        if skip_target is not None:
            pos = skip_target
            continue

        next_idx = start + prefix_len
        if next_idx < len(xml) and xml[next_idx] not in (' ', '>', '/'):
            pos = next_idx
            continue

        end = _find_matching_close(xml, start, open_prefix, close_tag)
        if end == -1:
            break
        results.append((start, end))
        pos = end

    return results


def _find_matching_close(xml, start, open_prefix, close_tag):
    """Find matching close tag from start position using depth tracking.

    Skips CDATA sections and XML comments. Uses _advance_to_lt() to skip
    past non-tag text content between tags.

    Returns end offset (position after close_tag), or -1 if not found.
    """
    depth = 0
    prefix_len = len(open_prefix)
    close_len = len(close_tag)
    xml_len = len(xml)
    i = start

    while i < xml_len:
        # Skip CDATA and comments
        new_i = _skip_non_tag(xml, i)
        if new_i != i:
            i = new_i
            continue

        # Skip text content between tags; re-enter loop so _skip_non_tag
        # can check the new position (it may land on a CDATA/comment opener)
        new_i = _advance_to_lt(xml, i, xml_len)
        if new_i != i:
            i = new_i
            continue

        if xml[i:i + prefix_len] == open_prefix:
            nc = i + prefix_len
            if nc < xml_len and xml[nc] in (' ', '>', '/'):
                depth += 1
            i += prefix_len
            continue
        if xml[i:i + close_len] == close_tag:
            depth -= 1
            if depth == 0:
                return i + close_len
            i += close_len
            continue
        i += 1

    return -1
