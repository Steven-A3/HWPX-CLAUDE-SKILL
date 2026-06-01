---
name: hwpx
description: "**HWPX Document Generator**: Create Korean government-style HWPX (한글) documents with proper formatting, tables, headers, and cover pages based on the 이노베이션아카데미 standard report template. Supports structured reports with title headers, hierarchical content (□/ㅇ/-/* markers), data tables, and appendix sections.\n  - MANDATORY TRIGGERS: HWPX, .hwpx, 한글, 한글파일, HWP, 보고서, 업무보고, 한컴, Hancom"
---

# HWPX Document Generator

## Overview

HWPX is the modern XML-based format for Hancom Office (한글). It is a ZIP archive containing XML files following the OWPML (KS X 6101) standard. This skill generates properly formatted HWPX documents that open correctly in Hancom Office.

The bundled template (`assets/template.hwpx`) is the **MS_YOON 이노베이션아카데미 standard report** — a real government-style report carrying the correct fonts (HY헤드라인M, 휴먼명조, 맑은 고딕 …), the main title bar, and the 붙임/참고 attachment bars. The canonical document shape is **one main body (본문) + one attachment (붙임)**; see `examples/sample_report.json`.

## Architecture: Template-Based Generation

This skill uses a **template-based approach** for reliable HWPX generation:

1. **header.xml** is copied verbatim from a known-good template (contains all font, style, border definitions)
2. **Section skeletons** (title bar, date line, spacer) are extracted from the template's section1.xml and section2.xml, with dynamic text injected via structural pattern matching
3. **Content paragraphs** (headings, bullets, tables, etc.) are generated dynamically and appended after the skeleton
4. **META-INF**, **version.xml**, **settings.xml** are copied from the template
5. **BinData** (logos/images) are preserved from the template

This approach ensures Hancom Office compatibility because the complex header.xml and structural section XML (secPr, colPr, title bar tables) come directly from a Hancom-saved template. If the template sections cannot be parsed, the generator falls back to fully-generated XML.

**Template customization**: Editing the template in Hancom Office (e.g., changing fonts, colors, or layout in the title bar) will propagate to all generated documents automatically.

### Byte-Preserving Editing Architecture

For reading and modifying existing HWPX files, a separate set of modules enforces **byte-level XML preservation**:

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  zip_handler.py │────→│  read_hwpx.py    │────→│ (analysis only) │
│  (ZIP I/O with  │     │  (etree parsing   │     │  structure info  │
│  compress_type  │     │   for analysis,   │     │  style catalog   │
│  preservation)  │     │   NO tostring())  │     │  table inventory │
└────────┬────────┘     └──────────────────┘     └─────────────────┘
         │
         │              ┌──────────────────┐     ┌─────────────────┐
         └─────────────→│  modify_hwpx.py  │────→│ (byte surgery)  │
                        │  (str.replace &  │     │  text replace    │
                        │   regex on raw   │     │  para insert     │
                        │   XML bytes)     │     │  row insert      │
                        └────────┬─────────┘     └─────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
            ┌──────────┐ ┌────────────┐ ┌────────────┐
            │xml_templ │ │table_fixer │ │zip_handler │
            │ates.py   │ │.py         │ │.py         │
            │(pattern  │ │(rowCnt,    │ │(repackage  │
            │ extract  │ │ cellAddr,  │ │ with same  │
            │ & render)│ │ rowAddr    │ │ compress   │
            │          │ │ auto-fix)  │ │ types)     │
            └──────────┘ └────────────┘ └────────────┘
```

**Core principle**: `etree.parse()`는 분석(read) 전용. 수정(write)은 반드시 원본 바이트에 문자열 연산으로 수행. `etree.tostring()`은 최종 출력에 절대 사용 금지.

## How to Use

Run the Python script to generate HWPX:

```bash
python SKILL_DIR/scripts/generate_hwpx.py --output OUTPUT_PATH --config CONFIG_JSON
```

Where `SKILL_DIR` is the directory containing this SKILL.md file, and `CONFIG_JSON` is a JSON file describing the document content.

### Config JSON Structure

```json
{
  "title": "보고서 제목",
  "subtitle": "부제목 (optional)",
  "date": "2026.02.14.",
  "department": "담당부서",
  "include_cover": true,
  "sections": [
    {
      "type": "body",
      "title_bar": "본문 제목",
      "content": [
        {"type": "heading", "text": "첫 번째 항목"},
        {"type": "paragraph", "text": "본문 내용입니다."},
        {"type": "bullet", "text": "하위 항목"},
        {"type": "dash", "text": "세부 항목"},
        {"type": "star", "text": "상세 내용"},
        {"type": "table", "caption": "표 제목",
         "headers": ["항목", "내용", "비고"],
         "rows": [["데이터1", "설명1", "비고1"], ["데이터2", "설명2", "비고2"]]},
        {"type": "note", "text": "참고 내용"}
      ]
    },
    {
      "type": "appendix",
      "title_bar": "붙임",
      "appendix_title": "붙임 제목",
      "content": [...]
    }
  ]
}
```

**Appendix / attachment sections (붙임 · 참고):**

- `title_bar` is the **tab label** in the bar's left cell — use `"붙임"` for an
  attachment or `"참고1"`, `"참고2"`, … for numbered references.
- `appendix_title` is the **bar title text** (the right cell). It is
  **required** for `appendix` sections — generation raises `ValueError` if it is
  missing or blank, so a 붙임/참고 bar can never ship with an empty title.
- The title is injected whether the template's title cell uses a single combined
  text run or a separate space-run + title-run.

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

### Content Types and Style Mapping

| Type | Marker | Role |
|------|--------|------|
| `heading` | □ | Section heading (LEFT-aligned, large) |
| `paragraph` | (none) | Plain body text |
| `bullet` | ㅇ | First-level bullet (JUSTIFY, hanging indent) |
| `dash` | - | Second-level item (JUSTIFY, hanging indent) |
| `star` | * | Footnote/detail (smaller) |
| `note` | ▷ | Post-table note |
| `table` | (table) | Data table with header row + body rows |
| `title_bar` | (bar) | Body section title bar (3×1) |
| `appendix_bar` | (bar) | 붙임/참고 attachment bar (1×3: tab │ sep │ title) |

The concrete fonts, sizes and `charPr`/`paraPr` IDs are **auto-discovered from the
template** at generation time (the discovered map is cached in
`assets/default_styles.json`, keyed by the template's hash). The skill matches the
five marker glyphs (`□`/`ㅇ`/`-`/`*` and the post-table note) by text and binds
each to the template's most-common paraPr for that marker — so changing the
template's marker styles in Hancom propagates automatically and no IDs are
hard-coded against a specific template.

### Section Types

- **`body`** (본문): Standard report body section with title bar and content.
- **`appendix`** (붙임 · 참고): Attachment section with a tab-style bar. Set
  `title_bar` to the tab label (`"붙임"`, `"참고1"`, …) and `appendix_title` to the
  bar title (**required** — see above).

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

## HWPX File Structure Reference

```
document.hwpx (ZIP)
├── mimetype                    # "application/hwp+zip" (STORED, first entry)
├── version.xml                 # Format version
├── settings.xml                # Application settings
├── META-INF/
│   ├── container.xml           # Root file references
│   ├── container.rdf           # RDF relationships
│   └── manifest.xml            # Manifest
├── Preview/
│   └── PrvText.txt             # Preview text
├── Contents/
│   ├── content.hpf             # OPF package manifest
│   ├── header.xml              # Style definitions (fonts, charPr, paraPr, borderFills, styles)
│   ├── section0.xml            # Cover page
│   ├── section1.xml            # Body section(s)
│   └── section2.xml            # Appendix section(s)
└── BinData/
    ├── image1.png              # Logo image
    └── image2.jpg              # Organization image
```

## Critical HWPX Rules

1. **mimetype must be first ZIP entry**, stored uncompressed (no compression)
2. **Section root tag**: `<hs:sec>` (NOT `<hp:sec>`)
3. **First paragraph** in each section must contain `<hp:secPr>` with page layout
4. **Namespace URIs**: `http://www.hancom.co.kr/hwpml/2011/...` (section, paragraph, core, head)
5. **Tables**: `<hp:tbl>` → `<hp:tr>` → `<hp:tc>` → `<hp:subList>` → `<hp:p>`
6. **Each paragraph must have** `<hp:linesegarray>` after all runs
7. **charPrIDRef** and **paraPrIDRef** must reference valid IDs in header.xml
8. **content.hpf** must list all sections and binary data in manifest and spine

## Critical Integrity Rules (Lessons Learned)

These rules were discovered through production failures where generated files were rejected by Hancom Office:

### Rule 9: NO lxml/etree Serialization on Original XML
- **Problem**: 원본 HWPX XML은 한 줄 compact 포맷이다. `lxml`이나 `etree.tostring()`으로 재직렬화하면 pretty-print/속성 재정렬이 발생하여 한컴오피스가 변조(corruption)로 감지한다.
- **Solution**: 최종 출력에 `etree.tostring()` 절대 사용 금지. 원본 XML 바이트를 그대로 보존하고, 문자열 삽입(string surgery) 방식으로 수정한다.
- **Pattern**: 파싱은 `etree.parse()`로 하되 분석 전용. 수정은 원본 바이트에 `str.replace()` 또는 정규식으로 처리.
- **Applies to**: `read_hwpx.py` (분석만), `modify_hwpx.py` (바이트 보존 편집), `xml_templates.py` (문자열 치환)

### Rule 10: Table rowCnt/cellAddr Consistency (with colSpan + rowSpan)
- **Problem**: `<hp:tbl>` 의 `rowCnt` 속성이 실제 `<hp:tr>` 개수와 불일치하면 파일 열기 오류 발생.
- **Solution**: 테이블 수정(행 추가/삭제) 후 반드시 `rowCnt`, `cellAddr`, `rowAddr` 를 일괄 업데이트한다.
- **Validation**: `table_fixer.py`가 모든 테이블의 정합성을 자동 검증/수정.
- **Formula**: `rowCnt = len(tr_elements)`, `rowAddr = row_idx` (0-based)
- **colAddr Formula**: 셀 병합(colSpan)과 행 병합(rowSpan)을 모두 고려한 논리적 그리드 위치 계산:
  ```
  # 1단계: 모든 행의 rowSpan 점유 열을 한 번에 계산 (O(R*C))
  occupied_sets = _build_occupied_sets(rows_addrs)

  # 2단계: 각 행에서 점유된 열을 건너뛰며 colAddr 할당
  for row_idx, row in enumerate(rows):
      occupied = occupied_sets[row_idx]
      logical_col = 0
      for cell in row:
          while logical_col in occupied:
              logical_col += 1   # rowSpan으로 점유된 열 건너뜀
          cell.colAddr = logical_col
          logical_col += cell.colSpan   # colSpan>1이면 병합 열 건너뜀
  ```
- **colSpan Example**: colCnt=3, Row 0에 colSpan=2 셀 + 일반 셀 → colAddr=0, colAddr=2 (1을 건너뜀)
- **rowSpan Example**: colCnt=3, Row 0의 첫 셀이 rowSpan=2 → Row 1의 셀들은 colAddr=1부터 시작 (col 0은 점유됨)
- **Nested Table Safety**: `_extract_col_span()` / `_extract_row_span()`은 마지막 `</hp:subList>` 이후의 메타데이터만 검색하여 중첩 테이블의 cellSpan 값과 혼동하지 않음

### Rule 12: Validate XML Well-Formedness at Integration Boundary
- **Problem**: 문자열 수술(string surgery) 후 잘못된 위치에 삽입하면 XML 구조가 깨질 수 있으나, 같은 파서로 검증하면 동일한 버그를 공유하여 발견 불가.
- **Solution**: `update_section()` / `update_sections()`에서 수정 전후 XML을 `ET.fromstring()`으로 검증 (기본값 `validate=True`). 이는 읽기 전용 검증이며 `ET.tostring()`은 절대 사용하지 않음.
- **Pattern**: 입력 검증(corrupted source 탐지) + 출력 검증(string surgery 오류 탐지) = 이중 안전망

### Rule 13: Unclosed CDATA/Comment Safety
- **Problem**: 손상된 XML에서 `<![CDATA[`가 열리고 `]]>`로 닫히지 않으면, 파서가 CDATA 내부의 태그형 문자열을 실제 태그로 잘못 인식하여 phantom 요소를 생성함.
- **Solution**: `_skip_cdata()` / `_skip_comment()`에서 닫는 태그를 찾지 못하면 `len(xml)`을 반환하여 나머지 전체를 스킵. 보수적 접근: 데이터 손실보다 안전 우선.
- **Detection**: `check_for_unclosed_constructs(xml)`로 파싱 전 미리 미닫힘 CDATA/comment를 탐지 가능. 빈 리스트면 안전, 비어있지 않으면 파싱 결과가 불완전할 수 있음.
- **Pattern**: 탐지 → 판단 → 파싱 (탐지 단계에서 위험 신호를 명시적으로 제공)

### Rule 11: ZIP Compress Type Preservation
- **Problem**: 원본 HWPX ZIP의 각 엔트리별 압축방식(`STORED`/`DEFLATED`)을 변경하면 무결성 검증 실패.
- **Solution**: 원본과 동일한 `compress_type`을 엔트리별로 보존한다. `mimetype`은 반드시 `STORED`, 나머지는 원본의 압축방식을 따른다.
- **Implementation**: `zip_handler.py`가 원본 ZIP 엔트리 메타데이터를 기록하고, 재패키징 시 동일한 `compress_type` 적용.

### Rule 14: Table `<hp:sz height>` Must Match cellSz Row Heights
- **Problem**: 행을 추가/삭제한 뒤 `rowCnt`, `cellAddr`만 갱신하고 `<hp:tbl>`의 외부 `<hp:sz height="N">`을 그대로 두면 한컴오피스가 파일 열기 자체를 실패시킨다(XML 형식은 well-formed이지만 한컴이 거부). 증상: `validate_wellformed`은 통과하지만 한컴이 열리지 않음.
- **Rule**: `<hp:sz height>` 는 모든 행의 col-0 `<hp:cellSz height>` 합과 정확히 일치해야 한다.
- **Solution**: `table_fixer.fix_table()` 가 자동으로 `<hp:sz height>`를 col-0 cellSz 합으로 갱신한다. 행 추가 코드에서 별도로 신경 쓸 필요 없다 — `fix_table()`만 호출하면 된다.
- **Validation**: `table_fixer.validate_table()`이 `sz.height` 필드 불일치를 명시적으로 보고한다.

### Rule 15: In-Cell Lineseg Flags Must Be 393216 (FIRST_LINE)
- **Problem**: `<hp:tc>` 내부 단락에서 줄바꿈 시 `<hp:lineseg flags="1441792">` (FLAGS_CONTINUATION, 본문 단락 컨벤션)을 사용하면 한컴이 파일을 변조된 것으로 표시한다. 본문 단락(table 바깥)에서는 1441792가 정상이지만 셀 안에서는 다르다.
- **Rule**: `<hp:tc>` 안 모든 `<hp:lineseg>`는 (첫줄·연속줄 무관) `flags="393216"` 사용.
- **Solution**: `modify_hwpx.IN_CELL_LINESEG_FLAGS = 393216` 상수와 `append_to_cell_subList()`, `replace_cell_subList()` 가 이를 자동 적용한다.
- **Origin**: 본문 단락은 `FLAGS_FIRST_LINE=393216` + `FLAGS_CONTINUATION=1441792` 둘 다 사용하지만, 셀 내부는 한컴이 단일 단락처럼 처리하여 모든 줄을 FIRST_LINE으로 표기.

### Rule 16: Empty-Cell Text Injection Requires subList Swap
- **Problem**: 빈 셀(`<hp:run charPrIDRef="X"/>`, `<hp:t>` 없음)에 인라인으로 `<hp:t>NEW</hp:t>`를 추가하면, 그 셀의 paraPr/charPr이 "빈 셀용"(작은 크기·투명 등)이라 텍스트가 비정상적으로 렌더링된다.
- **Rule**: 같은 행의 채워진 셀(filled cell)의 `<hp:subList>` 내용을 통째로 복사한 뒤 `<hp:t>` 텍스트만 교체한다.
- **Solution**: `modify_hwpx.set_cell_text(... filled_cell_template=...)`이 자동 처리. 채워진 셀 본문을 `filled_cell_template`로 전달하면 빈 셀일 때는 subList를 swap, 채워진 셀일 때는 단순 텍스트 교체.

### Rule 17: Hancom Tamper Detection on Section-Level Insertions
- **Symptom**: "문서가 손상되었거나 변조되었을 가능성이 있습니다. 이 문서를 불러오려면 [문서 보안 설정]을 [낮음]으로 설정해야 합니다." 경고. XML도 well-formed, 모든 reference도 유효한데 한컴이 거부.
- **Empirical Trigger**: **새 표 단락(self-contained `<hp:p>` containing `<hp:tbl>`)을 섹션 레벨에 삽입** + 같은 섹션의 **다른 어떤 변경**이라도 함께 있으면 트리거. 단독 삽입은 통과. 다른 변경 단독도 통과. 둘이 합쳐졌을 때만 발생.
- **What's safe (R-style)**:
  - 새 단락 삽입 (텍스트 본문, ㅇ·- 마커 등, 표 없음): OK
  - 기존 표의 행 추가 (in-place table row insertion): OK
  - 기존 셀의 텍스트 변경 / `<hp:subList>` 내용 추가·교체: OK
  - 위 셋의 임의 조합: OK
- **What triggers**:
  - 새 표 단락 삽입 + 위 R-style 변경 중 하나 이상: TRIGGER
- **Workaround**: 새 표를 만들지 말고, 기존 가까운 표/단락의 내용을 확장(append) 한다. 예: 새 요구사항을 별도 표로 추가하는 대신, 기존 마지막 요구사항 표의 `세부 내용` 셀(`<hp:subList>`)에 ㅇ 항목으로 append. `modify_hwpx.append_to_cell_subList()` 가 이 패턴을 지원.
- **Last resort**: 사용자가 한컴 환경설정에서 **문서 보안 설정 → 낮음** 으로 변경하면 외부 편집 파일도 경고 없이 열림 (일회성 설정 변경).

## Module Architecture

The HWPX skill uses a modular architecture. `generate_hwpx.py` handles new document creation from config JSON. The following modules handle reading and modifying existing HWPX files:

### scripts/read_hwpx.py — HWPX Parser & Structure Analyzer
- **Purpose**: 기존 HWPX 파일을 열어 구조를 분석하고, 섹션/테이블/스타일 정보를 추출
- **Key Functions**:
  - `open_hwpx(path)` → 압축 해제 + 엔트리 메타데이터(compress_type 포함) 기록
  - `parse_sections()` → section XML을 etree로 파싱 (분석 전용, 직렬화 금지)
  - `list_tables()` → 모든 테이블의 위치, 크기, 헤더 정보 반환
  - `get_styles()` → header.xml에서 charPr/paraPr/borderFill 카탈로그 추출
  - `get_structure_summary()` → 문서 구조 요약 (섹션 수, 테이블 수, 이미지 수 등)
- **Constraint**: `etree.tostring()` 절대 사용 금지 — 분석만 수행, 수정은 `modify_hwpx.py`에 위임

### scripts/modify_hwpx.py — Byte-Preserving HWPX Editor
- **Purpose**: 원본 XML 바이트를 보존하면서 HWPX 내용을 수정
- **Key Functions**:
  - `replace_text(section_bytes, old_text, new_text)` → 텍스트 내용 치환 (XML 태그 보존)
  - `insert_paragraph_after(section_bytes, anchor_pattern, new_para_xml)` → 특정 위치 뒤에 문단 삽입
  - `insert_table_row(section_bytes, table_pattern, row_xml, position)` → 테이블 행 삽입
  - `delete_paragraph(section_bytes, para_pattern)` → 문단 삭제
  - `update_section(hwpx_path, section_name, modifier_fn, output_path)` → 섹션 단위 수정 + ZIP 재패키징
- **Cell-content helpers (Rules 15-17)**:
  - `find_cell(paragraph_xml, col, row)` → 단락 안의 `<hp:tc>` 위치/본문 반환 (중첩 테이블 안전)
  - `set_cell_text(paragraph_xml, col, row, new_text, filled_cell_template=None)` → 셀 텍스트 설정. 빈 셀에는 `filled_cell_template`의 subList를 복제하여 올바른 paraPr/charPr 사용 (Rule 16)
  - `append_to_cell_subList(paragraph_xml, col, row, new_lines, ...)` → 셀의 `<hp:subList>` 끝에 ㅇ-bullet 단락 추가. **Rule 17의 권장 패턴** — 새 표를 추가하는 대신 기존 셀을 확장.
  - `replace_cell_subList(paragraph_xml, col, row, new_lines, ...)` → 셀 subList 전체 교체
  - 두 helper 모두 `flags=393216` 강제 적용 (Rule 15) + `vertpos=0` (한컴이 재계산)
- **Constraint**: 모든 수정은 `str.replace()` 또는 정규식으로 원본 바이트에 직접 수행. DOM 직렬화 금지.

### scripts/xml_templates.py — XML Template Extraction & String Substitution
- **Purpose**: 원본 HWPX에서 XML 패턴을 추출하여 템플릿화하고, 문자열 치환으로 새 요소 생성
- **Key Functions**:
  - `extract_paragraph_template(section_bytes, para_pattern)` → 기존 문단을 템플릿으로 추출 (플레이스홀더 삽입)
  - `extract_table_template(section_bytes, table_pattern)` → 기존 테이블 구조를 템플릿으로 추출
  - `render_paragraph(template, text, charPrIDRef, paraPrIDRef)` → 템플릿에 값 주입하여 새 문단 XML 생성
  - `render_table_row(template, cells)` → 템플릿에 셀 데이터 주입하여 새 행 XML 생성
- **Constraint**: `etree.tostring()` 금지 — 템플릿은 문자열이며, `str.format()` 또는 `str.replace()`로 값 주입

### scripts/table_fixer.py — Table Consistency Validator & Auto-Fixer
- **Purpose**: 테이블의 rowCnt/cellAddr/rowAddr/sz-height 정합성을 자동 검증하고 수정
- **Key Functions**:
  - `validate_table(table_xml_bytes)` → 테이블 정합성 검증 (rowCnt, colAddr, rowAddr, sz.height)
  - `fix_table(table_xml_bytes)` → rowCnt, cellAddr, rowAddr, sz.height 자동 수정
  - `validate_all_tables(section_bytes)` → 섹션 내 모든 테이블 일괄 검증
  - `fix_all_tables(section_bytes)` → 섹션 내 모든 테이블 일괄 수정
- **Validation Rules**:
  - `rowCnt` == 실제 `<hp:tr>` 개수
  - `rowAddr` == `row_idx` (0-based)
  - `colAddr` == 논리적 그리드 열 위치 (colSpan 누적 + rowSpan 점유 열 건너뜀)
  - **`<hp:sz height>`** == col-0 `<hp:cellSz height>` 합 (Rule 14 — Hancom enforces this)
  - 중첩 테이블의 cellSpan은 무시 (마지막 `</hp:subList>` 이후 메타데이터만 검색)
  - 수정은 정규식으로 속성값만 교체 (XML 구조 보존)

### scripts/zip_handler.py — Compress-Type Preserving ZIP Handler
- **Purpose**: 원본 ZIP 엔트리 메타데이터를 보존하며 HWPX 재패키징
- **Key Functions**:
  - `read_hwpx_zip(path)` → ZIP 읽기 + 엔트리별 compress_type/compress_level 기록
  - `write_hwpx_zip(entries, metadata, output_path)` → 원본 compress_type 보존하며 재패키징
  - `replace_entry(path, entry_name, new_bytes, output_path)` → 단일 엔트리 교체 (나머지 보존)
  - `add_entry(path, entry_name, data, output_path)` → 새 엔트리 추가 (기존 엔트리 보존)
- **Rules**:
  - `mimetype`은 항상 `ZIP_STORED`, 반드시 첫 번째 엔트리
  - 기존 엔트리의 `compress_type` 변경 금지
  - 새 엔트리는 `ZIP_DEFLATED` 기본값 사용

## Namespace Declarations

All section XML files must include these namespace declarations on `<hs:sec>`:

```xml
xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app"
xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"
xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph"
xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core"
xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"
xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history"
xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page"
xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf"
xmlns:dc="http://purl.org/dc/elements/1.1/"
xmlns:opf="http://www.idpf.org/2007/opf/"
xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart"
xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar"
xmlns:epub="http://www.idpf.org/2007/ops"
xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"
```

## Example Usage

To generate a simple report:

```python
config = {
    "title": "2026년 1분기 업무 추진현황",
    "date": "2026.02.14.",
    "department": "전략기획팀",
    "include_cover": True,
    "sections": [
        {
            "type": "body",
            "title_bar": "업무 추진현황",
            "content": [
                {"type": "heading", "text": "주요 추진 실적"},
                {"type": "bullet", "text": "신규 프로젝트 3건 착수"},
                {"type": "dash", "text": "AI 기반 문서 자동화 시스템 개발"},
                {"type": "dash", "text": "클라우드 인프라 마이그레이션"},
                {"type": "heading", "text": "향후 계획"},
                {"type": "bullet", "text": "2분기 목표 수립 완료"},
                {"type": "table", "caption": "분기별 실적",
                 "headers": ["구분", "목표", "실적"],
                 "rows": [["1월", "100", "120"], ["2월", "100", "95"]]}
            ]
        }
    ]
}
```

Then save as JSON and run the script, or call `generate_hwpx()` directly from Python.
