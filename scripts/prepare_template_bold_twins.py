#!/usr/bin/env python3
"""Bake exact bold twins for body styles into an HWPX template.

For each body style (paragraph/bullet/dash/star/note) that lacks an exact bold
twin in header.xml, clone its base <hh:charPr>, insert <hh:bold/>, assign the
next free id, append it, and bump <hh:charProperties itemCnt>. Idempotent: a
style that already has a twin is skipped. Repackages the .hwpx (preserving entry
order/compression) and regenerates assets/default_styles.json.

Usage: python3 scripts/prepare_template_bold_twins.py [path/to/template.hwpx]
"""
import os, re, sys, json, zipfile, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import generate_hwpx as G

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TEMPLATE = os.path.join(SKILL_DIR, "assets", "template.hwpx")
CACHE_PATH = os.path.join(SKILL_DIR, "assets", "default_styles.json")
STYLE_KEYS = ("paragraph", "bullet", "dash", "star", "note")


def _make_twin(base_xml, new_id):
    """Clone a base <hh:charPr> as id=new_id with <hh:bold/> inserted before
    <hh:underline> (the canonical position used by existing twins)."""
    twin = re.sub(r'(<hh:charPr )id="\d+"', r'\g<1>id="%d"' % new_id, base_xml, count=1)
    if '<hh:bold' not in twin:
        twin = re.sub(r'(<hh:underline\b)', r'<hh:bold/>\g<1>', twin, count=1)
    return twin


def prepare(template_path=DEFAULT_TEMPLATE):
    """Add missing body bold twins to the template. Returns list of
    (style_key, new_charPr_id) for the twins added (empty if none)."""
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(template_path) as zf:
            zf.extractall(os.path.join(td, "t"))
        sm = G.build_style_map_from_template(os.path.join(td, "t"))
    if sm is None:
        raise RuntimeError("could not build style map from template")

    with zipfile.ZipFile(template_path) as zf:
        header = zf.read("Contents/header.xml").decode("utf-8")

    chars = {m.group(1): m.group(0)
             for m in re.finditer(r'<hh:charPr id="(\d+)".*?</hh:charPr>', header, re.DOTALL)}
    next_id = max(int(c) for c in chars) + 1

    added = []
    base_to_twin = {}  # reuse a twin if two styles share a base
    new_blocks = []
    for key in STYLE_KEYS:
        base_id = sm[key][0]
        if G._find_bold_twin(header, base_id) != str(base_id):
            continue  # twin already exists
        if base_id in base_to_twin:
            added.append((key, base_to_twin[base_id]))
            continue
        twin_xml = _make_twin(chars[str(base_id)], next_id)
        new_blocks.append(twin_xml)
        base_to_twin[base_id] = str(next_id)
        added.append((key, str(next_id)))
        next_id += 1

    if not new_blocks:
        return []

    # Append new charPr blocks before </hh:charProperties> and bump itemCnt.
    header = header.replace("</hh:charProperties>",
                            "".join(new_blocks) + "</hh:charProperties>", 1)
    cur = int(re.search(r'<hh:charProperties itemCnt="(\d+)"', header).group(1))
    header = re.sub(r'(<hh:charProperties itemCnt=")\d+(")',
                    r'\g<1>%d\g<2>' % (cur + len(new_blocks)), header, count=1)

    _rewrite_zip(template_path, {"Contents/header.xml": header.encode("utf-8")})
    # Only refresh the committed cache when prepping the bundled template;
    # never touch it when a test (or a caller) preps a copy elsewhere.
    if os.path.abspath(template_path) == os.path.abspath(DEFAULT_TEMPLATE):
        _regenerate_cache(template_path)
    return added


def _rewrite_zip(path, replacements):
    """Rewrite a zip in place, replacing named entries; preserve order and
    per-entry compression. The 'mimetype' entry (stored first, uncompressed in
    OPC) is preserved by keeping the original order/compress_type."""
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        data = {i.filename: zf.read(i.filename) for i in infos}
    for name, blob in replacements.items():
        data[name] = blob
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w") as zf:
        for i in infos:
            zf.writestr(i, data[i.filename], compress_type=i.compress_type)
    os.replace(tmp, path)


def _regenerate_cache(template_path):
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(template_path) as zf:
            zf.extractall(os.path.join(td, "t"))
        sm = G.build_style_map_from_template(os.path.join(td, "t"))
    h = G.compute_template_hash(template_path)
    G.save_style_map_cache(CACHE_PATH, h, sm)


if __name__ == "__main__":
    tp = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEMPLATE
    result = prepare(tp)
    if result:
        print("Added bold twins:", ", ".join(f"{k}->{i}" for k, i in result))
    else:
        print("No twins added (all body styles already have exact twins).")
