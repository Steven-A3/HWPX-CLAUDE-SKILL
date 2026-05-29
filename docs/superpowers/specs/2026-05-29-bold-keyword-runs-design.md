# Bold keyword runs in body content — Design

**Date:** 2026-05-29
**Branch:** feat/ms-yoon-template-and-appendix-title
**Status:** Approved (design)

## Problem

The MS_YOON 이노베이션아카데미 standard report (now the bundled engine template)
emphasizes selected keywords inside body sentences with **bold** weight. The
generator currently emits each body item's text as a single run with one
`charPrIDRef`, so there is no way for an author to mark a word or phrase as bold.
The template's `header.xml` already contains bold character properties
(100 charPrs carry `<hh:bold/>`); the feature should reuse those rather than
invent new styling.

## Goal

Let an author mark spans of body text as bold in the source JSON, and have the
generator render those spans as separate bold runs whose styling is discovered
from the template, while leaving layout math and all existing (string-text)
output byte-identical.

## Non-goals

- Bold in `heading` items (headings already use a distinct emphasized style).
- Bold in table cells (`table_cell_xml` is a separate code path; out of scope).
- Italic, underline, color, or any emphasis other than bold.
- Synthesizing new charPr definitions. Bold styling is discovered from the
  template only.

## Authoring interface

Every supported body item's `text` field accepts **either** form:

1. **Plain string** (unchanged) — renders exactly as today, single run:
   ```json
   { "type": "paragraph", "text": "올해 목표 달성률은 95%로 상승했다." }
   ```

2. **Array of segments** — each segment is an object with a required string `t`
   and an optional boolean `bold` (default `false`):
   ```json
   { "type": "paragraph",
     "text": [
       {"t": "올해 "},
       {"t": "목표 달성률", "bold": true},
       {"t": "은 95%로 상승했다."}
     ] }
   ```

A normalizer collapses both forms to a canonical list of `(text, bold)` tuples:
- string `s` → `[(s, False)]`
- array → `[(seg["t"], bool(seg.get("bold", False))) for seg in array]`

The **flattened plain text** (concatenation of every segment's `t`) is what feeds
`estimate_line_count` and the `full_text` argument to `lineseg_xml`. For the
example above the flattened text is `"올해 목표 달성률은 95%로 상승했다."`, identical
to the string form — so line-count estimation and `VertPosTracker` advancement
are unchanged. This matters because Hancom Office does not recalculate lineseg
(see memory `hancom_recalculates_lineseg`); the computed line geometry must stay
accurate and must not drift when a run is split into segments.

### Scope

Segment arrays are honored for: `paragraph`, `bullet`, `dash`, `star`, `note`.

- `heading`: a segment array is **flattened to plain text** (bold ignored). No
  error.
- Table cells: unaffected; segment arrays are not supported there.

## Run emission

`generate_content_item` keeps two code paths per supported item type:

- **String text** → the existing single-run path is used verbatim:
  `run_xml(base, full_text) + run_xml(end)`. Output is byte-identical to today.
- **Array text** → multi-run path:
  1. Emit the marker/indent **prefix** as a normal run with the item's base
     charPr. Prefixes per type: `paragraph` `" "`, `bullet` `" ㅇ "`,
     `dash` `"   - "`, `star` `"     * "`, `note` `"▷ "`.
  2. Emit **one run per segment**: base charPr when `bold` is false, the
     discovered **bold** charPr when `bold` is true. Text is XML-escaped by the
     existing `run_xml`/`xml_escape`.
  3. Emit the existing trailing `*_end` run unchanged (where the type has one).

Adjacent normal runs (prefix + leading normal segment) are acceptable HWPX and
need not be merged.

A shared helper builds the run XML from the canonical segment list, the base
charPr id, the bold charPr id, and the prefix string, so all five item types use
one implementation.

## Bold-style discovery

`build_style_map_from_template` resolves a bold charPr id for each body base
style and stores it in the style map as:
`paragraph_bold`, `bullet_bold`, `dash_bold`, `star_bold`, `note_bold`.

Discovery is performed by a new helper `_find_bold_twin(header_xml, base_id)`:

1. **Exact twin (preferred).** Take the base style's full `<hh:charPr>` element;
   strip its `id` attribute and any `<hh:bold/>` child to form a normalized
   signature. For each catalog charPr with `bold=True`, compute the same
   normalized signature (id + `<hh:bold/>` removed). A candidate whose normalized
   signature **exactly equals** the base's is an exact twin — identical font,
   size, color, and spacing, differing only in weight. Lowest matching id wins
   (deterministic).
2. **Loose match.** If no exact twin exists, match any `bold=True` charPr with
   the same `(face, height)` as the base (the data already in the char catalog).
   Lowest matching id wins.
3. **Base fallback.** If neither matches, use the base charPr id itself; bold
   segments in that style render as normal weight. Emit a one-line warning naming
   the style. No error, no synthesis.

The resolved bold ids are written into the style map and therefore persisted to
`assets/default_styles.json`. Because the cache is keyed by template hash, the
cache is regenerated as part of this change so the new keys are present.

## Validation

- A segment array element that is not an object, or whose `t` is missing/not a
  string, raises `ValueError` identifying the offending item (by content index)
  and segment.
- `bold` that is present but not boolean → coerced via `bool()`; documented.
- Empty-string and whitespace-only segments are permitted and pass through
  unchanged.

## Affected code

- `scripts/generate_hwpx.py`
  - `generate_content_item` — dual path for the five supported types.
  - new run-builder helper for segmented text.
  - new segment normalizer + validation helper.
  - `_find_bold_twin` helper.
  - `build_style_map_from_template` — resolve and store the five `*_bold` keys.
  - `DEFAULT_STYLE_MAP` — add the five `*_bold` keys (fallback values).
- `assets/default_styles.json` — regenerated with the new keys.
- `SKILL.md` — document the segment schema and body-only scope.
- `CHANGELOG.md` — new entry.

## Testing

1. **Round-trip bold.** A `paragraph` (and one other type) with a bold segment
   produces a section where exactly the bold run carries the discovered bold
   charPrIDRef and the normal runs carry the base charPr.
2. **Backward-compat.** String `text` yields output byte-identical to the
   pre-change generator for the same input (regression guard against accidental
   path changes).
3. **Layout invariance.** Flattened plain text equals the string form, so
   `estimate_line_count` and the resulting `vertpos`/`lineseg` values match the
   string-form output for the same visible text.
4. **Discovery.** `_find_bold_twin` returns an exact twin for at least one body
   base style on the MS_YOON template; the base-fallback path returns the base id
   (no exception) when given a style with no bold twin.
5. **Heading flattening.** A `heading` given a segment array renders its plain
   text with no bold run and does not raise.
6. **Validation.** A malformed segment raises `ValueError` naming the item.
