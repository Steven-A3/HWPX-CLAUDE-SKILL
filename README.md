# HWPX Claude Skill - 한글 문서 생성기 (Korean Document Generator)

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![No Dependencies](https://img.shields.io/badge/Dependencies-None-green.svg)](#요구-사항--requirements)

> Claude가 올바른 서식의 **HWPX(한글)** 문서를 생성할 수 있게 해주는 Claude Skill입니다. 한국 정부 및 공공기관 스타일 보고서의 서식, 표, 제목, 표지 등을 완벽하게 지원합니다.

> A Claude Skill that generates properly formatted **HWPX (한글/Hangul)** documents — the native file format for [Hancom Office (한컴오피스)](https://www.hancom.com/), the standard word processor used across Korean government and enterprise.

---

## 이 프로젝트는? / What is this?

이 프로젝트는 Claude가 네이티브 **HWPX** 파일([한컴오피스](https://www.hancom.com/)의 최신 문서 형식)을 생성할 수 있게 해주는 [Claude Skill](https://docs.anthropic.com/)입니다. 생성된 파일은 한컴오피스에서 올바른 서식이 유지된 상태로 정상적으로 열립니다.

This project is a [Claude Skill](https://docs.anthropic.com/) that enables Claude to generate native **HWPX** files — the modern XML-based document format for [Hancom Office (한컴오피스)](https://www.hancom.com/). Generated files open in Hancom Office with correct formatting preserved.

### 주요 기능 / Key Features

- **템플릿 기반 생성**: 실제 HWPX 템플릿을 사용하여 한컴오피스 호환성 보장
- **동적 스타일 탐색**: 템플릿의 스타일 ID를 구조 분석으로 자동 인식 — 한컴오피스에서 템플릿을 수정해도 자동 대응
- **기존 파일 읽기/수정**: 바이트 보존 방식으로 기존 HWPX 파일을 안전하게 편집 (v0.2.0+)
- **완전한 서식 지원**: 그라데이션 제목바, 계층형 마커(□/ㅇ/-/*), 데이터 표, 부록 섹션
- **이노베이션아카데미 표준 보고서 템플릿** 기본 포함
- **JSON 기반 콘텐츠**: 간단한 JSON으로 문서 내용 정의
- **표지 자동 생성**: 로고와 조직 브랜딩이 포함된 표지 (선택 사항)
- **외부 의존성 없음**: Python 표준 라이브러리만 사용
- **독립 실행 가능**: Python CLI 도구로 단독 사용하거나 Claude Skill로 통합 사용

## HWPX 형식 / Why HWPX?

HWPX는 **OWPML** 표준([KS X 6101](https://standard.go.kr/))을 기반으로 한 **ZIP+XML** 문서 형식입니다. 레거시 HWP 바이너리 형식의 후속이며, 한국 정부 및 공공기관, 기업에서 주로 사용되는 워드프로세서인 한컴오피스(한글)의 네이티브 형식입니다.

HWPX is the modern ZIP+XML document format based on the OWPML standard (KS X 6101). It replaces the legacy binary HWP format and is the native format for Hancom Office, used across Korean government agencies and businesses.

### 왜 어려운가? / The Problem

DOCX와 달리(DOCX에는 `python-docx` 같은 풍부한 라이브러리가 있음), **HWPX는 오픈소스 도구가 거의 없습니다.** 유효한 HWPX 파일을 생성하려면 다음이 필요합니다:

1. `mimetype`이 첫 번째 STORED 항목인 올바른 ZIP 구조
2. 글꼴, 문자 속성, 문단 속성, 테두리 채움, 스타일이 포함된 복잡한 `header.xml`
3. 정확한 네임스페이스 사용(`hs:sec`, `hp:p`, `hp:run`, `hp:tbl` 등)이 포함된 섹션 XML
4. 모든 문단 뒤에 올바른 `linesegarray` 요소
5. `header.xml`의 정의와 일치해야 하는 스타일 ID 참조

이 스킬은 실제 HWPX 파일을 역공학하고 템플릿 기반 접근 방식을 사용하여 이러한 문제를 해결합니다.

## 설치 방법 / Installation

### Claude Desktop에서 스킬 설치하기 (권장)

1. **GitHub에서 ZIP 파일 다운로드**
   - [HWPX-CLAUDE-SKILL GitHub 저장소](https://github.com/Steven-A3/HWPX-CLAUDE-SKILL)에 접속합니다.
   - 녹색 **"Code"** 버튼을 클릭한 후 **"Download ZIP"** 을 선택합니다.

2. **Claude Desktop 설정에서 스킬 추가**
   - Claude Desktop 앱을 실행합니다.
   - **설정(Settings)** → **스킬(Skills)** 또는 **Custom Skills** 메뉴로 이동합니다.
   - **"Add Skill"** 또는 **"스킬 추가"** 버튼을 클릭합니다.
   - 다운로드한 ZIP 파일을 선택하여 추가합니다.
   - 스킬이 정상적으로 등록되면 바로 사용할 수 있습니다.

### Git Clone으로 설치하기

```bash
# 저장소 클론
git clone https://github.com/Steven-A3/HWPX-CLAUDE-SKILL.git

# Claude 스킬 디렉토리에 복사
cp -r HWPX-CLAUDE-SKILL ~/.claude/skills/hwpx
```

### 독립 실행형 Python 사용

```bash
# 클론 후 직접 사용
git clone https://github.com/Steven-A3/HWPX-CLAUDE-SKILL.git
cd HWPX-CLAUDE-SKILL

# 샘플 문서 생성
python scripts/generate_hwpx.py --output output.hwpx --config examples/sample_report.json
```

## 사용 방법 / Usage

### Claude에서 사용하기

Claude에게 HWPX 문서를 만들어 달라고 요청하면 됩니다:

> "2026년 1분기 업무 추진현황 보고서를 한글 파일로 만들어 줘"

`HWPX`, `한글`, `보고서`, `HWP`, `한컴` 등의 키워드로 스킬이 자동으로 실행됩니다.

### 프로그래밍 방식 (Python API)

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
  --template custom_template.hwpx  # 선택사항: 사용자 정의 템플릿 사용
```

## 콘텐츠 유형 / Supported Content Types

| 유형 | 마커 | 글꼴 | 크기 | 설명 |
|------|------|------|------|------|
| `heading` | □ | HY헤드라인M | 15pt | 섹션 제목 (굵게) |
| `paragraph` | — | 휴먼명조 | 15pt | 본문 텍스트 |
| `bullet` | ㅇ | 휴먼명조 | 15pt | 1단계 글머리 기호 |
| `dash` | - | 휴먼명조 | 15pt | 2단계 항목 (들여쓰기) |
| `star` | * | 맑은고딕 | 13pt | 3단계 세부사항 (추가 들여쓰기) |
| `table` | — | 맑은고딕 | 12pt | 머리글 행이 있는 데이터 표 |
| `note` | ▷ | — | 14pt | 참조/비고 텍스트 |
| `empty` | — | — | — | 빈 줄 (간격 조절용) |

## 섹션 유형 / Section Types

- **`body`**: 그라데이션 제목바와 계층형 콘텐츠가 포함된 표준 보고서 본문
- **`appendix`**: 번호가 매겨진 탭(참고1, 참고2 등)과 별도의 제목이 있는 부록 섹션

## 프로젝트 구조 / Project Structure

```
HWPX-CLAUDE-SKILL/
├── SKILL.md              # Claude Skill 정의 (트리거 규칙, 형식 문서)
├── README.md             # 이 파일
├── CHANGELOG.md          # 버전별 변경 이력
├── LICENSE               # GPL v3 라이선스
├── CITATION.cff          # 인용 메타데이터
├── .gitignore
├── assets/
│   ├── template.hwpx     # 기본 템플릿 (이노베이션아카데미 표준 보고서)
│   └── default_styles.json # 자동 생성된 스타일 캐시 (템플릿 해시 포함)
├── scripts/
│   ├── __init__.py       # 패키지 초기화
│   ├── generate_hwpx.py  # 새 문서 생성 (JSON → HWPX)
│   ├── _parser.py        # 공유 XML 파서 (깊이 추적, CDATA/주석 안전, 인용부호 인식, bisect 검증)
│   ├── read_hwpx.py      # 기존 HWPX 읽기 및 구조 분석
│   ├── modify_hwpx.py    # 바이트 보존 편집 (텍스트/문단/행 수정)
│   ├── xml_templates.py  # 원본 XML에서 템플릿 추출 및 렌더링
│   ├── table_fixer.py    # 테이블 정합성 자동 검증/수정 (colSpan 지원)
│   └── zip_handler.py    # 압축모드 보존 ZIP 핸들러
└── examples/
    └── sample_report.json # 예제 설정 파일
```

## 기존 HWPX 파일 편집 / Editing Existing HWPX Files (v0.2.0+)

새 문서 생성뿐 아니라, 기존 HWPX 파일을 열어서 분석하고 수정할 수 있습니다.

In addition to creating new documents, you can open, analyze, and modify existing HWPX files.

### 사용 예시 / Usage Example

```python
from scripts.read_hwpx import open_hwpx
from scripts.modify_hwpx import replace_text, insert_paragraph_after, update_section
from scripts.table_fixer import fix_all_tables

# 기존 파일 열기 / Open existing file
doc = open_hwpx('report.hwpx')
print(doc.list_sections())     # ['Contents/section0.xml', ...]
print(doc.list_tables())       # [{'section': ..., 'rowCnt': 3, 'colCnt': 4, ...}]

# 텍스트 치환 / Replace text
section_xml = doc.get_section_text('Contents/section1.xml')
modified = replace_text(section_xml, '2025년', '2026년')

# 문단 삽입 / Insert paragraph
new_para = '<hp:p paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>새 문단</hp:t></hp:run></hp:p>'
modified = insert_paragraph_after(modified, 0, new_para)

# 섹션 수정 후 저장 / Save modified section
update_section('report.hwpx', 'Contents/section1.xml',
               lambda xml: replace_text(xml, 'old', 'new'),
               output_path='modified_report.hwpx')
```

### 핵심 모듈 / Core Modules

| 모듈 | 용도 | 주요 함수 |
|------|------|-----------|
| `read_hwpx.py` | 구조 분석 (읽기 전용) | `open_hwpx()`, `list_tables()`, `get_styles()` |
| `modify_hwpx.py` | 바이트 보존 편집 | `replace_text()`, `insert_paragraph_after()`, `update_section()` |
| `xml_templates.py` | 템플릿 추출/렌더링 | `extract_paragraph_template()`, `render_table_row()` |
| `table_fixer.py` | 테이블 정합성 수정 | `validate_table()`, `fix_table()`, `fix_all_tables()` |
| `zip_handler.py` | ZIP 압축모드 보존 | `read_hwpx_zip()`, `write_hwpx_zip()` |
| `_parser.py` | 공유 XML 파서 (CDATA/주석 안전, 인용부호 인식, O(log n) 구조 검증) | `find_top_level_paragraphs()`, `find_direct_cells()`, `check_for_unclosed_constructs()` |

### 바이트 보존 아키텍처 / Byte-Preserving Architecture

HWPX 편집의 핵심 제약: **`etree.tostring()` 절대 사용 금지**.

The critical constraint for HWPX editing: **never use `etree.tostring()`**.

한컴오피스는 원본 XML의 바이트 수준 무결성을 검증합니다. lxml/etree 등의 XML 파서가 들여쓰기, 속성 순서, 공백 등을 변경하면 파일이 손상된 것으로 감지됩니다. 따라서 모든 수정은 원본 XML 바이트에 `str.replace()` 또는 정규식으로 직접 수행합니다.

Hancom Office verifies byte-level XML integrity. If any XML parser (lxml, etree) reformats indentation, attribute order, or whitespace, the file is detected as corrupted. All modifications are performed directly on the original XML bytes using `str.replace()` or regex.

```
┌─────────────────┐     ┌──────────────────┐
│  zip_handler.py │────→│  read_hwpx.py    │──→ 구조 분석 (analysis)
│  (ZIP 압축모드   │     │  (etree 분석만,  │
│   보존)          │     │   tostring 금지) │
└────────┬────────┘     └──────────────────┘
         │
         └─────────────→│  modify_hwpx.py  │──→ 바이트 수술 (byte surgery)
                        │  (str.replace &  │
                        │   regex only)    │
                        └────────┬─────────┘
                                 │
                   ┌─────────────┼─────────────┐
                   ▼             ▼             ▼
           ┌────────────┐ ┌────────────┐ ┌────────────┐
           │xml_templates│ │table_fixer │ │_parser.py    │
           │.py          │ │.py         │ │(깊이 추적     │
           │(패턴 추출)   │ │(rowCnt,    │ │ CDATA 안전    │
           └────────────┘ │cellAddr,   │ │ 인용부호 인식  │
                          │colSpan 수정)│ │ bisect 검증)  │
                          └────────────┘ └──────────────┘
```

### 무결성 규칙 / Integrity Rules

이 모듈들은 개발 과정에서 발견된 실패 사례를 바탕으로 다음 규칙을 엄격히 준수합니다:

These modules strictly follow integrity rules discovered through production failures:

| 규칙 | 문제 | 해결 |
|------|------|------|
| **Rule 9**: XML 직렬화 금지 | `etree.tostring()`이 compact XML을 pretty-print로 변환 → 변조 감지 | 원본 바이트에 문자열 수술만 수행 |
| **Rule 10**: 테이블 정합성 | rowCnt ≠ 실제 행 수이면 파일 오류 | `table_fixer.py`가 rowCnt, cellAddr, colSpan 자동 수정 |
| **Rule 11**: ZIP 압축모드 | 엔트리별 compress_type 변경 시 무결성 실패 | `zip_handler.py`가 원본 compress_type 보존 |
| **Rule 12**: 출력 검증 | 문자열 수술 후 XML 구조 오류 가능 | `update_section(validate=True)`로 수정 전후 검증 |
| **Rule 13**: CDATA 안전 | 손상된 CDATA가 phantom 요소 생성 | 닫히지 않은 CDATA/주석은 나머지 전체 스킵 |
| **Rule 14**: 섹션 헤더 파싱 | `<hs:sec>` 속성 값 내 `>`가 잘못된 분할 유발 | 인용부호 인식 파싱 + CDATA/주석 내 `<hs:sec` 무시 |
| **Rule 15**: 구조 검증 성능 | 닫힌 CDATA/주석 내부 검사가 O(n×m) 재스캔 | 사전 계산된 범위 + bisect로 O(log n) 조회 |

### 병합 셀(colSpan) 지원 / Merged Cell Support (v0.3.0)

`table_fixer.py`는 셀 병합(colSpan)이 적용된 테이블의 `colAddr`를 올바르게 계산합니다:

`table_fixer.py` correctly computes `colAddr` for tables with column-spanning merged cells:

```
colCnt=3인 테이블:
┌──────────────┬─────────┐
│  병합 셀 A+B  │    C    │   ← Row 0: 2개 셀, 첫 셀 colSpan=2
│  (colSpan=2) │         │
├─────┬────────┼─────────┤
│  A  │   B    │    C    │   ← Row 1: 3개 셀, 각각 colSpan=1
└─────┴────────┴─────────┘

cellAddr 계산:
  Row 0: colAddr=0 (colSpan=2), colAddr=2 (colSpan=1)  ← 열 1을 건너뜀
  Row 1: colAddr=0, colAddr=1, colAddr=2                ← 순차
```

## 작동 원리 / How It Works

1. **템플릿 추출**: 번들된 `template.hwpx`를 임시 디렉토리로 추출
2. **스타일 탐색**: 템플릿의 SHA-256 해시를 확인하여 캐시된 스타일 맵을 로드하거나, 변경 시 구조 분석을 통해 스타일 맵을 자동 재구축
3. **스켈레톤 추출**: 템플릿 섹션에서 제목바, 날짜선, 부록 헤더 등의 골격 구조를 추출하고, 텍스트만 교체하여 원본 서식 완벽 보존
4. **동적 생성**: JSON 설정에 따라 콘텐츠 문단을 생성, 탐색된 스타일 ID로 올바른 서식 참조
5. **스타일 최적화**: 사용되지 않는 스타일을 제거하고 ID를 재매핑하여 파일 크기 최적화
6. **패키지 조립**: `mimetype`이 첫 번째 STORED 항목인 유효한 HWPX 파일로 압축

### 동적 스타일 탐색 시스템 / Dynamic Style Discovery

한컴오피스에서 템플릿을 수정하면 `charPrIDRef`, `paraPrIDRef`, `borderFillIDRef` 등의 스타일 ID가 재배정됩니다. 이 시스템은 텍스트 내용이 아닌 **구조적 마커**를 사용하여 템플릿 변경에 자동 대응합니다:

- **`<hp:colPr>`**: 페이지 레이아웃이 포함된 첫 번째 문단 (제목바) 식별
- **paraPr RIGHT 정렬**: 날짜선 문단 식별 (paraPr 카탈로그 조회)
- **`styleIDRef="15"`**: 제목(heading) 문단 식별
- **charPr face name**: 글꼴 이름(예: "헤드라인")으로 역할 분류
- **테이블 셀 위치**: `rowAddr`/`colAddr`로 제목바·부록 셀 식별 (borderFillIDRef에 의존하지 않음)

탐색 결과는 `assets/default_styles.json`에 템플릿 해시와 함께 캐시됩니다. 템플릿이 변경되면 다음 실행 시 자동으로 재구축됩니다.

### 주요 기술 세부사항 / Technical Details

- **네임스페이스**: `hs:`는 섹션 루트, `hp:`는 문단/실행/표, `hh:`는 헤더 정의, `hc:`는 코어 요소
- **mimetype**: `application/hwp+zip`이어야 함 (STORED, 비압축, 첫 번째 ZIP 항목)
- **테이블 구조**: `hp:tbl` → `hp:tr` → `hp:tc` → `hp:subList` → `hp:p`
- **모든 문단**에는 모든 run 뒤에 `hp:linesegarray` 필요
- **각 섹션의 첫 번째 문단**에는 페이지 레이아웃이 포함된 `hp:secPr` 필요

## 커스터마이징 / Custom Templates

기본 제공되는 이노베이션아카데미 표준 보고서 템플릿 대신 자신만의 템플릿을 사용할 수 있습니다.

1. 한컴오피스(한글)에서 원하는 서식의 문서를 작성하고 **HWPX 형식으로 저장**합니다 (파일 → 다른 이름으로 저장 → HWPX 선택)
2. `assets/template.hwpx` 파일을 새로 만든 HWPX 파일로 교체합니다 (파일명은 반드시 `template.hwpx`로 유지)
3. 다음 실행 시 스타일 맵이 자동으로 재구축됩니다 (`assets/default_styles.json`이 업데이트됨)
4. CLI에서 `--template` 옵션으로 별도 템플릿 지정도 가능합니다

동적 스타일 탐색 시스템이 구조적 마커를 분석하여 새 템플릿의 스타일 ID를 자동으로 인식합니다. 인식에 실패한 역할은 기본값으로 대체됩니다.

## 요구 사항 / Requirements

- **Python 3.9** 이상
- **외부 의존성 없음** — 표준 라이브러리만 사용 (`zipfile`, `json`, `xml`, `hashlib`, `shutil`, `tempfile`)

## 배경 / Background

이 스킬은 HWPX 형식의 역공학을 통해 개발되었습니다:

1. **웹 리서치**: OWPML/KS X 6101 표준 조사
2. **실제 파일 분석**: 실제 HWPX 파일을 추출하고 분석하여 XML 구조 파악
3. **시행착오**: 한컴오피스에서 생성된 파일의 유효성을 검증하는 반복 테스트
4. **템플릿 접근**: 검증된 파일에서 `header.xml`을 복사하는 것이 처음부터 생성하는 것보다 훨씬 안정적이라는 것을 발견
5. **구조적 탐색**: 텍스트 매칭 대신 XML 구조 마커(colPr, cellAddr, paraPr 정렬, charPr 글꼴명)를 사용하여 템플릿 변경에 강건한 스타일 탐색 구현
6. **반복적 적대적 검토**: 각 버전의 코드를 자체 검토하여 가정을 찾고 실패 시나리오를 구성하는 방식으로 4라운드에 걸쳐 버그를 발견하고 수정 (v0.1.0 → v0.2.0 → v0.3.0 → v0.4.0 → v0.5.0)

## 라이선스 / License

이 프로젝트는 [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html) 하에 배포됩니다. 자세한 내용은 [LICENSE](LICENSE)를 참조하세요.

## 기여하기 / Contributing

기여를 환영합니다! 특히 다음 분야:

- 추가 콘텐츠 유형 (이미지, 차트, 각주)
- 다양한 보고서 템플릿
- linesegarray 계산 정밀도 향상
- 테스트 케이스 (특히 병합 셀이 있는 실제 문서 테스트)
- 한컴오피스 자동화 검증 (CLI 기반 외부 검증)
- 속성 값 내 특수문자를 포함하는 실제 HWPX 파일 테스트

## 감사의 글 / Acknowledgments

- [이노베이션아카데미](https://innovationacademy.kr/) — 표준 보고서 템플릿 제공
- [Claude](https://claude.ai/) (Anthropic) 기반으로 개발
