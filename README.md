# HWPX Claude Skill - 한글 문서 생성기 (Korean Document Generator)

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.7+](https://img.shields.io/badge/Python-3.7%2B-blue.svg)](https://www.python.org/downloads/)
[![No Dependencies](https://img.shields.io/badge/Dependencies-None-green.svg)](#요구-사항--requirements)

> Claude가 올바른 서식의 **HWPX(한글)** 문서를 생성할 수 있게 해주는 Claude Skill입니다. 한국 정부 및 공공기관 스타일 보고서의 서식, 표, 제목, 표지 등을 완벽하게 지원합니다.

> A Claude Skill that generates properly formatted **HWPX (한글/Hangul)** documents — the native file format for [Hancom Office (한컴오피스)](https://www.hancom.com/), the standard word processor used across Korean government and enterprise.

---

## 이 프로젝트는? / What is this?

이 프로젝트는 Claude가 네이티브 **HWPX** 파일([한컴오피스](https://www.hancom.com/)의 최신 문서 형식)을 생성할 수 있게 해주는 [Claude Skill](https://docs.anthropic.com/)입니다. 생성된 파일은 한컴오피스에서 올바른 서식이 유지된 상태로 정상적으로 열립니다.

This project is a [Claude Skill](https://docs.anthropic.com/) that enables Claude to generate native **HWPX** files — the modern XML-based document format for [Hancom Office (한컴오피스)](https://www.hancom.com/). Generated files open in Hancom Office with correct formatting preserved.

### 주요 기능 / Key Features

- **템플릿 기반 생성**: 실제 HWPX 템플릿을 사용하여 한컴오피스 호환성 보장
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
├── LICENSE               # GPL v3 라이선스
├── CITATION.cff          # 인용 메타데이터
├── .gitignore
├── assets/
│   └── template.hwpx     # 기본 템플릿 (이노베이션아카데미 표준 보고서)
├── scripts/
│   └── generate_hwpx.py  # 메인 생성 스크립트 (Python)
└── examples/
    └── sample_report.json # 예제 설정 파일
```

## 작동 원리 / How It Works

1. **템플릿 추출**: 번들된 `template.hwpx`를 임시 디렉토리로 추출
2. **정적 복사**: `header.xml`, `BinData/`(로고), `META-INF/`, `settings.xml`, `version.xml`은 템플릿에서 그대로 복사 — 모든 글꼴/스타일/테두리 정의 보존
3. **동적 생성**: JSON 설정에 따라 섹션 XML 파일 생성, 템플릿 `header.xml`의 올바른 `charPrIDRef` 및 `paraPrIDRef` ID 참조
4. **패키지 조립**: `mimetype`이 첫 번째 STORED 항목인 유효한 HWPX 파일로 압축

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
3. Claude Desktop에서 스킬을 재등록합니다

스타일 자동 탐색 기능이 포함되어 있어 유효한 HWPX 템플릿이라면 자동으로 스타일을 인식합니다.

## 요구 사항 / Requirements

- **Python 3.7** 이상
- **외부 의존성 없음** — 표준 라이브러리만 사용 (`zipfile`, `json`, `xml`, `shutil`, `tempfile`)

## 배경 / Background

이 스킬은 HWPX 형식의 역공학을 통해 개발되었습니다:

1. **웹 리서치**: OWPML/KS X 6101 표준 조사
2. **실제 파일 분석**: 실제 HWPX 파일을 추출하고 분석하여 XML 구조 파악
3. **시행착오**: 한컴오피스에서 생성된 파일의 유효성을 검증하는 반복 테스트
4. **템플릿 접근**: 검증된 파일에서 `header.xml`을 복사하는 것이 처음부터 생성하는 것보다 훨씬 안정적이라는 것을 발견

## 라이선스 / License

이 프로젝트는 [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html) 하에 배포됩니다. 자세한 내용은 [LICENSE](LICENSE)를 참조하세요.

## 기여하기 / Contributing

기여를 환영합니다! 특히 다음 분야:

- 추가 콘텐츠 유형 (이미지, 차트, 각주)
- 더 많은 템플릿 스타일
- 더 나은 linesegarray 계산
- 문서 개선
- 테스트 케이스

## 감사의 글 / Acknowledgments

- [이노베이션아카데미](https://innovationacademy.kr/) — 표준 보고서 템플릿 제공
- [Claude](https://claude.ai/) (Anthropic) 기반으로 개발
