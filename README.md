# HWPX Claude Skill - Korean Document Generator (한글 문서 생성기)

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.7+](https://img.shields.io/badge/Python-3.7%2B-blue.svg)](https://www.python.org/downloads/)
[![No Dependencies](https://img.shields.io/badge/Dependencies-None-green.svg)](#requirements)

> A Claude Skill that generates properly formatted **HWPX (한글/Hangul)** documents — the native file format for [Hancom Office (한컴오피스)](https://www.hancom.com/), the standard word processor used across Korean government and enterprise.

> Claude가 올바른 서식의 HWPX(한글) 문서를 생성할 수 있게 해주는 Claude Skill입니다. 한국 정부 스타일 보고서의 서식, 표, 제목, 표지 등을 완벽하게 지원합니다.

---

## What is this? / 이 프로젝트는?

This project is a [Claude Skill](https://docs.anthropic.com/) that enables Claude to generate native **HWPX** files — the modern XML-based document format for [Hancom Office (한컴오피스)](https://www.hancom.com/). Generated files open in Hancom Office with correct formatting preserved.

이 프로젝트는 Claude가 네이티브 **HWPX** 파일을 생성할 수 있게 해주는 [Claude Skill](https://docs.anthropic.com/)입니다. 생성된 파일은 한컴오피스에서 올바른 서식이 유지된 상태로 정상적으로 열립니다.

### Key Features / 주요 기능

- **Template-based generation** using real HWPX templates for guaranteed Hancom Office compatibility
- **Full formatting support**: gradient title bars, hierarchical markers (□/ㅇ/-/*), data tables, appendix sections
- **Innovation Academy standard report template** (이노베이션아카데미 표준 보고서 템플릿) included
- **JSON-driven content** — define your document structure in simple JSON
- **Auto-generated cover pages** with logo and organization branding (optional)
- **Zero dependencies** — uses only Python standard library
- **Works standalone** as a Python CLI tool, or integrated as a Claude Skill

## Why HWPX? / HWPX 형식

HWPX is the modern **ZIP+XML** document format based on the **OWPML** standard ([KS X 6101](https://standard.go.kr/)). It replaces the legacy binary HWP format and is the native format for Hancom Office (한글), the word processor used across Korean government agencies and businesses.

### The Problem / 왜 어려운가?

Unlike DOCX (which has mature libraries like `python-docx`), **HWPX has virtually no open-source tooling**. Creating valid HWPX files requires:

1. Correct ZIP structure with `mimetype` as the first STORED entry
2. Complex `header.xml` with fonts, character properties, paragraph properties, border fills, and styles
3. Section XML with precise namespace usage (`hs:sec`, `hp:p`, `hp:run`, `hp:tbl`, etc.)
4. Proper `linesegarray` elements after every paragraph
5. Style ID references that match definitions in `header.xml`

This skill solves these problems by reverse-engineering real HWPX files and using a template-based approach.

이 스킬은 실제 HWPX 파일을 역공학하고 템플릿 기반 접근 방식을 사용하여 이러한 문제를 해결합니다.

## Installation / 설치 방법

### Install as a Claude Skill in Claude Desktop (Recommended)

1. **Download the ZIP from GitHub**
   - Visit the [HWPX-CLAUDE-SKILL repository](https://github.com/Steven-A3/HWPX-CLAUDE-SKILL)
   - Click the green **"Code"** button, then select **"Download ZIP"**

2. **Add the Skill in Claude Desktop**
   - Open Claude Desktop app
   - Go to **Settings** → **Skills** or **Custom Skills**
   - Click **"Add Skill"** and select the downloaded ZIP file
   - The skill is ready to use once registered

### Install via Git Clone

```bash
# Clone the repository
git clone https://github.com/Steven-A3/HWPX-CLAUDE-SKILL.git

# Copy to Claude skills directory
cp -r HWPX-CLAUDE-SKILL ~/.claude/skills/hwpx
```

### Standalone Python Usage

```bash
# Clone and use directly
git clone https://github.com/Steven-A3/HWPX-CLAUDE-SKILL.git
cd HWPX-CLAUDE-SKILL

# Generate a sample document
python scripts/generate_hwpx.py --output output.hwpx --config examples/sample_report.json
```

## Usage / 사용 방법

### Using with Claude / Claude에서 사용하기

Ask Claude to create an HWPX document:

> "2026년 1분기 업무 추진현황 보고서를 한글 파일로 만들어 줘"

The skill activates automatically on keywords: `HWPX`, `한글`, `보고서`, `HWP`, `한컴`, etc.

### Python API

```python
from scripts.generate_hwpx import generate_hwpx

config = {
    "title": "2026년 업무보고",
    "date": "26.02.14.",
    "department": "전략기획팀",
    "include_cover": True,
    "sections": [
        {
            "type": "body",
            "title_bar": "업무 추진현황",
            "content": [
                {"type": "heading", "text": "주요 실적"},
                {"type": "bullet", "text": "프로젝트 A 완료"},
                {"type": "dash", "text": "세부 내용 설명"},
                {"type": "star", "text": "상세 참고 사항"},
                {"type": "table",
                 "caption": "실적 현황",
                 "headers": ["구분", "목표", "실적"],
                 "rows": [["1월", "100", "120"]]},
            ]
        }
    ]
}

generate_hwpx(config, "output.hwpx")
```

### CLI

```bash
python scripts/generate_hwpx.py \
  --output my_report.hwpx \
  --config my_config.json \
  --template custom_template.hwpx  # Optional: use a custom template
```

## Supported Content Types / 콘텐츠 유형

| Type | Marker | Font | Size | Description |
|------|--------|------|------|-------------|
| `heading` | □ | HY헤드라인M | 15pt | Section heading (bold) |
| `paragraph` | — | 휴먼명조 | 15pt | Body text |
| `bullet` | ㅇ | 휴먼명조 | 15pt | Level 1 bullet point |
| `dash` | - | 휴먼명조 | 15pt | Level 2 item (indented) |
| `star` | * | 맑은고딕 | 13pt | Level 3 detail (further indented) |
| `table` | — | 맑은고딕 | 12pt | Data table with header row |
| `note` | ▷ | — | 14pt | Reference/note text |
| `empty` | — | — | — | Blank line (spacing) |

## Section Types / 섹션 유형

- **`body`**: Standard report body with gradient title bar and hierarchical content
- **`appendix`**: Appendix section with numbered tabs (참고1, 참고2, etc.)

## Project Structure / 프로젝트 구조

```
HWPX-CLAUDE-SKILL/
├── SKILL.md              # Claude Skill definition (trigger rules, format docs)
├── README.md             # This file
├── LICENSE               # GPL v3 License
├── CITATION.cff          # Citation metadata
├── .gitignore
├── assets/
│   └── template.hwpx     # Base template (Innovation Academy standard report)
├── scripts/
│   └── generate_hwpx.py  # Main generation script (Python)
└── examples/
    └── sample_report.json # Example configuration file
```

## How It Works / 작동 원리

1. **Template extraction**: Extracts the bundled `template.hwpx` to a temporary directory
2. **Static copy**: `header.xml`, `BinData/` (logos), `META-INF/`, `settings.xml`, `version.xml` are copied from the template — preserving all font/style/border definitions
3. **Dynamic generation**: Section XML files are generated from JSON config, referencing correct `charPrIDRef` and `paraPrIDRef` IDs from the template's `header.xml`
4. **Package assembly**: Compressed into a valid HWPX file with `mimetype` as first STORED entry

### Technical Details

- **Namespaces**: `hs:` for section root, `hp:` for paragraphs/runs/tables, `hh:` for header definitions, `hc:` for core elements
- **mimetype**: Must be `application/hwp+zip` (STORED, uncompressed, first ZIP entry)
- **Table structure**: `hp:tbl` → `hp:tr` → `hp:tc` → `hp:subList` → `hp:p`
- **Every paragraph** requires `hp:linesegarray` after all runs
- **First paragraph** of each section requires `hp:secPr` with page layout

## Custom Templates / 커스터마이징

You can replace the default Innovation Academy template with your own:

1. Create a document in Hancom Office with your desired formatting
2. Save as **HWPX format** (File → Save As → select HWPX)
3. Replace `assets/template.hwpx` with your file (keep the filename `template.hwpx`)
4. Re-register the skill in Claude Desktop

The generator auto-discovers styles from any valid HWPX template.

## Requirements / 요구 사항

- **Python 3.7** or higher
- **No external dependencies** — uses only Python standard library (`zipfile`, `json`, `xml`, `shutil`, `tempfile`)

## Background / 배경

This skill was developed through reverse-engineering of the HWPX format:

1. **Web research**: Investigation of OWPML/KS X 6101 standard
2. **File analysis**: Extracted and analyzed real HWPX files to understand XML structure
3. **Trial and error**: Iterative testing validating files in Hancom Office
4. **Template approach**: Discovered that copying `header.xml` from verified files is far more reliable than generating from scratch

## License / 라이선스

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html). See [LICENSE](LICENSE) for details.

## Contributing / 기여하기

Contributions are welcome! Areas of interest:

- Additional content types (images, charts, footnotes)
- More template styles
- Improved linesegarray calculation
- Documentation improvements
- Test cases

## Acknowledgments / 감사의 글

- [Innovation Academy (이노베이션아카데미)](https://innovationacademy.kr/) — Standard report template
- Built with [Claude](https://claude.ai/) by Anthropic
