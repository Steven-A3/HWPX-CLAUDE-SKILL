#!/usr/bin/env python3
"""
HWPX Document Generator
Generates properly formatted HWPX (한글) documents based on the 이노베이션아카데미 standard report template.

Usage:
    python generate_hwpx.py --output output.hwpx --config config.json

Or import and call generate_hwpx() directly.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

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

# Page dimensions (A4 landscape-style, matching template)
PAGE_WIDTH = 59528
PAGE_HEIGHT = 84188
MARGIN_LEFT = 5669
MARGIN_RIGHT = 5669
MARGIN_TOP = 2834
MARGIN_BOTTOM = 4251
MARGIN_HEADER = 4251
MARGIN_FOOTER = 2834
CONTENT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT  # 48190

# ============================================================================
# XML Building Helpers
# ============================================================================

def sec_pr_xml(outline_ref="1"):
    """Generate the secPr (section properties) element for the first paragraph."""
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
                baseline=850, spacing=600, horzpos=0, horzsize=48188):
    """Generate linesegarray element."""
    return (f'<hp:linesegarray>'
            f'<hp:lineseg textpos="{textpos}" vertpos="{vertpos}" '
            f'vertsize="{vertsize}" textheight="{textheight}" '
            f'baseline="{baseline}" spacing="{spacing}" '
            f'horzpos="{horzpos}" horzsize="{horzsize}" flags="393216"/>'
            f'</hp:linesegarray>')


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
        # Empty run
        return f'<hp:run charPrIDRef="{char_pr_id}"/>'
    return f'<hp:run charPrIDRef="{char_pr_id}">{content}</hp:run>'


def table_cell_xml(col_addr, row_addr, width, height, border_fill_id,
                   para_pr_id, char_pr_id, text, vert_align="CENTER",
                   style_id="0"):
    """Generate a table cell element."""
    # Calculate inner horzsize (width minus margins)
    inner_hz = width - 1020  # 510*2 margins

    # Default lineseg sizes based on char height
    vs = 1200
    th = 1200
    bl = 1020
    sp = 360

    return (f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" '
            f'borderFillIDRef="{border_fill_id}">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" '
            f'vertAlign="{vert_align}" linkListIDRef="0" linkListNextIDRef="0" '
            f'textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f'<hp:p id="2147483648" paraPrIDRef="{para_pr_id}" styleIDRef="{style_id}" '
            f'pageBreak="0" columnBreak="0" merged="0">'
            f'{run_xml(char_pr_id, text)}'
            f'{lineseg_xml(vertsize=vs, textheight=th, baseline=bl, spacing=sp, horzsize=inner_hz)}'
            f'</hp:p></hp:subList>'
            f'<hp:cellAddr colAddr="{col_addr}" rowAddr="{row_addr}"/>'
            f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{width}" height="{height}"/>'
            f'<hp:cellMargin left="510" right="510" top="141" bottom="141"/>'
            f'</hp:tc>')


# ============================================================================
# Title Bar Generator (3-row gradient bar)
# ============================================================================

def title_bar_xml(title_text, table_id=1975012386):
    """Generate the 3-row title bar (gradient top, title, gradient bottom)."""
    bar_width = 48077

    # Row 1: gradient top bar (empty, small)
    row1 = (f'<hp:tr>'
            f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="14">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
            f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f'<hp:p id="2147483648" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="20"/>'
            f'{lineseg_xml(vertsize=100, textheight=100, baseline=85, spacing=60, horzsize=47796)}'
            f'</hp:p></hp:subList>'
            f'<hp:cellAddr colAddr="0" rowAddr="0"/>'
            f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{bar_width}" height="380"/>'
            f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/>'
            f'</hp:tc></hp:tr>')

    # Row 2: title (HY헤드라인M 20pt)
    row2 = (f'<hp:tr>'
            f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="9">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
            f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f'<hp:p id="2147483648" paraPrIDRef="15" styleIDRef="15" pageBreak="0" columnBreak="0" merged="0">'
            f'{run_xml("1", title_text)}'
            f'<hp:run charPrIDRef="0"/>'
            f'{lineseg_xml(vertsize=2000, textheight=2000, baseline=1700, spacing=1800, horzsize=47796)}'
            f'</hp:p></hp:subList>'
            f'<hp:cellAddr colAddr="0" rowAddr="1"/>'
            f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{bar_width}" height="2563"/>'
            f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/>'
            f'</hp:tc></hp:tr>')

    # Row 3: gradient bottom bar (empty, small)
    row3 = (f'<hp:tr>'
            f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="15">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
            f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f'<hp:p id="2147483648" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="22"/>'
            f'{lineseg_xml(vertsize=100, textheight=100, baseline=85, spacing=60, horzsize=47796)}'
            f'</hp:p></hp:subList>'
            f'<hp:cellAddr colAddr="0" rowAddr="2"/>'
            f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{bar_width}" height="380"/>'
            f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/>'
            f'</hp:tc></hp:tr>')

    return (f'<hp:tbl id="{table_id}" zOrder="2" numberingType="TABLE" '
            f'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" '
            f'pageBreak="NONE" repeatHeader="1" rowCnt="3" colCnt="1" cellSpacing="0" '
            f'borderFillIDRef="3" noAdjust="0">'
            f'<hp:sz width="{bar_width}" widthRelTo="ABSOLUTE" height="3323" heightRelTo="ABSOLUTE" protect="0"/>'
            f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
            f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" '
            f'vertOffset="0" horzOffset="0"/>'
            f'<hp:outMargin left="140" right="140" top="140" bottom="140"/>'
            f'<hp:inMargin left="140" right="140" top="140" bottom="140"/>'
            f'{row1}{row2}{row3}</hp:tbl>')


# ============================================================================
# Appendix Bar Generator (3-column bar: tab | separator | title)
# ============================================================================

def appendix_bar_xml(tab_label="참고1", title_text="부록 제목", table_id=1977606721):
    """Generate the appendix-style title bar (참고N | separator | title)."""
    total_width = 48159
    col1_w = 5968   # tab
    col2_w = 565    # separator
    col3_w = 41626  # title

    cells = (
        # Tab cell (dark background, white text)
        f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="17">'
        f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
        f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        f'<hp:p id="2147483648" paraPrIDRef="18" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'{run_xml("8", tab_label)}'
        f'{lineseg_xml(vertsize=1600, textheight=1600, baseline=1360, spacing=960, horzsize=5684)}'
        f'</hp:p></hp:subList>'
        f'<hp:cellAddr colAddr="0" rowAddr="0"/>'
        f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="{col1_w}" height="2831"/>'
        f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/>'
        f'</hp:tc>'
        # Separator cell
        f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="10">'
        f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
        f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        f'<hp:p id="2147483648" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="5"/>'
        f'{lineseg_xml(vertsize=1550, textheight=1550, baseline=1318, spacing=928, horzsize=1440)}'
        f'</hp:p></hp:subList>'
        f'<hp:cellAddr colAddr="1" rowAddr="0"/>'
        f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="{col2_w}" height="2831"/>'
        f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/>'
        f'</hp:tc>'
        # Title cell
        f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="11">'
        f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
        f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        f'<hp:p id="2147483648" paraPrIDRef="16" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'{run_xml("6", " ")}'
        f'{run_xml("3", title_text)}'
        f'{lineseg_xml(vertsize=1600, textheight=1600, baseline=1360, spacing=480, horzsize=41344)}'
        f'</hp:p></hp:subList>'
        f'<hp:cellAddr colAddr="2" rowAddr="0"/>'
        f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="{col3_w}" height="2831"/>'
        f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/>'
        f'</hp:tc>'
    )

    return (f'<hp:tbl id="{table_id}" zOrder="3" numberingType="TABLE" '
            f'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" '
            f'pageBreak="CELL" repeatHeader="1" rowCnt="1" colCnt="3" cellSpacing="0" '
            f'borderFillIDRef="3" noAdjust="0">'
            f'<hp:sz width="{total_width}" widthRelTo="ABSOLUTE" height="2831" heightRelTo="ABSOLUTE" protect="0"/>'
            f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
            f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" '
            f'vertOffset="0" horzOffset="0"/>'
            f'<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
            f'<hp:inMargin left="141" right="141" top="141" bottom="141"/>'
            f'<hp:tr>{cells}</hp:tr></hp:tbl>')


# ============================================================================
# Data Table Generator
# ============================================================================

def data_table_xml(headers, rows, caption="", table_id=1974981391):
    """Generate a data table with header row and body rows."""
    num_cols = len(headers)
    num_rows = len(rows) + 1  # +1 for header
    total_width = 47622

    # Distribute column widths evenly
    col_width = total_width // num_cols
    remainder = total_width - (col_width * num_cols)
    col_widths = [col_width] * num_cols
    col_widths[-1] += remainder  # give remainder to last column

    row_height = 2048
    total_height = row_height * num_rows

    # Header row
    header_cells = ""
    for i, (hdr, w) in enumerate(zip(headers, col_widths)):
        header_cells += table_cell_xml(
            col_addr=i, row_addr=0, width=w, height=row_height,
            border_fill_id="16", para_pr_id="25", char_pr_id="28",
            text=hdr
        )

    # Body rows
    body_rows = ""
    for r_idx, row in enumerate(rows):
        cells = ""
        for c_idx, (cell_text, w) in enumerate(zip(row, col_widths)):
            cells += table_cell_xml(
                col_addr=c_idx, row_addr=r_idx + 1, width=w, height=row_height,
                border_fill_id="3", para_pr_id="25", char_pr_id="33",
                text=str(cell_text)
            )
        body_rows += f'<hp:tr>{cells}</hp:tr>'

    paragraphs = ""
    # Add caption paragraph if provided
    if caption:
        paragraphs += paragraph_xml(
            "22", "0",
            run_xml("17", f"&lt; {caption} &gt;"),
            lineseg_xml(vertsize=1300, textheight=1300, baseline=1105, spacing=780)
        )

    # Table paragraph
    table_xml = (
        f'<hp:tbl id="{table_id}" zOrder="0" numberingType="TABLE" '
        f'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" '
        f'pageBreak="CELL" repeatHeader="1" rowCnt="{num_rows}" colCnt="{num_cols}" '
        f'cellSpacing="0" borderFillIDRef="3" noAdjust="0">'
        f'<hp:sz width="{total_width}" widthRelTo="ABSOLUTE" height="{total_height}" '
        f'heightRelTo="ABSOLUTE" protect="0"/>'
        f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
        f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" '
        f'vertOffset="0" horzOffset="0"/>'
        f'<hp:outMargin left="283" right="283" top="283" bottom="283"/>'
        f'<hp:inMargin left="510" right="510" top="141" bottom="141"/>'
        f'<hp:tr>{header_cells}</hp:tr>'
        f'{body_rows}</hp:tbl>'
    )

    paragraphs += paragraph_xml(
        "22", "0",
        f'<hp:run charPrIDRef="9">{table_xml}<hp:t/></hp:run>',
        lineseg_xml(vertsize=6710, textheight=6710, baseline=5704, spacing=600)
    )

    return paragraphs


# ============================================================================
# Content Item Generators
# ============================================================================

def generate_content_item(item):
    """Generate XML for a single content item."""
    item_type = item.get("type", "paragraph")
    text = item.get("text", "")

    if item_type == "heading":
        # □ heading (HY헤드라인M 15pt Bold)
        runs = (run_xml("27", "□") +
                run_xml("2", f" {text}") +
                run_xml("0", " ") +
                run_xml("29"))
        return paragraph_xml("28", "15", runs,
                           lineseg_xml(vertsize=1500, textheight=1500, baseline=1275, spacing=900))

    elif item_type == "paragraph":
        # Plain paragraph (휴먼명조 15pt)
        runs = run_xml("36", f" {text}") + run_xml("38")
        return paragraph_xml("19", "0", runs,
                           lineseg_xml(vertsize=1500, textheight=1500, baseline=1275, spacing=900))

    elif item_type == "bullet":
        # ㅇ bullet (휴먼명조 15pt)
        runs = run_xml("36", f" ㅇ {text}") + run_xml("38")
        return paragraph_xml("19", "0", runs,
                           lineseg_xml(vertsize=1500, textheight=1500, baseline=1275, spacing=900))

    elif item_type == "dash":
        # - dash item (휴먼명조 15pt, indented)
        runs = run_xml("36", f"   - {text}") + run_xml("43")
        return paragraph_xml("20", "0", runs,
                           lineseg_xml(vertsize=1500, textheight=1500, baseline=1275, spacing=900))

    elif item_type == "star":
        # * star item (맑은고딕 13pt, further indented)
        runs = run_xml("57", f"     * {text}") + run_xml("48")
        return paragraph_xml("21", "0", runs,
                           lineseg_xml(vertsize=1300, textheight=1300, baseline=1105, spacing=780))

    elif item_type == "table":
        headers = item.get("headers", [])
        rows = item.get("rows", [])
        caption = item.get("caption", "")
        table_id = item.get("table_id", 1974981391)
        return data_table_xml(headers, rows, caption, table_id)

    elif item_type == "note":
        # Note/reference text
        runs = run_xml("47", f"▷ {text}")
        return paragraph_xml("24", "0", runs,
                           lineseg_xml(vertsize=1400, textheight=1400, baseline=1190, spacing=840))

    elif item_type == "empty":
        # Empty line
        runs = run_xml("41")
        return paragraph_xml("19", "0", runs,
                           lineseg_xml(vertsize=600, textheight=600, baseline=510, spacing=360))

    else:
        # Default: plain text
        runs = run_xml("36", text) + run_xml("38")
        return paragraph_xml("19", "0", runs,
                           lineseg_xml(vertsize=1500, textheight=1500, baseline=1275, spacing=900))


# ============================================================================
# Section Generators
# ============================================================================

def generate_body_section_xml(section_config, outline_ref="3"):
    """Generate a body section with title bar and content."""
    title = section_config.get("title_bar", "보고서 제목")
    content_items = section_config.get("content", [])
    date_text = section_config.get("date", "")
    department = section_config.get("department", "")

    paragraphs = ""

    # First paragraph: secPr + title bar
    title_bar = title_bar_xml(title)
    first_para = (
        f'<hp:p id="0" paraPrIDRef="17" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="0">'
        f'<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
        f'{sec_pr_xml(outline_ref)}'
        f'</hp:run>'
        f'<hp:run charPrIDRef="0">{title_bar}</hp:run>'
        f'<hp:run charPrIDRef="10"><hp:t/></hp:run>'
        f'{lineseg_xml(vertsize=3603, textheight=3603, baseline=3063, spacing=900)}'
        f'</hp:p>'
    )
    paragraphs += first_para

    # Date/department line (if provided)
    if date_text or department:
        date_str = date_text or ""
        dept_str = department or ""
        date_line = f"('{date_str}, {dept_str})" if date_str and dept_str else ""
        if date_line:
            runs = (run_xml("50", f"('{date_str}, ") +
                    run_xml("58", dept_str) +
                    run_xml("50", ")"))
            paragraphs += paragraph_xml("17", "0", runs,
                                       lineseg_xml(vertsize=1200, textheight=1200, baseline=1020, spacing=720))

    # Empty spacer
    paragraphs += paragraph_xml("3", "0", run_xml("39"),
                               lineseg_xml(vertsize=800, textheight=800, baseline=680, spacing=480))

    # Content items
    for item in content_items:
        # Add spacing before headings (except the first one)
        if item.get("type") == "heading":
            paragraphs += paragraph_xml("19", "0", run_xml("41"),
                                       lineseg_xml(vertsize=600, textheight=600, baseline=510, spacing=360))
        paragraphs += generate_content_item(item)

    return (f'<?xml version="1.0" ?>'
            f'<hs:sec {NS_DECL}>{paragraphs}</hs:sec>')


def generate_appendix_section_xml(section_config, outline_ref="2"):
    """Generate an appendix section with tab-style title bar."""
    tab_label = section_config.get("title_bar", "참고1")
    appendix_title = section_config.get("appendix_title", "")
    content_items = section_config.get("content", [])

    paragraphs = ""

    # First paragraph: secPr + appendix bar
    app_bar = appendix_bar_xml(tab_label, appendix_title)
    first_para = (
        f'<hp:p id="2147483648" paraPrIDRef="17" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="10">'
        f'<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
        f'{sec_pr_xml(outline_ref)}'
        f'</hp:run>'
        f'<hp:run charPrIDRef="10">{app_bar}<hp:t/></hp:run>'
        f'{lineseg_xml(vertsize=2831, textheight=2831, baseline=2406, spacing=300)}'
        f'</hp:p>'
    )
    paragraphs += first_para

    # Empty spacer
    paragraphs += paragraph_xml("28", "15", run_xml("40"),
                               lineseg_xml(vertsize=1500, textheight=1500, baseline=1275, spacing=900))

    # Content items
    for item in content_items:
        if item.get("type") == "heading":
            paragraphs += paragraph_xml("19", "0", run_xml("41"),
                                       lineseg_xml(vertsize=600, textheight=600, baseline=510, spacing=360))
        paragraphs += generate_content_item(item)

    return (f'<?xml version="1.0" ?>'
            f'<hs:sec {NS_DECL}>{paragraphs}</hs:sec>')


# ============================================================================
# content.hpf Generator
# ============================================================================

def generate_content_hpf(num_sections, has_images=True, title="보고서", creator="이노베이션아카데미"):
    """Generate the content.hpf (OPF package manifest)."""
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest_items = '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
    if has_images:
        manifest_items += '<opf:item id="image1" href="BinData/image1.png" media-type="image/png" isEmbeded="1"/>'
        manifest_items += '<opf:item id="image2" href="BinData/image2.jpg" media-type="image/jpg" isEmbeded="1"/>'

    for i in range(num_sections):
        manifest_items += f'<opf:item id="section{i}" href="Contents/section{i}.xml" media-type="application/xml"/>'
    manifest_items += '<opf:item id="settings" href="settings.xml" media-type="application/xml"/>'

    spine_items = '<opf:itemref idref="header" linear="yes"/>'
    for i in range(num_sections):
        spine_items += f'<opf:itemref idref="section{i}" linear="yes"/>'

    return (f'<?xml version="1.0" ?>'
            f'<opf:package xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
            f'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
            f'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
            f'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
            f'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
            f'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
            f'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
            f'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
            f'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" '
            f'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            f'xmlns:opf="http://www.idpf.org/2007/opf/" '
            f'xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
            f'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" '
            f'xmlns:epub="http://www.idpf.org/2007/ops" '
            f'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0" '
            f'version="" unique-identifier="" id="">'
            f'<opf:metadata>'
            f'<opf:title>{xml_escape(title)}</opf:title>'
            f'<opf:language>ko</opf:language>'
            f'<opf:meta name="creator" content="text">{xml_escape(creator)}</opf:meta>'
            f'<opf:meta name="subject" content="text"/>'
            f'<opf:meta name="description" content="text"/>'
            f'<opf:meta name="lastsaveby" content="text">Claude</opf:meta>'
            f'<opf:meta name="CreatedDate" content="text">{now}</opf:meta>'
            f'<opf:meta name="ModifiedDate" content="text">{now}</opf:meta>'
            f'<opf:meta name="keyword" content="text"/>'
            f'</opf:metadata>'
            f'<opf:manifest>{manifest_items}</opf:manifest>'
            f'<opf:spine>{spine_items}</opf:spine>'
            f'</opf:package>')


def generate_container_rdf(num_sections):
    """Generate container.rdf with proper RDF relationships."""
    descriptions = (
        '<rdf:Description rdf:about="">'
        '<ns0:hasPart xmlns:ns0="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" '
        'rdf:resource="Contents/header.xml"/></rdf:Description>'
        '<rdf:Description rdf:about="Contents/header.xml">'
        '<rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#HeaderFile"/>'
        '</rdf:Description>'
    )

    for i in range(num_sections):
        descriptions += (
            f'<rdf:Description rdf:about="">'
            f'<ns0:hasPart xmlns:ns0="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" '
            f'rdf:resource="Contents/section{i}.xml"/></rdf:Description>'
            f'<rdf:Description rdf:about="Contents/section{i}.xml">'
            f'<rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#SectionFile"/>'
            f'</rdf:Description>'
        )

    descriptions += (
        '<rdf:Description rdf:about="">'
        '<rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#Document"/>'
        '</rdf:Description>'
    )

    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
            f'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            f'{descriptions}</rdf:RDF>')


# ============================================================================
# Main HWPX Package Builder
# ============================================================================

def generate_hwpx(config, output_path, template_path=None):
    """
    Generate an HWPX file from a configuration dictionary.

    Args:
        config: Dictionary with document configuration
        output_path: Path for the output .hwpx file
        template_path: Path to template .hwpx (defaults to bundled template)
    """
    if template_path is None:
        template_path = TEMPLATE_PATH

    template_path = Path(template_path)
    output_path = Path(output_path)

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    # Extract template to temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Extract template
        with zipfile.ZipFile(template_path, 'r') as zf:
            zf.extractall(tmpdir / "template")

        # Prepare output structure
        out_dir = tmpdir / "output"
        out_dir.mkdir()

        # Copy static files from template
        # mimetype
        shutil.copy2(tmpdir / "template" / "mimetype", out_dir / "mimetype")

        # version.xml
        if (tmpdir / "template" / "version.xml").exists():
            shutil.copy2(tmpdir / "template" / "version.xml", out_dir / "version.xml")

        # settings.xml
        if (tmpdir / "template" / "settings.xml").exists():
            shutil.copy2(tmpdir / "template" / "settings.xml", out_dir / "settings.xml")

        # META-INF
        meta_src = tmpdir / "template" / "META-INF"
        meta_dst = out_dir / "META-INF"
        meta_dst.mkdir(parents=True, exist_ok=True)
        if (meta_src / "container.xml").exists():
            shutil.copy2(meta_src / "container.xml", meta_dst / "container.xml")
        if (meta_src / "manifest.xml").exists():
            shutil.copy2(meta_src / "manifest.xml", meta_dst / "manifest.xml")

        # BinData (images)
        bin_src = tmpdir / "template" / "BinData"
        if bin_src.exists():
            shutil.copytree(bin_src, out_dir / "BinData")

        # Preview
        preview_src = tmpdir / "template" / "Preview"
        if preview_src.exists():
            shutil.copytree(preview_src, out_dir / "Preview")

        # Contents directory
        contents_dir = out_dir / "Contents"
        contents_dir.mkdir(parents=True, exist_ok=True)

        # Copy header.xml from template (critical!)
        shutil.copy2(tmpdir / "template" / "Contents" / "header.xml",
                     contents_dir / "header.xml")

        # Determine sections to generate
        include_cover = config.get("include_cover", True)
        user_sections = config.get("sections", [])

        section_files = []

        if include_cover:
            # Copy cover page (section0.xml) from template
            cover_src = tmpdir / "template" / "Contents" / "section0.xml"
            if cover_src.exists():
                shutil.copy2(cover_src, contents_dir / "section0.xml")
                section_files.append("section0.xml")

        # Generate content sections
        section_idx = 1 if include_cover else 0
        for sec_config in user_sections:
            sec_type = sec_config.get("type", "body")

            # Pass date/department to body sections
            if sec_type == "body":
                sec_config.setdefault("date", config.get("date", ""))
                sec_config.setdefault("department", config.get("department", ""))
                xml_content = generate_body_section_xml(sec_config)
            elif sec_type == "appendix":
                xml_content = generate_appendix_section_xml(sec_config)
            else:
                xml_content = generate_body_section_xml(sec_config)

            section_file = f"section{section_idx}.xml"
            (contents_dir / section_file).write_text(xml_content, encoding="utf-8")
            section_files.append(section_file)
            section_idx += 1

        # If no sections were generated, create a minimal body
        if not section_files:
            xml_content = generate_body_section_xml({"title_bar": "보고서", "content": []})
            (contents_dir / "section0.xml").write_text(xml_content, encoding="utf-8")
            section_files.append("section0.xml")

        total_sections = len(section_files)
        has_images = (out_dir / "BinData").exists()

        # Generate content.hpf
        title = config.get("title", "보고서")
        creator = config.get("creator", "이노베이션아카데미")
        content_hpf = generate_content_hpf(total_sections, has_images, title, creator)
        (contents_dir / "content.hpf").write_text(content_hpf, encoding="utf-8")

        # Generate container.rdf
        container_rdf = generate_container_rdf(total_sections)
        (meta_dst / "container.rdf").write_text(container_rdf, encoding="utf-8")

        # Update preview text
        preview_dir = out_dir / "Preview"
        preview_dir.mkdir(exist_ok=True)
        preview_text = title
        for sec in user_sections:
            preview_text += f"\n{sec.get('title_bar', '')}"
            for item in sec.get("content", []):
                if item.get("text"):
                    preview_text += f"\n{item['text']}"
        (preview_dir / "PrvText.txt").write_text(preview_text, encoding="utf-8")

        # Update header.xml secCnt if needed
        header_path = contents_dir / "header.xml"
        header_content = header_path.read_text(encoding="utf-8")
        # Update secCnt attribute
        import re
        header_content = re.sub(
            r'secCnt="\d+"',
            f'secCnt="{total_sections}"',
            header_content
        )
        header_path.write_text(header_content, encoding="utf-8")

        # Build HWPX (ZIP) file
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(output_path, 'w') as zf:
            # mimetype MUST be first, STORED (no compression)
            zf.write(out_dir / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)

            # Add all other files with DEFLATED compression
            for root, dirs, files in os.walk(out_dir):
                for file in sorted(files):
                    if file == "mimetype":
                        continue
                    file_path = Path(root) / file
                    arcname = str(file_path.relative_to(out_dir))
                    zf.write(file_path, arcname, compress_type=zipfile.ZIP_DEFLATED)

    return output_path


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Generate HWPX documents")
    parser.add_argument("--output", "-o", required=True, help="Output .hwpx file path")
    parser.add_argument("--config", "-c", required=True, help="Config JSON file path")
    parser.add_argument("--template", "-t", help="Template .hwpx file (default: bundled)")

    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        config = json.load(f)

    template = args.template if args.template else None
    result = generate_hwpx(config, args.output, template)
    print(f"Generated: {result}")


if __name__ == "__main__":
    main()
