#!/usr/bin/env python3
"""
Compress-Type Preserving ZIP Handler for HWPX files.

Reads and writes HWPX ZIP archives while preserving per-entry compress_type
metadata. Hancom Office validates ZIP entry compression methods — changing
STORED to DEFLATED (or vice versa) causes integrity check failures.

Rules:
  - mimetype is always ZIP_STORED and must be the first entry
  - Existing entries preserve their original compress_type
  - New entries default to ZIP_DEFLATED
"""

import os
import shutil
import tempfile
import zipfile
from pathlib import Path


class HwpxZipEntry:
    """Metadata for a single ZIP entry."""
    __slots__ = ('name', 'compress_type', 'external_attr', 'comment')

    def __init__(self, name, compress_type=zipfile.ZIP_DEFLATED,
                 external_attr=0, comment=b''):
        self.name = name
        self.compress_type = compress_type
        self.external_attr = external_attr
        self.comment = comment


class HwpxZipInfo:
    """Container for HWPX ZIP contents and per-entry metadata."""

    def __init__(self):
        self.entries = {}      # name -> bytes
        self.metadata = {}     # name -> HwpxZipEntry
        self._order = []       # insertion order (mimetype first)

    @property
    def entry_names(self):
        """Return entry names in correct order (mimetype first)."""
        return list(self._order)

    def __contains__(self, name):
        return name in self.entries

    def __getitem__(self, name):
        return self.entries[name]

    def __setitem__(self, name, data):
        """Set entry data, preserving existing metadata if present."""
        if not isinstance(data, bytes):
            if isinstance(data, str):
                data = data.encode('utf-8')
            else:
                raise TypeError(f"Entry data must be bytes or str, got {type(data)}")
        self.entries[name] = data
        if name not in self.metadata:
            ct = zipfile.ZIP_STORED if name == 'mimetype' else zipfile.ZIP_DEFLATED
            self.metadata[name] = HwpxZipEntry(name, compress_type=ct)
        if name not in self._order:
            if name == 'mimetype':
                self._order.insert(0, name)
            else:
                self._order.append(name)

    def get(self, name, default=None):
        return self.entries.get(name, default)

    def get_text(self, name, encoding='utf-8'):
        """Get entry content as string."""
        data = self.entries.get(name)
        if data is None:
            return None
        return data.decode(encoding)

    def set_text(self, name, text, encoding='utf-8'):
        """Set entry content from string."""
        self[name] = text.encode(encoding)

    def remove(self, name):
        """Remove an entry."""
        self.entries.pop(name, None)
        self.metadata.pop(name, None)
        if name in self._order:
            self._order.remove(name)

    def list_entries(self):
        """List all entry names in order."""
        return list(self._order)


def read_hwpx_zip(path):
    """Read an HWPX ZIP file, preserving per-entry compress_type.

    Returns an HwpxZipInfo containing all entries with their data and
    original compression metadata.

    Args:
        path: Path to the .hwpx file.

    Returns:
        HwpxZipInfo with entries, metadata, and ordering.
    """
    path = Path(path)
    info = HwpxZipInfo()

    with zipfile.ZipFile(path, 'r') as zf:
        # Read entries in archive order
        for zi in zf.infolist():
            if zi.is_dir():
                continue
            entry = HwpxZipEntry(
                name=zi.filename,
                compress_type=zi.compress_type,
                external_attr=zi.external_attr,
                comment=zi.comment or b'',
            )
            info.entries[zi.filename] = zf.read(zi.filename)
            info.metadata[zi.filename] = entry
            info._order.append(zi.filename)

    # Ensure mimetype is first in order
    if 'mimetype' in info._order:
        info._order.remove('mimetype')
        info._order.insert(0, 'mimetype')

    return info


def write_hwpx_zip(hwpx_info, output_path):
    """Write an HWPX ZIP file preserving per-entry compress_type.

    Args:
        hwpx_info: HwpxZipInfo containing entries and metadata.
        output_path: Path for the output .hwpx file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_path, 'w') as zf:
        for name in hwpx_info.entry_names:
            data = hwpx_info.entries.get(name)
            if data is None:
                continue
            meta = hwpx_info.metadata.get(name)
            ct = meta.compress_type if meta else zipfile.ZIP_DEFLATED
            # mimetype is always STORED
            if name == 'mimetype':
                ct = zipfile.ZIP_STORED
            zi = zipfile.ZipInfo(name)
            zi.compress_type = ct
            if meta:
                zi.external_attr = meta.external_attr
            zf.writestr(zi, data)


def replace_entry(hwpx_path, entry_name, new_data, output_path):
    """Replace a single entry in an HWPX file, preserving all others.

    Args:
        hwpx_path: Path to the source .hwpx file.
        entry_name: Name of the entry to replace (e.g. 'Contents/section1.xml').
        new_data: New content as bytes or str (str will be encoded as UTF-8).
        output_path: Path for the output .hwpx file.

    Raises:
        KeyError: If entry_name does not exist in the archive.
    """
    info = read_hwpx_zip(hwpx_path)
    if entry_name not in info:
        raise KeyError(f"Entry '{entry_name}' not found in {hwpx_path}")
    info[entry_name] = new_data if isinstance(new_data, bytes) else new_data.encode('utf-8')
    write_hwpx_zip(info, output_path)


def add_entry(hwpx_path, entry_name, data, output_path):
    """Add a new entry to an HWPX file, preserving all existing entries.

    Args:
        hwpx_path: Path to the source .hwpx file.
        entry_name: Name for the new entry.
        data: Content as bytes or str.
        output_path: Path for the output .hwpx file.
    """
    info = read_hwpx_zip(hwpx_path)
    info[entry_name] = data if isinstance(data, bytes) else data.encode('utf-8')
    write_hwpx_zip(info, output_path)


def remove_entry(hwpx_path, entry_name, output_path):
    """Remove an entry from an HWPX file, preserving all others.

    Args:
        hwpx_path: Path to the source .hwpx file.
        entry_name: Name of the entry to remove.
        output_path: Path for the output .hwpx file.

    Raises:
        KeyError: If entry_name does not exist in the archive.
    """
    info = read_hwpx_zip(hwpx_path)
    if entry_name not in info:
        raise KeyError(f"Entry '{entry_name}' not found in {hwpx_path}")
    info.remove(entry_name)
    write_hwpx_zip(info, output_path)
