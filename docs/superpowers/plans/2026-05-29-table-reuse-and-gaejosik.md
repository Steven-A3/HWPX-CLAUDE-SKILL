# Template Table Reuse + 개조식 Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generated data tables reuse a real template table's per-cell styling (borders/fonts/alignment) with content-aware column widths; and SKILL.md gains binding 개조식 authoring rules.

**Architecture:** `build_style_map_from_template` builds a `table_profiles` catalog keyed by column count, capturing per-position cell styles (header / first-body / interior-body / last-body) plus the table's total width from a *clean* template table. `data_table_xml` renders by reusing those styles, computing column widths from content within the total width, and regenerating each cell's text + lineseg (Hancom does not recalc lineseg). Column counts with no template match fall back to today's generated table. Part B is SKILL.md docs only.

**Tech Stack:** Python 3 stdlib (`re`, `json`), pytest/unittest, HWPX (zipped XML).

---

## Background facts (verified against the repo)

- `data_table_xml(headers, rows, sm, caption="", table_id=...)` at `scripts/generate_hwpx.py:1694` — currently equal widths, `row_height=2048`, single `bf_table_header`/`bf_table` fill, `total_width=47622`.
- `table_cell_xml(...)` at `:1546` — emits one `<hp:tc>`; computes `nlines` and `lineseg` from `vertsize` and `inner_hz = width - 1022`. Keep for the fallback path.
- `_extract_table_cells(para_xml)` at `:519` — returns per-cell `rowAddr/colAddr/bf/charPrIDRefs/paraPrIDRefs`. Does NOT capture width/margin/valign — Task 2 adds a richer extractor.
- `estimate_text_width(text, char_height)` at `:84` — sums `_char_width`; Korean glyph = full `char_height`.
- `estimate_line_count(text, char_height, horzsize)` at `:116`; `lineseg_xml(...)`, `paragraph_xml(...)`, `run_xml(...)`.
- `build_style_map_from_template` at `:746`; its table discovery (Phase D) sets `table_header`, `table_body`, `bf_table`, `bf_table_header` from the first non-colPr table (`table_wrapper_idx`).
- `DEFAULT_STYLE_MAP` at `:252`.
- Cache: `save_style_map_cache` (`:300`) JSON-dumps the map (tuples→lists, dicts pass through); `load_cached_style_map` (`:281`) converts top-level list values back to tuples and leaves dict values as dicts — so a nested `table_profiles` dict round-trips unchanged. `generate_hwpx` auto-rebuilds + saves the cache when the template hash changes.
- Bundled template fact: a clean 6-col data table has header fills `[85,86,86,86,86,87]` (left-corner/middle/right-corner), first body row `[88,79,79,79,79,51]`, interior `[...,3,...,28]`; header charPr is bold, all cells center-aligned. Template tables size columns to content (a 6-col table is `[4713,6128,10563,8109,13252,5328]`).

## Profile data structure (used across Tasks 2–5)

A `table_profiles` style-map entry is JSON-serializable:

```python
# sm["table_profiles"] = { "<ncols>": profile }
profile = {
    "total_width": 48093,                 # Σ source table column widths
    "cell_margin": {"left":510,"right":510,"top":141,"bottom":141},
    "header_h": 1100,                      # header charPr height
    "body_h":   1150,                      # body charPr height
    "row_h": {"header":2048,"first":2048,"interior":2048,"last":2048},
    "header":   [cell, cell, ...],         # one per column
    "first":    [cell, ...],
    "interior": [cell, ...],
    "last":     [cell, ...],
}
# cell = {"bf":"85","charPr":"136","paraPr":"67","valign":"CENTER"}
```

## File structure

- Modify: `scripts/generate_hwpx.py` — width helper, cell-profile extractor, profile builder + catalog, style-map wiring, profile-driven cell emitter, `data_table_xml` rewrite, `DEFAULT_STYLE_MAP`.
- Regenerate: `assets/default_styles.json`.
- Create: `tests/test_table_reuse.py`.
- Modify: `SKILL.md`, `CHANGELOG.md`.

## Test command

Single: `python3 -m pytest tests/test_table_reuse.py::Class::test -v`
Full: `python3 -m pytest tests/ -q`

---

### Task 1: Content-aware column widths

**Files:**
- Modify: `scripts/generate_hwpx.py` (add `MIN_COL_WIDTH` constant + `_compute_column_widths` near `estimate_text_width`, after `:89`)
- Test: `tests/test_table_reuse.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_table_reuse.py`:

```python
#!/usr/bin/env python3
"""Tests for template table reuse (docs/superpowers/specs/2026-05-29-table-reuse-and-gaejosik-design.md)."""
import os, re, sys, json, zipfile, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import generate_hwpx as G

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(SKILL_DIR, "assets", "template.hwpx")


class TestColumnWidths(unittest.TestCase):
    def test_widths_sum_to_total(self):
        w = G._compute_column_widths(["연도", "구분"], [["2023년", "SW중심대학"]], 1200, 40000)
        self.assertEqual(sum(w), 40000)
        self.assertEqual(len(w), 2)

    def test_long_content_column_is_wider(self):
        w = G._compute_column_widths(
            ["구분", "내용"],
            [["A", "교육생 미선발에 따른 자체 주력사업 부재를 코디세이 사업으로 전환"]],
            1200, 40000)
        self.assertGreater(w[1], w[0])

    def test_min_width_floor(self):
        # many columns, tiny total -> every column still >= MIN_COL_WIDTH
        w = G._compute_column_widths(["a","b","c","d"], [["1","2","3","4"]], 1200, 4000)
        self.assertTrue(all(c >= G.MIN_COL_WIDTH for c in w))

    def test_single_column(self):
        w = G._compute_column_widths(["제목"], [["내용"]], 1200, 47000)
        self.assertEqual(w, [47000])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_table_reuse.py::TestColumnWidths -v`
Expected: FAIL — `_compute_column_widths` / `MIN_COL_WIDTH` not defined.

- [ ] **Step 3: Implement**

In `scripts/generate_hwpx.py`, immediately after `estimate_text_width` (after `:89`), add:

```python
# Minimum table column width (~2 Korean glyphs + L/R cell margins) in HWPUNIT.
MIN_COL_WIDTH = 3000


def _compute_column_widths(headers, rows, char_height, total_width,
                           min_col_width=MIN_COL_WIDTH, h_margin=1020):
    """Compute per-column widths from content, fitted to total_width.

    Width of a column = max rendered text width of its header and body cells
    (plus horizontal cell margins), floored at min_col_width, then scaled so the
    widths sum exactly to total_width. Returns a list of ints (len == #columns).
    """
    n = len(headers)
    if n == 0:
        return []
    intrinsic = []
    for j in range(n):
        texts = [headers[j]] + [str(r[j]) for r in rows if j < len(r)]
        w = max((estimate_text_width(t, char_height) for t in texts), default=0)
        intrinsic.append(max(min_col_width, w + h_margin))
    # Scale to total_width while respecting the floor.
    total_int = sum(intrinsic)
    if total_int <= total_width:
        # distribute slack proportionally to intrinsic width
        slack = total_width - total_int
        widths = [iw + slack * iw // total_int for iw in intrinsic]
    else:
        # scale down proportionally, but never below the floor
        widths = [max(min_col_width, iw * total_width // total_int) for iw in intrinsic]
    # Fix rounding so the sum is exactly total_width (adjust the widest column).
    diff = total_width - sum(widths)
    widest = max(range(n), key=lambda j: widths[j])
    widths[widest] += diff
    return widths
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_table_reuse.py::TestColumnWidths -v`
Expected: 4 passed.

- [ ] **Step 5: Run full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_hwpx.py tests/test_table_reuse.py
git commit -m "feat: content-aware table column width helper"
```

---

### Task 2: Rich table-cell extractor

**Files:**
- Modify: `scripts/generate_hwpx.py` (add `_extract_table_cells_rich` right after `_extract_table_cells` at `:540`)
- Test: `tests/test_table_reuse.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_table_reuse.py`:

```python
class TestRichCellExtractor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        zipfile.ZipFile(TEMPLATE).extractall(self.tmp.name)
        body, _ = G._detect_template_sections(self.tmp.name)
        bx = open(body, encoding="utf-8").read()
        paras, _ = G._extract_all_top_level_paragraphs(bx)
        attrs = [G._extract_para_attrs(p) for p in paras]
        self.tbl = next(paras[i] for i, a in enumerate(attrs)
                        if a['has_tbl'] and not a['has_colpr'])

    def test_rich_cells_have_geometry(self):
        cells = G._extract_table_cells_rich(self.tbl)
        self.assertTrue(cells)
        c = cells[0]
        for k in ("rowAddr", "colAddr", "bf", "charPr", "paraPr", "width", "valign", "margin"):
            self.assertIn(k, c)
        self.assertIsInstance(c["width"], int)
        self.assertEqual(set(c["margin"]), {"left", "right", "top", "bottom"})
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_table_reuse.py::TestRichCellExtractor -v`
Expected: FAIL — `_extract_table_cells_rich` not defined.

- [ ] **Step 3: Implement**

Add after `_extract_table_cells` (after `:540`):

```python
def _extract_table_cells_rich(para_xml):
    """Like _extract_table_cells but also captures cellSz width, vertAlign,
    cellMargin, and the primary charPr/paraPr. Returns list of dicts:
    rowAddr, colAddr, bf, charPr, paraPr, width, height, valign, margin{l,r,t,b}.
    Cells with rowSpan/colSpan > 1 set 'spanned' True.
    """
    cells = []
    for tc_m in re.finditer(r'<hp:tc\b([^>]*)>(.*?)</hp:tc>', para_xml, re.DOTALL):
        attrs, body = tc_m.group(1), tc_m.group(2)
        addr = re.search(r'<hp:cellAddr\s+colAddr="(\d+)"\s+rowAddr="(\d+)"', body)
        bf = re.search(r'borderFillIDRef="(\d+)"', attrs)
        cp = re.search(r'charPrIDRef="(\d+)"', body)
        pp = re.search(r'paraPrIDRef="(\d+)"', body)
        sz = re.search(r'<hp:cellSz\s+width="(\d+)"\s+height="(\d+)"', body)
        va = re.search(r'vertAlign="(\w+)"', body)
        span = re.search(r'<hp:cellSpan\s+colSpan="(\d+)"\s+rowSpan="(\d+)"', body)
        mg = re.search(r'<hp:cellMargin\s+left="(\d+)"\s+right="(\d+)"\s+top="(\d+)"\s+bottom="(\d+)"', body)
        cells.append({
            "rowAddr": int(addr.group(2)) if addr else -1,
            "colAddr": int(addr.group(1)) if addr else -1,
            "bf": bf.group(1) if bf else "1",
            "charPr": cp.group(1) if cp else "0",
            "paraPr": pp.group(1) if pp else "0",
            "width": int(sz.group(1)) if sz else 0,
            "height": int(sz.group(2)) if sz else 0,
            "valign": va.group(1) if va else "CENTER",
            "margin": ({"left": int(mg.group(1)), "right": int(mg.group(2)),
                        "top": int(mg.group(3)), "bottom": int(mg.group(4))}
                       if mg else {"left": 510, "right": 510, "top": 141, "bottom": 141}),
            "spanned": bool(span and (int(span.group(1)) > 1 or int(span.group(2)) > 1)),
        })
    return cells
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_table_reuse.py::TestRichCellExtractor -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_hwpx.py tests/test_table_reuse.py
git commit -m "feat: rich table-cell extractor (width/margin/valign)"
```

---

### Task 3: Build a table profile from a clean source table

**Files:**
- Modify: `scripts/generate_hwpx.py` (add `_char_height_of`, `_build_table_profile`, `_build_table_profile_catalog` after `_extract_table_cells_rich`)
- Test: `tests/test_table_reuse.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_table_reuse.py`:

```python
class TestTableProfile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        zipfile.ZipFile(TEMPLATE).extractall(self.tmp.name)
        self.tdir = self.tmp.name
        self.body, _ = G._detect_template_sections(self.tdir)
        self.header_xml = open(os.path.join(self.tdir, "Contents", "header.xml"), encoding="utf-8").read()

    def test_catalog_has_common_col_counts_and_shape(self):
        bx = open(self.body, encoding="utf-8").read()
        cat = G._build_table_profile_catalog(bx, self.header_xml)
        self.assertTrue(cat)  # non-empty
        # pick any profile and check structure
        prof = next(iter(cat.values()))
        for k in ("total_width", "cell_margin", "header_h", "body_h", "row_h",
                  "header", "first", "interior", "last"):
            self.assertIn(k, prof)
        ncols = len(prof["header"])
        for role in ("header", "first", "interior", "last"):
            self.assertEqual(len(prof[role]), ncols)
            self.assertTrue(all("bf" in c and "charPr" in c for c in prof[role]))

    def test_header_distinct_corner_fills(self):
        # A clean multi-col profile distinguishes left/right corner fills in header.
        bx = open(self.body, encoding="utf-8").read()
        cat = G._build_table_profile_catalog(bx, self.header_xml)
        multi = [p for p in cat.values() if len(p["header"]) >= 3]
        self.assertTrue(multi)
        p = multi[0]
        bfs = [c["bf"] for c in p["header"]]
        self.assertNotEqual(bfs[0], bfs[-1])  # left corner != right corner
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_table_reuse.py::TestTableProfile -v`
Expected: FAIL — `_build_table_profile_catalog` not defined.

- [ ] **Step 3: Implement**

Add after `_extract_table_cells_rich`:

```python
def _char_height_of(header_xml, char_pr_id):
    """Look up a charPr's height (HWPUNIT) from header.xml; default 1200."""
    m = re.search(r'<hh:charPr id="%s"[^>]*height="(\d+)"' % char_pr_id, header_xml)
    return int(m.group(1)) if m else 1200


def _build_table_profile(table_para_xml, header_xml):
    """Build a per-position style profile from ONE data-table paragraph.

    Returns a profile dict (see plan's 'Profile data structure') or None if the
    table is unsuitable (has spanned cells, no header row, or < 2 body rows).
    """
    cells = _extract_table_cells_rich(table_para_xml)
    if not cells or any(c["spanned"] for c in cells):
        return None
    rows = {}
    for c in cells:
        rows.setdefault(c["rowAddr"], {})[c["colAddr"]] = c
    row_ids = sorted(r for r in rows if r >= 0)
    if len(row_ids) < 3:                      # need header + >=2 body rows
        return None
    ncols = max(len(rows[r]) for r in row_ids)
    # require a full rectangular grid (clean table)
    for r in row_ids:
        if len(rows[r]) != ncols or any(j not in rows[r] for j in range(ncols)):
            return None

    def row_cells(r):
        return [rows[r][j] for j in range(ncols)]

    header_r, first_r, last_r = row_ids[0], row_ids[1], row_ids[-1]
    interior_r = row_ids[2] if len(row_ids) >= 4 else row_ids[1]

    def style_row(r):
        return [{"bf": c["bf"], "charPr": c["charPr"], "paraPr": c["paraPr"],
                 "valign": c["valign"]} for c in row_cells(r)]

    hdr_cells = row_cells(header_r)
    body_cells = row_cells(first_r)
    total_width = sum(c["width"] for c in hdr_cells)
    return {
        "total_width": total_width,
        "cell_margin": hdr_cells[0]["margin"],
        "header_h": _char_height_of(header_xml, hdr_cells[0]["charPr"]),
        "body_h": _char_height_of(header_xml, body_cells[0]["charPr"]),
        "row_h": {"header": hdr_cells[0]["height"], "first": body_cells[0]["height"],
                  "interior": row_cells(interior_r)[0]["height"],
                  "last": row_cells(last_r)[0]["height"]},
        "header": style_row(header_r),
        "first": style_row(first_r),
        "interior": style_row(interior_r),
        "last": style_row(last_r),
    }


def _build_table_profile_catalog(body_section_xml, header_xml):
    """Scan a body section for clean data tables and return
    {ncols(str): profile} keeping the first clean table found per column count."""
    catalog = {}
    paras, _ = _extract_all_top_level_paragraphs(body_section_xml)
    attrs = [_extract_para_attrs(p) for p in paras]
    for i, a in enumerate(attrs):
        if not (a['has_tbl'] and not a['has_colpr']):
            continue
        prof = _build_table_profile(paras[i], header_xml)
        if prof is None:
            continue
        key = str(len(prof["header"]))
        if key not in catalog:
            catalog[key] = prof
    return catalog
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_table_reuse.py::TestTableProfile -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_hwpx.py tests/test_table_reuse.py
git commit -m "feat: build per-position table style profiles from template"
```

---

### Task 4: Wire `table_profiles` into the style map

**Files:**
- Modify: `scripts/generate_hwpx.py` (`DEFAULT_STYLE_MAP` at `:252`; `build_style_map_from_template` — add after the existing data-table Phase D block that sets `table_header`/`table_body`)
- Test: `tests/test_table_reuse.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_table_reuse.py`:

```python
class TestStyleMapTableProfiles(unittest.TestCase):
    def test_default_has_empty_table_profiles(self):
        self.assertIn("table_profiles", G.DEFAULT_STYLE_MAP)
        self.assertEqual(G.DEFAULT_STYLE_MAP["table_profiles"], {})

    def test_build_populates_table_profiles(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        zipfile.ZipFile(TEMPLATE).extractall(os.path.join(tmp.name, "t"))
        sm = G.build_style_map_from_template(os.path.join(tmp.name, "t"))
        self.assertIn("table_profiles", sm)
        self.assertTrue(sm["table_profiles"])  # non-empty for the bundled template
        # every profile has 4 role rows of equal column count
        for ncols, prof in sm["table_profiles"].items():
            self.assertEqual(len(prof["header"]), int(ncols))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_table_reuse.py::TestStyleMapTableProfiles -v`
Expected: FAIL — key missing.

- [ ] **Step 3a: Add the default**

In `DEFAULT_STYLE_MAP`, immediately after the `"note":` entry (the last marker style) add:

```python
    # Table style profiles keyed by column count (discovered per-template).
    "table_profiles":   {},
```

- [ ] **Step 3b: Populate during discovery**

In `build_style_map_from_template`, find the data-table Phase D block — it ends with the assignment of `sm['table_body']` from `body_cp` (search for `sm['table_body'] = _make_style_tuple`). Immediately AFTER that block (and before the title-bar/border-fill code or the function's return — anywhere after `s1_xml` and the table detection are available), add:

```python
        # Per-position table style profiles keyed by column count.
        try:
            sm['table_profiles'] = _build_table_profile_catalog(
                s1_xml, header_path.read_text(encoding='utf-8'))
        except Exception as e:
            print(f"Warning: could not build table profiles: {e}")
            sm['table_profiles'] = {}
```

(`s1_xml` is the body-section text already read near the top of the `try` block; `header_path` is the local header path. If `s1_xml` is not in scope at your chosen insertion point, read it via `body_section_path.read_text(encoding='utf-8')`.)

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_table_reuse.py::TestStyleMapTableProfiles -v`
Expected: 2 passed.

- [ ] **Step 5: Run full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_hwpx.py tests/test_table_reuse.py
git commit -m "feat: store discovered table_profiles in style map"
```

---

### Task 5: Profile-driven `data_table_xml`

**Files:**
- Modify: `scripts/generate_hwpx.py` (add `_profile_cell_xml` and a `_data_table_from_profile`; rewrite `data_table_xml` dispatch at `:1694`)
- Test: `tests/test_table_reuse.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_table_reuse.py`:

```python
class TestProfileDrivenTable(unittest.TestCase):
    def _sm(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        zipfile.ZipFile(TEMPLATE).extractall(os.path.join(tmp.name, "t"))
        return G.build_style_map_from_template(os.path.join(tmp.name, "t"))

    def test_uses_profile_border_fills(self):
        sm = self._sm()
        # pick a column count the template has
        ncols = int(sorted(sm["table_profiles"], key=int)[0])
        prof = sm["table_profiles"][str(ncols)]
        headers = [f"H{i}" for i in range(ncols)]
        rows = [[f"r{r}c{c}" for c in range(ncols)] for r in range(3)]
        xml, _ = G.data_table_xml(headers, rows, sm)
        # parse the first <hp:tr> (header row) and read each cell's fill, in order
        header_tr = re.search(r'<hp:tr>(.*?)</hp:tr>', xml, re.DOTALL).group(1)
        hdr_cell_bfs = re.findall(r'<hp:tc\b[^>]*borderFillIDRef="(\d+)"', header_tr)
        self.assertEqual(hdr_cell_bfs, [c["bf"] for c in prof["header"]])

    def test_last_row_uses_last_profile_fill(self):
        sm = self._sm()
        ncols = int(sorted(sm["table_profiles"], key=int)[0])
        prof = sm["table_profiles"][str(ncols)]
        headers = [f"H{i}" for i in range(ncols)]
        rows = [[f"r{r}c{c}" for c in range(ncols)] for r in range(4)]
        xml, _ = G.data_table_xml(headers, rows, sm)
        last_fill = prof["last"][0]["bf"]
        self.assertIn(last_fill, xml)

    def test_widths_sum_to_profile_total(self):
        sm = self._sm()
        ncols = int(sorted(sm["table_profiles"], key=int)[0])
        prof = sm["table_profiles"][str(ncols)]
        headers = [f"H{i}" for i in range(ncols)]
        rows = [[f"r{r}c{c}" for c in range(ncols)] for r in range(2)]
        xml, _ = G.data_table_xml(headers, rows, sm)
        widths = [int(w) for w in re.findall(r'<hp:cellSz width="(\d+)"', xml)]
        # first ncols widths are the header row; they sum to the profile total
        self.assertEqual(sum(widths[:ncols]), prof["total_width"])

    def test_fallback_when_no_profile(self):
        sm = self._sm()
        # choose a column count not present in the catalog
        present = {int(k) for k in sm["table_profiles"]}
        ncols = next(c for c in range(2, 40) if c not in present)
        headers = [f"H{i}" for i in range(ncols)]
        rows = [[f"r{c}" for c in range(ncols)]]
        xml, vs = G.data_table_xml(headers, rows, sm)   # must not raise
        self.assertIn("<hp:tbl", xml)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_table_reuse.py::TestProfileDrivenTable -v`
Expected: FAIL (current `data_table_xml` ignores profiles).

- [ ] **Step 3: Implement the cell emitter + profile renderer**

Add just above `def data_table_xml` (`:1694`):

```python
def _profile_cell_xml(col, row, width, height, text, cell, char_h, margin):
    """Emit one <hp:tc> reusing a profile cell's style, with regenerated text
    and a recomputed lineseg for the given width (Hancom does not recalc)."""
    inner_hz = max(width - 1022, 0)
    nlines = estimate_line_count(text, char_h, inner_hz) if text else 1
    baseline = int(char_h * 0.85)
    return (f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" '
            f'borderFillIDRef="{cell["bf"]}">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" '
            f'vertAlign="{cell["valign"]}" linkListIDRef="0" linkListNextIDRef="0" '
            f'textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f'<hp:p id="2147483648" paraPrIDRef="{cell["paraPr"]}" styleIDRef="0" '
            f'pageBreak="0" columnBreak="0" merged="0">'
            f'{run_xml(cell["charPr"], text)}'
            f'{lineseg_xml(vertsize=char_h, textheight=char_h, baseline=baseline, spacing=360, horzsize=inner_hz, num_lines=nlines, full_text=text)}'
            f'</hp:p></hp:subList>'
            f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
            f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{width}" height="{height}"/>'
            f'<hp:cellMargin left="{margin["left"]}" right="{margin["right"]}" '
            f'top="{margin["top"]}" bottom="{margin["bottom"]}"/>'
            f'</hp:tc>')


def _row_height(texts, widths, char_h, base_h, margin):
    """Row height = max over cells of (wrapped lines) accommodated, >= base_h."""
    max_lines = 1
    for t, w in zip(texts, widths):
        if t:
            max_lines = max(max_lines, estimate_line_count(t, char_h, max(w - 1022, 0)))
    computed = max_lines * char_h + (max_lines - 1) * 360 + margin["top"] + margin["bottom"]
    return max(base_h, computed)


def _data_table_from_profile(headers, rows, prof, sm, caption, table_id):
    """Render a data table reusing a template profile. Returns (xml, wrapper_vs)."""
    ncols = len(headers)
    total_width = prof["total_width"]
    margin = prof["cell_margin"]
    widths = _compute_column_widths(headers, rows, max(prof["header_h"], prof["body_h"]),
                                    total_width, h_margin=margin["left"] + margin["right"])

    # choose body-row profile role per row index
    R = len(rows)
    def body_role(i):
        if R == 1:
            return "last"
        if i == 0:
            return "first"
        if i == R - 1:
            return "last"
        return "interior"

    # header row
    h_h = _row_height(headers, widths, prof["header_h"], prof["row_h"]["header"], margin)
    header_cells = "".join(
        _profile_cell_xml(j, 0, widths[j], h_h, str(headers[j]), prof["header"][j],
                          prof["header_h"], margin)
        for j in range(ncols))
    total_height = h_h
    body_rows = ""
    for i, row in enumerate(rows):
        role = body_role(i)
        texts = [str(row[j]) if j < len(row) else "" for j in range(ncols)]
        rh = _row_height(texts, widths, prof["body_h"], prof["row_h"][role], margin)
        total_height += rh
        cells = "".join(
            _profile_cell_xml(j, i + 1, widths[j], rh, texts[j], prof[role][j],
                              prof["body_h"], margin)
            for j in range(ncols))
        body_rows += f'<hp:tr>{cells}</hp:tr>'

    paragraphs = ""
    if caption:
        tc = sm["table_caption"]
        paragraphs += paragraph_xml(tc[1], "0", run_xml(tc[0], f"< {caption} >"),
                                     lineseg_xml(vertsize=tc[2], textheight=tc[3], baseline=tc[4], spacing=tc[5]))
    wrapper_vertsize = total_height + 566
    tw = sm["table_wrapper"]
    tbl = (f'<hp:tbl id="{table_id}" zOrder="0" numberingType="TABLE" '
           f'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" '
           f'pageBreak="CELL" repeatHeader="1" rowCnt="{R + 1}" colCnt="{ncols}" '
           f'cellSpacing="0" borderFillIDRef="{prof["interior"][0]["bf"]}" noAdjust="0">'
           f'<hp:sz width="{total_width}" widthRelTo="ABSOLUTE" height="{total_height}" heightRelTo="ABSOLUTE" protect="0"/>'
           f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
           f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" '
           f'vertOffset="0" horzOffset="0"/>'
           f'<hp:outMargin left="283" right="283" top="283" bottom="283"/>'
           f'<hp:inMargin left="{margin["left"]}" right="{margin["right"]}" top="{margin["top"]}" bottom="{margin["bottom"]}"/>'
           f'<hp:tr>{header_cells}</hp:tr>{body_rows}</hp:tbl>')
    paragraphs += paragraph_xml(tw[1], "0",
                                 f'<hp:run charPrIDRef="{tw[0]}">{tbl}<hp:t/></hp:run>',
                                 lineseg_xml(vertsize=wrapper_vertsize, textheight=wrapper_vertsize,
                                             baseline=int(wrapper_vertsize * 0.85), spacing=tw[5]))
    return paragraphs, wrapper_vertsize
```

- [ ] **Step 4: Make `data_table_xml` dispatch to the profile path**

Replace the body of `data_table_xml` (`:1694`) so it tries the profile first, else runs the existing generated logic. Change the function to:

```python
def data_table_xml(headers, rows, sm, caption="", table_id=1974981391):
    """Generate a data table. Reuses a template style profile for the table's
    column count when available; otherwise falls back to a generated table."""
    num_cols = len(headers)
    prof = sm.get("table_profiles", {}).get(str(num_cols))
    if prof:
        return _data_table_from_profile(headers, rows, prof, sm, caption, table_id)

    # ---- fallback: generated table (original behavior, content-aware widths) ----
    num_rows = len(rows) + 1
    total_width = 47622
    col_widths = _compute_column_widths(headers, rows, sm["table_body"][2], total_width)
    row_height = 2048
    total_height = row_height * num_rows
    th = sm["table_header"]; tb = sm["table_body"]
    header_cells = ""
    for i, (hdr, w) in enumerate(zip(headers, col_widths)):
        header_cells += table_cell_xml(i, 0, w, row_height, sm["bf_table_header"],
                                        th[1], th[0], hdr,
                                        vertsize=th[2], textheight=th[3], baseline=th[4], spacing=th[5])
    body_rows = ""
    for r_idx, row in enumerate(rows):
        cells = ""
        for c_idx, (cell_text, w) in enumerate(zip(row, col_widths)):
            cells += table_cell_xml(c_idx, r_idx + 1, w, row_height, sm["bf_table"],
                                     tb[1], tb[0], str(cell_text),
                                     vertsize=tb[2], textheight=tb[3], baseline=tb[4], spacing=tb[5])
        body_rows += f'<hp:tr>{cells}</hp:tr>'
    paragraphs = ""
    if caption:
        tc = sm["table_caption"]
        paragraphs += paragraph_xml(tc[1], "0", run_xml(tc[0], f"< {caption} >"),
                                     lineseg_xml(vertsize=tc[2], textheight=tc[3], baseline=tc[4], spacing=tc[5]))
    wrapper_vertsize = total_height + 566
    tw = sm["table_wrapper"]
    tbl = (f'<hp:tbl id="{table_id}" zOrder="0" numberingType="TABLE" '
           f'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" '
           f'pageBreak="CELL" repeatHeader="1" rowCnt="{num_rows}" colCnt="{num_cols}" '
           f'cellSpacing="0" borderFillIDRef="{sm["bf_table"]}" noAdjust="0">'
           f'<hp:sz width="{total_width}" widthRelTo="ABSOLUTE" height="{total_height}" heightRelTo="ABSOLUTE" protect="0"/>'
           f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
           f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" '
           f'vertOffset="0" horzOffset="0"/>'
           f'<hp:outMargin left="283" right="283" top="283" bottom="283"/>'
           f'<hp:inMargin left="510" right="510" top="141" bottom="141"/>'
           f'<hp:tr>{header_cells}</hp:tr>{body_rows}</hp:tbl>')
    paragraphs += paragraph_xml(tw[1], "0",
                                 f'<hp:run charPrIDRef="{tw[0]}">{tbl}<hp:t/></hp:run>',
                                 lineseg_xml(vertsize=wrapper_vertsize, textheight=wrapper_vertsize,
                                             baseline=int(wrapper_vertsize * 0.85), spacing=tw[5]))
    return paragraphs, wrapper_vertsize
```

(The only change to the fallback vs. the original is content-aware `col_widths` via `_compute_column_widths`.)

- [ ] **Step 5: Run the new tests**

Run: `python3 -m pytest tests/test_table_reuse.py::TestProfileDrivenTable -v`
Expected: 4 passed.

- [ ] **Step 6: Run full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass. (If a pre-existing table test asserted equal column widths or `total_width=47622` exactly, update that test to the content-aware widths — the table now reuses the template profile. Note any such change in your report.)

- [ ] **Step 7: Commit**

```bash
git add scripts/generate_hwpx.py tests/test_table_reuse.py
git commit -m "feat: profile-driven data_table_xml with content-aware widths + fallback"
```

---

### Task 6: Regenerate the bundled style cache

**Files:**
- Regenerate: `assets/default_styles.json`

- [ ] **Step 1: Regenerate the cache so it carries `table_profiles`**

Run:
```bash
python3 -c "
import json, zipfile, tempfile, os
from scripts import generate_hwpx as G
tp='assets/template.hwpx'
td=tempfile.mkdtemp(); zipfile.ZipFile(tp).extractall(os.path.join(td,'t'))
sm=G.build_style_map_from_template(os.path.join(td,'t'))
G.save_style_map_cache('assets/default_styles.json', G.compute_template_hash(tp), sm)
print('profiles for col counts:', sorted(sm['table_profiles'], key=int))
"
```
Expected: prints a non-empty list of column counts.

- [ ] **Step 2: Verify hash + profiles present**

Run:
```bash
python3 -c "
import json
from scripts import generate_hwpx as G
d=json.load(open('assets/default_styles.json'))
print('hash match:', d['template_hash']==G.compute_template_hash('assets/template.hwpx'))
print('has table_profiles:', bool(d['style_map'].get('table_profiles')))
"
```
Expected: `hash match: True` and `has table_profiles: True`.

- [ ] **Step 3: Full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add assets/default_styles.json
git commit -m "chore: regenerate default_styles.json with table_profiles"
```

---

### Task 7: End-to-end table fidelity test

**Files:**
- Test: `tests/test_table_reuse.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_table_reuse.py`:

```python
class TestEndToEndTable(unittest.TestCase):
    def test_generated_doc_table_matches_template_fills(self):
        # Build a document with a table whose column count exists in the template.
        sm = json.load(open(os.path.join(SKILL_DIR, "assets", "default_styles.json")))["style_map"]
        ncols = int(sorted(sm["table_profiles"], key=int)[0])
        headers = [f"항목{i}" for i in range(ncols)]
        rows = [[f"행{r}열{c}" for c in range(ncols)] for r in range(3)]
        config = {"include_cover": False, "sections": [{
            "type": "body", "title_bar": "표 양식 점검",
            "content": [
                {"type": "heading", "text": "표 점검"},
                {"type": "table", "caption": "샘플", "headers": headers, "rows": rows},
            ]}]}
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        out = os.path.join(tmp.name, "t.hwpx")
        G.generate_hwpx(config, out)
        self.assertTrue(zipfile.is_zipfile(out))
        with zipfile.ZipFile(out) as zf:
            secs = sorted(n for n in zf.namelist() if re.search(r'section\d+\.xml$', n))
            body = "".join(zf.read(n).decode("utf-8") for n in secs)
        # the generated table is present with the right column count
        m = re.search(r'<hp:tbl[^>]*colCnt="%d"' % ncols, body)
        self.assertIsNotNone(m, "generated table with expected colCnt not found")
```

- [ ] **Step 2: Run**

Run: `python3 -m pytest tests/test_table_reuse.py::TestEndToEndTable -v`
Expected: PASS. (Requires Task 6 so the committed cache carries profiles.)

If the table renders through the skeleton/appendix path differently, inspect the generated `body` to confirm the `<hp:tbl>` appears; adjust only the test's locator if needed (do not change production code).

- [ ] **Step 3: Full suite + commit**

Run: `python3 -m pytest tests/ -q` (expect all pass)
```bash
git add tests/test_table_reuse.py
git commit -m "test: end-to-end generated table uses template profile"
```

---

### Task 8: 개조식 authoring rules (SKILL.md) + CHANGELOG

**Files:**
- Modify: `SKILL.md`, `CHANGELOG.md`

- [ ] **Step 1: Add the mandatory section to SKILL.md**

Open `SKILL.md`. After the `### Config JSON Structure` section (and its `#### Bold keywords in body text` subsection added earlier), insert a new top-level section. Use this exact content:

```markdown
## 개조식 Authoring Rules (MANDATORY)

When turning any source material into report content, you MUST produce Korean
government 개조식(個條式) style. Never paste or lightly-edit source text verbatim.

1. **Summarize, never transcribe.** Reduce each source passage to its essential
   point(s). Copying a sentence and tweaking it is a violation.
2. **Nominalized / 음슴체 endings.** End each line on a noun or nominal form
   (`~함, ~필요, ~추진, ~예정, ~검토, ~전환`), never 서술식 (`~한다 / ~이다 / ~했다`).
3. **One idea per line, with hierarchy** `□` heading → `○` bullet → `-` dash →
   `*` detail. Split compound sentences into separate lines.
4. **Lead with a label** where natural: `(배경)`, `(현황)`, `(추진방향)`, `(기대효과)`.
5. **Strip connectives and redundant subjects;** keep numbers, proper nouns, and
   key terms.
6. **Bold the key term** in each line using the `{ "t": "...", "bold": true }`
   segment form (see "Bold keywords in body text").
7. **Tabulate enumerable / comparative data** (years, figures, categories) instead
   of writing it as prose. Tables automatically reuse the template's table style.

**Example — before → after**

- 서술식 (WRONG, verbatim): "AI가 인간 주니어 개발자보다 더 빠르고 정확하게 코드를 짜는
  2026년, 진짜 중요한 능력은 '문법'이 아니라 '의도(Intent)'를 설계하는 능력이다."
- 개조식 (RIGHT): `○ (핵심역량 전환)` AI가 코드 작성 대체 → 인간 경쟁력은
  **'의도(Intent) 설계'** 로 이동
```

- [ ] **Step 2: Add a CHANGELOG entry**

In `CHANGELOG.md`, immediately below `# CHANGELOG`, insert:

```markdown
## [0.11.0] - 2026-05-29

### Template-matched tables + 개조식 authoring rules

- **Table style reuse.** Generated data tables now reuse a real template table's
  per-position cell styling (border fills, fonts, alignment) discovered into
  `table_profiles`, instead of fabricating uniform borders. Column counts with no
  template match fall back to the generated table.
- **Content-aware column widths.** Column widths are computed from cell content
  within the template table's total width (the template itself sizes columns to
  content), with a minimum-width floor.
- **개조식 authoring rules.** SKILL.md gains a mandatory section requiring terse,
  itemized Korean-government 개조식 output — never verbatim source text.
```

- [ ] **Step 3: Sanity-check + commit**

Run: `python3 -m pytest tests/ -q` (docs change; expect all pass)
```bash
git add SKILL.md CHANGELOG.md
git commit -m "docs: 개조식 authoring rules + changelog 0.11.0"
```

---

## Final verification

- [ ] `python3 -m pytest tests/ -q` → all pass.
- [ ] Profiles present: `python3 -c "import json;print(sorted(json.load(open('assets/default_styles.json'))['style_map']['table_profiles'],key=int))"` → non-empty.
- [ ] Regenerate the coding-report sample (or any doc with a table) and confirm the table's cell `borderFillIDRef`s match the template profile for that column count.
- [ ] `git status` clean except intended changes.
