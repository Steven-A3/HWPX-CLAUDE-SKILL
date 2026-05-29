# Bold Keyword Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let authors mark spans of body text bold via a `{t, bold}` segment array in the source JSON, rendering them as bold runs whose style is discovered from the template, with correct line geometry.

**Architecture:** `text` accepts a string (unchanged single-run path) or a list of `{t, bold}` segments (new multi-run path). Bold charPr ids are discovered per body style by exact-twin matching in `header.xml`; missing twins are baked into the bundled template once by an idempotent prep script. Line counts for segmented text are computed with a bold-aware width model (Hangul is weight-invariant; proportional glyphs are widened).

**Tech Stack:** Python 3 (stdlib only: `re`, `zipfile`, `json`, `xml.etree`), pytest/unittest, HWPX (zipped XML).

---

## Background facts (verified against the repo — read before starting)

- Body content for BOTH render paths (`generate_body_section_xml` skeleton path at `scripts/generate_hwpx.py:1886` and fully-generated fallback at `:1943`) is emitted by `generate_content_item` (`:1690`). There is no second renderer.
- `run_xml(char_pr_id, text="", inner_xml="")` (`:1444`) emits one `<hp:run charPrIDRef=...>`.
- Style map entries are tuples `(charPrIDRef, paraPrIDRef, vertsize, textheight, baseline, spacing)`; `bf_*` entries are plain string ids. New `*_bold` entries are plain string charPr ids (like `bf_*`).
- `DEFAULT_STYLE_MAP` is at `:216`; `build_style_map_from_template` is at `:671`; marker styles (`paragraph`, `bullet`, `dash`, `star`, `note`) are assigned `:824-867`.
- `_char_width(ch, char_height)` is at `:92`; `estimate_line_breaks` at `:129`; `estimate_line_count` at `:110`; `EFFECTIVE_WIDTH_RATIO=0.91` at `:107`; `HORZSIZE_DEFAULT` is a module constant used as the default horzsize.
- `_extract_paragraph_first_text` (`:488`) joins ALL `<hp:t>` nodes, so multi-run paragraphs read back as the full plain text.
- On the bundled MS_YOON template: paragraph/bullet/note base charPr = 38 (exact twin 71 exists); dash base = 397 (no twin); star base = 273 (no twin). charPr ids are contiguous 0–546; `<hh:charProperties itemCnt="547">`.
- Cache: `compute_template_hash` (`:272`), `load_cached_style_map` (`:281`), `save_style_map_cache` (`:300`). `generate_hwpx` rebuilds + saves cache when the template hash changes.

## File structure

- Modify: `scripts/generate_hwpx.py` — width model, segment helpers, discovery, content rendering, style-map wiring, `DEFAULT_STYLE_MAP`.
- Create: `scripts/prepare_template_bold_twins.py` — one-time/idempotent template prep.
- Regenerate (committed artifacts): `assets/template.hwpx`, `assets/default_styles.json`.
- Create: `tests/test_bold_keyword_runs.py` — all new unit/integration tests.
- Modify: `SKILL.md`, `CHANGELOG.md` — docs.

## Test command

Single test: `python3 -m pytest tests/test_bold_keyword_runs.py::ClassName::test_name -v`
Full suite: `python3 -m pytest tests/ -q`

---

### Task 1: Bold-aware width model + segmented line count

**Files:**
- Modify: `scripts/generate_hwpx.py` (`_char_width` at `:92`; add module constant; add `_segmented_line_count` near `estimate_line_breaks` `:168`)
- Test: `tests/test_bold_keyword_runs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_bold_keyword_runs.py`:

```python
#!/usr/bin/env python3
"""Tests for bold keyword runs (docs/superpowers/specs/2026-05-29-bold-keyword-runs-design.md)."""
import os, re, sys, json, zipfile, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import generate_hwpx as G

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(SKILL_DIR, "assets", "template.hwpx")


class TestBoldWidth(unittest.TestCase):
    def test_hangul_width_weight_invariant(self):
        # Korean syllables occupy a fixed em square regardless of weight.
        self.assertEqual(G._char_width('가', 1500, bold=False),
                         G._char_width('가', 1500, bold=True))

    def test_proportional_width_widened_by_bold(self):
        # ASCII letters/digits are proportional; bold must be wider.
        self.assertGreater(G._char_width('A', 1500, bold=True),
                           G._char_width('A', 1500, bold=False))

    def test_default_bold_false_unchanged(self):
        # Backward compat: the 2-arg call is identical to the old behavior.
        self.assertEqual(G._char_width('A', 1500), int(1500 * 0.50))

    def test_segmented_line_count_matches_string_when_no_bold(self):
        text = "올해 목표 달성률은 전년 대비 크게 상승하여 목표치를 초과 달성했다 " * 2
        segs = [(text, False)]
        self.assertEqual(G._segmented_line_count(segs, 1500),
                         G.estimate_line_count(text, 1500))

    def test_segmented_line_count_bold_latin_not_fewer(self):
        latin = "performance metric exceeded baseline target " * 3
        normal = G._segmented_line_count([(latin, False)], 1500)
        bold = G._segmented_line_count([(latin, True)], 1500)
        self.assertGreaterEqual(bold, normal)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bold_keyword_runs.py::TestBoldWidth -v`
Expected: FAIL — `_char_width()` takes 2 positional args / `_segmented_line_count` not defined.

- [ ] **Step 3: Implement the bold-aware width + segmented counter**

In `scripts/generate_hwpx.py`, replace `_char_width` (`:92-102`) with:

```python
# Bold proportional glyphs render wider; Hangul/CJK keep fixed em width.
BOLD_WIDTH_FACTOR = 1.1


def _char_width(ch, char_height, bold=False):
    """Get estimated rendered width of a single character."""
    if '가' <= ch <= '힣':      return char_height  # Korean syllables
    elif 'ㄱ' <= ch <= 'ㆎ':     return char_height  # Korean jamo
    elif '─' <= ch <= '╿':     return char_height  # Box drawing
    elif '＀' <= ch <= '￯':     return char_height  # Fullwidth forms
    elif ord(ch) >= 0x2E80:              return char_height  # CJK, symbols
    elif ch == ' ':                      return int(char_height * 0.25)
    elif ch.isascii() and (ch.isalpha() or ch.isdigit()):
        w = char_height * 0.50
        return int(w * BOLD_WIDTH_FACTOR) if bold else int(w)
    else:
        w = char_height * 0.55
        return int(w * BOLD_WIDTH_FACTOR) if bold else int(w)
```

Add `_segmented_line_count` immediately after `estimate_line_breaks` (after `:168`):

```python
def _segmented_line_count(segments, char_height, horzsize=HORZSIZE_DEFAULT):
    """Line count for a list of (text, bold) segments, weight-aware.

    Mirrors estimate_line_breaks() but applies each character's bold flag to
    its width. For all-normal segments this equals estimate_line_count() on the
    joined text.
    """
    chars = [(ch, bold) for text, bold in segments for ch in text]
    if not chars:
        return 1
    effective_width = int(horzsize * EFFECTIVE_WIDTH_RATIO)
    breaks = [0]
    cumulative_width = 0
    last_space_pos = None
    for i, (ch, bold) in enumerate(chars):
        cumulative_width += _char_width(ch, char_height, bold)
        if ch == ' ':
            last_space_pos = i + 1
        if cumulative_width > effective_width:
            if last_space_pos and last_space_pos > breaks[-1]:
                breaks.append(last_space_pos)
                cumulative_width = sum(_char_width(c, char_height, b)
                                       for c, b in chars[last_space_pos:i + 1])
            elif i > breaks[-1]:
                breaks.append(i)
                cumulative_width = _char_width(ch, char_height, bold)
            last_space_pos = None
    return len(breaks)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_bold_keyword_runs.py::TestBoldWidth -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `python3 -m pytest tests/ -q`
Expected: all existing tests still PASS (the 2-arg `_char_width` default keeps old behavior).

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_hwpx.py tests/test_bold_keyword_runs.py
git commit -m "feat: bold-aware char width + segmented line counter"
```

---

### Task 2: Segment normalizer + validation

**Files:**
- Modify: `scripts/generate_hwpx.py` (add helpers near other content helpers, e.g. just above `generate_content_item` at `:1690`)
- Test: `tests/test_bold_keyword_runs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bold_keyword_runs.py`:

```python
class TestSegmentNormalizer(unittest.TestCase):
    def test_string_becomes_single_normal_segment(self):
        self.assertEqual(G._normalize_text_segments("hello"), [("hello", False)])

    def test_array_maps_to_tuples(self):
        text = [{"t": "올해 "}, {"t": "목표", "bold": True}, {"t": "은"}]
        self.assertEqual(G._normalize_text_segments(text),
                         [("올해 ", False), ("목표", True), ("은", False)])

    def test_bold_coerced_to_bool(self):
        self.assertEqual(G._normalize_text_segments([{"t": "x", "bold": 1}]),
                         [("x", True)])

    def test_missing_t_raises_with_index(self):
        with self.assertRaises(ValueError) as cm:
            G._normalize_text_segments([{"bold": True}], item_index=3)
        self.assertIn("3", str(cm.exception))

    def test_non_string_t_raises(self):
        with self.assertRaises(ValueError):
            G._normalize_text_segments([{"t": 5}])

    def test_non_list_non_string_raises(self):
        with self.assertRaises(ValueError):
            G._normalize_text_segments(42)

    def test_plain_text_joins(self):
        segs = [("올해 ", False), ("목표", True), ("은", False)]
        self.assertEqual(G._segments_plain_text(segs), "올해 목표은")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bold_keyword_runs.py::TestSegmentNormalizer -v`
Expected: FAIL — `_normalize_text_segments` not defined.

- [ ] **Step 3: Implement the helpers**

Add to `scripts/generate_hwpx.py` just above `def generate_content_item` (`:1690`):

```python
def _normalize_text_segments(text, item_index=None):
    """Normalize an item's 'text' to a list of (text, bold) tuples.

    A plain string -> [(string, False)]. A list of {'t': str, 'bold': bool}
    objects -> one tuple per segment. Raises ValueError on malformed input,
    naming the offending content item / segment.
    """
    if isinstance(text, str):
        return [(text, False)]
    if not isinstance(text, list):
        raise ValueError(
            f"content item {item_index}: 'text' must be a string or a list of "
            f"segments, got {type(text).__name__}")
    out = []
    for j, seg in enumerate(text):
        if not isinstance(seg, dict) or 't' not in seg or not isinstance(seg['t'], str):
            raise ValueError(
                f"content item {item_index}, segment {j}: each segment must be "
                f"an object with a string 't'")
        out.append((seg['t'], bool(seg.get('bold', False))))
    return out


def _segments_plain_text(segments):
    """Concatenate segment text (the visible string), ignoring weight."""
    return ''.join(t for t, _bold in segments)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_bold_keyword_runs.py::TestSegmentNormalizer -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_hwpx.py tests/test_bold_keyword_runs.py
git commit -m "feat: text segment normalizer + validation"
```

---

### Task 3: Exact bold-twin discovery (`_find_bold_twin`)

**Files:**
- Modify: `scripts/generate_hwpx.py` (add near `_parse_header_catalogs` at `:316`)
- Test: `tests/test_bold_keyword_runs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bold_keyword_runs.py`:

```python
class TestFindBoldTwin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with zipfile.ZipFile(TEMPLATE) as zf:
            zf.extractall(self.tmp.name)
        hp = os.path.join(self.tmp.name, "Contents", "header.xml")
        with open(hp, encoding="utf-8") as f:
            self.header = f.read()

    def tearDown(self):
        self.tmp.cleanup()

    def _has_bold(self, cid):
        m = re.search(r'<hh:charPr id="%s".*?</hh:charPr>' % cid, self.header, re.DOTALL)
        return m is not None and '<hh:bold' in m.group(0)

    def test_exact_twin_found_and_is_true_twin(self):
        # Base 38 (paragraph) has an exact bold twin in the bundled template.
        twin = G._find_bold_twin(self.header, "38")
        self.assertNotEqual(twin, "38")
        self.assertTrue(self._has_bold(twin))

    def test_no_twin_returns_base(self):
        # A fabricated id with no twin returns the base unchanged.
        self.assertEqual(G._find_bold_twin(self.header, "999999"), "999999")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bold_keyword_runs.py::TestFindBoldTwin -v`
Expected: FAIL — `_find_bold_twin` not defined.

- [ ] **Step 3: Implement discovery**

Add to `scripts/generate_hwpx.py` immediately after `_parse_header_catalogs` (after `:386`):

```python
def _charpr_canonical(charpr_xml):
    """Canonical form of a <hh:charPr> for twin comparison: drop the id
    attribute and any <hh:bold/> marker, collapse whitespace."""
    s = re.sub(r'\s+id="\d+"', '', charpr_xml, count=1)
    s = re.sub(r'<hh:bold\s*/>', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _find_bold_twin(header_xml, base_id):
    """Return the id of a bold charPr identical to base_id except for weight.

    Exact match only: a candidate qualifies iff, after removing its id and any
    <hh:bold/>, its serialized form equals the base's. Lowest matching id wins.
    Returns str(base_id) when no exact twin exists (caller renders normal).
    """
    base_id = str(base_id)
    chars = {}
    for m in re.finditer(r'<hh:charPr id="(\d+)".*?</hh:charPr>', header_xml, re.DOTALL):
        chars[m.group(1)] = m.group(0)
    base = chars.get(base_id)
    if base is None:
        return base_id
    base_canon = _charpr_canonical(base)
    matches = []
    for cid, xml in chars.items():
        if cid == base_id or '<hh:bold' not in xml:
            continue
        if _charpr_canonical(xml) == base_canon:
            matches.append(int(cid))
    return str(min(matches)) if matches else base_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_bold_keyword_runs.py::TestFindBoldTwin -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_hwpx.py tests/test_bold_keyword_runs.py
git commit -m "feat: exact bold-twin discovery in header.xml"
```

---

### Task 4: Wire bold twins into the style map

**Files:**
- Modify: `scripts/generate_hwpx.py` (`DEFAULT_STYLE_MAP` at `:216`; `build_style_map_from_template` after the note assignment at `:867`)
- Test: `tests/test_bold_keyword_runs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bold_keyword_runs.py`:

```python
class TestStyleMapBoldKeys(unittest.TestCase):
    def test_default_style_map_has_bold_keys(self):
        for k in ("paragraph_bold", "bullet_bold", "dash_bold",
                  "star_bold", "note_bold"):
            self.assertIn(k, G.DEFAULT_STYLE_MAP)

    def test_build_resolves_paragraph_bold_to_twin(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with zipfile.ZipFile(TEMPLATE) as zf:
            zf.extractall(os.path.join(tmp.name, "t"))
        sm = G.build_style_map_from_template(os.path.join(tmp.name, "t"))
        self.assertIsNotNone(sm)
        # paragraph base (38) has a twin -> resolved id differs from base.
        self.assertIn("paragraph_bold", sm)
        self.assertNotEqual(sm["paragraph_bold"], sm["paragraph"][0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bold_keyword_runs.py::TestStyleMapBoldKeys -v`
Expected: FAIL — keys missing from `DEFAULT_STYLE_MAP` / not in built map.

- [ ] **Step 3: Add defaults to `DEFAULT_STYLE_MAP`**

In `scripts/generate_hwpx.py`, inside `DEFAULT_STYLE_MAP`, add these entries just before the `# Border fill IDs` comment block (the defaults equal each style's base charPr, i.e. render-normal fallback):

```python
    # Bold twins for body styles (resolved per-template; default = base id)
    "paragraph_bold":   "22",
    "bullet_bold":      "22",
    "dash_bold":        "15",
    "star_bold":        "71",
    "note_bold":        "22",
```

- [ ] **Step 4: Resolve twins in `build_style_map_from_template`**

In `build_style_map_from_template`, immediately AFTER the note-assignment block that ends at `:867` (the `break` inside `if table_wrapper_idx is not None:`) and BEFORE the `# --- table_caption ---` comment, insert:

```python
        # --- Bold twins for body styles (exact-twin discovery) ---
        header_xml_text = header_path.read_text(encoding='utf-8')
        for style_key, bold_key in (("paragraph", "paragraph_bold"),
                                    ("bullet", "bullet_bold"),
                                    ("dash", "dash_bold"),
                                    ("star", "star_bold"),
                                    ("note", "note_bold")):
            base_cp = sm[style_key][0]
            twin = _find_bold_twin(header_xml_text, base_cp)
            sm[bold_key] = twin
            if twin == base_cp:
                print(f"Warning: no exact bold twin for '{style_key}' "
                      f"(charPr {base_cp}); bold segments render normal weight.")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_bold_keyword_runs.py::TestStyleMapBoldKeys -v`
Expected: PASS (2 tests). (A warning for dash/star printing is expected until Task 7.)

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_hwpx.py tests/test_bold_keyword_runs.py
git commit -m "feat: resolve and store body bold-twin charPr ids in style map"
```

---

### Task 5: Render segmented runs in `generate_content_item`

**Files:**
- Modify: `scripts/generate_hwpx.py` (`generate_content_item` `:1690-1798`; both call sites `:1886`, `:1943`)
- Test: `tests/test_bold_keyword_runs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bold_keyword_runs.py`:

```python
class TestSegmentedRunBuilder(unittest.TestCase):
    def test_builds_prefix_and_bold_segment(self):
        xml = G._build_segmented_runs(" ", [("올해 ", False), ("목표", True)],
                                      base_cp="38", bold_cp="71", end_cp="33")
        self.assertIn('<hp:run charPrIDRef="38"><hp:t> </hp:t></hp:run>', xml)
        self.assertIn('charPrIDRef="71"><hp:t>목표</hp:t>', xml)
        self.assertTrue(xml.rstrip().endswith('<hp:run charPrIDRef="33"/>'))

    def test_no_end_run_when_none(self):
        xml = G._build_segmented_runs("▷ ", [("주의", True)],
                                      base_cp="38", bold_cp="71", end_cp=None)
        self.assertNotIn('charPrIDRef="None"', xml)


class TestContentItemBold(unittest.TestCase):
    def _sm(self):
        sm = dict(G.DEFAULT_STYLE_MAP)
        sm["paragraph_bold"] = "71"  # force a distinct bold id for assertion
        return sm

    def test_string_paragraph_byte_identical(self):
        sm = self._sm()
        a = G.generate_content_item({"type": "paragraph", "text": "안녕"}, sm, G.VertPosTracker())
        b = G.generate_content_item({"type": "paragraph", "text": "안녕"}, dict(G.DEFAULT_STYLE_MAP), G.VertPosTracker())
        self.assertEqual(a, b)  # string path unchanged regardless of bold key

    def test_array_paragraph_emits_bold_run(self):
        sm = self._sm()
        xml = G.generate_content_item(
            {"type": "paragraph",
             "text": [{"t": "올해 "}, {"t": "목표", "bold": True}, {"t": "달성"}]},
            sm, G.VertPosTracker())
        self.assertIn('charPrIDRef="71"><hp:t>목표</hp:t>', xml)
        # plain text round-trips
        self.assertEqual(G._extract_paragraph_first_text(xml), " 올해 목표달성")

    def test_heading_flattens_array(self):
        sm = self._sm()
        xml = G.generate_content_item(
            {"type": "heading", "text": [{"t": "제목", "bold": True}]},
            sm, G.VertPosTracker())
        self.assertNotIn('charPrIDRef="71"', xml)  # heading ignores bold
        self.assertIn("제목", xml)

    def test_malformed_segment_raises(self):
        with self.assertRaises(ValueError):
            G.generate_content_item(
                {"type": "bullet", "text": [{"bold": True}]},
                self._sm(), G.VertPosTracker(), item_index=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bold_keyword_runs.py::TestSegmentedRunBuilder tests/test_bold_keyword_runs.py::TestContentItemBold -v`
Expected: FAIL — `_build_segmented_runs` undefined / `generate_content_item` has no `item_index`.

- [ ] **Step 3: Add the run-builder and the marker-config helper**

In `scripts/generate_hwpx.py`, just above `def generate_content_item` (`:1690`), add:

```python
# Marker body items that support bold segments: prefix + style/bold/end keys.
_MARKER_ITEM_CFG = {
    "paragraph": {"prefix": " ",        "style": "paragraph", "bold": "paragraph_bold", "end": "paragraph_end"},
    "bullet":    {"prefix": " ㅇ ",      "style": "bullet",    "bold": "bullet_bold",    "end": "bullet_end"},
    "dash":      {"prefix": "   - ",     "style": "dash",      "bold": "dash_bold",      "end": "dash_end"},
    "star":      {"prefix": "     * ",   "style": "star",      "bold": "star_bold",      "end": "star_end"},
    "note":      {"prefix": "▷ ",        "style": "note",      "bold": "note_bold",      "end": None},
}


def _build_segmented_runs(prefix, segments, base_cp, bold_cp, end_cp=None):
    """Build run XML: a normal prefix run, one run per segment (base or bold
    charPr), then an optional trailing end run."""
    runs = run_xml(base_cp, prefix) if prefix else ""
    for t, bold in segments:
        runs += run_xml(bold_cp if bold else base_cp, t)
    if end_cp is not None:
        runs += run_xml(end_cp)
    return runs


def _render_marker_item(item, sm, vpt, cfg, item_index=None):
    """Render paragraph/bullet/dash/star/note, supporting string or segment
    array text. String text uses the unchanged single-run path."""
    text = item.get("text", "")
    s = sm[cfg["style"]]
    end_cp = sm[cfg["end"]][0] if cfg["end"] else None
    segments = _normalize_text_segments(text, item_index)
    full_text = f"{cfg['prefix']}{_segments_plain_text(segments)}"
    if isinstance(text, str):
        nlines = estimate_line_count(full_text, s[2])
        vp = vpt.next(s[2], s[5], nlines)
        runs = run_xml(s[0], full_text) + (run_xml(end_cp) if end_cp is not None else "")
    else:
        nlines = _segmented_line_count([(cfg["prefix"], False)] + segments, s[2])
        vp = vpt.next(s[2], s[5], nlines)
        # Fall back to the base charPr if no bold key is present (e.g. a cache
        # written before bold support) -> bold segments render at normal weight.
        bold_cp = sm.get(cfg["bold"], s[0])
        runs = _build_segmented_runs(cfg["prefix"], segments, s[0], bold_cp, end_cp)
    return paragraph_xml(s[1], "0", runs,
                         lineseg_xml(vertpos=vp, vertsize=s[2], textheight=s[3],
                                     baseline=s[4], spacing=s[5],
                                     num_lines=nlines, full_text=full_text))
```

- [ ] **Step 4: Rewrite `generate_content_item` to delegate**

Replace the signature and the `paragraph`/`bullet`/`dash`/`star`/`note` branches in `generate_content_item` (`:1691-1798`). Change the signature line `:1691`:

```python
def generate_content_item(item, sm, vpt, item_index=None):
```

In the `heading` branch (`:1696-1708`), change the first lines so an array flattens to plain text. Replace `text = item.get("text", "")` usage by inserting at the very top of the `if item_type == "heading":` block:

```python
    if item_type == "heading":
        text = _segments_plain_text(_normalize_text_segments(text, item_index))
        s = sm["heading_marker"]
        full_text = f"□ {text} "
        # ... (rest of the existing heading body unchanged) ...
```

Replace the FIVE branches `elif item_type == "paragraph":` ... through the `elif item_type == "note":` block (`:1710-1779`) with:

```python
    elif item_type in _MARKER_ITEM_CFG:
        return _render_marker_item(item, sm, vpt, _MARKER_ITEM_CFG[item_type], item_index)
```

Leave the `elif item_type == "table":`, `elif item_type == "empty":`, and the final `else:` branches unchanged.

- [ ] **Step 5: Pass `item_index` from both call sites**

In `generate_body_section_xml`, update the skeleton-path loop at `:1875`:

```python
                            for idx, item in enumerate(content_items):
```
and its content call at `:1886`:
```python
                                content_xml += generate_content_item(item, sm, vpt, item_index=idx)
```

Update the fallback-path loop at `:1932`:
```python
    for idx, item in enumerate(content_items):
```
and its content call at `:1943`:
```python
        paragraphs += generate_content_item(item, sm, vpt, item_index=idx)
```

- [ ] **Step 6: Run the new tests**

Run: `python3 -m pytest tests/test_bold_keyword_runs.py::TestSegmentedRunBuilder tests/test_bold_keyword_runs.py::TestContentItemBold -v`
Expected: PASS (6 tests).

- [ ] **Step 7: Run the full suite (string paths must stay byte-identical)**

Run: `python3 -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/generate_hwpx.py tests/test_bold_keyword_runs.py
git commit -m "feat: render bold segments in body content items"
```

---

### Task 6: Template bold-twin prep script

**Files:**
- Create: `scripts/prepare_template_bold_twins.py`
- Test: `tests/test_bold_keyword_runs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bold_keyword_runs.py`:

```python
class TestPrepScript(unittest.TestCase):
    def _twin_count(self, header):
        return sum(1 for m in re.finditer(r'<hh:charPr id="\d+".*?</hh:charPr>',
                                          header, re.DOTALL) if '<hh:bold' in m.group(0))

    def test_prep_adds_missing_twins_and_is_idempotent(self):
        from scripts import prepare_template_bold_twins as P
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        work = os.path.join(tmp.name, "template.hwpx")
        import shutil; shutil.copy(TEMPLATE, work)

        added1 = P.prepare(work)            # returns list of (style, new_id)
        with zipfile.ZipFile(work) as zf:
            header = zf.read("Contents/header.xml").decode("utf-8")
        # itemCnt matches actual charPr count
        ic = int(re.search(r'<hh:charProperties itemCnt="(\d+)"', header).group(1))
        n = len(re.findall(r'<hh:charPr id="\d+"', header))
        self.assertEqual(ic, n)
        # every body style now resolves to a real twin
        sm = self._build_sm(work)
        for k in ("paragraph_bold", "dash_bold", "star_bold"):
            base = sm[k[:-5]][0] if isinstance(sm[k[:-5]], (list, tuple)) else None
            self.assertNotEqual(sm[k], base)

        added2 = P.prepare(work)            # second run: no-op
        self.assertEqual(added2, [])

    def _build_sm(self, hwpx):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        with zipfile.ZipFile(hwpx) as zf:
            zf.extractall(os.path.join(tmp.name, "t"))
        return G.build_style_map_from_template(os.path.join(tmp.name, "t"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bold_keyword_runs.py::TestPrepScript -v`
Expected: FAIL — module `prepare_template_bold_twins` does not exist.

- [ ] **Step 3: Implement the prep script**

Create `scripts/prepare_template_bold_twins.py`:

```python
#!/usr/bin/env python3
"""Bake exact bold twins for body styles into an HWPX template.

For each body style (paragraph/bullet/dash/star/note) that lacks an exact bold
twin in header.xml, clone its base <hh:charPr>, insert <hh:bold/>, assign the
next free id, append it, and bump <hh:charProperties itemCnt>. Idempotent: a
style that already has a twin is skipped. Repackages the .hwpx (preserving entry
order/compression) and regenerates assets/default_styles.json.

Usage: python3 scripts/prepare_template_bold_twins.py [path/to/template.hwpx]
"""
import os, re, sys, json, zipfile, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import generate_hwpx as G

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TEMPLATE = os.path.join(SKILL_DIR, "assets", "template.hwpx")
CACHE_PATH = os.path.join(SKILL_DIR, "assets", "default_styles.json")
STYLE_KEYS = ("paragraph", "bullet", "dash", "star", "note")


def _make_twin(base_xml, new_id):
    """Clone a base <hh:charPr> as id=new_id with <hh:bold/> inserted before
    <hh:underline> (the canonical position used by existing twins)."""
    twin = re.sub(r'(<hh:charPr )id="\d+"', r'\g<1>id="%d"' % new_id, base_xml, count=1)
    if '<hh:bold' not in twin:
        twin = re.sub(r'(<hh:underline\b)', r'<hh:bold/>\g<1>', twin, count=1)
    return twin


def prepare(template_path=DEFAULT_TEMPLATE):
    """Add missing body bold twins to the template. Returns list of
    (style_key, new_charPr_id) for the twins added (empty if none)."""
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(template_path) as zf:
            zf.extractall(os.path.join(td, "t"))
        sm = G.build_style_map_from_template(os.path.join(td, "t"))
    if sm is None:
        raise RuntimeError("could not build style map from template")

    with zipfile.ZipFile(template_path) as zf:
        header = zf.read("Contents/header.xml").decode("utf-8")

    chars = {m.group(1): m.group(0)
             for m in re.finditer(r'<hh:charPr id="(\d+)".*?</hh:charPr>', header, re.DOTALL)}
    next_id = max(int(c) for c in chars) + 1

    added = []
    base_to_twin = {}  # reuse a twin if two styles share a base
    new_blocks = []
    for key in STYLE_KEYS:
        base_id = sm[key][0]
        if G._find_bold_twin(header, base_id) != str(base_id):
            continue  # twin already exists
        if base_id in base_to_twin:
            added.append((key, base_to_twin[base_id]))
            continue
        twin_xml = _make_twin(chars[str(base_id)], next_id)
        new_blocks.append(twin_xml)
        base_to_twin[base_id] = str(next_id)
        added.append((key, str(next_id)))
        next_id += 1

    if not new_blocks:
        return []

    # Append new charPr blocks before </hh:charProperties> and bump itemCnt.
    header = header.replace("</hh:charProperties>",
                            "".join(new_blocks) + "</hh:charProperties>", 1)
    cur = int(re.search(r'<hh:charProperties itemCnt="(\d+)"', header).group(1))
    header = re.sub(r'(<hh:charProperties itemCnt=")\d+(")',
                    r'\g<1>%d\g<2>' % (cur + len(new_blocks)), header, count=1)

    _rewrite_zip(template_path, {"Contents/header.xml": header.encode("utf-8")})
    # Only refresh the committed cache when prepping the bundled template;
    # never touch it when a test (or a caller) preps a copy elsewhere.
    if os.path.abspath(template_path) == os.path.abspath(DEFAULT_TEMPLATE):
        _regenerate_cache(template_path)
    return added


def _rewrite_zip(path, replacements):
    """Rewrite a zip in place, replacing named entries; preserve order and
    per-entry compression. The 'mimetype' entry (stored first, uncompressed in
    OPC) is preserved by keeping the original order/compress_type."""
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        data = {i.filename: zf.read(i.filename) for i in infos}
    for name, blob in replacements.items():
        data[name] = blob
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w") as zf:
        for i in infos:
            zf.writestr(i, data[i.filename], compress_type=i.compress_type)
    os.replace(tmp, path)


def _regenerate_cache(template_path):
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(template_path) as zf:
            zf.extractall(os.path.join(td, "t"))
        sm = G.build_style_map_from_template(os.path.join(td, "t"))
    h = G.compute_template_hash(template_path)
    G.save_style_map_cache(CACHE_PATH, h, sm)


if __name__ == "__main__":
    tp = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEMPLATE
    result = prepare(tp)
    if result:
        print("Added bold twins:", ", ".join(f"{k}->{i}" for k, i in result))
    else:
        print("No twins added (all body styles already have exact twins).")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_bold_keyword_runs.py::TestPrepScript -v`
Expected: PASS (1 test). Note: this test copies the template, so it does NOT mutate the bundled `assets/template.hwpx`.

- [ ] **Step 5: Commit**

```bash
git add scripts/prepare_template_bold_twins.py tests/test_bold_keyword_runs.py
git commit -m "feat: idempotent template bold-twin prep script"
```

---

### Task 7: Run prep on the bundled template + regenerate artifacts

**Files:**
- Regenerate: `assets/template.hwpx`, `assets/default_styles.json`

- [ ] **Step 1: Run the prep script against the bundled template**

Run: `python3 scripts/prepare_template_bold_twins.py`
Expected output: `Added bold twins: dash->547, star->548` (paragraph/bullet/note already have twin 71, so they are skipped).

- [ ] **Step 2: Verify all five body styles now resolve to a real twin**

Run:
```bash
python3 -c "
import zipfile, tempfile, os
from scripts import generate_hwpx as G
td=tempfile.mkdtemp()
zipfile.ZipFile('assets/template.hwpx').extractall(os.path.join(td,'t'))
sm=G.build_style_map_from_template(os.path.join(td,'t'))
for k in ('paragraph','bullet','dash','star','note'):
    print(k, 'base', sm[k][0], 'bold', sm[k+'_bold'], 'OK' if sm[k+'_bold']!=sm[k][0] else 'FALLBACK')
"
```
Expected: every line prints `OK` (no `FALLBACK`).

- [ ] **Step 3: Verify default_styles.json hash matches the new template**

Run:
```bash
python3 -c "
import json
from scripts import generate_hwpx as G
d=json.load(open('assets/default_styles.json'))
print('hash match:', d['template_hash']==G.compute_template_hash('assets/template.hwpx'))
print('bold keys:', [k for k in d['style_map'] if k.endswith('_bold')])
"
```
Expected: `hash match: True` and all five `*_bold` keys present.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all PASS (no `no exact bold twin` warnings for the bundled template).

- [ ] **Step 5: Commit the regenerated artifacts**

```bash
git add assets/template.hwpx assets/default_styles.json
git commit -m "chore: bake dash/star bold twins into bundled template + regen cache"
```

---

### Task 8: End-to-end integration test

**Files:**
- Test: `tests/test_bold_keyword_runs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bold_keyword_runs.py`:

```python
class TestEndToEnd(unittest.TestCase):
    def test_generate_document_with_bold_keywords(self):
        config = {
            "include_cover": False,
            "sections": [{
                "type": "body",
                "title_bar": "테스트 보고서",
                "content": [
                    {"type": "heading", "text": "추진 배경"},
                    {"type": "paragraph",
                     "text": [{"t": "올해 "}, {"t": "목표 달성률", "bold": True},
                              {"t": "은 95%로 상승했다."}]},
                    {"type": "dash",
                     "text": [{"t": "핵심 "}, {"t": "지표", "bold": True}, {"t": " 개선"}]},
                ],
            }]
        }
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        out = os.path.join(tmp.name, "out.hwpx")
        G.generate_hwpx(config, out)

        self.assertTrue(zipfile.is_zipfile(out))
        with zipfile.ZipFile(out) as zf:
            secs = sorted(n for n in zf.namelist() if re.search(r'section\d+\.xml$', n))
            body = "".join(zf.read(n).decode("utf-8") for n in secs)

        sm = json.load(open(os.path.join(SKILL_DIR, "assets", "default_styles.json")))["style_map"]
        # paragraph bold run present with the discovered twin charPr
        self.assertIn('charPrIDRef="%s"><hp:t>목표 달성률</hp:t>' % sm["paragraph_bold"], body)
        # dash bold run present with its own twin charPr
        self.assertIn('charPrIDRef="%s"><hp:t>지표</hp:t>' % sm["dash_bold"], body)
        # heading rendered without a bold run
        self.assertIn("추진 배경", body)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python3 -m pytest tests/test_bold_keyword_runs.py::TestEndToEnd -v`
Expected: PASS. (Requires Task 7 done so the twins exist; this is the first test exercising the real bundled artifacts end-to-end.)

If the config schema in this repo differs (e.g. a top-level key other than `sections`/`type: body`), inspect `examples/sample_report.json` and adjust the config shape to match — keep the `content` items exactly as above.

- [ ] **Step 3: Commit**

```bash
git add tests/test_bold_keyword_runs.py
git commit -m "test: end-to-end bold keyword generation"
```

---

### Task 9: Documentation

**Files:**
- Modify: `SKILL.md` (Config JSON Structure section, around `:70`)
- Modify: `CHANGELOG.md` (top of file)

- [ ] **Step 1: Document the segment schema in SKILL.md**

In `SKILL.md`, under the Config JSON Structure section (around `:70`), add a subsection. Use this exact text:

```markdown
#### Bold keywords in body text

For `paragraph`, `bullet`, `dash`, `star`, and `note` items, `text` may be either
a plain string (no emphasis) or an array of segments to mark keywords bold:

```json
{ "type": "paragraph",
  "text": [
    {"t": "올해 "},
    {"t": "목표 달성률", "bold": true},
    {"t": "은 95%로 상승했다."}
  ] }
```

Each segment is `{"t": "<text>", "bold": <true|false>}` (`bold` defaults to false).
`heading` items ignore the array form (rendered as plain text); table cells do not
support segments. The bold style is discovered from the template; if you swap in a
template whose body styles lack a bold twin, run
`python3 scripts/prepare_template_bold_twins.py path/to/template.hwpx` to bake the
twins in (otherwise those segments render at normal weight, with a build warning).
```

- [ ] **Step 2: Add a CHANGELOG entry**

In `CHANGELOG.md`, add at the top (below the `# CHANGELOG` line):

```markdown
## [0.10.0] - 2026-05-29

### Bold keyword runs in body text

- **Bold segments.** `text` for paragraph/bullet/dash/star/note now accepts an
  array of `{t, bold}` segments; bold spans render as separate runs using a
  charPr discovered from the template (exact-twin match on font/size/color).
- **Weight-aware line counting.** `_char_width` accounts for bold glyph width
  (Hangul is weight-invariant; proportional glyphs widened) so line geometry
  stays accurate for segmented text.
- **Template prep.** `scripts/prepare_template_bold_twins.py` bakes missing exact
  bold twins (dash, star) into the bundled template; `default_styles.json` and
  `template.hwpx` regenerated. Backward compatible: string `text` is unchanged.
```

- [ ] **Step 3: Commit**

```bash
git add SKILL.md CHANGELOG.md
git commit -m "docs: document bold keyword segments + changelog 0.10.0"
```

---

## Final verification

- [ ] Run the full suite: `python3 -m pytest tests/ -q` → all PASS.
- [ ] Confirm no `no exact bold twin` warning prints for the bundled template:
  `python3 -c "from scripts import generate_hwpx as G; import zipfile,tempfile,os; td=tempfile.mkdtemp(); zipfile.ZipFile('assets/template.hwpx').extractall(os.path.join(td,'t')); G.build_style_map_from_template(os.path.join(td,'t'))"` → prints nothing.
- [ ] `git status` clean except intended changes.
