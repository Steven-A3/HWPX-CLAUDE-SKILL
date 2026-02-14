---
name: hwpx
description: "**HWPX Document Generator**: Create Korean government-style HWPX (한글) documents with proper formatting, tables, headers, and cover pages based on the 이노베이션아카데미 standard report template. Supports structured reports with title headers, hierarchical content (□/ㅇ/-/* markers), data tables, and appendix sections.\n  - MANDATORY TRIGGERS: HWPX, .hwpx, 한글, 한글파일, HWP, 보고서, 업무보고, 한컴, Hancom"
---

# HWPX Document Generator

## Overview

HWPX is the modern XML-based format for Hancom Office (한글). It is a ZIP archive containing XML files following the OWPML (KS X 6101) standard. This skill generates properly formatted HWPX documents that open correctly in Hancom Office.

## Architecture: Template-Based Generation

This skill uses a **template-based approach** for reliable HWPX generation:

1. **header.xml** is copied verbatim from a known-good template (contains all font, style, border definitions)
2. **Section XML** is generated dynamically using the template's style ID references
3. **META-INF**, **version.xml**, **settings.xml** are copied from the template
4. **BinData** (logos/images) are preserved from the template

This approach ensures Hancom Office compatibility because the complex header.xml (font definitions, charProperties, paraProperties, borderFills, styles) is never hand-crafted.

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
      "title_bar": "참고1",
      "appendix_title": "부록 제목",
      "content": [...]
    }
  ]
}
```

### Content Types and Style Mapping

| Type | Marker | Font | Size | Style IDs (charPr/paraPr) |
|------|--------|------|------|---------------------------|
| `heading` | □ | HY헤드라인M | 15pt | charPr=27+2, paraPr=28 |
| `paragraph` | (none) | 휴먼명조 | 15pt | charPr=36, paraPr=19 |
| `bullet` | ㅇ | 휴먼명조 | 15pt | charPr=36, paraPr=19 |
| `dash` | - | 휴먼명조 | 15pt | charPr=36, paraPr=20 |
| `star` | * | 맑은고딕 | 13pt | charPr=57, paraPr=21 |
| `table` | (table) | 맑은고딕 | 12pt | charPr=28/33, paraPr=25/23 |
| `title_bar` | (bar) | HY헤드라인M | 20pt | charPr=1/30, paraPr=15 |
| `appendix_bar` | (bar) | HY헤드라인M | 16pt | charPr=8/3/31, paraPr=18/16 |

### Section Types

- **`body`**: Standard report body section with title bar and content
- **`appendix`**: Appendix section with numbered tab (참고1, 참고2, etc.)

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
