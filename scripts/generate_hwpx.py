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

# Hardcoded IDs for the bundled 이노베이션아카데미 template
DEFAULT_STYLE_MAP = {
    # (charPrIDRef, paraPrIDRef, vertsize, textheight, baseline, spacing)
    "heading_marker":   ("27", "28", 1500, 1500, 1275, 900),   # □ marker
    "heading_text":     ("2",  "28", 1500, 1500, 1275, 900),   # HY헤드라인M 15pt
    "heading_tail":     ("0",  "28", 1500, 1500, 1275, 900),   # trailing space
    "heading_end":      ("29", "28", 1500, 1500, 1275, 900),   # closing run
    "paragraph":        ("36", "19", 1500, 1500, 1275, 900),   # 휴먼명조 15pt
    "paragraph_end":    ("38", "19", 1500, 1500, 1275, 900),
    "bullet":           ("36", "19", 1500, 1500, 1275, 900),   # ㅇ bullet
    "bullet_end":       ("38", "19", 1500, 1500, 1275, 900),
    "dash":             ("36", "20", 1500, 1500, 1275, 900),   # - dash
    "dash_end":         ("43", "20", 1500, 1500, 1275, 900),
    "star":             ("57", "21", 1300, 1300, 1105, 780),   # * detail
    "star_end":         ("48", "21", 1300, 1300, 1105, 780),
    "note":             ("47", "24", 1400, 1400, 1190, 840),   # ▷ note
    "table_caption":    ("17", "22", 1300, 1300, 1105, 780),   # < caption >
    "table_wrapper":    ("9",  "22", 6710, 6710, 5704, 600),   # table container (base; overridden dynamically)
    "table_header":     ("28", "25", 1200, 1200, 1020, 360),   # header cell
    "table_body":       ("33", "25", 1200, 1200, 1020, 360),   # body cell
    "title_bar_title":  ("1",  "15", 2000, 2000, 1700, 1800),  # title 20pt
    "title_bar_top":    ("20", "3",  100,  100,  85,   60),    # gradient top
    "title_bar_bottom": ("22", "3",  100,  100,  85,   60),    # gradient bottom
    "date_line":        ("50", "17", 1200, 1200, 1020, 720),   # date
    "date_emphasis":    ("58", "17", 1200, 1200, 1020, 720),   # department
    "spacer_small":     ("41", "19", 600,  600,  510,  360),   # small spacer
    "spacer_medium":    ("39", "3",  800,  800,  680,  480),   # medium spacer
    "first_para":       ("10", "17", 3603, 3603, 3063, 900),   # first para with bar
    "appendix_tab":     ("8",  "18", 1600, 1600, 1360, 960),   # 참고N tab
    "appendix_title":   ("3",  "16", 1600, 1600, 1360, 480),   # appendix title
    "appendix_sep_char": ("6", "16", 1600, 1600, 1360, 480),   # separator space
    "appendix_sep_cell": ("5", "3",  1550, 1550, 1318, 928),   # separator cell
    "appendix_first":   ("10", "17", 2831, 2831, 2406, 300),   # appendix first para
    "appendix_spacer":  ("40", "28", 1500, 1500, 1275, 900),
    # Cover page title area
    "cover_title":      ("25", "26", 2500, 2500, 2125, 1252),
    # Cover page date
    "cover_date":       ("37", "27", 2400, 2400, 2040, 1680),
    # Border fill IDs
    "bf_none":          "1",
    "bf_table":         "3",
    "bf_gradient_top":  "14",
    "bf_title_bg":      "9",
    "bf_gradient_bot":  "15",
    "bf_table_header":  "16",
    "bf_appendix_tab":  "17",
    "bf_appendix_sep":  "10",
    "bf_appendix_title": "11",
    "bf_cover_grad_top": "12",
    "bf_cover_title_bg": "8",
    "bf_cover_grad_bot": "13",
    "bf_cover_border":  "7",
}


def discover_styles_from_header(header_xml_path):
    """
    Parse header.xml to discover available style IDs.
    Returns a style map compatible with DEFAULT_STYLE_MAP, or None on failure.
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
                'hangul_font': hangul_ref,
                'hangul_face': hangul_face,
                'bold': has_bold,
            }

        def find_char_pr(face_substr, height, bold=None):
            candidates = []
            for cpid, info in char_catalog.items():
                if face_substr and face_substr not in info['hangul_face']:
                    continue
                if bold is not None and info['bold'] != bold:
                    continue
                dist = abs(info['height'] - height)
                candidates.append((dist, cpid, info['height']))
            if not candidates:
                return None
            candidates.sort()
            return (candidates[0][1], candidates[0][2])

        style_map = dict(DEFAULT_STYLE_MAP)

        hy_15 = find_char_pr('HY헤드라인', 1500)
        hy_20 = find_char_pr('HY헤드라인', 2000)
        hm_15 = find_char_pr('휴먼명조', 1500)
        mg_13 = find_char_pr('맑은', 1300)
        mg_12 = find_char_pr('맑은', 1200)

        if hy_15:
            style_map["heading_text"] = (hy_15[0], style_map["heading_text"][1],
                                          hy_15[1], hy_15[1], int(hy_15[1]*0.85), int(hy_15[1]*0.6))
        if hy_20:
            style_map["title_bar_title"] = (hy_20[0], style_map["title_bar_title"][1],
                                             hy_20[1], hy_20[1], int(hy_20[1]*0.85), int(hy_20[1]*0.9))
        if hm_15:
            for role in ("paragraph", "bullet", "dash"):
                style_map[role] = (hm_15[0], style_map[role][1],
                                    hm_15[1], hm_15[1], int(hm_15[1]*0.85), int(hm_15[1]*0.6))
        if mg_13:
            style_map["star"] = (mg_13[0], style_map["star"][1],
                                  mg_13[1], mg_13[1], int(mg_13[1]*0.85), int(mg_13[1]*0.6))
        if mg_12:
            for role in ("table_header", "table_body"):
                style_map[role] = (mg_12[0], style_map[role][1],
                                    mg_12[1], mg_12[1], int(mg_12[1]*0.85), int(mg_12[1]*0.3))
        return style_map

    except Exception as e:
        print(f"Warning: Could not auto-discover styles: {e}")
        return None


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
    inner_hz = width - 1020  # 510*2 margins
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
    hz = bar_width - 282

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

def generate_body_section_xml(section_config, sm, outline_ref="3"):
    """Generate a body section with title bar and content."""
    title = section_config.get("title_bar", "보고서 제목")
    content_items = section_config.get("content", [])
    date_text = section_config.get("date", "")
    department = section_config.get("department", "")

    vpt = VertPosTracker()
    paragraphs = ""

    # First paragraph: secPr + colPr + title bar
    fp = sm["first_para"]
    vpt.next(fp[2], fp[5])

    title_bar = title_bar_xml(title, sm)
    first_para = (
        f'<hp:p id="0" paraPrIDRef="{fp[1]}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{sm["heading_tail"][0]}">'
        f'<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
        f'{sec_pr_xml(outline_ref)}'
        f'</hp:run>'
        f'<hp:run charPrIDRef="{sm["heading_tail"][0]}">{title_bar}</hp:run>'
        f'<hp:run charPrIDRef="{fp[0]}"><hp:t/></hp:run>'
        f'{lineseg_xml(vertpos=0, vertsize=fp[2], textheight=fp[3], baseline=fp[4], spacing=fp[5])}'
        f'</hp:p>')
    paragraphs += first_para

    # Date/department line
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

    # Empty spacer
    sp = sm["spacer_medium"]
    vp = vpt.next(sp[2], sp[5])
    paragraphs += paragraph_xml(sp[1], "0", run_xml(sp[0]),
                                 lineseg_xml(vertpos=vp, vertsize=sp[2], textheight=sp[3],
                                             baseline=sp[4], spacing=sp[5]))

    # Content items
    for item in content_items:
        if item.get("type") == "heading":
            ss = sm["spacer_small"]
            vp = vpt.next(ss[2], ss[5])
            paragraphs += paragraph_xml(ss[1], "0", run_xml(ss[0]),
                                         lineseg_xml(vertpos=vp, vertsize=ss[2], textheight=ss[3],
                                                     baseline=ss[4], spacing=ss[5]))
        paragraphs += generate_content_item(item, sm, vpt)

    return f'<?xml version="1.0" ?><hs:sec {NS_DECL}>{paragraphs}</hs:sec>'


def generate_appendix_section_xml(section_config, sm, outline_ref="2"):
    """Generate an appendix section with tab-style title bar."""
    tab_label = section_config.get("title_bar", "참고1")
    appendix_title = section_config.get("appendix_title", "")
    content_items = section_config.get("content", [])

    vpt = VertPosTracker()
    paragraphs = ""

    # First paragraph: secPr + appendix bar
    af = sm["appendix_first"]
    vpt.next(af[2], af[5])

    app_bar = appendix_bar_xml(tab_label, appendix_title, sm)
    first_para = (
        f'<hp:p id="2147483648" paraPrIDRef="{af[1]}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{af[0]}">'
        f'<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
        f'{sec_pr_xml(outline_ref)}'
        f'</hp:run>'
        f'<hp:run charPrIDRef="{af[0]}">{app_bar}<hp:t/></hp:run>'
        f'{lineseg_xml(vertpos=0, vertsize=af[2], textheight=af[3], baseline=af[4], spacing=af[5])}'
        f'</hp:p>')
    paragraphs += first_para

    # Empty spacer
    asp = sm["appendix_spacer"]
    vp = vpt.next(asp[2], asp[5])
    paragraphs += paragraph_xml(asp[1], "15", run_xml(asp[0]),
                                 lineseg_xml(vertpos=vp, vertsize=asp[2], textheight=asp[3],
                                             baseline=asp[4], spacing=asp[5]))

    # Content
    for item in content_items:
        if item.get("type") == "heading":
            ss = sm["spacer_small"]
            vp = vpt.next(ss[2], ss[5])
            paragraphs += paragraph_xml(ss[1], "0", run_xml(ss[0]),
                                         lineseg_xml(vertpos=vp, vertsize=ss[2], textheight=ss[3],
                                                     baseline=ss[4], spacing=ss[5]))
        paragraphs += generate_content_item(item, sm, vpt)

    return f'<?xml version="1.0" ?><hs:sec {NS_DECL}>{paragraphs}</hs:sec>'


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

def generate_content_hpf(num_sections, has_images=True, title="보고서", creator="이노베이션아카데미"):
    """Generate the content.hpf (OPF package manifest)."""
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
    if has_images:
        manifest += '<opf:item id="image1" href="BinData/image1.png" media-type="image/png" isEmbeded="1"/>'
        manifest += '<opf:item id="image2" href="BinData/image2.jpg" media-type="image/jpg" isEmbeded="1"/>'
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

    return (f'<?xml version="1.0" ?><opf:package {ns_block} version="" unique-identifier="" id="">'
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

    is_bundled_template = (template_path.resolve() == TEMPLATE_PATH.resolve())

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        with zipfile.ZipFile(template_path, 'r') as zf:
            zf.extractall(tmpdir / "template")

        # Determine style map
        if is_bundled_template:
            sm = DEFAULT_STYLE_MAP
        else:
            header_xml = tmpdir / "template" / "Contents" / "header.xml"
            discovered = discover_styles_from_header(header_xml) if header_xml.exists() else None
            sm = discovered if discovered else DEFAULT_STYLE_MAP

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
                cover_xml = generate_cover_section_xml(cover_src, config, sm)
                (contents_dir / "section0.xml").write_text(cover_xml, encoding="utf-8")
            else:
                include_cover = False

            if include_cover:
                section_files.append("section0.xml")

        # Content sections
        section_idx = 1 if include_cover else 0
        for sec_config in user_sections:
            sec_type = sec_config.get("type", "body")
            if sec_type == "body":
                sec_config.setdefault("date", config.get("date", ""))
                sec_config.setdefault("department", config.get("department", ""))
                xml_content = generate_body_section_xml(sec_config, sm)
            elif sec_type == "appendix":
                xml_content = generate_appendix_section_xml(sec_config, sm)
            else:
                xml_content = generate_body_section_xml(sec_config, sm)

            section_file = f"section{section_idx}.xml"
            (contents_dir / section_file).write_text(xml_content, encoding="utf-8")
            section_files.append(section_file)
            section_idx += 1

        if not section_files:
            xml_content = generate_body_section_xml({"title_bar": "보고서", "content": []}, sm)
            (contents_dir / "section0.xml").write_text(xml_content, encoding="utf-8")
            section_files.append("section0.xml")

        total_sections = len(section_files)
        has_images = (out_dir / "BinData").exists()

        # Generate metadata files
        title = config.get("title", "보고서")
        creator = config.get("creator", "이노베이션아카데미")
        (contents_dir / "content.hpf").write_text(
            generate_content_hpf(total_sections, has_images, title, creator), encoding="utf-8")
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
