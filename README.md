# HWPX Claude Skill

> A Claude Skill for generating properly formatted HWPX (한글) documents — Korean government-style reports with full styling, tables, headers, and cover pages.

## What is this?

This is a [Claude Skill](https://docs.anthropic.com/) that enables Claude to generate native **HWPX** files (the modern format used by [Hancom Office / 한컴오피스](https://www.hancom.com/)). The generated files open correctly in Hancom Office with proper formatting preserved.

### Key Features

- **Template-based generation**: Uses a real HWPX template to ensure Hancom Office compatibility
- **Full formatting support**: Gradient title bars, hierarchical markers (□/ㅇ/-/*), data tables, appendix sections
- **이노베이션아카데미 standard report template**: Based on the official report format
- **JSON-driven content**: Define your document content as simple JSON
- **Cover page**: Optional auto-generated cover page with logo and organization branding

## HWPX Format

HWPX is a ZIP+XML document format based on the **OWPML** standard (KS X 6101). It's the successor to the legacy HWP binary format and is the native format of Hancom Office (한글), the dominant word processor in Korean government and business.

### Why is this hard?

Unlike DOCX (which has extensive libraries like `python-docx`), HWPX has virtually no open-source tooling. Creating valid HWPX files requires:

1. Correct ZIP structure with `mimetype` as the first STORED entry
2. Complex `header.xml` with font faces, character properties, paragraph properties, border fills, and styles
3. Section XML with precise namespace usage (`hs:sec`, `hp:p`, `hp:run`, `hp:tbl`, etc.)
4. Correct `linesegarray` elements after every paragraph
5. Style ID references that must match definitions in `header.xml`

This skill solves these challenges by reverse-engineering real HWPX files and using a template-based approach.

## Installation

### As a Claude Skill (Claude Desktop / Cowork)

Copy the entire repository to your Claude skills directory:

```bash
# Clone the repository
git clone https://github.com/Steven-A3/HWPX-CLAUDE-SKILL.git

# Copy to your Claude skills directory
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

## Usage

### With Claude

Simply ask Claude to create an HWPX document:

> "2026년 1분기 업무 추진현황 보고서를 한글 파일로 만들어 줘"

The skill automatically triggers on keywords like `HWPX`, `한글`, `보고서`, `HWP`, `한컴`, etc.

### Programmatic (Python)

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
  --template custom_template.hwpx  # optional: use your own template
```

## Content Types

| Type | Marker | Font | Size | Description |
|------|--------|------|------|-------------|
| `heading` | □ | HY헤드라인M | 15pt | Section heading (bold) |
| `paragraph` | — | 휴먼명조 | 15pt | Body text |
| `bullet` | ㅇ | 휴먼명조 | 15pt | First-level bullet |
| `dash` | - | 휴먼명조 | 15pt | Second-level item (indented) |
| `star` | * | 맑은고딕 | 13pt | Third-level detail (further indented) |
| `table` | — | 맑은고딕 | 12pt | Data table with header row |
| `note` | ▷ | — | 14pt | Reference/note text |
| `empty` | — | — | — | Empty spacer line |

## Section Types

- **`body`**: Standard report body with gradient title bar and hierarchical content
- **`appendix`**: Appendix section with numbered tab (참고1, 참고2, etc.) and separate title

## Project Structure

```
HWPX-CLAUDE-SKILL/
├── SKILL.md              # Claude Skill definition (trigger rules, format docs)
├── README.md             # This file
├── LICENSE               # MIT License
├── .gitignore
├── assets/
│   └── template.hwpx     # Base template (이노베이션아카데미 standard report)
├── scripts/
│   └── generate_hwpx.py  # Main generation script
└── examples/
    └── sample_report.json # Example configuration
```

## How It Works

1. **Template Extraction**: The bundled `template.hwpx` is extracted to a temp directory
2. **Static Copy**: `header.xml`, `BinData/` (logos), `META-INF/`, `settings.xml`, `version.xml` are copied as-is from the template — this preserves all font/style/border definitions
3. **Dynamic Generation**: Section XML files are generated based on your JSON config, referencing the correct `charPrIDRef` and `paraPrIDRef` IDs from the template's `header.xml`
4. **Package Assembly**: Everything is zipped into a valid HWPX file with `mimetype` as the first STORED entry

### Key Technical Details

- **Namespace**: `hs:` for section root, `hp:` for paragraphs/runs/tables, `hh:` for header definitions, `hc:` for core elements
- **mimetype**: Must be `application/hwp+zip` (STORED, not compressed, first ZIP entry)
- **Table structure**: `hp:tbl` → `hp:tr` → `hp:tc` → `hp:subList` → `hp:p`
- **Every paragraph** requires `hp:linesegarray` after all runs
- **First paragraph** in each section must contain `hp:secPr` with page layout

## Customization

### Using Your Own Template

You can replace `assets/template.hwpx` with your own HWPX file (created in Hancom Office). The script will use your template's `header.xml` for all style definitions and copy your images/logos.

```bash
python scripts/generate_hwpx.py \
  --output output.hwpx \
  --config config.json \
  --template /path/to/your/template.hwpx
```

### Adding New Content Types

Edit `scripts/generate_hwpx.py` and add new cases to the `generate_content_item()` function. You'll need to reference valid `charPrIDRef` and `paraPrIDRef` IDs from your template's `header.xml`.

## Requirements

- Python 3.7+
- No external dependencies (uses only stdlib: `zipfile`, `json`, `xml`, `shutil`, `tempfile`)

## Background

This skill was developed through reverse-engineering of the HWPX format:

1. **Web research** on OWPML/KS X 6101 standard
2. **Real file analysis**: Extracted and analyzed actual HWPX files to understand the XML structure
3. **Trial and error**: Iterative testing with Hancom Office to validate generated files
4. **Template approach**: Discovered that copying `header.xml` from a known-good file is far more reliable than generating it from scratch

## License

MIT License — see [LICENSE](LICENSE) for details.

## Contributing

Contributions welcome! Especially:

- Additional content types (images, charts, footnotes)
- More template styles
- Better linesegarray calculation
- Documentation improvements
- Test cases

## Acknowledgments

- [이노베이션아카데미](https://innovationacademy.kr/) for the standard report template
- Built with [Claude](https://claude.ai/) by Anthropic
