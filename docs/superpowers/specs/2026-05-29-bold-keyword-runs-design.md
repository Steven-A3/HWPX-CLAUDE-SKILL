# Bold keyword runs in body content — Design (rev. 2)

**Date:** 2026-05-29
**Branch:** feat/ms-yoon-template-and-appendix-title
**Status:** Approved (design), revised after adversarial self-review

## Problem

The MS_YOON 이노베이션아카데미 standard report (now the bundled engine template)
emphasizes selected keywords inside body sentences with **bold** weight. The
generator currently emits each body item's text as a single run with one
`charPrIDRef`, so there is no way for an author to mark a word or phrase as bold.
The template's `header.xml` already contains bold character properties
(100 charPrs carry `<hh:bold/>`); the feature reuses those rather than invent new
styling.

## Goal

Let an author mark spans of body text as bold in the source JSON, render those
spans as separate bold runs whose styling is **discovered from the template**,
and keep layout geometry correct (Hancom does not recalculate lineseg — see
memory `hancom_recalculates_lineseg`). Where the bundled template lacks an exact
bold twin for a body style, the twin is **baked into the template once** via a
preparation step so discovery succeeds for all five styles.

## Non-goals

- Bold in `heading` items, table cells, or anything beyond the five body types.
- Italic, underline, color, or any emphasis other than bold.
- **Runtime** synthesis of charPr definitions. The runtime stays pure discovery;
  the only place a twin is created is the one-time template-preparation step
  (§"Template preparation"), which writes it into the template artifact.

---

## Revisions from rev. 1 (adversarial review findings)

Three weaknesses were found in rev. 1 and are addressed below:

1. **Layout was *not* invariant.** Rev. 1 claimed splitting a run leaves line
   math unchanged "because the plain text is identical." False for proportional
   (Latin/digit) glyphs: bold widens them, and the width model `_char_width`
   ignored weight. See §"Layout / line-count math".
2. **Discovery's loose fallback was unsafe.** Measured on the bundled template:
   `paragraph`/`bullet`/`note` (base charPr 38) have an exact bold twin
   (charPr 71), but `dash` (397) and `star` (273) have **none** — their bases
   differ by `spacing="-14"` and a distinct `borderFillIDRef`. Rev. 1 would have
   fallen back to the lowest-id bold charPr sharing only font+height, silently
   rendering a different **color/spacing/border**. The loose fallback is removed;
   instead the missing `dash`/`star` twins are baked into the template by a
   one-time prep step so discovery succeeds. See §"Bold-style discovery" and
   §"Template preparation".
3. **Other code paths were unaudited.** Confirmed during review: both body
   render paths (`generate_body_section_xml` skeleton path and fully-generated
   fallback) emit content via `generate_content_item`; `render_paragraph` /
   `insert_paragraph_from_template` are **not** in the body path.
   `_extract_paragraph_first_text` joins all `<hp:t>` nodes, so multi-run
   paragraphs read back intact. No second renderer needs changing; regression
   tests are added to lock this in. See §"Affected code" and §"Testing".

---

## Authoring interface

Every supported body item's `text` field accepts **either** form:

1. **Plain string** (unchanged) — renders exactly as today, single run.
2. **Array of segments** — each segment an object with required string `t` and
   optional boolean `bold` (default `false`):
   ```json
   { "type": "paragraph",
     "text": [
       {"t": "올해 "},
       {"t": "목표 달성률", "bold": true},
       {"t": "은 95%로 상승했다."}
     ] }
   ```

A normalizer collapses both forms to a canonical list of `(text, bold)` tuples
(string `s` → `[(s, False)]`).

### Scope

Segment arrays are honored for `paragraph`, `bullet`, `dash`, `star`, `note`.
`heading` flattens a segment array to plain text (bold ignored, no error). Table
cells do not support segments.

---

## Layout / line-count math (rev. 1 fix #1)

Rev. 1 fed the flattened plain text to `estimate_line_count`, implicitly assuming
bold does not change width. That holds for **Hangul/CJK** glyphs — they occupy a
fixed em square and `_char_width` returns the full `char_height` regardless of
weight, so bolding them does **not** change advance width or wrapping. Korean
report bodies are overwhelmingly Hangul, so the common case is genuinely
layout-safe, and this is now stated as a justified fact, not an assumption.

It does **not** hold for proportional glyphs (Latin letters, digits, ASCII), for
which `_char_width` returns a fraction of `char_height` and bold visibly widens
the glyph. To account for this:

- `_char_width(ch, char_height, bold=False)` gains an optional `bold` flag. For
  Hangul/CJK/fullwidth/box-drawing/symbol glyphs it returns `char_height`
  unchanged (weight-invariant). For proportional ASCII alpha/digit glyphs it
  multiplies the existing width by a bold factor (`BOLD_WIDTH_FACTOR`, ~1.1).
- The array path computes its line count with a new
  `_segmented_line_count(segments, char_height, horzsize)` that accumulates
  per-character widths using each segment's `bold` flag, instead of flattening
  and calling `estimate_line_count`. The string path is unchanged and still calls
  `estimate_line_count`.
- The flattened plain text is still passed as `full_text` to `lineseg_xml` (so
  the rendered text content and `<hp:t>` round-trip are correct); only the
  **line count** is computed with weight awareness.

This means a near-margin bold Latin phrase that pushes content onto an extra line
is counted as an extra line, so the computed lineseg geometry matches what Hancom
renders. Hangul-only bold continues to match the string-form line count exactly.

---

## Run emission

`generate_content_item` keeps two paths per supported type:

- **String text** → existing single-run path, byte-identical to today:
  `run_xml(base, full_text) + run_xml(end)`.
- **Array text** → multi-run path:
  1. Emit the marker/indent **prefix** as a normal run with the base charPr
     (`paragraph` `" "`, `bullet` `" ㅇ "`, `dash` `"   - "`, `star` `"     * "`,
     `note` `"▷ "`).
  2. Emit **one run per segment**: base charPr if `bold` is false, the discovered
     **bold** charPr if true. `run_xml`/`xml_escape` handle escaping.
  3. Emit the existing trailing `*_end` run unchanged.

A shared helper builds the run XML from the canonical segment list, base charPr,
bold charPr, and prefix, so all five types share one implementation.

---

## Bold-style discovery (rev. 1 fix #2 — exact twin only)

`build_style_map_from_template` resolves a bold charPr id for each body base
style and stores `paragraph_bold`, `bullet_bold`, `dash_bold`, `star_bold`,
`note_bold` in the style map (persisted to `assets/default_styles.json`; cache
regenerated since it is keyed by template hash).

`_find_bold_twin(header_xml, base_id)` returns an **exact twin only**:

- Parse the base `<hh:charPr>` and every `bold=True` candidate. A candidate is a
  twin iff, after removing the `id` attribute and the `<hh:bold/>` element, its
  attribute set and child-element set are **identical** to the base's (order- and
  whitespace-insensitive, compared structurally). This guarantees the bold run
  matches the base in font, size, color, spacing, border, and all decorations —
  differing only in weight.
- **No loose fallback.** If no exact twin exists, return the **base id** (bold
  segments in that style render at normal weight) and emit a prominent warning
  naming the style and stating that bold will not apply. The loose font+height
  match from rev. 1 is deliberately removed because it silently changes visible
  attributes (the dash base differs by `spacing="-14"` and `borderFillIDRef`).

### Coverage on the bundled template (after preparation)

| body style | base charPr | exact twin |
|---|---|---|
| paragraph / bullet / note | 38 | **71** (already present) |
| dash | 397 | **547** (added by prep step) |
| star | 273 | **548** (added by prep step) |

`dash`/`star` originally lacked an exact twin because their base charPr carries a
unique `spacing="-14"` / `borderFillIDRef`. Rather than leave their bold inert or
do unsafe loose matching, the preparation step (below) adds the missing exact
twins to the template so all five styles resolve. The exact-twin-only +
base-fallback runtime logic is unchanged and now finds a twin for every body
style on the bundled template; the base fallback remains a safety net for any
future template that ships without prep.

---

## Template preparation (one-time, committed)

A small, **idempotent** maintenance script `scripts/prepare_template_bold_twins.py`
ensures every body base style has an exact bold twin in the bundled template:

1. Resolve the five body base charPr ids from the current template via the same
   discovery used at build time.
2. For each base, run `_find_bold_twin`. If an exact twin already exists
   (e.g., 38→71), do nothing.
3. If none exists, **clone the base `<hh:charPr>`**, insert `<hh:bold/>` in the
   canonical position (immediately before `<hh:underline>`, matching how existing
   twins like 71 are ordered), assign the next free id, append it to
   `<hh:charProperties>`, and bump `itemCnt` accordingly.
4. Repackage `assets/template.hwpx` (preserving entry compression/order) and
   regenerate `assets/default_styles.json` (cache is keyed by template hash).

On the current template this adds exactly two charPrs: **547** (clone of dash base
397 + bold) and **548** (clone of star base 273 + bold); `itemCnt` goes 547 → 549,
ids stay contiguous (0–548). The script is committed and re-runnable: a second run
is a no-op because the twins now exist (idempotent — guards against double-adding).

**Tamper-detection note.** Rule 17 (SKILL.md) concerns *section-level insertion of
a new table paragraph combined with other section edits* in a delivered document.
The prep step only adds well-formed `charPr` **definitions** to `header.xml` and
corrects `itemCnt`; it is a build-time template artifact change, not a section
edit, and is outside Rule 17's trigger. The plan still includes verifying the
prepared template and a document generated from it open cleanly (round-trip /
existing structural tests) before the change is considered done.

---

## Validation

- A segment array element that is not an object, or whose `t` is missing or not a
  string, raises `ValueError` identifying the offending item (by content index)
  and segment index.
- `bold` present but non-boolean is coerced via `bool()` (documented).
- Empty-string / whitespace-only segments are permitted and pass through.

---

## Affected code

- `scripts/generate_hwpx.py`
  - `_char_width` — add optional `bold` flag (Hangul/CJK weight-invariant;
    proportional glyphs widened by `BOLD_WIDTH_FACTOR`).
  - new `_segmented_line_count` helper (weight-aware line count for arrays).
  - new segment normalizer + validation helper.
  - new run-builder helper for segmented text.
  - new `_find_bold_twin` helper (exact-twin-only).
  - `build_style_map_from_template` — resolve and store the five `*_bold` keys.
  - `DEFAULT_STYLE_MAP` — add the five `*_bold` keys (fallback = base id).
  - `generate_content_item` — dual path for the five supported types.
- `scripts/prepare_template_bold_twins.py` — **new** one-time/idempotent prep
  script that adds missing exact bold twins to the bundled template.
- `assets/template.hwpx` — regenerated with the two added twins (547, 548).
- `assets/default_styles.json` — regenerated with the new keys (all five `*_bold`
  now resolve to exact twins).
- `SKILL.md` — segment schema, body-only scope, and a note on running the prep
  script when swapping templates.
- `CHANGELOG.md` — new entry.

No change to `render_paragraph` / `insert_paragraph_from_template` — confirmed not
in the body content path.

---

## Testing

1. **Round-trip bold.** A `paragraph` with a bold segment yields a section where
   exactly the bold run carries the discovered bold charPrIDRef (71 on the bundled
   template) and normal runs carry the base charPr.
2. **Backward-compat.** String `text` yields output byte-identical to the
   pre-change generator for the same input.
3. **Hangul layout safety (honest, not self-referential).** A Hangul-only bold
   segment produces the **same line count** as the equivalent plain string — proves
   the weight-invariant path for Hangul.
4. **Latin bold widening.** A Latin/digit-heavy line, when bolded, produces a line
   count **≥** the same text at normal weight — proves `_char_width`'s bold factor
   is actually applied (this is the test rev. 1 lacked; it would have caught the
   width bug).
5. **Discovery — exact only.** `_find_bold_twin` returns a true twin (identical
   minus `<hh:bold/>`) for base 38, and the **base id** (no exception, no loose
   match) for a synthetic base with no twin. After prep, **all five** body styles
   resolve to an exact twin on the bundled template (assert each `*_bold` ≠ its
   base and is a true twin).
9. **Prep step.** `prepare_template_bold_twins.py` adds exactly the missing twins,
   bumps `itemCnt` correctly, keeps ids contiguous, and is **idempotent** (a second
   run adds nothing). The prepared template and a document generated from it pass
   the existing structural/round-trip checks (well-formed XML, valid refs,
   `itemCnt` matches actual count).
6. **Heading flattening.** A `heading` given a segment array renders plain text,
   no bold run, no error.
7. **Read-back / detection.** A segmented multi-run paragraph: `_extract_paragraph_first_text`
   returns the flattened plain text, and marker-based classification
   (`_count_body_headings` / paragraph classification) is unaffected.
8. **Validation.** A malformed segment raises `ValueError` naming the item.
