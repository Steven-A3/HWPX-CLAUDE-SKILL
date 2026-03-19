#!/usr/bin/env python3
"""
HWPX Parser & Structure Analyzer.

Opens existing HWPX files and extracts structural information:
sections, tables, styles, images, and document metadata.

CONSTRAINT: etree.parse() is used for analysis ONLY.
etree.tostring() is NEVER called — all raw XML bytes are preserved
for downstream modification by modify_hwpx.py.
"""

import re
from pathlib import Path
from xml.etree import ElementTree as ET

from . import zip_handler
from . import _parser


# Namespaces used in HWPX
NS = {
    'ha': 'http://www.hancom.co.kr/hwpml/2011/app',
    'hp': 'http://www.hancom.co.kr/hwpml/2011/paragraph',
    'hp10': 'http://www.hancom.co.kr/hwpml/2016/paragraph',
    'hs': 'http://www.hancom.co.kr/hwpml/2011/section',
    'hc': 'http://www.hancom.co.kr/hwpml/2011/core',
    'hh': 'http://www.hancom.co.kr/hwpml/2011/head',
    'hhs': 'http://www.hancom.co.kr/hwpml/2011/history',
    'hm': 'http://www.hancom.co.kr/hwpml/2011/master-page',
    'hpf': 'http://www.hancom.co.kr/schema/2011/hpf',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'opf': 'http://www.idpf.org/2007/opf/',
}


class HwpxDocument:
    """Parsed HWPX document with structural analysis capabilities.

    Holds both raw bytes (for modification) and parsed trees (for analysis).
    """

    def __init__(self, hwpx_info):
        """Initialize from an HwpxZipInfo object.

        Args:
            hwpx_info: zip_handler.HwpxZipInfo containing all ZIP entries.
        """
        self._info = hwpx_info
        self._header_tree = None

    @property
    def zip_info(self):
        """Access the underlying HwpxZipInfo for raw byte operations."""
        return self._info

    # ================================================================
    # Entry Access
    # ================================================================

    def get_entry_bytes(self, name):
        """Get raw bytes for a ZIP entry."""
        return self._info.get(name)

    def get_entry_text(self, name, encoding='utf-8'):
        """Get text content of a ZIP entry."""
        return self._info.get_text(name, encoding)

    def list_entries(self):
        """List all ZIP entry names."""
        return self._info.list_entries()

    # ================================================================
    # Section Discovery
    # ================================================================

    def list_sections(self):
        """List section entry names in order.

        Returns:
            List of entry names like ['Contents/section0.xml', ...].
        """
        sections = []
        for name in self._info.list_entries():
            if re.match(r'Contents/section\d+\.xml$', name):
                sections.append(name)
        return sorted(sections, key=lambda n: int(re.search(r'(\d+)', n).group(1)))

    def get_section_text(self, section_name):
        """Get raw XML text for a section (for modification).

        Args:
            section_name: Entry name like 'Contents/section0.xml'.

        Returns:
            Raw XML string, or None if not found.
        """
        return self._info.get_text(section_name)

    def get_section_count(self):
        """Get number of sections."""
        return len(self.list_sections())

    # ================================================================
    # Header Analysis (etree parsing — analysis only)
    # ================================================================

    def _ensure_header_parsed(self):
        """Parse header.xml into an ET tree for analysis."""
        if self._header_tree is not None:
            return
        header_bytes = self._info.get('Contents/header.xml')
        if header_bytes is None:
            return
        self._header_tree = ET.fromstring(header_bytes)

    def get_styles(self):
        """Extract charPr, paraPr, and borderFill catalogs from header.xml.

        Returns:
            dict with:
              'charPr': {id: {'height': int, 'face': str, 'bold': bool}}
              'paraPr': {id: {'align': str, 'lineSpacingType': str, 'lineSpacingValue': str}}
              'borderFill': {id: {'type': str}}
              'fonts': {(lang, id): face_name}
            Returns None if header cannot be parsed.
        """
        self._ensure_header_parsed()
        if self._header_tree is None:
            return None

        root = self._header_tree

        # Font map
        font_map = {}
        for fontface in root.findall('.//hh:fontface', NS):
            lang = fontface.get('lang', '')
            for font in fontface.findall('hh:font', NS):
                fid = font.get('id', '')
                face = font.get('face', '')
                font_map[(lang, fid)] = face

        # charPr catalog
        char_catalog = {}
        for cp in root.findall('.//hh:charPr', NS):
            cpid = cp.get('id', '')
            height = int(cp.get('height', '0'))
            font_ref = cp.find('hh:fontRef', NS)
            hangul_ref = font_ref.get('hangul', '0') if font_ref is not None else '0'
            has_bold = cp.find('hh:bold', NS) is not None
            hangul_face = font_map.get(('HANGUL', hangul_ref), '')
            char_catalog[cpid] = {
                'height': height,
                'face': hangul_face,
                'bold': has_bold,
            }

        # paraPr catalog
        para_catalog = {}
        for pp in root.findall('.//hh:paraPr', NS):
            ppid = pp.get('id', '')
            align_el = pp.find('hh:align', NS)
            h_align = align_el.get('horizontal', 'JUSTIFY') if align_el is not None else 'JUSTIFY'
            ls_el = pp.find('hh:lineSpacing', NS)
            ls_type = ls_el.get('type', 'PERCENT') if ls_el is not None else 'PERCENT'
            ls_value = ls_el.get('value', '160') if ls_el is not None else '160'
            para_catalog[ppid] = {
                'align': h_align,
                'lineSpacingType': ls_type,
                'lineSpacingValue': ls_value,
            }

        # borderFill catalog
        bf_catalog = {}
        for bf in root.findall('.//hh:borderFill', NS):
            bfid = bf.get('id', '')
            bf_type = bf.get('type', '')
            bf_catalog[bfid] = {'type': bf_type}

        return {
            'charPr': char_catalog,
            'paraPr': para_catalog,
            'borderFill': bf_catalog,
            'fonts': font_map,
        }

    # ================================================================
    # Table Discovery (regex-based — no etree.tostring())
    # ================================================================

    def list_tables(self, section_name=None):
        """List all tables across sections (or in a specific section).

        Args:
            section_name: Optional entry name to restrict search.

        Returns:
            List of dicts with:
              'section': section entry name
              'index': table index within section
              'rowCnt': declared row count
              'colCnt': declared column count
              'headers': list of header cell text values
              'position': (start, end) byte offsets in section XML
        """
        sections = [section_name] if section_name else self.list_sections()
        tables = []

        for sec_name in sections:
            sec_xml = self.get_section_text(sec_name)
            if not sec_xml:
                continue

            for idx, (start, end, tbl_xml) in enumerate(_parser.find_tables(sec_xml)):
                row_m = re.search(r'rowCnt="(\d+)"', tbl_xml)
                col_m = re.search(r'colCnt="(\d+)"', tbl_xml)
                row_cnt = int(row_m.group(1)) if row_m else 0
                col_cnt = int(col_m.group(1)) if col_m else 0

                # Extract header row text using depth-tracked row finder
                headers = []
                first_row = _parser.find_first_row(tbl_xml)
                if first_row:
                    headers = re.findall(r'<hp:t>([^<]*)</hp:t>', first_row)

                tables.append({
                    'section': sec_name,
                    'index': idx,
                    'rowCnt': row_cnt,
                    'colCnt': col_cnt,
                    'headers': headers,
                    'position': (start, end),
                })

        return tables

    # ================================================================
    # Paragraph Discovery
    # ================================================================

    def list_paragraphs(self, section_name):
        """List top-level paragraphs in a section.

        Args:
            section_name: Section entry name.

        Returns:
            List of dicts with:
              'index': paragraph index
              'paraPrIDRef': paragraph style ID
              'styleIDRef': style reference
              'has_table': whether paragraph contains a table
              'has_colpr': whether paragraph has column properties
              'text': concatenated text content
              'position': (start, end) byte offsets
        """
        sec_xml = self.get_section_text(section_name)
        if not sec_xml:
            return []

        paragraphs = _parser.find_top_level_paragraphs(sec_xml)
        results = []

        for idx, (start, end) in enumerate(paragraphs):
            para_xml = sec_xml[start:end]
            pp_m = re.search(r'paraPrIDRef="(\d+)"', para_xml)
            st_m = re.search(r'styleIDRef="(\d+)"', para_xml)
            texts = re.findall(r'<hp:t>([^<]*)</hp:t>', para_xml)

            results.append({
                'index': idx,
                'paraPrIDRef': pp_m.group(1) if pp_m else '0',
                'styleIDRef': st_m.group(1) if st_m else '0',
                'has_table': '<hp:tbl' in para_xml,
                'has_colpr': '<hp:colPr' in para_xml,
                'text': ' '.join(t for t in texts if t.strip()),
                'position': (start, end),
            })

        return results

    # ================================================================
    # Image/Binary Discovery
    # ================================================================

    def list_images(self):
        """List binary data entries (images).

        Returns:
            List of entry names in BinData/ directory.
        """
        return [n for n in self._info.list_entries() if n.startswith('BinData/')]

    # ================================================================
    # Structure Summary
    # ================================================================

    def get_structure_summary(self):
        """Get a high-level summary of the document structure.

        Returns:
            dict with:
              'section_count': number of sections
              'sections': list of section summaries
              'table_count': total tables
              'image_count': number of images
              'styles': charPr/paraPr/borderFill counts
        """
        sections = self.list_sections()
        all_tables = self.list_tables()
        images = self.list_images()

        section_summaries = []
        for sec_name in sections:
            paras = self.list_paragraphs(sec_name)
            sec_tables = [t for t in all_tables if t['section'] == sec_name]
            has_cover = any(p.get('has_colpr') for p in paras)

            section_summaries.append({
                'name': sec_name,
                'paragraph_count': len(paras),
                'table_count': len(sec_tables),
                'has_page_layout': has_cover,
                'text_preview': _get_text_preview(paras),
            })

        styles = self.get_styles()
        style_counts = {}
        if styles:
            style_counts = {
                'charPr_count': len(styles.get('charPr', {})),
                'paraPr_count': len(styles.get('paraPr', {})),
                'borderFill_count': len(styles.get('borderFill', {})),
                'font_count': len(styles.get('fonts', {})),
            }

        return {
            'section_count': len(sections),
            'sections': section_summaries,
            'table_count': len(all_tables),
            'image_count': len(images),
            'styles': style_counts,
        }


# ============================================================================
# Module-level convenience functions
# ============================================================================

def open_hwpx(path):
    """Open an HWPX file and return an HwpxDocument.

    Args:
        path: Path to the .hwpx file.

    Returns:
        HwpxDocument instance.
    """
    info = zip_handler.read_hwpx_zip(path)
    return HwpxDocument(info)


# ============================================================================
# Internal Helpers
# ============================================================================

def _get_text_preview(paragraphs, max_len=80):
    """Get a text preview from a list of paragraph dicts."""
    texts = [p['text'] for p in paragraphs if p.get('text')]
    preview = ' | '.join(texts)
    if len(preview) > max_len:
        preview = preview[:max_len] + '...'
    return preview
