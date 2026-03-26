# CHANGELOG

## [0.6.0] - 2026-03-26

### Template Update & Adaptive Section Detection

Updated `template.hwpx` to a new 2-section layout (body + appendix, no separate cover)
and refactored all section detection logic to work with both old and new templates.

---

### New Template Structure

- **Old template**: 3 sections — section0 (cover), section1 (body), section2 (appendix)
- **New template**: 2 sections — section0 (body), section1 (appendix)
- Updated `default_styles.json` with new style IDs auto-discovered from the template
- Updated `sample_report.json` to set `include_cover: false` for the new template

### Adaptive Section Detection (`_detect_template_sections`)

Added `_detect_template_sections()` helper that identifies body and appendix sections
by structural analysis rather than hardcoded file names:

- **Body section**: detected by highest `styleIDRef="15"` count (□ heading markers)
- **Appendix section**: detected by `colPr` + 1×3 table (appendix bar), excluding body
- **Cover section**: detected by absence of `styleIDRef="15"` headings
- Replaces fragile `colPr`-only detection that failed when cover sections also had `colPr`
- Backward compatible with old 3-section templates

### Single-Run Date Line Support

`inject_body_date()` now handles templates where the date line uses a single `<hp:run>`
(all text in one charPrIDRef) instead of the legacy multi-run format. Falls through to
multi-run path when 2+ unique charPrIDRefs are found.

### Dynamic Image Manifest

`generate_content_hpf()` now accepts an `image_files` list and generates manifest entries
for all images found in `BinData/`, instead of hardcoding `image1.png` + `image2.jpg`.

### Appendix Spacer Detection

Appendix skeleton extraction now validates spacer paragraphs (must be empty, no tables)
instead of blindly taking the next paragraph after the appendix bar. Generates a spacer
when the template doesn't include one.

---

## [0.5.0] - 2026-03-20

### Adversarial Self-Review Round 4: Three Fixes

Fourth adversarial review of the v0.4.0 fixes revealed three remaining vulnerabilities
in `_parser.py`. Each was proven with executable probes before the fix was applied.

---

### Fix 1: `_skip_section_header` Naive String Search — Two Failure Modes

**Vulnerability**: `_skip_section_header()` used `xml.index('<hs:sec')` to find the
section tag and `xml.index('>', sec_idx)` to find its closing bracket. This has two
failure modes:

- **`>` inside attribute values**: `>` is legal inside XML attribute values without
  escaping. Given `<hs:sec attr="val>ue">`, the function splits at `val>` instead of
  the real closing bracket. All downstream offsets from `find_tables()` and
  `find_top_level_paragraphs()` are wrong — callers doing substring replacement
  corrupt the XML.

- **`<hs:sec` inside CDATA/comments**: `xml.index('<hs:sec')` finds the *first*
  occurrence, including matches inside comments or CDATA. Given
  `<!-- <hs:sec fake> --><hs:sec real>`, it matches the one inside the comment.

**Proof (v0.4.0)**:
```python
xml = '<hs:sec attr="value>with>angles"><hp:p>hello</hp:p></hs:sec>'
_skip_section_header(xml)
# → offset=20, header='<hs:sec attr="value>'  ← WRONG, split inside attribute

xml2 = '<!-- <hs:sec fake> --><hs:sec real><hp:p>hi</hp:p></hs:sec>'
_skip_section_header(xml2)
# → offset=19, header='<!-- <hs:sec fake>'    ← WRONG, matched inside comment
```

**Fix**: Rewrote `_skip_section_header()` in two phases:

1. **Phase 1**: Walk forward using `_skip_non_tag()` and `_advance_to_lt()` to find
   `<hs:sec` that is NOT inside a CDATA section or XML comment.
2. **Phase 2**: Walk through the tag's attributes with quote tracking (`"` and `'`)
   to find the real closing `>`, skipping `>` characters inside quoted values.

**After fix**: Both failure scenarios return correct offsets. Normal case (no tricky
attributes) is unaffected.

**Files Changed**: `scripts/_parser.py` (`_skip_section_header`)

---

### Fix 2: Partial CDATA Regex False Positives on Valid XML Conditional Sections

**Vulnerability**: `check_for_unclosed_constructs()` used the regex
`r'<!\[(?!CDATA\[)'` to detect partial/malformed CDATA openers. This matches
`<![INCLUDE[` and `<![IGNORE[` — valid XML DTD conditional sections defined in the
XML specification. The function's docstring claimed these indicate "file corruption"
when they are legitimate markup.

**Proof (v0.4.0)**:
```python
xml = '<root><![INCLUDE[<hp:p>included</hp:p>]]></root>'
check_for_unclosed_constructs(xml)
# → [{'type': 'partial_CDATA', 'position': 6}]  ← FALSE POSITIVE
```

**Fix**: Updated the regex to `r'<!\[(?!CDATA\[|INCLUDE\[|IGNORE\[)'` — excludes
the two standard XML conditional section keywords. Genuine corruption like `<![FOO`
is still caught.

**After fix**: `<![INCLUDE[` and `<![IGNORE[` produce no issues. `<![FOO` still
produces `partial_CDATA`.

**Files Changed**: `scripts/_parser.py` (`check_for_unclosed_constructs`)

---

### Fix 3: `_is_inside_closed_construct` O(n×m) Rescanning Replaced with O(n + m log n) Bisect

**Vulnerability**: For each partial match found by the regex in the second pass,
`_is_inside_closed_construct()` rescanned the entire XML string from position 0
through every CDATA/comment to check if the match fell inside one. With `k` closed
constructs and `m` partial matches, this is O(k × m) total work — quadratic.

The irony: the first pass already walks every CDATA/comment and knows their
positions. That information was discarded, then re-derived from scratch for every
regex match.

**Proof (v0.4.0)**:
```python
# 10k CDATAs + 10k partial openers
many_cdata = ''.join(f'<![CDATA[data{i}]]>' for i in range(10000))
many_partial = ''.join(f'<![FOO{i}]' for i in range(10000))
check_for_unclosed_constructs(many_cdata + many_partial)
# → O(n*m) — each partial triggers a full rescan from position 0
```

**Fix**: Three changes:

1. The first pass now builds `closed_ranges` (sorted list of `(start, end)` tuples)
   and `closed_starts` (parallel list of start positions) as it discovers each
   properly closed CDATA/comment.

2. Deleted `_is_inside_closed_construct()` entirely.

3. Added `_is_inside_closed_ranges(closed_starts, closed_ranges, target_pos)` which
   uses `bisect.bisect_right` for O(log n) per-query lookup against the precomputed
   ranges.

**After fix**: Total complexity is O(n + m log k) where n is string length, m is
partial match count, and k is closed construct count. The 10k+10k benchmark runs
in the same time envelope as before for small inputs, but scales correctly.

**Files Changed**: `scripts/_parser.py` (`check_for_unclosed_constructs`, `_is_inside_closed_ranges`, removed `_is_inside_closed_construct`)

---

### Test Coverage Summary

| Test Group | Count | Status |
|---|---|---|
| Fix 1: `_skip_section_header` (5 patterns: `>` in attrs, `<hs:sec` in comment, `<hs:sec` in CDATA, absent, normal) | 5 | ✅ new |
| Fix 2: Conditional section exclusion (`INCLUDE`, `IGNORE`, genuine partial) | 3 | ✅ new |
| Fix 3: Bisect correctness (partial inside/outside closed CDATA) + perf (10k+10k) | 3 | ✅ new |
| Existing regression suite | 21 | ✅ pass |
| **Total** | **32** | |

---

## [0.4.0] - 2026-03-19

### Adversarial Self-Review Round 3: Three Fixes

Third adversarial review of the v0.3.0 fixes revealed three remaining vulnerabilities.
Each was proven with executable probes before the fix was applied.

---

### Fix 1: Nested Table `cellSpan` Regex Matched Wrong Element

**Vulnerability**: `_extract_col_span()` used `re.search()` across the entire cell XML.
When a cell contained a nested table, `re.search` returned the *first* match — the
nested table's `<hp:cellSpan>` element — not the outer cell's own metadata.

**Proof (v0.3.0)**:
```python
# Outer cell has colSpan=2, inner nested table cell has colSpan=1
cell = '<hp:tc><hp:subList>...<hp:cellSpan colSpan="1"/>...</hp:subList>'
       '<hp:cellSpan colSpan="2"/></hp:tc>'
_extract_col_span(cell)  # → 1 (WRONG — matched inner, not outer)
```

**Fix**: Added `_extract_cell_metadata_suffix(cell_xml)` that extracts only the
portion after the last `</hp:subList>`. Updated `_extract_col_span()` and new
`_extract_row_span()` to search only in this suffix. Graceful fallback: if no
`</hp:subList>` exists, searches the full cell (backwards-compatible).

**After fix**: Returns 2 — the outer cell's own colSpan value.

**Files Changed**: `scripts/table_fixer.py` (`_extract_cell_metadata_suffix`, `_extract_col_span`, `_extract_row_span`)

---

### Fix 2: `rowSpan` Not Tracked — Wrong `colAddr` in Subsequent Rows

**Vulnerability**: `fix_table()` and `validate_table()` only considered `colSpan` when
computing `colAddr`. A cell with `rowSpan=2` in row 0 occupies columns in row 1, but
row 1's cells were assigned `colAddr` values starting from 0, ignoring the occupied columns.

**Proof (v0.3.0)**:
```
Grid (colCnt=3):
┌─────┬─────┬─────┐
│  A  │  B  │  C  │   Row 0: A(rowSpan=2), B, C
│(rs2)│     │     │
├─────┼─────┼─────┤
│     │  D  │  E  │   Row 1: should be colAddr=1,2
└─────┴─────┴─────┘

v0.3.0 output:  Row 1: colAddr=0, colAddr=1   ← WRONG
Expected:       Row 1: colAddr=1, colAddr=2   ← skip occupied col 0
```

**Fix**: Added `_build_occupied_set(rows_addrs, row_idx)` that computes which columns
are occupied by `rowSpan` cells from previous rows. Both `fix_table()` and
`validate_table()` now skip occupied columns when computing `colAddr`:

```python
occupied = _build_occupied_set(rows_addrs, row_idx)
logical_col = 0
for cell in row_addrs:
    while logical_col in occupied:
        logical_col += 1   # skip columns reserved by rowSpan above
    cell.colAddr = logical_col
    logical_col += cell.colSpan
```

The occupation grid is self-consistent: it recomputes correct `colAddr` for all
previous rows from scratch (since the XML values may be wrong), avoiding circular
dependencies on incorrect data.

**After fix**: Row 1: `colAddr=1, colAddr=2` — correct.

Also updated `_extract_cell_addrs_by_row()` to return 6-tuples including `rowSpan`:
`(colAddr, rowAddr, colSpan, rowSpan, abs_start, abs_end)`.

**Files Changed**: `scripts/table_fixer.py` (`_build_occupied_set`, `_extract_cell_addrs_by_row`, `validate_table`, `fix_table`)

---

### Fix 3: Silent Element Loss from Unclosed CDATA/Comment

**Vulnerability**: When `_skip_cdata()` encounters an unclosed `<![CDATA[` section,
it returns `len(xml)` — correctly preventing phantom element matches, but silently
causing the parser to produce fewer elements than exist. Callers have no signal that
elements were lost vs. genuinely absent.

**Proof (v0.3.0)**:
```python
xml = '<root>'
      '<hp:p><hp:t><![CDATA[unclosed</hp:t></hp:p>'
      '<hp:p><hp:t>second</hp:t></hp:p>'
      '<hp:p><hp:t>third</hp:t></hp:p>'
      '</root>'
find_top_level_paragraphs(xml)
# → 0 paragraphs (SILENT — should be 3, 0 with warning)
```

**Fix**: Added `check_for_unclosed_constructs(xml_string)` to `_parser.py`. This is
a standalone guard function that callers use *before* parsing to detect truncation risk.
Returns a list of `{'type': 'CDATA'|'comment', 'position': int}` for each unclosed
construct found. Empty list means safe to parse.

Design choice: a standalone function rather than modifying parser return types preserves
the simple `List[tuple]` API (Open/Closed principle).

**After fix**: Callers can detect truncation:
```python
issues = check_for_unclosed_constructs(xml)
if issues:
    # Handle: warn user, skip file, raise error
```

**Files Changed**: `scripts/_parser.py` (`check_for_unclosed_constructs`)

---

### Test Coverage Summary

| Test Group | Count | Status |
|---|---|---|
| Fix 1: Nested cellSpan suffix extraction (4 patterns) | 4 | ✅ new |
| Fix 2: rowSpan occupation grid (8 patterns) | 8 | ✅ new |
| Fix 3: Unclosed construct detection (7 patterns) | 7 | ✅ new |
| Integration: fix_all_tables with rowSpan | 1 | ✅ new |
| colSpan-only regression | 1 | ✅ new |
| **Total** | **21** | |

Template validation: all 3 sections pass (section0.xml pre-existing `rowAddr` error auto-fixed).

---

## [0.3.0] - 2026-03-19

### Adversarial Self-Review Round 2: Three Fixes

Second adversarial review of the v0.2.0 fixes revealed three remaining vulnerabilities.
Each was proven with executable probes before the fix was applied.

---

### Fix 1: Unclosed CDATA/Comment Falls Through Silently

**Vulnerability**: `_skip_cdata()` returned `pos` unchanged when `]]>` was not found.
The parser then scanned into the unclosed CDATA content, matching tag-like strings
as real elements — producing phantom paragraphs.

**Proof (v0.2.0)**:
```python
xml = '<hp:p><hp:t><![CDATA[</hp:p><hp:p>fake</hp:p>x</hp:t></hp:p>'
find_top_level_paragraphs(xml)
# → Found 2 paragraphs (WRONG — "fake" is inside CDATA)
```

**Fix**: When `<![CDATA[` is opened but `]]>` never found, return `len(xml)` instead
of `pos`. This treats everything after the unclosed opener as CDATA content, preventing
any tag matches inside it. Same fix applied to `_skip_comment()`.

**After fix**: `find_top_level_paragraphs()` returns 0 paragraphs — the unclosed CDATA
makes the entire remainder unparseable. Callers should use `validate_wellformed()` to
detect this condition before parsing.

**Files Changed**: `scripts/_parser.py` (`_skip_cdata`, `_skip_comment`)

---

### Fix 2: O(n × g) Scan-Ahead Replaced with O(n) `str.find`

**Vulnerability**: `_find_elements()` had a character-by-character Python loop that
scanned from `pos` to `start` checking every character for `<![CDATA[` or `<!--`.
With large gaps between elements, this was O(gap_size) per element.

**Proof (v0.2.0 performance)**:
```
gap=  100 (  31KB):  0.007s    4.5 MB/s
gap=20000 (6.0MB):   1.289s    4.7 MB/s   ← 1.3 seconds!
```

**Fix**: Replaced the `while scan < start: scan += 1` loop with a new helper
`_find_cdata_or_comment_in_range()` that uses C-level `str.find('<![CDATA[', ...)` and
`str.find('<!--', ...)`. Same correctness, dramatically faster.

**After fix (v0.3.0 performance)**:
```
gap=  100 (  31KB):  0.0004s    77 MB/s
gap=20000 (6.0MB):   0.006s   971 MB/s    ← 200× faster
```

**Files Changed**: `scripts/_parser.py` (`_find_cdata_or_comment_in_range`, `_find_elements`)

---

### Fix 3: colSpan-Aware `colAddr` Assignment

**Vulnerability**: `fix_table()` assigned `colAddr` sequentially (0, 1, 2...) based on
physical cell order within each row. For column-spanning merged cells, `colAddr` should
reflect the logical grid position, not the cell index.

**Proof (v0.2.0)**:
```
Grid (colCnt=3):
┌──────────────┬─────────┐
│  Merged A+B  │    C    │   ← Row 0: 2 <hp:tc>, colSpan=2 on first
│  (colSpan=2) │         │
├─────┬────────┼─────────┤
│  A  │   B    │    C    │   ← Row 1: 3 <hp:tc>
└─────┴────────┴─────────┘

v0.2.0 output:  Row 0: colAddr=0, colAddr=1   ← WRONG (C should be 2)
Expected:       Row 0: colAddr=0, colAddr=2   ← skip over spanned column
```

**Root Cause**: The code enumerated cells as `col_idx` (0, 1, 2...) without reading
`<hp:cellSpan colSpan="N"/>` to know how many grid columns each cell occupies.

**Fix**: Added `_extract_col_span()` helper and changed `_extract_cell_addrs_by_row()`
to return a 5-tuple `(colAddr, rowAddr, colSpan, abs_start, abs_end)`. In `fix_table()`,
replaced:

```python
# OLD: sequential physical index
for col_idx, (old_col, old_row, start, end) in enumerate(row_addrs):
    colAddr = col_idx

# NEW: logical grid position via colSpan accumulation
logical_col = 0
for old_col, old_row, col_span, start, end in row_addrs:
    colAddr = logical_col
    logical_col += col_span   # skip spanned columns
```

**After fix**:
```
Row 0: colAddr=0 (colSpan=2), colAddr=2 (colSpan=1)   ← correct
Row 1: colAddr=0, colAddr=1, colAddr=2                  ← unchanged
```

**Validation also updated**: `validate_table()` now computes expected `colAddr` using
the same colSpan accumulation, detecting mismatches like `colAddr=1` where `colAddr=2`
is expected after a `colSpan=2` cell.

**Bonus finding**: This stricter validator detected a pre-existing `rowAddr` error in
`assets/template.hwpx` (section0.xml, table 1, row 2: `rowAddr="0"` → should be `"2"`).
`fix_all_tables()` corrects it.

**Files Changed**: `scripts/table_fixer.py` (`_extract_col_span`, `_extract_cell_addrs_by_row`, `validate_table`, `fix_table`)

---

### Validation Enforcement at Integration Boundary

Added `validate=True` parameter (default) to `update_section()` and `update_sections()`
in `modify_hwpx.py`. These are the only functions that commit modified XML back to a
ZIP file. With validation enabled:

1. **Input validation**: `validate_wellformed(original)` catches corrupted source files
   before the parser operates on them (prevents CDATA/comment edge cases)
2. **Output validation**: `validate_wellformed(modified)` catches structural errors
   introduced by string surgery before they're written to disk

Both use `ET.fromstring()` (read-only) — never `ET.tostring()`.

Can be disabled with `validate=False` for performance-critical batch operations.

**Files Changed**: `scripts/modify_hwpx.py` (`update_section`, `update_sections`)

---

### Performance Comparison

| Operation | v0.2.0 | v0.3.0 | Improvement |
|---|---|---|---|
| 6MB XML with 50 paragraphs (large gaps) | 1.289s | 0.006s | **215×** |
| 1.5MB XML (medium gaps) | 0.318s | 0.002s | **159×** |
| Compact XML (no gaps) | 0.125s | 0.125s | same |
| Merged cell table fix | ❌ wrong | ✅ correct | bug fix |
| Unclosed CDATA | ❌ phantom | ✅ safe | bug fix |

---

### Test Coverage Summary

| Test Group | Count | Status |
|---|---|---|
| Core functionality (zip, read, templates, modify) | 6 | ✅ |
| Table validation (3 sections) | 3 | ✅ (1 known template error auto-fixed) |
| Fix 1: Unclosed CDATA safety | 3 | ✅ new |
| Fix 2: O(n) performance (2 sizes) | 2 | ✅ new |
| Fix 3: colSpan-aware colAddr (3 patterns) | 3 | ✅ new |
| Validation enforcement | 3 | ✅ new |
| Non-merged regression | 1 | ✅ new |
| **Total** | **21** | |

---

## [0.2.0] - 2026-03-19

### Parser Robustness, Merged Cell Support, Structural Validation

This release addresses three critical vulnerabilities discovered through adversarial self-review of the v0.1.0 module suite. Each vulnerability was identified by examining the assumptions behind the "all tests pass" result and constructing failure scenarios where those assumptions break.

---

### Vulnerability 1: String Parser Fooled by CDATA and Comments

**Root Cause**: The depth-tracking parser in `_parser.py` scanned raw XML character-by-character to match tags like `<hp:tbl>`, `</hp:tbl>`, `<hp:tr>`, etc. It had no awareness of CDATA sections or XML comments. Tag-like strings inside these constructs would corrupt depth counters.

**Example Failure**:
```xml
<!-- This comment contains </hp:p> which would decrement depth -->
<hp:t><![CDATA[fake </hp:tbl> closing tag]]></hp:t>
```

Both constructs would cause the parser to miscount element depth, producing wrong paragraph/table/cell boundaries.

**Fix**: Added three skip functions to `_parser.py`:

| Function | Purpose |
|---|---|
| `_skip_cdata(xml, pos)` | If `pos` is at `<![CDATA[`, jump past `]]>` |
| `_skip_comment(xml, pos)` | If `pos` is at `<!--`, jump past `-->` |
| `_skip_non_tag(xml, pos)` | Dispatch to both, called before every tag match |

All depth-tracking loops (`_find_elements`, `_find_matching_close`, `find_direct_rows`, `find_direct_cells`) now call `_skip_non_tag()` before evaluating potential tag matches. Depth counters are frozen while traversing CDATA/comment content.

**Files Changed**: `scripts/_parser.py`

**Tests Added**:
- `<![CDATA[fake </hp:p> tag]]>` inside a paragraph — parser still finds exactly 1 paragraph
- `<!-- </hp:p> -->` inside a paragraph — parser still finds exactly 1 paragraph
- `<![CDATA[</hp:tbl> </hp:tr>]]>` inside a table cell — parser still finds 1 table, 1 row, 1 cell

---

### Vulnerability 2: Flat Cell Counter Breaks on Merged Cells

**Root Cause**: `table_fixer.fix_table()` used a flat counter to assign `cellAddr` values across the entire table:

```python
# OLD (broken for merged cells):
current_row = 0
current_col = 0
for col_addr, row_addr, start, end in addrs:  # flat iteration
    # assign colAddr=current_col, rowAddr=current_row
    current_col += 1
    if current_col >= col_cnt:  # wrap to next row
        current_col = 0
        current_row += 1
```

This assumed every row contains exactly `colCnt` cells. With merged cells (colspan), a row may have fewer `<hp:tc>` elements than `colCnt`. The counter would fail to wrap at the row boundary, cascading wrong addresses to all subsequent cells.

**Example Failure**:
```
┌──────────────┬─────────┐
│  Merged A+B  │    C    │   ← Row 0: 2 cells (colCnt=3, but merged)
├─────┬────────┼─────────┤
│  A  │   B    │    C    │   ← Row 1: 3 cells
└─────┴────────┴─────────┘

Old output:  (0,0) (1,0) (2,0) (3,1) (4,1)  ← wrong from cell 3
Correct:     (0,0) (1,0) (0,1) (1,1) (2,1)  ← colAddr resets per row
```

**Fix**: Replaced `_extract_cell_addrs()` (flat iteration) with `_extract_cell_addrs_by_row()` (per-row iteration):

```python
# NEW (correct for merged cells):
rows_addrs = _extract_cell_addrs_by_row(result)  # list of lists
for row_idx, row_addrs in enumerate(rows_addrs):
    for col_idx, (old_col, old_row, start, end) in enumerate(row_addrs):
        # assign colAddr=col_idx, rowAddr=row_idx
```

The new function uses `_parser.find_direct_rows()` and `_parser.find_direct_cells()` (with depth tracking) to discover actual row boundaries, then numbers cells independently within each row.

`validate_table()` was also updated to use per-row validation: it now checks `rowAddr == row_idx` (exact match) instead of the old `0 <= rowAddr < actual_rows` (range check).

**Files Changed**: `scripts/table_fixer.py`

**Tests Added**:
- Merged cell table (row 0: 2 cells, row 1: 3 cells, `colCnt=3`) — produces correct `[(0,0),(1,0),(0,1),(1,1),(2,1)]`
- Nested table (outer cell contains inner `<hp:tbl>`) — outer cells fixed, inner table's `cellAddr` untouched

**Bonus Finding**: The improved per-row validator detected a real inconsistency in `assets/template.hwpx` that the old validator missed: Table 1 in section0.xml had Row 2 with `rowAddr="0"` instead of `rowAddr="2"`. The old range-check (`0 <= 0 < 6`) passed; the new exact-match (`0 != 2`) correctly flags it. `fix_all_tables()` repairs it.

---

### Vulnerability 3: No Structural Validation of Modified XML

**Root Cause**: All integration tests verified output by re-reading it with the same Python parser that wrote it. This is a circular validation — bugs in the parser mask bugs in the writer. There was no independent check that modified XML was structurally valid.

**Mitigation**: Added `validate_wellformed()` to `_parser.py` and `validate_output()` to `modify_hwpx.py`. Both use `ET.fromstring()` as a read-only well-formedness check. The key architectural distinction:

| Operation | Tool | Allowed? |
|---|---|---|
| Parse input for analysis | `ET.fromstring()` | Yes (read-only) |
| Validate output structure | `ET.fromstring()` | Yes (read-only) |
| Serialize modified XML | `ET.tostring()` | **Never** (Rule 9) |

This catches mismatched tags, broken attributes, and other structural errors introduced by string surgery — without violating the byte-preservation constraint.

**Remaining Limitation**: Well-formedness validation does not guarantee Hancom Office acceptance. Semantic rules (valid `paraPrIDRef` references, correct `<hp:secPr>` placement, etc.) can only be validated by opening the file in Hancom Office. This is documented as a known limitation.

**Files Changed**: `scripts/_parser.py`, `scripts/modify_hwpx.py`

**Tests Added**:
- `validate_wellformed()` accepts valid XML, raises `ValueError` on malformed XML
- `validate_output()` exposed through `modify_hwpx` module interface

---

### New Shared Module: `_parser.py`

Extracted from duplicated code across `read_hwpx.py`, `modify_hwpx.py`, `xml_templates.py`, and `table_fixer.py`. Eliminates ~300 lines of duplicated depth-tracking parser code.

**Public API**:
| Function | Purpose |
|---|---|
| `validate_wellformed(xml)` | Read-only XML well-formedness check |
| `find_top_level_paragraphs(xml)` | Top-level `<hp:p>` elements with depth tracking |
| `find_tables(xml)` | Top-level `<hp:tbl>` elements |
| `find_direct_rows(table_xml)` | Direct `<hp:tr>` children (skips nested tables) |
| `find_direct_cells(row_xml)` | Direct `<hp:tc>` children (skips nested tables) |
| `count_direct_rows(table_xml)` | Count of direct `<hp:tr>` children |
| `find_first_row(table_xml)` | XML of the first `<hp:tr>` |

All functions skip CDATA sections and XML comments.

---

### Test Coverage Summary

| Test Group | Count | Description |
|---|---|---|
| zip_handler round-trip | 1 | 15 entries, compress_type preserved |
| read_hwpx parsing | 1 | 3 sections, 5 tables, 59 charPr, 31 paraPr |
| table_fixer validation | 3 | All sections validated (1 pre-existing error found and fixable) |
| **Merged cell fix** | 1 | 2-cell row + 3-cell row → correct per-row addressing |
| **CDATA safety** | 3 | Fake tags in CDATA/comments ignored by parser |
| **Well-formedness** | 2 | Valid XML accepted, malformed rejected |
| **Nested table fix** | 1 | Outer cells fixed, inner table untouched |
| xml_templates | 1 | Paragraph template extract + render |
| modify_hwpx ops | 1 | Insert + delete paragraphs |
| ZIP integrity | 1 | Full write/read cycle with compress_type verification |
| **Total** | **15** | |

---

### Architecture Insight

The three vulnerabilities shared a common pattern — **testing your own decoder**:

```
Writer produces output → Reader (same codebase) validates → "Pass" ✓
                         ↑                                       ↑
                         Same bugs in both                 False confidence
```

The fixes break this cycle at three levels:

1. **Parser level**: CDATA/comment skipping prevents the parser from being fooled by content it should ignore
2. **Logic level**: Per-row cell iteration prevents the fixer from making assumptions about table structure
3. **Structural level**: `ET.fromstring()` provides an independent validator orthogonal to the string-surgery parser

Full external validation (opening in Hancom Office) remains a manual step documented as a known limitation.
