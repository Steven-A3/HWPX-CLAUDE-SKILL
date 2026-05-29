# Template table reuse + 개조식 authoring — Design

**Date:** 2026-05-29
**Status:** Approved (design)

## Problem

Two defects in how the skill produces Korean-government reports:

1. **Tables don't match the template.** `data_table_xml` fabricates borders: it
   applies a single `borderFillIDRef` to every header cell and a single one to
   every body cell, with equal column widths, fixed `row_height=2048`, and a
   single body alignment. The bundled MS_YOON template's real data tables use
   **~13 position-keyed border fills** (corner/edge/interior × header / first-body
   / interior / last-body) so the outer box, header separator, inner grid, and
   bottom border render correctly. Generated tables therefore look off-brand
   (wrong/missing outer borders, no header separator).

2. **Content is filled verbatim, not 개조식.** Nothing instructs the report author
   to transform source material into Korean-government **개조식(個條式)** style.
   An earlier article→report generation copied full 서술식 prose paragraphs almost
   verbatim — the opposite of a government report.

## Goal

- Generated tables reuse a real template table's per-cell styling so they match
  the template; content + line geometry are regenerated correctly.
- A binding SKILL.md rule set makes report content terse, itemized 개조식 — never
  a verbatim copy of the source.

## Non-goals

- No change to non-table content rendering (headings/bullets/etc. are fine).
- No automated 개조식 enforcement in code (it is an authoring/writing task; rules
  live in SKILL.md). A lint check was explicitly declined.
- No new column layouts beyond what the template provides; column counts with no
  template match fall back to the current generated table.

---

## Part A — Template table reuse

### A1. Discovery: a table-skeleton catalog

Extend `build_style_map_from_template` to scan the template's body section for
data tables and build a **catalog keyed by column count**. For each column count,
select one *clean* source table, preferring tables that:
- have **no** `rowSpan`/`colSpan` (a plain grid),
- have a recognizable header row (row 0), and
- have **≥2 body rows** (so first-body / interior / last-body styles can be
  distinguished).

From the chosen table, capture a **per-cell style profile** by position. For each
of these row roles — **header**, **first-body**, **interior-body**, **last-body** —
record, per column, the tuple:
`(borderFillIDRef, charPrIDRef, paraPrIDRef, width, cellMargin, vertAlign)`.

Store as a serializable entry `table_profiles` in the style map:
`{ "<ncols>": { "header": [cell,...], "first": [...], "interior": [...], "last": [...] } }`.
This persists into `assets/default_styles.json` (cache regenerated; keyed by
template hash).

If discovery finds no clean table for a given column count, that column count is
simply absent from the catalog (renderer falls back — see A2).

### A2. Rendering: `data_table_xml` uses the profile

For a data table of **N columns × R data rows**:

1. Look up `table_profiles[str(N)]`. **If absent → fall back** to the current
   generated table (preserve today's behavior) and `log()` a warning naming N.
2. **Header row:** for each column, emit a cell reusing the header profile's
   `borderFillIDRef` / `charPrIDRef` / `paraPrIDRef` / `width` / `cellMargin` /
   `vertAlign`; **regenerate** the cell's `<hp:t>` text and its `lineseg`
   (recomputed for that cell's own width and font height — mandatory because
   Hancom does not recalc lineseg; see memory `hancom_recalculates_lineseg`).
3. **Body rows:** map the R rows onto the body profiles by position:
   - R = 1 → use the **last-body** profile (its bottom border closes the table).
     The header-row/body separator is drawn by the header cells' own bottom
     border, so no special "combined" border fill is needed.
   - R ≥ 2 → row 1 = **first-body** profile, final row = **last-body** profile,
     all middle rows = **interior-body** profile.
   Each cell regenerates text + lineseg as in step 2.
4. **Geometry:** each row's height = max over its cells of the wrapped line count ×
   line height + vertical margins; the table `<hp:sz>` height = Σ row heights;
   `rowCnt = R+1`, `colCnt = N`. Column widths come from the profile (the
   template's own widths).

The cell-emitting helper is a generalization of `table_cell_xml` that takes a full
per-cell style profile instead of the current fixed args.

### A3. Fallback and widths

- Column widths are the template's (matching the template is the goal).
- Any data whose column count is not in the catalog uses the existing generated
  `data_table_xml` path unchanged. This guarantees no regression for shapes the
  template can't supply.

### A4. Verification

- Tamper note: report generation builds a **fresh** section from skeletons, so
  Rule 17 (which concerns in-place edits of a delivered doc) does not apply. The
  plan still verifies a generated document containing a reused table is a valid
  zip, well-formed, and that its table cells reference the **same**
  `borderFillIDRef`s as the chosen template source table.
- Round-trip: generated table cells read back correctly; `table_fixer` validation
  (if applicable) passes.

### A5. Affected code

- `scripts/generate_hwpx.py`
  - `build_style_map_from_template` — build and store `table_profiles`.
  - new discovery helper(s) to pick a clean source table per column count and
    extract per-position cell profiles (builds on `_extract_table_cells`).
  - `data_table_xml` — profile-driven rendering with generated-path fallback.
  - a per-cell-profile cell emitter (generalizing `table_cell_xml`); keep
    `table_cell_xml` for the fallback path.
  - `DEFAULT_STYLE_MAP` — add `table_profiles` default (`{}` → always falls back).
- `assets/default_styles.json` — regenerated with `table_profiles`.
- `tests/` — new tests.

### A6. Testing

1. **Discovery:** `table_profiles` is built for the common column counts present
   in the bundled template; each profile has header + first + interior + last with
   the right number of columns; cells carry distinct position-keyed border fills.
2. **Render fidelity:** a generated N-col table's header cells reference exactly
   the template source table's header `borderFillIDRef`s (corner/edge/interior),
   and body rows reference the first/interior/last fills; header is bold/centered
   per the profile.
3. **Row-count mapping:** R=1, R=2, R=5 produce correct first/interior/last row
   assignment and a bottom border on the final row.
4. **Lineseg correctness:** multi-line cell text gets a recomputed lineseg with the
   right line count for the cell width (not a copied/stale one).
5. **Fallback:** a column count absent from the template falls back to the
   generated table and logs a warning; output still valid.
6. **End-to-end:** a generated document with a reused table is a valid HWPX whose
   table cell border fills match the template source.

---

## Part B — 개조식 authoring rules (SKILL.md)

Add a section `## 개조식 Authoring Rules (MANDATORY)` to `SKILL.md`. Documentation
only — no engine code. Rules:

1. **Summarize, never transcribe.** Each source passage → its essential point(s).
   Never copy a sentence and lightly edit it.
2. **Nominalized / 음슴체 endings.** End lines on noun / nominal forms —
   `~함, ~필요, ~추진, ~예정, ~검토, ~전환` — never 서술식 `~한다 / ~이다 / ~했다`.
3. **One idea per line; hierarchy** `□` heading → `○` bullet → `-` dash → `*`
   detail. Split compound sentences into separate lines.
4. **Lead with a label** where natural: `(배경)`, `(현황)`, `(추진방향)`,
   `(기대효과)`.
5. **Strip connectives / redundant subjects;** keep numbers, proper nouns, key
   terms.
6. **Bold the key term** in each line via the `{t, bold}` segment feature.
7. **Tabulate enumerable / comparative data** (years, figures, categories) instead
   of writing it as prose — tables use Part A's template styling.

Include a worked **before → after** example:

> **서술식 (wrong, verbatim):** "AI가 인간 주니어 개발자보다 더 빠르고 정확하게 코드를
> 짜는 2026년, 진짜 중요한 능력은 '문법'이 아니라 '의도(Intent)'를 설계하는 능력이다."
>
> **개조식 (right):** `○ (핵심역량 전환)` AI가 코드 작성 대체 → 인간 경쟁력은
> **'의도(Intent) 설계'** 로 이동

### B1. Affected code / docs
- `SKILL.md` — new mandatory section with the seven rules + the before/after
  example.
- `CHANGELOG.md` — entry.

### B2. Testing
- No automated test (documentation). The plan verifies the section exists, is
  marked mandatory, and contains the seven rules + the worked example.

---

## Build order

Part A and Part B are independent. Part A (engine + tests) first, then Part B
(docs), then regenerate `default_styles.json` once as part of Part A.
