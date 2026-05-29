# MS_YOON Template Adoption + 붙임 Title Fix — Design

**Date:** 2026-05-27
**Status:** Approved (brainstorming)

## Goal

The skill must reliably generate the standard 이노베이션아카데미 report shape seen in
`assets/MS_YOON_TEMPLATE.pdf`: **one main body (본문)** followed by an **attachment
(붙임)** whose title bar is correctly filled (`붙임 │ <title>`). Adopt the
MS_YOON template as the engine template and add regression tests.

## Background / findings

- `assets/MS_YOON_TEMPLATE.hwpx` (user-converted from `.hwp`) is a **finished
  29-page document in a single `section0.xml`** (1816 paragraphs). Headings use
  `styleIDRef="14/54"`, **not `"15"`**. Its `header.xml` carries the real fonts
  (HY헤드라인M, 휴먼명조, 맑은 고딕 …) and every bar already exists:
  main title bar (3×1), `붙임 │ 사업 안건별 현황 조사` (1×3), numbered section
  bars 1~8 (1×3), and 참고1~3 (1×3).
- The engine (`scripts/generate_hwpx.py`) is **template-skeleton based** and
  assumes: a separate body section + appendix section, and `styleIDRef="15"`
  for body headings. Neither holds for MS_YOON.
- **Confirmed bug ("fill the 붙임 title"):** `inject_appendix_labels()` assumes
  the appendix title cell has *two* `<hp:t>` runs (space + title) and writes a
  bare space into the first match. Real bars (old template *and* MS_YOON) use a
  *single* combined run, so the title is silently dropped. Reproduced:
  generated 붙임 bar → `col0='참고1'  col2=' '` (title lost).

## Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| MS_YOON role | Adopt as engine template |
| Template wiring | **Overwrite `assets/template.hwpx`** with MS_YOON content (keep canonical filename) |
| Scope | Core fix + structure (no new PDF markers this round) |
| Missing 붙임 title | **Hard error** (`ValueError`) |
| Approach | **Approach L** — adopt MS_YOON directly + targeted engine fixes (reuses real title-bar bytes for body; routes 붙임 bar through the existing tested fallback generator with correctly-discovered styles). Lower-risk than hand-building skeleton sections. |

## Engine changes — `scripts/generate_hwpx.py`

1. **`inject_appendix_labels()` — fix single-run title injection.**
   In the `colAddr==2` cell, replace the title text robustly whether the cell has
   one combined `<hp:t>` or a separate space-run + title-run. Net result: the
   title text always lands in the title cell; no bare-space output. Keep tab-label
   (col 0) behavior. `inject_body_title()` already handles single-run cells — no
   change needed there, but covered by a test.

2. **Empty-title guard.** `generate_appendix_section_xml()` raises
   `ValueError("appendix section '<tab>' is missing 'appendix_title'")` when
   `appendix_title` is empty/blank. Surfaced from `generate_hwpx()` so the CLI
   fails loudly.

3. **Marker-based body/heading detection.** Add `_count_body_headings(xml)` that
   counts top-level `□` heading paragraphs by marker text. Use it in:
   - `_detect_template_sections()` to pick the body section (fallback to the old
     `styleIDRef="15"` count if no `□` found — back-compat with old template).
   - the cover-page check in `generate_hwpx()` (otherwise MS_YOON's body section,
     having zero `styleIDRef="15"`, is misread as a cover and corrupted).
   - Single-section templates: when no *distinct* appendix section exists,
     `appendix_path` falls back to the body section (never `None`).

4. **Appendix-bar style discovery.** In `build_style_map_from_template()` Phase E,
   locate the appendix bar by scanning the appendix section for a 1×3 table whose
   col-0 text is `붙임`/`참고` (instead of assuming the *first* colPr paragraph,
   which on MS_YOON is the 3×1 title bar). Guard Phase E against
   `appendix_path is None`. This binds `appendix_tab/sep/title` + `bf_appendix_*`
   to MS_YOON's real bar.

5. **Template wiring.** Overwrite `assets/template.hwpx` with MS_YOON content;
   regenerate `assets/default_styles.json` for the new template hash (cache is
   hash-keyed, so a stale cache auto-misses — regenerate to keep the fast path).

## Structure & docs

- Canonical example config = **본문 + 붙임(title filled)** demonstrating
  heading/bullet/dash/star + a table in the body and a filled 붙임 attachment.
- `SKILL.md`: document the 본문+붙임 structure, the **required** `appendix_title`
  for appendix sections, and the template adoption.

## Tests (TDD — `tests/test_appendix_title_and_template.py`)

Write first, confirm they fail against current code, then implement:

1. `inject_appendix_labels` injects the title for a **single-run** title cell
   (regression for the bug) and for a **two-run** cell.
2. End-to-end: generating a config with an appendix produces a 붙임/참고 bar whose
   col-2 text **equals the title** (not a bare space).
3. Empty `appendix_title` → `ValueError`.
4. Generated document has body + 붙임 sections with the expected tab labels and
   uses the MS_YOON fonts (e.g. header contains `HY헤드라인M`).
5. Marker-based body detection picks the body section on a `styleIDRef!=15`
   template; cover misdetection does not occur.
6. All 46 existing tests remain green.

## Verification checkpoint (requires user / Hancom)

Generated `.hwpx` must open in Hancom Office with **no tamper/corruption warning**
(Rules 9–17). I cannot run Hancom; the user validates a generated sample.

## Out of scope (this round)

`⇨` arrow bullets, `**` double-footnotes, colored category-row tables, navy ①②
sub-headers, process-flow diagrams, region maps. (Deferred — "Core + new markers"
option was not selected.)
