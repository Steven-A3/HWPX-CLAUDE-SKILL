#!/usr/bin/env python3
"""
HWPX Document Generator v3
Generates properly formatted HWPX (한글) documents based on template files.

Fixes over v2:
  - [Fix] Multi-line lineseg: paragraphs with wrapped text now generate multiple
    lineseg entries (one per visual line) with correct textpos, vertpos, and flags
  - [Fix] VertPosTracker accounts for total multi-line paragraph height
  - [Fix] Table wrapper vertsize is dynamically calculated from actual table height
  - [Fix] Continuation line flags (0x160000) match real HWPX behavior

Usage:
    python generate_hwpx.py --output output.hwpx --config config.json
"""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
from xml.etree import ElementTree as ET

from . import _parser

# ============================================================================
# Constants
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATE_PATH = SKILL_DIR / "assets" / "template.hwpx"

NS_DECL = (
    'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
    'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
    'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:opf="http://www.idpf.org/2007/opf/" '
    'xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
    'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" '
    'xmlns:epub="http://www.idpf.org/2007/ops" '
    'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"'
)

# Page dimensions (A4, matching template)
PAGE_WIDTH = 59528
PAGE_HEIGHT = 84188
MARGIN_LEFT = 5669
MARGIN_RIGHT = 5669
MARGIN_TOP = 2834
MARGIN_BOTTOM = 4251
MARGIN_HEADER = 4251
MARGIN_FOOTER = 2834
CONTENT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT  # 48190
HORZSIZE_DEFAULT = 48188

# Lineseg flags
FLAGS_FIRST_LINE = 393216       # 0x60000 - first or only line
FLAGS_CONTINUATION = 1441792    # 0x160000 - continuation line (2nd, 3rd, ...)

# 6-point empty line between bullet level changes (□↔ㅇ)
BULLET_TRANSITION_SPACER_HEIGHT = 600   # 6pt in HWPX units (100 units = 1pt)


# ============================================================================
# Text Width Estimation & Line Count
# ============================================================================

def estimate_text_width(text, char_height):
    """
    Estimate rendered width of text in HWPX units.
    Calibrated against real HWPX files: ~37-41 mixed Korean/ASCII chars
    fit in 48188 horzsize at 15pt (char_height=1500).
    """
    return sum(_char_width(ch, char_height) for ch in text)


def _char_width(ch, char_height):
    """Get estimated rendered width of a single character."""
    if '\uAC00' <= ch <= '\uD7A3':      return char_height  # Korean syllables
    elif '\u3131' <= ch <= '\u318E':     return char_height  # Korean jamo
    elif '\u2500' <= ch <= '\u257F':     return char_height  # Box drawing
    elif '\uFF00' <= ch <= '\uFFEF':     return char_height  # Fullwidth forms
    elif ord(ch) >= 0x2E80:              return char_height  # CJK, symbols
    elif ch == ' ':                      return int(char_height * 0.25)
    elif ch.isascii() and (ch.isalpha() or ch.isdigit()):
                                         return int(char_height * 0.50)
    else:                                return int(char_height * 0.55)


# Effective width ratio: 91% of horzsize matches Hancom's rendering.
# Calibrated against 9 test cases (body text + table cells) from Hancom-saved files.
EFFECTIVE_WIDTH_RATIO = 0.91


def estimate_line_count(text, char_height, horzsize=HORZSIZE_DEFAULT):
    """
    Estimate number of visual lines needed for text.
    Uses word-wrapping logic (breaking at spaces) with 91% effective width.
    """
    if not text:
        return 1
    breaks = estimate_line_breaks(text, char_height, horzsize)
    return len(breaks)


def estimate_chars_per_line(text, char_height, horzsize=HORZSIZE_DEFAULT):
    """Estimate how many characters fit per line."""
    if not text:
        return len(text) or 1
    total_lines = estimate_line_count(text, char_height, horzsize)
    return max(1, len(text) // total_lines)


def estimate_line_breaks(text, char_height, horzsize=HORZSIZE_DEFAULT):
    """
    Estimate line break positions using word-wrapping, matching Hancom's
    rendering behavior. Returns a list of textpos values (character indices)
    where each visual line starts.

    Algorithm: walk character-by-character accumulating width. When cumulative
    width exceeds the effective line width, break at the last space position
    (word wrap). If no space found, break at the overflow character.

    Uses 91% of horzsize as effective width, calibrated against Hancom.
    """
    if not text:
        return [0]

    effective_width = int(horzsize * EFFECTIVE_WIDTH_RATIO)
    breaks = [0]  # First line always starts at 0
    cumulative_width = 0
    last_space_pos = None  # Position AFTER the last space (= start of next word)

    for i, ch in enumerate(text):
        w = _char_width(ch, char_height)
        cumulative_width += w

        if ch == ' ':
            last_space_pos = i + 1  # Next line would start after this space

        if cumulative_width > effective_width:
            if last_space_pos and last_space_pos > breaks[-1]:
                # Word wrap: break at the last space boundary
                breaks.append(last_space_pos)
                # Recalculate cumulative width from the break point
                cumulative_width = sum(_char_width(c, char_height) for c in text[last_space_pos:i+1])
            elif i > breaks[-1]:
                # No space found: break at current character
                breaks.append(i)
                cumulative_width = w
            last_space_pos = None  # Reset for next line

    return breaks


# ============================================================================
# Vertical Position Tracker (multi-line aware)
# ============================================================================

class VertPosTracker:
    """
    Tracks cumulative vertical position for linesegarray.
    Now supports multi-line paragraphs: advances by total paragraph height.

    For single-line: total_height = vertsize
    For N lines:     total_height = N * vertsize + (N-1) * spacing

    Next paragraph: vertpos = prev_vertpos + prev_total_height + prev_spacing
    """
    def __init__(self):
        self._pos = 0
        self._last_total_height = 0
        self._last_spacing = 0
        self._first = True

    def next(self, vertsize, spacing, num_lines=1):
        """Advance position and return the vertpos for this paragraph's first line."""
        if self._first:
            self._first = False
            vp = 0
        else:
            vp = self._pos + self._last_total_height + self._last_spacing
        self._pos = vp
        # Total height consumed by this paragraph (all lines)
        if num_lines > 1:
            self._last_total_height = num_lines * vertsize + (num_lines - 1) * spacing
        else:
            self._last_total_height = vertsize
        self._last_spacing = spacing
        return vp

    def reset(self):
        self.__init__()


# ============================================================================
# Style Auto-Discovery from header.xml
# ============================================================================

# Default IDs (legacy fallback; auto-discovered from template at runtime)
DEFAULT_STYLE_MAP = {
    # (charPrIDRef, paraPrIDRef, vertsize, textheight, baseline, spacing)
    "heading_marker":   ("42", "26", 1500, 1500, 1275, 900),   # □ marker
    "heading_text":     ("2",  "26", 1500, 1500, 1275, 900),   # HY헤드라인M 15pt
    "heading_tail":     ("42", "26", 1500, 1500, 1275, 900),   # trailing space
    "heading_end":      ("29", "28", 1500, 1500, 1275, 900),   # closing run
    "paragraph":        ("22", "39", 1500, 1500, 1275, 900),   # 휴먼명조 15pt
    "paragraph_end":    ("33", "39", 1500, 1500, 1275, 900),
    "bullet":           ("22", "39", 1500, 1500, 1275, 900),   # ㅇ bullet
    "bullet_end":       ("33", "39", 1500, 1500, 1275, 900),
    "dash":             ("22", "18", 1500, 1500, 1275, 900),   # - dash
    "dash_end":         ("22", "18", 1500, 1500, 1275, 900),
    "star":             ("71", "48", 1300, 1300, 1105, 716),   # * detail
    "star_end":         ("71", "48", 1300, 1300, 1105, 716),
    "note":             ("22", "39", 1500, 1500, 1275, 900),   # ▷ note
    "table_caption":    ("27", "16", 1200, 1200, 1020, 720),   # < caption >
    "table_wrapper":    ("21", "22", 6104, 6104, 5188, 900),   # table container (base; overridden dynamically)
    "table_header":     ("35", "29", 1100, 1100, 935,  360),   # header cell
    "table_body":       ("33", "25", 1200, 1200, 1020, 360),   # body cell
    "title_bar_title":  ("1",  "23", 2000, 2000, 1700, 1800),  # title 20pt
    "title_bar_top":    ("17", "3",  100,  100,  85,   60),    # gradient top
    "title_bar_bottom": ("19", "3",  100,  100,  85,   60),    # gradient bottom
    "date_line":        ("27", "16", 1200, 1200, 1020, 720),   # date
    "date_emphasis":    ("58", "17", 1200, 1200, 1020, 720),   # department
    "spacer_small":     ("25", "25", 600,  600,  510,  360),   # small spacer
    "spacer_medium":    ("32", "26", 600,  600,  510,  360),   # medium spacer
    "first_para":       ("8",  "16", 1500, 1500, 1275, 900),   # first para with bar
    "appendix_tab":     ("7",  "17", 1600, 1600, 1360, 960),   # 참고N tab
    "appendix_title":   ("5",  "15", 1600, 1600, 1360, 480),   # appendix title
    "appendix_sep_char": ("23","15", 1600, 1600, 1360, 480),   # separator space
    "appendix_sep_cell": ("4", "3",  1550, 1550, 1317, 930),   # separator cell
    "appendix_first":   ("23", "16", 2831, 2831, 2406, 300),   # appendix first para
    "appendix_spacer":  ("25", "25", 1500, 1500, 1275, 900),   # charPr/paraPr from spacer_small
    # Cover page title area
    "cover_title":      ("25", "26", 2500, 2500, 2125, 1252),
    # Cover page date
    "cover_date":       ("37", "27", 2400, 2400, 2040, 1680),
    # Border fill IDs
    "bf_none":          "1",
    "bf_table":         "3",
    "bf_gradient_top":  "12",
    "bf_title_bg":      "9",
    "bf_gradient_bot":  "13",
    "bf_table_header":  "30",
    "bf_appendix_tab":  "14",
    "bf_appendix_sep":  "10",
    "bf_appendix_title": "11",
    "bf_cover_grad_top": "12",
    "bf_cover_title_bg": "8",
    "bf_cover_grad_bot": "13",
    "bf_cover_border":  "7",
}


def compute_template_hash(template_path):
    """Compute SHA-256 hash of the template .hwpx file."""
    h = hashlib.sha256()
    with open(template_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def load_cached_style_map(cache_path, expected_hash):
    """Load style map from JSON cache if hash matches. Returns dict or None."""
    try:
        cache_path = Path(cache_path)
        if not cache_path.exists():
            return None
        data = json.loads(cache_path.read_text(encoding='utf-8'))
        if data.get('template_hash') != expected_hash:
            return None
        sm = data.get('style_map', {})
        # Convert list values back to tuples for style entries
        for key, val in sm.items():
            if isinstance(val, list):
                sm[key] = tuple(val)
        return sm
    except Exception:
        return None


def save_style_map_cache(cache_path, hash_val, style_map):
    """Write style map + hash to JSON cache."""
    try:
        cache_path = Path(cache_path)
        # Convert tuples to lists for JSON serialization
        sm_json = {}
        for key, val in style_map.items():
            sm_json[key] = list(val) if isinstance(val, tuple) else val
        data = {
            'template_hash': hash_val,
            'style_map': sm_json,
        }
        cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as e:
        print(f"Warning: Could not save style map cache: {e}")


def _parse_header_catalogs(header_xml_path):
    """Parse header.xml to build charPr and paraPr catalogs.

    Returns (char_catalog, para_catalog) where:
      char_catalog: {id_str: {'height': int, 'face': str, 'bold': bool}}
      para_catalog: {id_str: {'align': str, 'line_spacing_type': str, 'line_spacing_value': str}}
    Returns (None, None) on failure.
    """
    try:
        ns = {
            'hh': 'http://www.hancom.co.kr/hwpml/2011/head',
            'hc': 'http://www.hancom.co.kr/hwpml/2011/core',
        }
        tree = ET.parse(header_xml_path)
        root = tree.getroot()

        # Build font ID -> face name map
        font_map = {}
        for fontface in root.findall('.//hh:fontface', ns):
            lang = fontface.get('lang', '')
            for font in fontface.findall('hh:font', ns):
                fid = font.get('id', '')
                face = font.get('face', '')
                font_map[(lang, fid)] = face

        # Build charPr catalog
        char_catalog = {}
        for cp in root.findall('.//hh:charPr', ns):
            cpid = cp.get('id', '')
            height = int(cp.get('height', '0'))
            font_ref = cp.find('hh:fontRef', ns)
            hangul_ref = font_ref.get('hangul', '0') if font_ref is not None else '0'
            has_bold = cp.find('hh:bold', ns) is not None
            hangul_face = font_map.get(('HANGUL', hangul_ref), '')
            char_catalog[cpid] = {
                'height': height,
                'face': hangul_face,
                'bold': has_bold,
            }

        # Build paraPr catalog
        para_catalog = {}
        for pp in root.findall('.//hh:paraPr', ns):
            ppid = pp.get('id', '')
            align_el = pp.find('hh:align', ns)
            h_align = align_el.get('horizontal', 'JUSTIFY') if align_el is not None else 'JUSTIFY'
            ls_el = pp.find('hh:lineSpacing', ns)
            ls_type = ls_el.get('type', 'PERCENT') if ls_el is not None else 'PERCENT'
            ls_value = ls_el.get('value', '160') if ls_el is not None else '160'
            para_catalog[ppid] = {
                'align': h_align,
                'line_spacing_type': ls_type,
                'line_spacing_value': ls_value,
            }

        return char_catalog, para_catalog
    except Exception as e:
        print(f"Warning: Could not parse header.xml catalogs: {e}")
        return None, None


def _extract_all_top_level_paragraphs(section_xml):
    """Extract ALL top-level paragraphs from section XML.

    Returns (paragraphs, section_header) where paragraphs is a list of
    raw XML strings and section_header is the ``<hs:sec ...>`` opening tag
    (including any ``<?xml ...?>`` declaration preceding it).

    Delegates to _parser.find_top_level_paragraphs() which handles
    CDATA sections, XML comments, partial tag name matching, and
    section-header skipping automatically.
    """
    try:
        sec_idx = section_xml.index('<hs:sec')
        sec_close = section_xml.index('>', sec_idx) + 1
        section_header = section_xml[:sec_close]

        spans = _parser.find_top_level_paragraphs(section_xml)
        paragraphs = [section_xml[start:end] for start, end in spans]

        return paragraphs, section_header
    except (ValueError, IndexError):
        return [], ""


def _extract_para_attrs(para_xml):
    """Extract key attributes from a paragraph XML string.

    Returns dict with: paraPrIDRef, styleIDRef, charPrIDRefs (list),
    has_colpr, has_tbl, has_text, vertsize, textheight, baseline, spacing.
    """
    pp_m = re.search(r'paraPrIDRef="(\d+)"', para_xml)
    st_m = re.search(r'styleIDRef="(\d+)"', para_xml)
    char_prs = re.findall(r'charPrIDRef="(\d+)"', para_xml)
    has_colpr = '<hp:colPr' in para_xml
    has_tbl = '<hp:tbl' in para_xml
    texts = re.findall(r'<hp:t>([^<]+)</hp:t>', para_xml)
    has_text = any(t.strip() for t in texts)

    ls = parse_last_lineseg(para_xml)

    return {
        'paraPrIDRef': pp_m.group(1) if pp_m else '0',
        'styleIDRef': st_m.group(1) if st_m else '0',
        'charPrIDRefs': char_prs,
        'has_colpr': has_colpr,
        'has_tbl': has_tbl,
        'has_text': has_text,
        'vertsize': ls['vertsize'] if ls else 0,
        'textheight': ls['textheight'] if ls else 0,
        'baseline': ls['baseline'] if ls else 0,
        'spacing': ls['spacing'] if ls else 0,
    }


def _extract_table_cells(para_xml):
    """Extract table cell info from a paragraph containing <hp:tbl>.

    Returns list of dicts with: rowAddr, colAddr, bf (borderFillIDRef),
    charPrIDRefs, paraPrIDRefs.
    """
    cells = []
    for tc_m in re.finditer(r'<hp:tc\b([^>]*)>(.*?)</hp:tc>', para_xml, re.DOTALL):
        tc_attrs = tc_m.group(1)
        tc_body = tc_m.group(2)
        addr_m = re.search(r'<hp:cellAddr\s+colAddr="(\d+)"\s+rowAddr="(\d+)"', tc_body)
        bf_m = re.search(r'borderFillIDRef="(\d+)"', tc_attrs)
        char_prs = re.findall(r'charPrIDRef="(\d+)"', tc_body)
        para_prs = re.findall(r'paraPrIDRef="(\d+)"', tc_body)
        cells.append({
            'rowAddr': int(addr_m.group(2)) if addr_m else -1,
            'colAddr': int(addr_m.group(1)) if addr_m else -1,
            'bf': bf_m.group(1) if bf_m else '1',
            'charPrIDRefs': char_prs,
            'paraPrIDRefs': para_prs,
        })
    return cells


def _make_style_tuple(char_pr_id, para_pr_id, vertsize, textheight, baseline, spacing):
    """Create a style map tuple entry."""
    return (str(char_pr_id), str(para_pr_id), int(vertsize), int(textheight),
            int(baseline), int(spacing))


def _detect_template_sections(template_dir):
    """Detect which section files contain body and appendix content.

    Uses styleIDRef="15" count as the primary discriminator:
      - Body section: has the most styleIDRef="15" paragraphs (□ headings)
      - Appendix section: has colPr + 1x3 table (appendix bar), not the body

    Returns (body_path, appendix_path). Either may be None if not found.
    """
    template_dir = Path(template_dir)
    section_paths = sorted(template_dir.glob("Contents/section*.xml"),
                           key=lambda p: int(re.search(r'(\d+)', p.name).group(1)))

    # Score each section
    candidates = []
    for path in section_paths:
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        heading_count = len(re.findall(r'styleIDRef="15"', text))
        has_colpr = '<hp:colPr' in text
        has_appendix_bar = bool(re.search(r'colCnt="3".*?rowCnt="1"', text, re.DOTALL)
                                or re.search(r'rowCnt="1".*?colCnt="3"', text, re.DOTALL))
        candidates.append({
            'path': path, 'headings': heading_count,
            'has_colpr': has_colpr, 'has_appendix_bar': has_appendix_bar,
        })

    # Body: section with most styleIDRef="15" headings (must have some)
    body_path = None
    body_candidates = [c for c in candidates if c['headings'] > 0]
    if body_candidates:
        body_path = max(body_candidates, key=lambda c: c['headings'])['path']

    # Appendix: section with colPr + 1x3 table, not the body section
    appendix_path = None
    for c in candidates:
        if c['path'] == body_path:
            continue
        if c['has_colpr'] and c['has_appendix_bar']:
            appendix_path = c['path']
            break

    # Fallback for legacy templates
    if body_path is None:
        fallback = template_dir / "Contents" / "section1.xml"
        if fallback.exists():
            body_path = fallback
    if appendix_path is None:
        fallback = template_dir / "Contents" / "section2.xml"
        if fallback.exists():
            appendix_path = fallback

    return body_path, appendix_path


def build_style_map_from_template(template_dir):
    """Build a complete style map by parsing the extracted template.

    Uses structural markers (colPr, styleIDRef, table geometry, paraPr alignment)
    and charPr catalog properties (font face, height) — never matches text content.

    Returns a style map dict compatible with DEFAULT_STYLE_MAP, or None on failure.
    """
    template_dir = Path(template_dir)
    header_path = template_dir / "Contents" / "header.xml"

    # Detect body and appendix sections by structural analysis
    body_section_path, appendix_section_path = _detect_template_sections(template_dir)

    if not header_path.exists() or not body_section_path.exists():
        return None

    # Phase A: Parse header catalogs
    char_catalog, para_catalog = _parse_header_catalogs(header_path)
    if char_catalog is None:
        return None

    sm = dict(DEFAULT_STYLE_MAP)

    try:
        # Phase B: Parse body section (section0 or section1 depending on template)
        s1_xml = body_section_path.read_text(encoding='utf-8')
        s1_paras, _ = _extract_all_top_level_paragraphs(s1_xml)
        if not s1_paras:
            return None

        # Classify paragraphs by structural markers
        first_para_idx = None
        date_line_idx = None
        spacer_medium_idx = None
        heading_idx = None
        table_wrapper_idx = None
        table_caption_idx = None

        para_attrs_list = [_extract_para_attrs(p) for p in s1_paras]

        for i, attrs in enumerate(para_attrs_list):
            if attrs['has_colpr'] and first_para_idx is None:
                first_para_idx = i
            elif (attrs['styleIDRef'] == '15' and heading_idx is None
                  and not attrs['has_tbl'] and attrs['has_text']):
                # Skip styleIDRef=15 paragraphs with tables or no text
                heading_idx = i
            elif attrs['has_tbl'] and not attrs['has_colpr'] and table_wrapper_idx is None:
                table_wrapper_idx = i

        # Find date_line: paraPr with RIGHT alignment, after first_para
        if first_para_idx is not None:
            for i, attrs in enumerate(para_attrs_list):
                if i <= (first_para_idx or 0):
                    continue
                if heading_idx is not None and i >= heading_idx:
                    break
                pp_id = attrs['paraPrIDRef']
                pp_info = para_catalog.get(pp_id, {})
                if pp_info.get('align') == 'RIGHT':
                    date_line_idx = i
                    break

        # Find spacer_medium: empty paragraph between date_line and heading
        if date_line_idx is not None and heading_idx is not None:
            for i in range(date_line_idx + 1, heading_idx):
                attrs = para_attrs_list[i]
                if not attrs['has_text'] and attrs['vertsize'] > 0:
                    spacer_medium_idx = i
                    break

        # Find table_caption: paragraph just before table_wrapper
        if table_wrapper_idx is not None and table_wrapper_idx > 0:
            table_caption_idx = table_wrapper_idx - 1

        # Phase C: Extract style tuples from classified paragraphs

        # --- first_para ---
        if first_para_idx is not None:
            a = para_attrs_list[first_para_idx]
            first_cp = a['charPrIDRefs'][-1] if a['charPrIDRefs'] else '0'
            sm['first_para'] = _make_style_tuple(
                first_cp, a['paraPrIDRef'], a['vertsize'], a['textheight'],
                a['baseline'], a['spacing'])

        # --- date_line and date_emphasis ---
        if date_line_idx is not None:
            a = para_attrs_list[date_line_idx]
            runs = re.findall(r'charPrIDRef="(\d+)"', s1_paras[date_line_idx])
            unique_cps = []
            seen = set()
            for cp in runs:
                if cp not in seen:
                    unique_cps.append(cp)
                    seen.add(cp)
            if len(unique_cps) >= 1:
                sm['date_line'] = _make_style_tuple(
                    unique_cps[0], a['paraPrIDRef'], a['vertsize'],
                    a['textheight'], a['baseline'], a['spacing'])
            if len(unique_cps) >= 2:
                sm['date_emphasis'] = _make_style_tuple(
                    unique_cps[1], a['paraPrIDRef'], a['vertsize'],
                    a['textheight'], a['baseline'], a['spacing'])

        # --- spacer_medium ---
        if spacer_medium_idx is not None:
            a = para_attrs_list[spacer_medium_idx]
            sp_cp = a['charPrIDRefs'][0] if a['charPrIDRefs'] else '0'
            sm['spacer_medium'] = _make_style_tuple(
                sp_cp, a['paraPrIDRef'], a['vertsize'], a['textheight'],
                a['baseline'], a['spacing'])

        # --- heading ---
        if heading_idx is not None:
            a = para_attrs_list[heading_idx]
            runs = a['charPrIDRefs']
            # Identify heading runs by charPr face from catalog
            heading_text_cp = None
            heading_marker_cp = None
            heading_tail_cp = None
            heading_end_cp = None
            for cp in runs:
                info = char_catalog.get(cp, {})
                face = info.get('face', '')
                if '헤드라인' in face and heading_text_cp is None:
                    heading_text_cp = cp
                elif heading_marker_cp is None and cp != heading_text_cp:
                    heading_marker_cp = cp
            # Tail/end: last two unique charPrs that aren't heading_text
            other_cps = [cp for cp in runs if cp != heading_text_cp]
            if len(other_cps) >= 1:
                heading_marker_cp = heading_marker_cp or other_cps[0]
                heading_tail_cp = other_cps[0]
            if len(other_cps) >= 2:
                heading_end_cp = other_cps[-1]

            if heading_text_cp:
                sm['heading_text'] = _make_style_tuple(
                    heading_text_cp, a['paraPrIDRef'], a['vertsize'],
                    a['textheight'], a['baseline'], a['spacing'])
            if heading_marker_cp:
                sm['heading_marker'] = _make_style_tuple(
                    heading_marker_cp, a['paraPrIDRef'], a['vertsize'],
                    a['textheight'], a['baseline'], a['spacing'])
            if heading_tail_cp:
                sm['heading_tail'] = _make_style_tuple(
                    heading_tail_cp, a['paraPrIDRef'], a['vertsize'],
                    a['textheight'], a['baseline'], a['spacing'])
            if heading_end_cp:
                sm['heading_end'] = _make_style_tuple(
                    heading_end_cp, a['paraPrIDRef'], a['vertsize'],
                    a['textheight'], a['baseline'], a['spacing'])

        # --- Content paragraphs: bullet, dash, star, note ---
        # Identify by charPr height from catalog + document order
        content_paras = []
        start_idx = (heading_idx + 1) if heading_idx is not None else 3
        note_found = False
        for i in range(start_idx, len(para_attrs_list)):
            a = para_attrs_list[i]
            if a['has_tbl']:
                continue
            if a['styleIDRef'] == '15':
                continue  # another heading
            if not a['has_text']:
                continue  # spacer
            # Get primary charPr height from catalog
            primary_cp = a['charPrIDRefs'][0] if a['charPrIDRefs'] else None
            cp_info = char_catalog.get(primary_cp, {}) if primary_cp else {}
            height = cp_info.get('height', 0)
            content_paras.append((i, a, height, primary_cp))

        # Group by (paraPrIDRef, primary_charPr) signature — first occurrence
        seen_sigs = {}
        for idx, a, height, primary_cp in content_paras:
            sig = (a['paraPrIDRef'], primary_cp)
            if sig not in seen_sigs:
                seen_sigs[sig] = (idx, a, height, primary_cp)

        # Assign roles by height ranking + order
        tall_groups = []  # height >= 1500 (bullet, dash)
        mid_groups = []   # height 1300-1499 (star, table_caption)
        other_groups = [] # everything else (note)

        for sig, (idx, a, height, primary_cp) in sorted(seen_sigs.items(), key=lambda x: x[1][0]):
            if height >= 1500:
                tall_groups.append((idx, a, height, primary_cp))
            elif height >= 1300:
                mid_groups.append((idx, a, height, primary_cp))
            else:
                other_groups.append((idx, a, height, primary_cp))

        # First tall group → bullet/paragraph, second → dash
        if len(tall_groups) >= 1:
            idx, a, h, cp = tall_groups[0]
            end_cp = a['charPrIDRefs'][-1] if len(a['charPrIDRefs']) > 1 else cp
            sm['bullet'] = _make_style_tuple(cp, a['paraPrIDRef'], a['vertsize'],
                                              a['textheight'], a['baseline'], a['spacing'])
            sm['bullet_end'] = _make_style_tuple(end_cp, a['paraPrIDRef'], a['vertsize'],
                                                  a['textheight'], a['baseline'], a['spacing'])
            sm['paragraph'] = sm['bullet']
            sm['paragraph_end'] = sm['bullet_end']

        if len(tall_groups) >= 2:
            idx, a, h, cp = tall_groups[1]
            end_cp = a['charPrIDRefs'][-1] if len(a['charPrIDRefs']) > 1 else cp
            sm['dash'] = _make_style_tuple(cp, a['paraPrIDRef'], a['vertsize'],
                                            a['textheight'], a['baseline'], a['spacing'])
            sm['dash_end'] = _make_style_tuple(end_cp, a['paraPrIDRef'], a['vertsize'],
                                                a['textheight'], a['baseline'], a['spacing'])

        # Mid groups → star
        if mid_groups:
            idx, a, h, cp = mid_groups[0]
            end_cp = a['charPrIDRefs'][-1] if len(a['charPrIDRefs']) > 1 else cp
            sm['star'] = _make_style_tuple(cp, a['paraPrIDRef'], a['vertsize'],
                                            a['textheight'], a['baseline'], a['spacing'])
            sm['star_end'] = _make_style_tuple(end_cp, a['paraPrIDRef'], a['vertsize'],
                                                a['textheight'], a['baseline'], a['spacing'])

        # Note: paragraph after table_wrapper with text
        if table_wrapper_idx is not None:
            for i in range(table_wrapper_idx + 1, len(para_attrs_list)):
                a = para_attrs_list[i]
                if a['has_text'] and a['styleIDRef'] != '15':
                    cp = a['charPrIDRefs'][0] if a['charPrIDRefs'] else '0'
                    end_cp = a['charPrIDRefs'][-1] if len(a['charPrIDRefs']) > 1 else cp
                    sm['note'] = _make_style_tuple(cp, a['paraPrIDRef'], a['vertsize'],
                                                    a['textheight'], a['baseline'], a['spacing'])
                    break

        # --- table_caption ---
        if table_caption_idx is not None:
            a = para_attrs_list[table_caption_idx]
            cp = a['charPrIDRefs'][0] if a['charPrIDRefs'] else '0'
            sm['table_caption'] = _make_style_tuple(
                cp, a['paraPrIDRef'], a['vertsize'], a['textheight'],
                a['baseline'], a['spacing'])

        # --- table_wrapper ---
        if table_wrapper_idx is not None:
            a = para_attrs_list[table_wrapper_idx]
            cp = a['charPrIDRefs'][0] if a['charPrIDRefs'] else '0'
            sm['table_wrapper'] = _make_style_tuple(
                cp, a['paraPrIDRef'], a['vertsize'], a['textheight'],
                a['baseline'], a['spacing'])

        # --- spacer_small: first empty paragraph after heading with small vertsize ---
        if heading_idx is not None:
            for i in range(heading_idx + 1, len(para_attrs_list)):
                a = para_attrs_list[i]
                if not a['has_text'] and 0 < a['vertsize'] <= 800:
                    sp_cp = a['charPrIDRefs'][0] if a['charPrIDRefs'] else '0'
                    sm['spacer_small'] = _make_style_tuple(
                        sp_cp, a['paraPrIDRef'], a['vertsize'], a['textheight'],
                        a['baseline'], a['spacing'])
                    break

        # Phase D: Extract borderFillIDRef from table cells

        # Title bar table (first_para's 3-row 1-col table)
        if first_para_idx is not None:
            cells = _extract_table_cells(s1_paras[first_para_idx])
            for cell in cells:
                if cell['rowAddr'] == 0:
                    sm['bf_gradient_top'] = cell['bf']
                    if cell['charPrIDRefs']:
                        sm['title_bar_top'] = _make_style_tuple(
                            cell['charPrIDRefs'][0],
                            cell['paraPrIDRefs'][0] if cell['paraPrIDRefs'] else '3',
                            100, 100, 85, 60)
                elif cell['rowAddr'] == 1:
                    sm['bf_title_bg'] = cell['bf']
                    # Title cell: find the charPr with largest height (title font)
                    title_cp = None
                    max_h = 0
                    for cp in cell['charPrIDRefs']:
                        info = char_catalog.get(cp, {})
                        if info.get('height', 0) > max_h:
                            max_h = info['height']
                            title_cp = cp
                    if title_cp:
                        sm['title_bar_title'] = _make_style_tuple(
                            title_cp,
                            cell['paraPrIDRefs'][0] if cell['paraPrIDRefs'] else '15',
                            max_h, max_h, int(max_h * 0.85), int(max_h * 0.9))
                elif cell['rowAddr'] == 2:
                    sm['bf_gradient_bot'] = cell['bf']
                    if cell['charPrIDRefs']:
                        sm['title_bar_bottom'] = _make_style_tuple(
                            cell['charPrIDRefs'][0],
                            cell['paraPrIDRefs'][0] if cell['paraPrIDRefs'] else '3',
                            100, 100, 85, 60)

        # Data table (table_wrapper's table)
        if table_wrapper_idx is not None:
            cells = _extract_table_cells(s1_paras[table_wrapper_idx])
            header_bf = None
            body_bf = None
            header_cp = None
            body_cp = None
            header_pp = None
            for cell in cells:
                if cell['rowAddr'] == 0 and header_bf is None:
                    header_bf = cell['bf']
                    header_cp = cell['charPrIDRefs'][0] if cell['charPrIDRefs'] else None
                    header_pp = cell['paraPrIDRefs'][0] if cell['paraPrIDRefs'] else None
                elif cell['rowAddr'] >= 1 and body_bf is None:
                    body_bf = cell['bf']
                    body_cp = cell['charPrIDRefs'][0] if cell['charPrIDRefs'] else None
            if header_bf:
                sm['bf_table_header'] = header_bf
            if body_bf:
                sm['bf_table'] = body_bf
            if header_cp and header_pp:
                cp_info = char_catalog.get(header_cp, {})
                h = cp_info.get('height', 1200)
                sm['table_header'] = _make_style_tuple(header_cp, header_pp, h, h, int(h*0.85), 360)
            if body_cp:
                cp_info = char_catalog.get(body_cp, {})
                h = cp_info.get('height', 1200)
                pp = header_pp or '25'
                sm['table_body'] = _make_style_tuple(body_cp, pp, h, h, int(h*0.85), 360)

        # Phase E: Parse appendix section for appendix roles
        if appendix_section_path.exists():
            try:
                s2_xml = appendix_section_path.read_text(encoding='utf-8')
                s2_paras, _ = _extract_all_top_level_paragraphs(s2_xml)
                s2_attrs = [_extract_para_attrs(p) for p in s2_paras]

                # Find appendix first_para (with colPr)
                app_first_idx = None
                for i, a in enumerate(s2_attrs):
                    if a['has_colpr']:
                        app_first_idx = i
                        break

                if app_first_idx is not None:
                    a = s2_attrs[app_first_idx]
                    app_cp = a['charPrIDRefs'][-1] if a['charPrIDRefs'] else '0'
                    sm['appendix_first'] = _make_style_tuple(
                        app_cp, a['paraPrIDRef'], a['vertsize'],
                        a['textheight'], a['baseline'], a['spacing'])

                    # Extract appendix bar table cells (1-row 3-col)
                    cells = _extract_table_cells(s2_paras[app_first_idx])
                    for cell in cells:
                        if cell['colAddr'] == 0:
                            sm['bf_appendix_tab'] = cell['bf']
                            if cell['charPrIDRefs']:
                                cp_info = char_catalog.get(cell['charPrIDRefs'][0], {})
                                h = cp_info.get('height', 1600)
                                sm['appendix_tab'] = _make_style_tuple(
                                    cell['charPrIDRefs'][0],
                                    cell['paraPrIDRefs'][0] if cell['paraPrIDRefs'] else '18',
                                    h, h, int(h*0.85), int(h*0.6))
                        elif cell['colAddr'] == 1:
                            sm['bf_appendix_sep'] = cell['bf']
                            if cell['charPrIDRefs']:
                                cp_info = char_catalog.get(cell['charPrIDRefs'][0], {})
                                h = cp_info.get('height', 1550)
                                sm['appendix_sep_cell'] = _make_style_tuple(
                                    cell['charPrIDRefs'][0],
                                    cell['paraPrIDRefs'][0] if cell['paraPrIDRefs'] else '3',
                                    h, h, int(h*0.85), int(h*0.6))
                        elif cell['colAddr'] == 2:
                            sm['bf_appendix_title'] = cell['bf']
                            cps = cell['charPrIDRefs']
                            if cps:
                                # Title charPr: the one with largest height
                                title_cp = cps[0]
                                max_h = 0
                                for cp in cps:
                                    info = char_catalog.get(cp, {})
                                    if info.get('height', 0) > max_h:
                                        max_h = info['height']
                                        title_cp = cp
                                pp = cell['paraPrIDRefs'][0] if cell['paraPrIDRefs'] else '16'
                                sm['appendix_title'] = _make_style_tuple(
                                    title_cp, pp, max_h, max_h, int(max_h*0.85), int(max_h*0.3))
                                # sep_char: different charPr in same cell
                                for cp in cps:
                                    if cp != title_cp:
                                        cp_info = char_catalog.get(cp, {})
                                        h = cp_info.get('height', 1600)
                                        sm['appendix_sep_char'] = _make_style_tuple(
                                            cp, pp, h, h, int(h*0.85), int(h*0.3))
                                        break

                # Appendix spacer: next empty (non-table) paragraph after first_para.
                # If the next paragraph contains a table, its lineseg metrics will
                # reflect the table wrapper (e.g. vertsize=65974) — skip it and
                # fall back to the body section's spacer_small (same visual role).
                if app_first_idx is not None and app_first_idx + 1 < len(s2_attrs):
                    a = s2_attrs[app_first_idx + 1]
                    if not a['has_tbl'] and not a['has_text']:
                        sp_cp = a['charPrIDRefs'][0] if a['charPrIDRefs'] else '0'
                        sm['appendix_spacer'] = _make_style_tuple(
                            sp_cp, a['paraPrIDRef'], a['vertsize'],
                            a['textheight'], a['baseline'], a['spacing'])
                    elif 'spacer_small' in sm:
                        ss = sm['spacer_small']
                        sm['appendix_spacer'] = _make_style_tuple(
                            ss[0], ss[1], 1500, 1500, 1275, 900)

            except Exception as e:
                print(f"Warning: Could not parse appendix section: {e}")

        return sm

    except Exception as e:
        print(f"Warning: Could not build style map from template: {e}")
        return None


# ============================================================================
# Template Skeleton Extraction & Injection (V4)
# ============================================================================

def parse_last_lineseg(paragraph_xml):
    """Parse the last paragraph-level <hp:lineseg> for layout values.

    Finds linesegs that belong to the paragraph itself, NOT those nested
    inside table cells (<hp:tc>).  Works by stripping all <hp:tc>…</hp:tc>
    blocks first, then searching the remaining XML.

    Note: For paragraphs that contain a table, the paragraph-level lineseg
    will have a large vertsize reflecting the table wrapper height.  This is
    correct (it IS the paragraph's own lineseg), but callers should check
    has_tbl before using such values for style discovery.

    Returns dict with textpos, vertpos, vertsize, textheight, baseline, spacing.
    Returns None if not found.
    """
    # Strip table cell blocks so we only see paragraph-level linesegs.
    stripped = re.sub(r'<hp:tc\b[^>]*>.*?</hp:tc>', '', paragraph_xml, flags=re.DOTALL)

    pattern = re.compile(r'<hp:lineseg\s+([^/]*/)')
    matches = list(pattern.finditer(stripped))
    if not matches:
        return None
    attrs_str = matches[-1].group(1)
    result = {}
    for name in ('textpos', 'vertpos', 'vertsize', 'textheight', 'baseline', 'spacing'):
        m = re.search(rf'{name}="(\d+)"', attrs_str)
        if m:
            result[name] = int(m.group(1))
        else:
            return None  # required attribute missing
    return result


def seed_vpt_from_skeleton(skeleton_paragraphs):
    """Create a VertPosTracker pre-seeded from skeleton paragraph linesegs.

    Reads actual vertpos/vertsize/spacing from each skeleton paragraph's
    lineseg so the tracker starts at the correct position for appending
    dynamic content paragraphs.
    """
    vpt = VertPosTracker()
    for para_xml in skeleton_paragraphs:
        ls = parse_last_lineseg(para_xml)
        if ls:
            vpt.next(ls['vertsize'], ls['spacing'])
        else:
            # Fallback: use a reasonable default
            vpt.next(1500, 900)
    return vpt


def inject_body_title(p0_xml, title_text):
    """Replace the title text in the body section skeleton P0.

    Finds the title cell by table geometry (3-row 1-col table, rowAddr="1")
    and replaces ALL <hp:t> content within that cell.
    Uses cell position instead of hardcoded borderFillIDRef. (V2 fix)

    Returns modified XML, or None if injection fails.
    """
    # Find the 3-row 1-col table
    tbl_m = re.search(r'<hp:tbl\b[^>]*rowCnt="3"[^>]*colCnt="1"[^>]*>(.*?)</hp:tbl>', p0_xml, re.DOTALL)
    if not tbl_m:
        # Try reversed attribute order
        tbl_m = re.search(r'<hp:tbl\b[^>]*colCnt="1"[^>]*rowCnt="3"[^>]*>(.*?)</hp:tbl>', p0_xml, re.DOTALL)
    if not tbl_m:
        return None

    tbl_xml = tbl_m.group(0)
    tbl_start = tbl_m.start()

    # Find the <hp:tc> with rowAddr="1" (title cell — middle row)
    tc_pattern = re.compile(r'(<hp:tc\b[^>]*>)(.*?)(</hp:tc>)', re.DOTALL)
    new_tbl = tbl_xml
    replaced = False

    for tc_m in tc_pattern.finditer(tbl_xml):
        tc_body = tc_m.group(2)
        addr_m = re.search(r'<hp:cellAddr\s+colAddr="\d+"\s+rowAddr="1"', tc_body)
        if not addr_m:
            continue

        # Found the title cell — replace all <hp:t> content
        cell_full = tc_m.group(0)
        replaced_count = [0]

        def replacer(match):
            replaced_count[0] += 1
            if replaced_count[0] == 1:
                return f'<hp:t>{xml_escape(title_text)}</hp:t>'
            return '<hp:t></hp:t>'

        new_cell = re.sub(r'<hp:t>[^<]*</hp:t>', replacer, cell_full)
        if replaced_count[0] > 0:
            new_tbl = new_tbl[:tc_m.start()] + new_cell + new_tbl[tc_m.end():]
            replaced = True
        break

    if not replaced:
        return None

    return p0_xml[:tbl_start] + new_tbl + p0_xml[tbl_start + len(tbl_xml):]


def inject_body_date(p1_xml, date_str, department):
    """Replace date and department in body section skeleton P1.

    Uses run position instead of hardcoded charPrIDRef values. (V2 fix)
    The date line has 3 runs: date prefix, department, date suffix.
    Identifies groups by unique charPrIDRef values in document order.

    Returns modified XML, or None if no replacements occurred.
    """
    if not date_str and not department:
        return p1_xml

    # Find all <hp:run> with <hp:t> content
    run_pattern = re.compile(
        r'(<hp:run\s+charPrIDRef="(\d+)"[^>]*>)(.*?)(</hp:run>)',
        re.DOTALL
    )
    runs = list(run_pattern.finditer(p1_xml))
    if not runs:
        return None

    # Identify unique charPrIDRef groups in order
    # First unique charPrIDRef = date runs, second = department run
    unique_cps = []
    seen = set()
    for rm in runs:
        cp = rm.group(2)
        if cp not in seen:
            unique_cps.append(cp)
            seen.add(cp)

    # Handle single-run date line (all text in one run)
    if len(unique_cps) < 2:
        if len(runs) >= 1 and (date_str or department):
            rm = runs[0]
            old_t = re.search(r'<hp:t>[^<]*</hp:t>', rm.group(3))
            if old_t:
                new_date_text = f"('{date_str}, {department})" if date_str and department else \
                                f"('{date_str})" if date_str else f"({department})"
                new_t = f"<hp:t>{xml_escape(new_date_text)}</hp:t>"
                new_body = rm.group(3)[:old_t.start()] + new_t + rm.group(3)[old_t.end():]
                return p1_xml[:rm.start()] + rm.group(1) + new_body + rm.group(4) + p1_xml[rm.end():]
        return None

    date_cp = unique_cps[0]
    dept_cp = unique_cps[1]

    result = p1_xml
    # Process runs in reverse order to preserve offsets
    runs_reversed = list(reversed(runs))

    date_runs = [rm for rm in runs if rm.group(2) == date_cp]
    dept_runs = [rm for rm in runs if rm.group(2) == dept_cp]

    # Replace in reverse offset order to preserve positions
    replacements = []

    # Date prefix: first date run
    if date_str and date_runs:
        rm = date_runs[0]
        old_t = re.search(r'<hp:t>[^<]*</hp:t>', rm.group(3))
        if old_t:
            date_prefix = xml_escape("('" + date_str + ", ")
            new_t = "<hp:t>" + date_prefix + "</hp:t>"
            new_body = rm.group(3)[:old_t.start()] + new_t + rm.group(3)[old_t.end():]
            replacements.append((rm.start(), rm.end(), rm.group(1) + new_body + rm.group(4)))

    # Date suffix: last date run (if there are at least 2 date runs)
    if (date_str or department) and len(date_runs) >= 2:
        rm = date_runs[-1]
        old_t = re.search(r'<hp:t>[^<]*</hp:t>', rm.group(3))
        if old_t:
            suffix_escaped = xml_escape(")")
            new_t = "<hp:t>" + suffix_escaped + "</hp:t>"
            new_body = rm.group(3)[:old_t.start()] + new_t + rm.group(3)[old_t.end():]
            replacements.append((rm.start(), rm.end(), rm.group(1) + new_body + rm.group(4)))

    # Department: first dept run
    if department and dept_runs:
        rm = dept_runs[0]
        old_t = re.search(r'<hp:t>[^<]*</hp:t>', rm.group(3))
        if old_t:
            dept_escaped = xml_escape(department)
            new_t = "<hp:t>" + dept_escaped + "</hp:t>"
            new_body = rm.group(3)[:old_t.start()] + new_t + rm.group(3)[old_t.end():]
            replacements.append((rm.start(), rm.end(), rm.group(1) + new_body + rm.group(4)))

    if not replacements:
        return None

    # Apply replacements in reverse offset order
    replacements.sort(key=lambda x: x[0], reverse=True)
    for start, end, new_text in replacements:
        result = result[:start] + new_text + result[end:]

    return result


def inject_appendix_labels(p0_xml, tab_label, title_text):
    """Replace tab label and title in appendix skeleton P0.

    Uses table geometry (1-row 3-col table) and cell position (colAddr)
    instead of hardcoded borderFillIDRef values. (V2 fix)
    colAddr=0 → tab label, colAddr=2 → title text.

    Returns modified XML, or None if injection fails.
    """
    # Find the 1-row 3-col table
    tbl_m = re.search(r'<hp:tbl\b[^>]*rowCnt="1"[^>]*colCnt="3"[^>]*>(.*?)</hp:tbl>', p0_xml, re.DOTALL)
    if not tbl_m:
        tbl_m = re.search(r'<hp:tbl\b[^>]*colCnt="3"[^>]*rowCnt="1"[^>]*>(.*?)</hp:tbl>', p0_xml, re.DOTALL)
    if not tbl_m:
        return None

    tbl_xml = tbl_m.group(0)
    tbl_start = tbl_m.start()
    new_tbl = tbl_xml
    injected = False

    # Process cells in reverse order to preserve offsets
    tc_pattern = re.compile(r'(<hp:tc\b[^>]*>)(.*?)(</hp:tc>)', re.DOTALL)
    tc_matches = list(tc_pattern.finditer(tbl_xml))

    # Build replacement list
    replacements = []
    for tc_m in tc_matches:
        tc_body = tc_m.group(2)
        addr_m = re.search(r'<hp:cellAddr\s+colAddr="(\d+)"\s+rowAddr="\d+"', tc_body)
        if not addr_m:
            continue
        col = int(addr_m.group(1))

        if col == 0 and tab_label:
            # Tab label: replace first <hp:t> content
            cell_full = tc_m.group(0)
            new_cell, n = re.subn(
                r'<hp:t>[^<]*</hp:t>',
                f'<hp:t>{xml_escape(tab_label)}</hp:t>',
                cell_full, count=1
            )
            if n > 0:
                replacements.append((tc_m.start(), tc_m.end(), new_cell))
                injected = True

        elif col == 2 and title_text:
            # Title: replace <hp:t> content (first gets space, second gets title)
            cell_full = tc_m.group(0)
            replaced_count = [0]

            def replacer(match):
                replaced_count[0] += 1
                if replaced_count[0] == 1:
                    return '<hp:t> </hp:t>'  # leading space
                elif replaced_count[0] == 2:
                    return f'<hp:t>{xml_escape(title_text)}</hp:t>'
                return '<hp:t></hp:t>'

            new_cell = re.sub(r'<hp:t>[^<]*</hp:t>', replacer, cell_full)
            if replaced_count[0] > 0:
                replacements.append((tc_m.start(), tc_m.end(), new_cell))
                injected = True

    if not injected:
        return None

    # Apply replacements in reverse order to preserve offsets
    replacements.sort(key=lambda x: x[0], reverse=True)
    for start, end, new_text in replacements:
        new_tbl = new_tbl[:start] + new_text + new_tbl[end:]

    return p0_xml[:tbl_start] + new_tbl + p0_xml[tbl_start + len(tbl_xml):]


# ============================================================================
# XML Building Helpers
# ============================================================================

def sec_pr_xml(outline_ref="1"):
    """Generate the secPr element for the first paragraph."""
    return f'''<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="{outline_ref}" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">
        <hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>
        <hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>
        <hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>
        <hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>
        <hp:pagePr landscape="WIDELY" width="{PAGE_WIDTH}" height="{PAGE_HEIGHT}" gutterType="LEFT_ONLY">
          <hp:margin header="{MARGIN_HEADER}" footer="{MARGIN_FOOTER}" gutter="0" left="{MARGIN_LEFT}" right="{MARGIN_RIGHT}" top="{MARGIN_TOP}" bottom="{MARGIN_BOTTOM}"/>
        </hp:pagePr>
        <hp:footNotePr>
          <hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>
          <hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>
          <hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/>
          <hp:numbering type="CONTINUOUS" newNum="1"/>
          <hp:placement place="EACH_COLUMN" beneathText="0"/>
        </hp:footNotePr>
        <hp:endNotePr>
          <hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>
          <hp:noteLine length="14692344" type="SOLID" width="0.12 mm" color="#000000"/>
          <hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/>
          <hp:numbering type="CONTINUOUS" newNum="1"/>
          <hp:placement place="END_OF_DOCUMENT" beneathText="0"/>
        </hp:endNotePr>
        <hp:pageBorderFill type="BOTH" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">
          <hp:offset left="1417" right="1417" top="1417" bottom="1417"/>
        </hp:pageBorderFill>
        <hp:pageBorderFill type="EVEN" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">
          <hp:offset left="1417" right="1417" top="1417" bottom="1417"/>
        </hp:pageBorderFill>
        <hp:pageBorderFill type="ODD" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">
          <hp:offset left="1417" right="1417" top="1417" bottom="1417"/>
        </hp:pageBorderFill>
      </hp:secPr>'''


def lineseg_xml(textpos=0, vertpos=0, vertsize=1000, textheight=1000,
                baseline=850, spacing=600, horzpos=0, horzsize=HORZSIZE_DEFAULT,
                num_lines=1, full_text="", text_len=0):
    """
    Generate linesegarray element with multi-line support.

    For single-line paragraphs: generates 1 lineseg entry.
    For multi-line paragraphs: generates N lineseg entries with:
      - Incrementing vertpos per line
      - Accurate textpos per line (via character-by-character width estimation)
      - flags=393216 for first line, flags=1441792 for continuation lines

    Args:
        full_text: The actual paragraph text — used to compute accurate line breaks.
        text_len: Deprecated fallback; use full_text instead.
    """
    if num_lines <= 1:
        return (f'<hp:linesegarray>'
                f'<hp:lineseg textpos="{textpos}" vertpos="{vertpos}" '
                f'vertsize="{vertsize}" textheight="{textheight}" '
                f'baseline="{baseline}" spacing="{spacing}" '
                f'horzpos="{horzpos}" horzsize="{horzsize}" flags="{FLAGS_FIRST_LINE}"/>'
                f'</hp:linesegarray>')

    # Compute accurate line break positions from actual text
    if full_text:
        breaks = estimate_line_breaks(full_text, vertsize, horzsize)
        # Pad breaks list if estimate_line_breaks returned fewer than num_lines
        while len(breaks) < num_lines:
            last_tp = breaks[-1]
            remaining = len(full_text) - last_tp
            chunk = max(1, remaining // (num_lines - len(breaks) + 1))
            breaks.append(last_tp + chunk)
    else:
        # Fallback: naive even division (legacy behavior)
        tl = text_len if text_len > 0 else 30
        chars_per_line = max(1, tl // num_lines)
        breaks = [i * chars_per_line for i in range(num_lines)]

    segs = ""
    for i in range(num_lines):
        vp = vertpos + i * (vertsize + spacing)
        tp = breaks[i] if i < len(breaks) else breaks[-1]
        flags = FLAGS_FIRST_LINE if i == 0 else FLAGS_CONTINUATION
        segs += (f'<hp:lineseg textpos="{tp}" vertpos="{vp}" '
                 f'vertsize="{vertsize}" textheight="{textheight}" '
                 f'baseline="{baseline}" spacing="{spacing}" '
                 f'horzpos="{horzpos}" horzsize="{horzsize}" flags="{flags}"/>')
    return f'<hp:linesegarray>{segs}</hp:linesegarray>'


def paragraph_xml(para_pr_id, style_id, runs_xml, lineseg, para_id="2147483648", page_break="0"):
    """Generate a complete paragraph element."""
    return (f'<hp:p id="{para_id}" paraPrIDRef="{para_pr_id}" styleIDRef="{style_id}" '
            f'pageBreak="{page_break}" columnBreak="0" merged="0">'
            f'{runs_xml}{lineseg}</hp:p>')


def run_xml(char_pr_id, text="", inner_xml=""):
    """Generate a run element."""
    content = ""
    if inner_xml:
        content = inner_xml
    if text:
        content += f'<hp:t>{xml_escape(text)}</hp:t>'
    if not content:
        return f'<hp:run charPrIDRef="{char_pr_id}"/>'
    return f'<hp:run charPrIDRef="{char_pr_id}">{content}</hp:run>'


def table_cell_xml(col_addr, row_addr, width, height, border_fill_id,
                   para_pr_id, char_pr_id, text, vert_align="CENTER",
                   style_id="0", vertsize=1200, textheight=1200, baseline=1020, spacing=360):
    """Generate a table cell element with multi-line support."""
    inner_hz = width - 1022  # Hancom uses width-1022 (e.g. 15874→14852)
    inner_hz = max(inner_hz, 0)

    # Estimate lines for cell text
    nlines = estimate_line_count(text, vertsize, inner_hz) if text else 1

    return (f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" '
            f'borderFillIDRef="{border_fill_id}">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" '
            f'vertAlign="{vert_align}" linkListIDRef="0" linkListNextIDRef="0" '
            f'textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f'<hp:p id="2147483648" paraPrIDRef="{para_pr_id}" styleIDRef="{style_id}" '
            f'pageBreak="0" columnBreak="0" merged="0">'
            f'{run_xml(char_pr_id, text)}'
            f'{lineseg_xml(vertsize=vertsize, textheight=textheight, baseline=baseline, spacing=spacing, horzsize=inner_hz, num_lines=nlines, full_text=text)}'
            f'</hp:p></hp:subList>'
            f'<hp:cellAddr colAddr="{col_addr}" rowAddr="{row_addr}"/>'
            f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{width}" height="{height}"/>'
            f'<hp:cellMargin left="510" right="510" top="141" bottom="141"/>'
            f'</hp:tc>')


# ============================================================================
# Title Bar Generator (3-row gradient bar)
# ============================================================================

def title_bar_xml(title_text, sm, table_id=1975012386):
    """Generate the 3-row title bar (gradient top, title, gradient bottom)."""
    bar_width = 48077
    hz = bar_width - 281  # Hancom uses 47796 (not 47795)

    top = sm["title_bar_top"]
    mid = sm["title_bar_title"]
    bot = sm["title_bar_bottom"]

    row1 = (f'<hp:tr><hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="{sm["bf_gradient_top"]}">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
            f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f'<hp:p id="2147483648" paraPrIDRef="{top[1]}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="{top[0]}"/>'
            f'{lineseg_xml(vertsize=top[2], textheight=top[3], baseline=top[4], spacing=top[5], horzsize=hz)}'
            f'</hp:p></hp:subList>'
            f'<hp:cellAddr colAddr="0" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{bar_width}" height="380"/>'
            f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc></hp:tr>')

    row2 = (f'<hp:tr><hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="{sm["bf_title_bg"]}">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
            f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f'<hp:p id="2147483648" paraPrIDRef="{mid[1]}" styleIDRef="15" pageBreak="0" columnBreak="0" merged="0">'
            f'{run_xml(mid[0], title_text)}'
            f'<hp:run charPrIDRef="{sm["heading_tail"][0]}"/>'
            f'{lineseg_xml(vertsize=mid[2], textheight=mid[3], baseline=mid[4], spacing=mid[5], horzsize=hz)}'
            f'</hp:p></hp:subList>'
            f'<hp:cellAddr colAddr="0" rowAddr="1"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{bar_width}" height="2563"/>'
            f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc></hp:tr>')

    row3 = (f'<hp:tr><hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="{sm["bf_gradient_bot"]}">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
            f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f'<hp:p id="2147483648" paraPrIDRef="{bot[1]}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="{bot[0]}"/>'
            f'{lineseg_xml(vertsize=bot[2], textheight=bot[3], baseline=bot[4], spacing=bot[5], horzsize=hz)}'
            f'</hp:p></hp:subList>'
            f'<hp:cellAddr colAddr="0" rowAddr="2"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{bar_width}" height="380"/>'
            f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc></hp:tr>')

    return (f'<hp:tbl id="{table_id}" zOrder="2" numberingType="TABLE" '
            f'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" '
            f'pageBreak="NONE" repeatHeader="1" rowCnt="3" colCnt="1" cellSpacing="0" '
            f'borderFillIDRef="{sm["bf_table"]}" noAdjust="0">'
            f'<hp:sz width="{bar_width}" widthRelTo="ABSOLUTE" height="3323" heightRelTo="ABSOLUTE" protect="0"/>'
            f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
            f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" '
            f'vertOffset="0" horzOffset="0"/>'
            f'<hp:outMargin left="140" right="140" top="140" bottom="140"/>'
            f'<hp:inMargin left="140" right="140" top="140" bottom="140"/>'
            f'{row1}{row2}{row3}</hp:tbl>')


# ============================================================================
# Appendix Bar Generator
# ============================================================================

def appendix_bar_xml(tab_label, title_text, sm, table_id=1977606721):
    """Generate appendix-style title bar (참고N | separator | title)."""
    total_width = 48159
    col1_w, col2_w, col3_w = 5968, 565, 41626

    tab_s = sm["appendix_tab"]
    sep_s = sm["appendix_sep_cell"]
    ttl_s = sm["appendix_title"]
    sep_c = sm["appendix_sep_char"]

    cells = (
        f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="{sm["bf_appendix_tab"]}">'
        f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        f'<hp:p id="2147483648" paraPrIDRef="{tab_s[1]}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'{run_xml(tab_s[0], tab_label)}'
        f'{lineseg_xml(vertsize=tab_s[2], textheight=tab_s[3], baseline=tab_s[4], spacing=tab_s[5], horzsize=5684)}'
        f'</hp:p></hp:subList>'
        f'<hp:cellAddr colAddr="0" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="{col1_w}" height="2831"/><hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc>'

        f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="{sm["bf_appendix_sep"]}">'
        f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        f'<hp:p id="2147483648" paraPrIDRef="{sep_s[1]}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{sep_s[0]}"/>'
        f'{lineseg_xml(vertsize=sep_s[2], textheight=sep_s[3], baseline=sep_s[4], spacing=sep_s[5], horzsize=1440)}'
        f'</hp:p></hp:subList>'
        f'<hp:cellAddr colAddr="1" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="{col2_w}" height="2831"/><hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc>'

        f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="{sm["bf_appendix_title"]}">'
        f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        f'<hp:p id="2147483648" paraPrIDRef="{ttl_s[1]}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'{run_xml(sep_c[0], " ")}{run_xml(ttl_s[0], title_text)}'
        f'{lineseg_xml(vertsize=ttl_s[2], textheight=ttl_s[3], baseline=ttl_s[4], spacing=ttl_s[5], horzsize=41344)}'
        f'</hp:p></hp:subList>'
        f'<hp:cellAddr colAddr="2" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="{col3_w}" height="2831"/><hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc>'
    )

    return (f'<hp:tbl id="{table_id}" zOrder="3" numberingType="TABLE" '
            f'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" '
            f'pageBreak="CELL" repeatHeader="1" rowCnt="1" colCnt="3" cellSpacing="0" '
            f'borderFillIDRef="{sm["bf_table"]}" noAdjust="0">'
            f'<hp:sz width="{total_width}" widthRelTo="ABSOLUTE" height="2831" heightRelTo="ABSOLUTE" protect="0"/>'
            f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
            f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" '
            f'vertOffset="0" horzOffset="0"/>'
            f'<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
            f'<hp:inMargin left="141" right="141" top="141" bottom="141"/>'
            f'<hp:tr>{cells}</hp:tr></hp:tbl>')


# ============================================================================
# Data Table Generator (with dynamic height)
# ============================================================================

def data_table_xml(headers, rows, sm, caption="", table_id=1974981391):
    """Generate a data table with header row and body rows."""
    num_cols = len(headers)
    num_rows = len(rows) + 1
    total_width = 47622
    col_width = total_width // num_cols
    col_widths = [col_width] * num_cols
    col_widths[-1] += total_width - col_width * num_cols
    row_height = 2048
    total_height = row_height * num_rows

    th = sm["table_header"]
    tb = sm["table_body"]

    header_cells = ""
    for i, (hdr, w) in enumerate(zip(headers, col_widths)):
        header_cells += table_cell_xml(i, 0, w, row_height, sm["bf_table_header"],
                                        th[1], th[0], hdr,
                                        vertsize=th[2], textheight=th[3], baseline=th[4], spacing=th[5])

    body_rows = ""
    for r_idx, row in enumerate(rows):
        cells = ""
        for c_idx, (cell_text, w) in enumerate(zip(row, col_widths)):
            cells += table_cell_xml(c_idx, r_idx + 1, w, row_height, sm["bf_table"],
                                     tb[1], tb[0], str(cell_text),
                                     vertsize=tb[2], textheight=tb[3], baseline=tb[4], spacing=tb[5])
        body_rows += f'<hp:tr>{cells}</hp:tr>'

    paragraphs = ""
    if caption:
        tc = sm["table_caption"]
        paragraphs += paragraph_xml(tc[1], "0", run_xml(tc[0], f"< {caption} >"),
                                     lineseg_xml(vertsize=tc[2], textheight=tc[3], baseline=tc[4], spacing=tc[5]))

    # Dynamic wrapper vertsize based on actual table height + margins
    wrapper_vertsize = total_height + 566   # table height + top/bottom outMargin (283*2)

    tw = sm["table_wrapper"]
    tbl = (f'<hp:tbl id="{table_id}" zOrder="0" numberingType="TABLE" '
           f'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" '
           f'pageBreak="CELL" repeatHeader="1" rowCnt="{num_rows}" colCnt="{num_cols}" '
           f'cellSpacing="0" borderFillIDRef="{sm["bf_table"]}" noAdjust="0">'
           f'<hp:sz width="{total_width}" widthRelTo="ABSOLUTE" height="{total_height}" heightRelTo="ABSOLUTE" protect="0"/>'
           f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
           f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" '
           f'vertOffset="0" horzOffset="0"/>'
           f'<hp:outMargin left="283" right="283" top="283" bottom="283"/>'
           f'<hp:inMargin left="510" right="510" top="141" bottom="141"/>'
           f'<hp:tr>{header_cells}</hp:tr>{body_rows}</hp:tbl>')

    paragraphs += paragraph_xml(tw[1], "0",
                                 f'<hp:run charPrIDRef="{tw[0]}">{tbl}<hp:t/></hp:run>',
                                 lineseg_xml(vertsize=wrapper_vertsize, textheight=wrapper_vertsize,
                                             baseline=int(wrapper_vertsize * 0.85), spacing=tw[5]))
    return paragraphs, wrapper_vertsize


# Bullet-level types for transition spacer detection
_LEVEL_SQUARE = {"heading"}   # □ level
_LEVEL_CIRCLE = {"bullet"}    # ㅇ level (only items with the ㅇ marker)


def _needs_bullet_transition_spacer(prev_type, curr_type):
    """Return True when switching between □ and ㅇ bullet levels."""
    if prev_type is None:
        return False
    return ((prev_type in _LEVEL_SQUARE and curr_type in _LEVEL_CIRCLE) or
            (prev_type in _LEVEL_CIRCLE and curr_type in _LEVEL_SQUARE))


def _bullet_transition_spacer_xml(sm, vpt):
    """Generate a 6pt empty-line spacer for bullet level transitions."""
    ss = sm["spacer_small"]
    h = BULLET_TRANSITION_SPACER_HEIGHT
    spacing = int(h * 0.6)
    baseline = int(h * 0.85)
    vp = vpt.next(h, spacing)
    return paragraph_xml(ss[1], "0", run_xml(ss[0]),
                         lineseg_xml(vertpos=vp, vertsize=h, textheight=h,
                                     baseline=baseline, spacing=spacing))


# ============================================================================
# Content Item Generators (multi-line aware)
# ============================================================================

def generate_content_item(item, sm, vpt):
    """Generate XML for a single content item. Updates vpt (VertPosTracker)."""
    item_type = item.get("type", "paragraph")
    text = item.get("text", "")

    if item_type == "heading":
        s = sm["heading_marker"]
        full_text = f"□ {text} "
        nlines = estimate_line_count(full_text, s[2])
        vp = vpt.next(s[2], s[5], nlines)
        runs = (run_xml(sm["heading_marker"][0], "□") +
                run_xml(sm["heading_text"][0], f" {text}") +
                run_xml(sm["heading_tail"][0], " ") +
                run_xml(sm["heading_end"][0]))
        return paragraph_xml(s[1], "15", runs,
                              lineseg_xml(vertpos=vp, vertsize=s[2], textheight=s[3],
                                          baseline=s[4], spacing=s[5],
                                          num_lines=nlines, full_text=full_text))

    elif item_type == "paragraph":
        s = sm["paragraph"]
        full_text = f" {text}"
        nlines = estimate_line_count(full_text, s[2])
        vp = vpt.next(s[2], s[5], nlines)
        runs = run_xml(s[0], full_text) + run_xml(sm["paragraph_end"][0])
        return paragraph_xml(s[1], "0", runs,
                              lineseg_xml(vertpos=vp, vertsize=s[2], textheight=s[3],
                                          baseline=s[4], spacing=s[5],
                                          num_lines=nlines, full_text=full_text))

    elif item_type == "bullet":
        s = sm["bullet"]
        full_text = f" ㅇ {text}"
        nlines = estimate_line_count(full_text, s[2])
        vp = vpt.next(s[2], s[5], nlines)
        runs = run_xml(s[0], full_text) + run_xml(sm["bullet_end"][0])
        return paragraph_xml(s[1], "0", runs,
                              lineseg_xml(vertpos=vp, vertsize=s[2], textheight=s[3],
                                          baseline=s[4], spacing=s[5],
                                          num_lines=nlines, full_text=full_text))

    elif item_type == "dash":
        s = sm["dash"]
        full_text = f"   - {text}"
        nlines = estimate_line_count(full_text, s[2])
        vp = vpt.next(s[2], s[5], nlines)
        runs = run_xml(s[0], full_text) + run_xml(sm["dash_end"][0])
        return paragraph_xml(s[1], "0", runs,
                              lineseg_xml(vertpos=vp, vertsize=s[2], textheight=s[3],
                                          baseline=s[4], spacing=s[5],
                                          num_lines=nlines, full_text=full_text))

    elif item_type == "star":
        s = sm["star"]
        full_text = f"     * {text}"
        nlines = estimate_line_count(full_text, s[2])
        vp = vpt.next(s[2], s[5], nlines)
        runs = run_xml(s[0], full_text) + run_xml(sm["star_end"][0])
        return paragraph_xml(s[1], "0", runs,
                              lineseg_xml(vertpos=vp, vertsize=s[2], textheight=s[3],
                                          baseline=s[4], spacing=s[5],
                                          num_lines=nlines, full_text=full_text))

    elif item_type == "table":
        # Tables use their own internal lineseg; advance vpt with actual sizes
        tc = sm["table_caption"]
        if item.get("caption"):
            cap_text = f"< {item['caption']} >"
            cap_nlines = estimate_line_count(cap_text, tc[2])
            vpt.next(tc[2], tc[5], cap_nlines)

        tbl_xml, wrapper_vs = data_table_xml(
            item.get("headers", []), item.get("rows", []),
            sm, item.get("caption", ""), item.get("table_id", 1974981391))

        tw = sm["table_wrapper"]
        vpt.next(wrapper_vs, tw[5])  # table wrapper para
        return tbl_xml

    elif item_type == "note":
        s = sm["note"]
        full_text = f"▷ {text}"
        nlines = estimate_line_count(full_text, s[2])
        vp = vpt.next(s[2], s[5], nlines)
        runs = run_xml(s[0], full_text)
        return paragraph_xml(s[1], "0", runs,
                              lineseg_xml(vertpos=vp, vertsize=s[2], textheight=s[3],
                                          baseline=s[4], spacing=s[5],
                                          num_lines=nlines, full_text=full_text))

    elif item_type == "empty":
        s = sm["spacer_small"]
        vp = vpt.next(s[2], s[5])
        runs = run_xml(s[0])
        return paragraph_xml(s[1], "0", runs,
                              lineseg_xml(vertpos=vp, vertsize=s[2], textheight=s[3],
                                          baseline=s[4], spacing=s[5]))

    else:
        s = sm["paragraph"]
        full_text = text
        nlines = estimate_line_count(full_text, s[2])
        vp = vpt.next(s[2], s[5], nlines)
        runs = run_xml(s[0], text) + run_xml(sm["paragraph_end"][0])
        return paragraph_xml(s[1], "0", runs,
                              lineseg_xml(vertpos=vp, vertsize=s[2], textheight=s[3],
                                          baseline=s[4], spacing=s[5],
                                          num_lines=nlines, full_text=full_text))


# ============================================================================
# Section Generators
# ============================================================================

def generate_body_section_xml(section_config, sm, template_dir=None, outline_ref="2"):
    """Generate a body section with title bar and content.

    When template_dir is provided, finds the body section (section0 or
    section1, whichever has colPr) and uses it as the structural skeleton
    (title bar, date line, spacer).  Appends dynamic content.  Falls back
    to fully-generated XML if template is unavailable or injection fails.
    """
    title = section_config.get("title_bar", "보고서 제목")
    content_items = section_config.get("content", [])
    date_text = section_config.get("date", "")
    department = section_config.get("department", "")

    # --- Template path: use skeleton from body section ---
    # Detects body section by styleIDRef="15" heading count.
    # Uses structural markers (colPr, RIGHT-aligned paraPr) instead of position. (V3 fix)
    if template_dir:
        header_path = Path(template_dir) / "Contents" / "header.xml"
        body_section_path, _ = _detect_template_sections(template_dir)
        if body_section_path is None:
            body_section_path = Path(template_dir) / "Contents" / "section1.xml"
        if body_section_path.exists():
            try:
                raw_xml = body_section_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                raw_xml = None
            if raw_xml:
                all_paras, sec_header = _extract_all_top_level_paragraphs(raw_xml)

                if len(all_paras) >= 3:
                    # Build paraPr catalog for alignment detection
                    _, para_cat = _parse_header_catalogs(header_path) if header_path.exists() else (None, None)

                    # Identify skeleton by structural markers
                    skeleton_first = None  # has <hp:colPr>
                    skeleton_date = None   # paraPr with RIGHT alignment
                    skeleton_spacer = None # empty paragraph between date and first heading

                    first_heading_idx = None
                    for i, p in enumerate(all_paras):
                        if '<hp:colPr' in p and skeleton_first is None:
                            skeleton_first = p
                        elif skeleton_first is not None and skeleton_date is None and first_heading_idx is None:
                            pp_m = re.search(r'paraPrIDRef="(\d+)"', p)
                            pp_id = pp_m.group(1) if pp_m else None
                            pp_info = (para_cat or {}).get(pp_id, {})
                            if pp_info.get('align') == 'RIGHT':
                                skeleton_date = p
                        elif skeleton_date is not None and skeleton_spacer is None:
                            # First empty paragraph after date line
                            texts = re.findall(r'<hp:t>([^<]+)</hp:t>', p)
                            has_text = any(t.strip() for t in texts)
                            if not has_text:
                                skeleton_spacer = p
                                break
                        # Track first heading for boundary
                        st_m = re.search(r'styleIDRef="(\d+)"', p)
                        if st_m and st_m.group(1) == '15' and first_heading_idx is None:
                            first_heading_idx = i

                    if skeleton_first is not None and skeleton_date is not None and skeleton_spacer is not None:
                        p0 = inject_body_title(skeleton_first, title)
                        p1 = inject_body_date(skeleton_date, date_text, department)
                        p2 = skeleton_spacer

                        if p0 is not None and p1 is not None:
                            vpt = seed_vpt_from_skeleton([p0, p1, p2])

                            content_xml = ""
                            prev_type = None
                            for item in content_items:
                                curr_type = item.get("type", "paragraph")
                                has_transition = _needs_bullet_transition_spacer(prev_type, curr_type)
                                if has_transition:
                                    content_xml += _bullet_transition_spacer_xml(sm, vpt)
                                if curr_type == "heading" and not has_transition:
                                    ss = sm["spacer_small"]
                                    vp = vpt.next(ss[2], ss[5])
                                    content_xml += paragraph_xml(ss[1], "0", run_xml(ss[0]),
                                        lineseg_xml(vertpos=vp, vertsize=ss[2], textheight=ss[3],
                                                    baseline=ss[4], spacing=ss[5]))
                                content_xml += generate_content_item(item, sm, vpt)
                                prev_type = curr_type

                            return sec_header + p0 + p1 + p2 + content_xml + '</hs:sec>'

    # --- Fallback: fully generated (original v3 behavior) ---
    vpt = VertPosTracker()
    paragraphs = ""

    fp = sm["first_para"]
    vpt.next(fp[2], fp[5])

    title_bar = title_bar_xml(title, sm)
    first_para = (
        f'<hp:p id="0" paraPrIDRef="{fp[1]}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{sm["heading_tail"][0]}">'
        f'<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
        f'{sec_pr_xml(outline_ref)}'
        f'</hp:run>'
        f'<hp:run charPrIDRef="0"><hp:ctrl><hp:pageNum pos="BOTTOM_CENTER" formatType="DIGIT" sideChar="-"/></hp:ctrl></hp:run>'
        f'<hp:run charPrIDRef="{sm["heading_tail"][0]}">{title_bar}</hp:run>'
        f'<hp:run charPrIDRef="{fp[0]}"><hp:t/></hp:run>'
        f'{lineseg_xml(vertpos=0, vertsize=fp[2], textheight=fp[3], baseline=fp[4], spacing=fp[5])}'
        f'</hp:p>')
    paragraphs += first_para

    if date_text and department:
        dl = sm["date_line"]
        date_full_text = f"('{date_text}, {department})"
        nlines = estimate_line_count(date_full_text, dl[2])
        vp = vpt.next(dl[2], dl[5], nlines)
        runs = (run_xml(dl[0], f"('{date_text}, ") +
                run_xml(sm["date_emphasis"][0], department) +
                run_xml(dl[0], ")"))
        paragraphs += paragraph_xml(dl[1], "0", runs,
                                     lineseg_xml(vertpos=vp, vertsize=dl[2], textheight=dl[3],
                                                 baseline=dl[4], spacing=dl[5],
                                                 num_lines=nlines, full_text=date_full_text))

    sp = sm["spacer_medium"]
    vp = vpt.next(sp[2], sp[5])
    paragraphs += paragraph_xml(sp[1], "0", run_xml(sp[0]),
                                 lineseg_xml(vertpos=vp, vertsize=sp[2], textheight=sp[3],
                                             baseline=sp[4], spacing=sp[5]))

    prev_type = None
    for item in content_items:
        curr_type = item.get("type", "paragraph")
        has_transition = _needs_bullet_transition_spacer(prev_type, curr_type)
        if has_transition:
            paragraphs += _bullet_transition_spacer_xml(sm, vpt)
        if curr_type == "heading" and not has_transition:
            ss = sm["spacer_small"]
            vp = vpt.next(ss[2], ss[5])
            paragraphs += paragraph_xml(ss[1], "0", run_xml(ss[0]),
                                         lineseg_xml(vertpos=vp, vertsize=ss[2], textheight=ss[3],
                                                     baseline=ss[4], spacing=ss[5]))
        paragraphs += generate_content_item(item, sm, vpt)
        prev_type = curr_type

    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><hs:sec {NS_DECL}>{paragraphs}</hs:sec>'


def generate_appendix_section_xml(section_config, sm, template_dir=None, outline_ref="2"):
    """Generate an appendix section with tab-style title bar.

    When template_dir is provided, finds the appendix section (section1 or
    section2) and uses it as the structural skeleton.  Falls back to
    fully-generated XML if unavailable.
    """
    tab_label = section_config.get("title_bar", "참고1")
    appendix_title = section_config.get("appendix_title", "")
    content_items = section_config.get("content", [])

    # --- Template path: use skeleton from appendix section ---
    # Detects appendix section by colPr + 1x3 table (appendix bar).
    # Uses structural markers (colPr) instead of position. (V3 fix)
    if template_dir:
        _, appendix_section_path = _detect_template_sections(template_dir)
        if appendix_section_path is None:
            appendix_section_path = Path(template_dir) / "Contents" / "section2.xml"
        if appendix_section_path.exists():
            try:
                raw_xml = appendix_section_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                raw_xml = None
            if raw_xml:
                all_paras, sec_header = _extract_all_top_level_paragraphs(raw_xml)

                if len(all_paras) >= 1:
                    # Identify skeleton by structural markers
                    skeleton_first = None  # has <hp:colPr>
                    skeleton_spacer = None # empty paragraph after first_para (optional)

                    for i, p in enumerate(all_paras):
                        if '<hp:colPr' in p and skeleton_first is None:
                            skeleton_first = p
                        elif skeleton_first is not None and skeleton_spacer is None:
                            # Only accept truly empty paragraphs as spacer
                            texts = re.findall(r'<hp:t>([^<]+)</hp:t>', p)
                            has_text = any(t.strip() for t in texts)
                            has_tbl = '<hp:tbl' in p
                            if not has_text and not has_tbl:
                                skeleton_spacer = p
                            break  # Stop after first candidate (spacer or not)

                    if skeleton_first is not None:
                        p0 = inject_appendix_labels(skeleton_first, tab_label, appendix_title)

                        if p0 is not None:
                            skeleton_parts = [p0]
                            if skeleton_spacer is not None:
                                skeleton_parts.append(skeleton_spacer)
                            vpt = seed_vpt_from_skeleton(skeleton_parts)

                            # Generate spacer if template didn't have one
                            spacer_xml = ""
                            if skeleton_spacer is None:
                                asp = sm["appendix_spacer"]
                                vp = vpt.next(asp[2], asp[5])
                                spacer_xml = paragraph_xml(asp[1], "15", run_xml(asp[0]),
                                    lineseg_xml(vertpos=vp, vertsize=asp[2], textheight=asp[3],
                                                baseline=asp[4], spacing=asp[5]))

                            content_xml = ""
                            prev_type = None
                            for item in content_items:
                                curr_type = item.get("type", "paragraph")
                                has_transition = _needs_bullet_transition_spacer(prev_type, curr_type)
                                if has_transition:
                                    content_xml += _bullet_transition_spacer_xml(sm, vpt)
                                if curr_type == "heading" and not has_transition:
                                    ss = sm["spacer_small"]
                                    vp = vpt.next(ss[2], ss[5])
                                    content_xml += paragraph_xml(ss[1], "0", run_xml(ss[0]),
                                        lineseg_xml(vertpos=vp, vertsize=ss[2], textheight=ss[3],
                                                    baseline=ss[4], spacing=ss[5]))
                                content_xml += generate_content_item(item, sm, vpt)
                                prev_type = curr_type

                            result = sec_header + p0
                            if skeleton_spacer is not None:
                                result += skeleton_spacer
                            result += spacer_xml + content_xml + '</hs:sec>'
                            return result

    # --- Fallback: fully generated (original v3 behavior) ---
    vpt = VertPosTracker()
    paragraphs = ""

    af = sm["appendix_first"]
    vpt.next(af[2], af[5])

    app_bar = appendix_bar_xml(tab_label, appendix_title, sm)
    first_para = (
        f'<hp:p id="2147483648" paraPrIDRef="{af[1]}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{af[0]}">'
        f'<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
        f'{sec_pr_xml(outline_ref)}'
        f'</hp:run>'
        f'<hp:run charPrIDRef="0"><hp:ctrl><hp:pageNum pos="BOTTOM_CENTER" formatType="DIGIT" sideChar="-"/></hp:ctrl></hp:run>'
        f'<hp:run charPrIDRef="{af[0]}">{app_bar}<hp:t/></hp:run>'
        f'{lineseg_xml(vertpos=0, vertsize=af[2], textheight=af[3], baseline=af[4], spacing=af[5])}'
        f'</hp:p>')
    paragraphs += first_para

    asp = sm["appendix_spacer"]
    vp = vpt.next(asp[2], asp[5])
    paragraphs += paragraph_xml(asp[1], "15", run_xml(asp[0]),
                                 lineseg_xml(vertpos=vp, vertsize=asp[2], textheight=asp[3],
                                             baseline=asp[4], spacing=asp[5]))

    prev_type = None
    for item in content_items:
        curr_type = item.get("type", "paragraph")
        has_transition = _needs_bullet_transition_spacer(prev_type, curr_type)
        if has_transition:
            paragraphs += _bullet_transition_spacer_xml(sm, vpt)
        if curr_type == "heading" and not has_transition:
            ss = sm["spacer_small"]
            vp = vpt.next(ss[2], ss[5])
            paragraphs += paragraph_xml(ss[1], "0", run_xml(ss[0]),
                                         lineseg_xml(vertpos=vp, vertsize=ss[2], textheight=ss[3],
                                                     baseline=ss[4], spacing=ss[5]))
        paragraphs += generate_content_item(item, sm, vpt)
        prev_type = curr_type

    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><hs:sec {NS_DECL}>{paragraphs}</hs:sec>'


# ============================================================================
# Cover Page Dynamic Generation
# ============================================================================

def generate_cover_section_xml(template_section0_path, config, sm):
    """
    Generate cover page by modifying the template's section0.xml.
    Injects title, date, and department into the correct cells.
    """
    content = Path(template_section0_path).read_text(encoding="utf-8")

    title = config.get("title", "")
    date_str = config.get("date", "")

    # --- Inject title ---
    if title:
        pattern = r'(borderFillIDRef="8".*?<hp:run charPrIDRef="25")/>'
        replacement = rf'\1><hp:t>{xml_escape(title)}</hp:t></hp:run>'
        content = re.sub(pattern, replacement, content, count=1, flags=re.DOTALL)

    # --- Inject date ---
    if date_str:
        parts = re.findall(r'\d+', date_str)
        if len(parts) >= 3:
            year = parts[0] if len(parts[0]) == 4 else f"20{parts[0]}"
            month = parts[1]
            day = parts[2]
            content = content.replace(
                '<hp:t>2026. </hp:t>',
                f'<hp:t>{year}. </hp:t>'
            )
            content = content.replace(
                '<hp:t>0. 0. </hp:t>',
                f'<hp:t>{month}. {day}. </hp:t>'
            )
        elif len(parts) >= 1:
            content = content.replace('<hp:t>2026. </hp:t>', f'<hp:t>{date_str} </hp:t>')
            content = content.replace('<hp:t>0. 0. </hp:t>', '<hp:t></hp:t>')

    return content


# ============================================================================
# content.hpf / container.rdf Generators
# ============================================================================

def generate_content_hpf(num_sections, has_images=True, image_files=None,
                         title="보고서", creator="이노베이션아카데미"):
    """Generate the content.hpf (OPF package manifest).

    Args:
        image_files: Optional list of image filenames in BinData/ (e.g. ['image1.png']).
            If None, falls back to has_images flag with image1.png only.
    """
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
    if image_files:
        for img in sorted(image_files):
            img_id = img.rsplit('.', 1)[0]  # e.g. 'image1'
            ext = img.rsplit('.', 1)[-1].lower()
            media_type = {'png': 'image/png', 'jpg': 'image/jpg', 'jpeg': 'image/jpeg',
                          'gif': 'image/gif', 'bmp': 'image/bmp'}.get(ext, 'image/png')
            manifest += f'<opf:item id="{img_id}" href="BinData/{img}" media-type="{media_type}" isEmbeded="1"/>'
    elif has_images:
        manifest += '<opf:item id="image1" href="BinData/image1.png" media-type="image/png" isEmbeded="1"/>'
    for i in range(num_sections):
        manifest += f'<opf:item id="section{i}" href="Contents/section{i}.xml" media-type="application/xml"/>'
    manifest += '<opf:item id="settings" href="settings.xml" media-type="application/xml"/>'

    spine = '<opf:itemref idref="header" linear="yes"/>'
    for i in range(num_sections):
        spine += f'<opf:itemref idref="section{i}" linear="yes"/>'

    ns_block = ' '.join(f'xmlns:{p}="{u}"' for p, u in [
        ('ha', 'http://www.hancom.co.kr/hwpml/2011/app'),
        ('hp', 'http://www.hancom.co.kr/hwpml/2011/paragraph'),
        ('hp10', 'http://www.hancom.co.kr/hwpml/2016/paragraph'),
        ('hs', 'http://www.hancom.co.kr/hwpml/2011/section'),
        ('hc', 'http://www.hancom.co.kr/hwpml/2011/core'),
        ('hh', 'http://www.hancom.co.kr/hwpml/2011/head'),
        ('hhs', 'http://www.hancom.co.kr/hwpml/2011/history'),
        ('hm', 'http://www.hancom.co.kr/hwpml/2011/master-page'),
        ('hpf', 'http://www.hancom.co.kr/schema/2011/hpf'),
        ('dc', 'http://purl.org/dc/elements/1.1/'),
        ('opf', 'http://www.idpf.org/2007/opf/'),
        ('ooxmlchart', 'http://www.hancom.co.kr/hwpml/2016/ooxmlchart'),
        ('hwpunitchar', 'http://www.hancom.co.kr/hwpml/2016/HwpUnitChar'),
        ('epub', 'http://www.idpf.org/2007/ops'),
        ('config', 'urn:oasis:names:tc:opendocument:xmlns:config:1.0'),
    ])

    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><opf:package {ns_block} version="" unique-identifier="" id="">'
            f'<opf:metadata><opf:title>{xml_escape(title)}</opf:title><opf:language>ko</opf:language>'
            f'<opf:meta name="creator" content="text">{xml_escape(creator)}</opf:meta>'
            f'<opf:meta name="subject" content="text"/><opf:meta name="description" content="text"/>'
            f'<opf:meta name="lastsaveby" content="text">Claude</opf:meta>'
            f'<opf:meta name="CreatedDate" content="text">{now}</opf:meta>'
            f'<opf:meta name="ModifiedDate" content="text">{now}</opf:meta>'
            f'<opf:meta name="keyword" content="text"/></opf:metadata>'
            f'<opf:manifest>{manifest}</opf:manifest><opf:spine>{spine}</opf:spine></opf:package>')


def generate_container_rdf(num_sections):
    """Generate container.rdf."""
    d = ('<rdf:Description rdf:about=""><ns0:hasPart xmlns:ns0="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" '
         'rdf:resource="Contents/header.xml"/></rdf:Description>'
         '<rdf:Description rdf:about="Contents/header.xml">'
         '<rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#HeaderFile"/></rdf:Description>')
    for i in range(num_sections):
        d += (f'<rdf:Description rdf:about=""><ns0:hasPart xmlns:ns0="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" '
              f'rdf:resource="Contents/section{i}.xml"/></rdf:Description>'
              f'<rdf:Description rdf:about="Contents/section{i}.xml">'
              f'<rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#SectionFile"/></rdf:Description>')
    d += ('<rdf:Description rdf:about="">'
          '<rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#Document"/></rdf:Description>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
            f'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">{d}</rdf:RDF>')


# ============================================================================
# Header.xml Style Trimming (post-processing)
# ============================================================================

def trim_unused_styles(contents_dir):
    """
    Post-process header.xml and section files to remove unused styles.

    Hancom Office removes unused charPr/paraPr entries from header.xml when
    saving, and renumbers all IDRef values. This function mimics that behavior
    to minimize diffs between skill-generated and Hancom-saved files.

    Steps:
    1. Scan all section XMLs to collect actually-used charPrIDRef, paraPrIDRef,
       and borderFillIDRef values
    2. Parse header.xml to find all defined style entries
    3. Remove unused entries (keeping ID 0 always)
    4. Build old→new ID mapping based on new sequential positions
    5. Apply remapping to header.xml and all section XMLs
    """
    header_path = contents_dir / "header.xml"
    if not header_path.exists():
        return

    # Collect section files
    section_files = sorted(contents_dir.glob("section*.xml"))
    if not section_files:
        return

    # Step 1: Scan all sections for used IDs
    used_char_ids = set()
    used_para_ids = set()
    used_bf_ids = set()

    for sf in section_files:
        content = sf.read_text(encoding="utf-8")
        used_char_ids.update(re.findall(r'charPrIDRef="(\d+)"', content))
        used_para_ids.update(re.findall(r'paraPrIDRef="(\d+)"', content))
        used_bf_ids.update(re.findall(r'borderFillIDRef="(\d+)"', content))

    # Also scan header.xml for IDs referenced by styles and other internal elements
    hdr_content = header_path.read_text(encoding="utf-8")
    # Styles reference charPr/paraPr IDs that must be kept even if not in sections
    style_char_refs = set(re.findall(r'<hh:style[^>]*charPrIDRef="(\d+)"', hdr_content))
    style_para_refs = set(re.findall(r'<hh:style[^>]*paraPrIDRef="(\d+)"', hdr_content))
    used_char_ids.update(style_char_refs)
    used_para_ids.update(style_para_refs)

    # Step 2: Parse header.xml to find defined IDs
    # charPr entries: <hh:charPr id="N" ...>
    char_pr_entries = list(re.finditer(r'<hh:charPr\s+id="(\d+)"', hdr_content))
    para_pr_entries = list(re.finditer(r'<hh:paraPr\s+id="(\d+)"', hdr_content))

    defined_char_ids = {m.group(1) for m in char_pr_entries}
    defined_para_ids = {m.group(1) for m in para_pr_entries}

    # Step 3: Determine which to keep (always keep id="0")
    keep_char_ids = (used_char_ids & defined_char_ids) | {"0"}
    keep_para_ids = (used_para_ids & defined_para_ids) | {"0"}

    # If nothing to remove, skip
    remove_char = defined_char_ids - keep_char_ids
    remove_para = defined_para_ids - keep_para_ids
    if not remove_char and not remove_para:
        return

    # Step 4: Remove unused entries from header.xml and build remapping
    # Process charPr entries - find full elements and remove unused ones
    # charPr elements are self-contained: <hh:charPr id="N" ...>...</hh:charPr>
    # or self-closing: <hh:charPr id="N" .../>

    def remove_and_remap_entries(content, tag, remove_ids):
        """Remove entries with given IDs and renumber remaining ones sequentially."""
        if not remove_ids:
            return content, {}

        # Find all entries of this tag
        # Must match EITHER:
        #   - Self-closing: <hh:tag id="N" ... /> (no nested children)
        #   - Paired: <hh:tag id="N" ...>...</hh:tag> (with nested children)
        # Use explicit closing tag match to avoid stopping at nested self-closing children
        pattern = re.compile(
            rf'(<hh:{tag}\s+id=")(\d+)("(?:[^<]*/>|.*?</hh:{tag}>))',
            re.DOTALL
        )

        # First pass: collect entries in order, mark for removal
        entries = []
        for m in pattern.finditer(content):
            old_id = m.group(2)
            entries.append((m.start(), m.end(), old_id, old_id in remove_ids))

        # Build old→new ID mapping (sequential, starting from 0)
        id_map = {}
        new_id = 0
        for _, _, old_id, should_remove in entries:
            if not should_remove:
                id_map[old_id] = str(new_id)
                new_id += 1

        # Second pass: rebuild content (process in reverse to preserve positions)
        for start, end, old_id, should_remove in reversed(entries):
            if should_remove:
                # Remove the entry (and any preceding whitespace/newline)
                rm_start = start
                while rm_start > 0 and content[rm_start - 1] in ' \t\n\r':
                    rm_start -= 1
                content = content[:rm_start] + content[end:]
            else:
                # Update the id attribute with new sequential value
                new_val = id_map[old_id]
                segment = content[start:end]
                segment = re.sub(rf'(id="){old_id}(")', rf'\g<1>{new_val}\2', segment, count=1)
                content = content[:start] + segment + content[end:]

        return content, id_map

    hdr_content, char_id_map = remove_and_remap_entries(hdr_content, "charPr", remove_char)
    hdr_content, para_id_map = remove_and_remap_entries(hdr_content, "paraPr", remove_para)

    # Update charPrCount and paraPrCount in header
    remaining_char = len(defined_char_ids) - len(remove_char)
    remaining_para = len(defined_para_ids) - len(remove_para)
    hdr_content = re.sub(r'(charPrCount=")(\d+)(")', rf'\g<1>{remaining_char}\3', hdr_content)
    hdr_content = re.sub(r'(paraPrCount=")(\d+)(")', rf'\g<1>{remaining_para}\3', hdr_content)

    # Step 5: Apply ID remapping everywhere (single-pass to avoid double-remap)
    def remap_attr(content, attr_name, id_map):
        """Single-pass regex replace to remap attribute values."""
        active_map = {k: v for k, v in id_map.items() if k != v}
        if not active_map:
            return content
        def replacer(m):
            old = m.group(1)
            return f'{attr_name}="{active_map.get(old, old)}"'
        return re.sub(rf'{attr_name}="(\d+)"', replacer, content)

    # Remap charPrIDRef and paraPrIDRef references WITHIN header.xml itself
    # (e.g., <hh:style> elements reference charPr/paraPr by IDRef)
    hdr_content = remap_attr(hdr_content, "charPrIDRef", char_id_map)
    hdr_content = remap_attr(hdr_content, "paraPrIDRef", para_id_map)

    # Write updated header
    header_path.write_text(hdr_content, encoding="utf-8")

    # Remap IDs in all section XMLs
    for sf in section_files:
        content = sf.read_text(encoding="utf-8")
        original = content
        content = remap_attr(content, "charPrIDRef", char_id_map)
        content = remap_attr(content, "paraPrIDRef", para_id_map)
        if content != original:
            sf.write_text(content, encoding="utf-8")


# ============================================================================
# Main HWPX Package Builder
# ============================================================================

def generate_hwpx(config, output_path, template_path=None):
    """Generate an HWPX file from a configuration dictionary."""
    if template_path is None:
        template_path = TEMPLATE_PATH

    template_path = Path(template_path)
    output_path = Path(output_path)

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        with zipfile.ZipFile(template_path, 'r') as zf:
            zf.extractall(tmpdir / "template")

        # Determine style map: hash-based cache with structural discovery
        template_hash = compute_template_hash(template_path)
        cache_path = SKILL_DIR / "assets" / "default_styles.json"
        sm = load_cached_style_map(cache_path, template_hash)
        if sm is None:
            sm = build_style_map_from_template(tmpdir / "template")
            if sm:
                save_style_map_cache(cache_path, template_hash, sm)
            else:
                sm = dict(DEFAULT_STYLE_MAP)

        # Prepare output structure
        out_dir = tmpdir / "output"
        out_dir.mkdir()

        shutil.copy2(tmpdir / "template" / "mimetype", out_dir / "mimetype")
        for f in ("version.xml", "settings.xml"):
            src = tmpdir / "template" / f
            if src.exists():
                shutil.copy2(src, out_dir / f)

        meta_dst = out_dir / "META-INF"
        meta_dst.mkdir(parents=True, exist_ok=True)
        meta_src = tmpdir / "template" / "META-INF"
        for f in ("container.xml", "manifest.xml"):
            src = meta_src / f
            if src.exists():
                shutil.copy2(src, meta_dst / f)

        if (tmpdir / "template" / "BinData").exists():
            shutil.copytree(tmpdir / "template" / "BinData", out_dir / "BinData")
        if (tmpdir / "template" / "Preview").exists():
            shutil.copytree(tmpdir / "template" / "Preview", out_dir / "Preview")

        contents_dir = out_dir / "Contents"
        contents_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmpdir / "template" / "Contents" / "header.xml", contents_dir / "header.xml")

        # Build sections
        include_cover = config.get("include_cover", True)
        user_sections = config.get("sections", [])
        section_files = []

        # Cover page
        if include_cover:
            cover_src = tmpdir / "template" / "Contents" / "section0.xml"
            if cover_src.exists():
                # Check if section0 is a cover-only section (no body headings)
                # Body sections have styleIDRef="15" (□ headings); cover sections don't.
                cover_check = cover_src.read_text(encoding="utf-8")
                heading_count = len(re.findall(r'styleIDRef="15"', cover_check))
                if heading_count == 0:
                    cover_xml = generate_cover_section_xml(cover_src, config, sm)
                    (contents_dir / "section0.xml").write_text(cover_xml, encoding="utf-8")
                else:
                    include_cover = False  # section0 is body, not cover
            else:
                include_cover = False

            if include_cover:
                section_files.append("section0.xml")

        # Content sections
        template_dir = tmpdir / "template"
        section_idx = 1 if include_cover else 0
        for sec_config in user_sections:
            sec_type = sec_config.get("type", "body")
            if sec_type == "body":
                sec_config.setdefault("date", config.get("date", ""))
                sec_config.setdefault("department", config.get("department", ""))
                xml_content = generate_body_section_xml(sec_config, sm, template_dir=template_dir)
            elif sec_type == "appendix":
                xml_content = generate_appendix_section_xml(sec_config, sm, template_dir=template_dir)
            else:
                xml_content = generate_body_section_xml(sec_config, sm, template_dir=template_dir)

            section_file = f"section{section_idx}.xml"
            (contents_dir / section_file).write_text(xml_content, encoding="utf-8")
            section_files.append(section_file)
            section_idx += 1

        if not section_files:
            xml_content = generate_body_section_xml({"title_bar": "보고서", "content": []}, sm, template_dir=template_dir)
            (contents_dir / "section0.xml").write_text(xml_content, encoding="utf-8")
            section_files.append("section0.xml")

        total_sections = len(section_files)
        bin_dir = out_dir / "BinData"
        has_images = bin_dir.exists()
        image_files = None
        if has_images:
            image_files = [f.name for f in sorted(bin_dir.iterdir()) if f.is_file()]

        # Generate metadata files
        title = config.get("title", "보고서")
        creator = config.get("creator", "이노베이션아카데미")
        (contents_dir / "content.hpf").write_text(
            generate_content_hpf(total_sections, has_images, image_files, title, creator), encoding="utf-8")
        (meta_dst / "container.rdf").write_text(
            generate_container_rdf(total_sections), encoding="utf-8")

        # Preview text
        preview_dir = out_dir / "Preview"
        preview_dir.mkdir(exist_ok=True)
        preview_text = title
        for sec in user_sections:
            preview_text += f"\n{sec.get('title_bar', '')}"
            for item in sec.get("content", []):
                if item.get("text"):
                    preview_text += f"\n{item['text']}"
        (preview_dir / "PrvText.txt").write_text(preview_text, encoding="utf-8")

        # Update header.xml secCnt
        header_path = contents_dir / "header.xml"
        hdr = header_path.read_text(encoding="utf-8")
        hdr = re.sub(r'secCnt="\d+"', f'secCnt="{total_sections}"', hdr)
        header_path.write_text(hdr, encoding="utf-8")

        # Trim unused styles from header.xml and remap IDs in sections
        trim_unused_styles(contents_dir)

        # Build HWPX ZIP
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, 'w') as zf:
            zf.write(out_dir / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
            for root, dirs, files in os.walk(out_dir):
                for file in sorted(files):
                    if file == "mimetype":
                        continue
                    fp = Path(root) / file
                    zf.write(fp, str(fp.relative_to(out_dir)), compress_type=zipfile.ZIP_DEFLATED)

    return output_path


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Generate HWPX documents (v3)")
    parser.add_argument("--output", "-o", required=True, help="Output .hwpx file path")
    parser.add_argument("--config", "-c", required=True, help="Config JSON file path")
    parser.add_argument("--template", "-t", help="Template .hwpx file (default: bundled)")
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = json.load(f)

    result = generate_hwpx(config, args.output, args.template)
    print(f"Generated: {result}")


if __name__ == "__main__":
    main()
