# -*- coding: utf-8 -*-
"""Minimal PE (Portable Executable) reader and byte-pattern scanner.

Pure standard library, no third-party dependencies.
Supports PE32+ (magic 0x20B) and PE32 (magic 0x10B).

This module is shared by the tools in this repository. It deliberately does
*not* hard-code virtual addresses: everything is derived from the file itself,
so the tools keep working when the game is updated.
"""
from __future__ import annotations

import struct

__all__ = ['PE', 'PEError', 'parse_pattern', 'find_pattern', 'find_all_patterns']


class PEError(Exception):
    """Raised when a file is not a PE image or is malformed."""


class Section:
    __slots__ = ('name', 'va', 'vsize', 'raw', 'rawsize')

    def __init__(self, name, va, vsize, raw, rawsize):
        self.name = name        # section name, e.g. '.text'
        self.va = va            # virtual address (RVA), not including image base
        self.vsize = vsize      # virtual size
        self.raw = raw          # file offset of the raw data
        self.rawsize = rawsize  # size of the raw data on disk

    def __repr__(self):  # pragma: no cover - debug helper
        return '<Section %s va=0x%x vsize=0x%x raw=0x%x rawsize=0x%x>' % (
            self.name, self.va, self.vsize, self.raw, self.rawsize)

    @property
    def has_raw(self) -> bool:
        return self.rawsize > 0


class PE:
    """A parsed PE image held entirely in memory."""

    def __init__(self, data: bytes, path: str = '<memory>'):
        self.data = data
        self.path = path
        self.sections: list[Section] = []
        self.image_base = 0
        self.machine = 0
        self._parse()

    # ---------------------------------------------------------------- parsing
    def _parse(self) -> None:
        d = self.data
        if len(d) < 0x40:
            raise PEError('%s: file too small to be a PE image' % self.path)
        if d[:2] != b'MZ':
            raise PEError('%s: missing MZ signature' % self.path)

        (e_lfanew,) = struct.unpack_from('<I', d, 0x3C)
        if e_lfanew + 24 > len(d) or d[e_lfanew:e_lfanew + 4] != b'PE\0\0':
            raise PEError('%s: missing PE\\0\\0 signature' % self.path)

        coff = e_lfanew + 4
        self.machine, nsec = struct.unpack_from('<HH', d, coff)
        (optsz,) = struct.unpack_from('<H', d, coff + 16)
        opt = coff + 20

        (magic,) = struct.unpack_from('<H', d, opt)
        if magic == 0x20B:      # PE32+
            (self.image_base,) = struct.unpack_from('<Q', d, opt + 24)
        elif magic == 0x10B:    # PE32
            (self.image_base,) = struct.unpack_from('<I', d, opt + 28)
        else:
            raise PEError('%s: unknown optional-header magic 0x%x' % (self.path, magic))
        self.magic = magic

        secoff = opt + optsz
        for i in range(nsec):
            o = secoff + i * 40
            if o + 40 > len(d):
                raise PEError('%s: section table truncated' % self.path)
            name = d[o:o + 8].rstrip(b'\0').decode('ascii', 'replace')
            vsize, va, rawsize, raw = struct.unpack_from('<IIII', d, o + 8)
            self.sections.append(Section(name, va, vsize, raw, rawsize))

    # -------------------------------------------------------------- mapping
    def section_for_rva(self, rva: int):
        for s in self.sections:
            if s.va <= rva < s.va + s.vsize:
                return s
        return None

    def rva_to_off(self, rva: int):
        """Map an RVA to a file offset, or None if not backed by file data."""
        s = self.section_for_rva(rva)
        if s is None or not s.has_raw:
            return None
        delta = rva - s.va
        if delta >= s.rawsize:
            return None
        off = s.raw + delta
        return off if off < len(self.data) else None

    def off_to_rva(self, off: int):
        for s in self.sections:
            if s.has_raw and s.raw <= off < s.raw + s.rawsize:
                return s.va + (off - s.raw)
        return None

    def va_to_off(self, va: int):
        return self.rva_to_off(va - self.image_base)

    def read(self, rva: int, n: int) -> bytes:
        off = self.rva_to_off(rva)
        if off is None:
            raise PEError('RVA 0x%x is not backed by file data' % rva)
        return self.data[off:off + n]

    def section(self, name: str):
        for s in self.sections:
            if s.name == name:
                return s
        return None

    # ------------------------------------------------------------- .pdata
    def function_bounds(self, rva: int):
        """Return (begin_rva, end_rva) of the function containing `rva`.

        Uses the exception directory (.pdata), which on MSVC x64 builds holds
        one 12-byte RUNTIME_FUNCTION per function: {BeginRVA, EndRVA, UnwindRVA}.
        This is exact, unlike linear disassembly (optimised builds split large
        functions into several chunks, so "disassemble until ret" is wrong).
        """
        pd = self.section('.pdata')
        if pd is None or not pd.has_raw:
            return None
        for i in range(0, pd.rawsize, 12):
            off = pd.raw + i
            if off + 12 > len(self.data):
                break
            begin, end, _unwind = struct.unpack_from('<III', self.data, off)
            if begin <= rva < end:
                return (begin, end)
        return None


# ------------------------------------------------------------------ patterns
def parse_pattern(pattern: str):
    """Parse a hex pattern with '?' wildcards into (bytes, mask).

    '41 B8 ?? 00' -> (b'\\x41\\xb8\\x00\\x00', (True, True, False, True))
    Accepted wildcard spellings: '?', '??', '**'.
    """
    out_b = bytearray()
    out_m = bytearray()
    for tok in pattern.split():
        if tok in ('?', '??', '**'):
            out_b.append(0)
            out_m.append(0)
        else:
            if len(tok) != 2:
                raise ValueError('bad pattern token %r' % tok)
            out_b.append(int(tok, 16))
            out_m.append(1)
    if not out_b:
        raise ValueError('empty pattern')
    return bytes(out_b), bytes(out_m)


def _anchor(pattern: bytes, mask: bytes):
    """Longest run of fixed bytes near the start, used to seed the search."""
    best_len, best_off, i = 0, 0, 0
    n = len(pattern)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            if j - i > best_len:
                best_len, best_off = j - i, i
            i = j
        else:
            i += 1
    if best_len == 0:
        return None, 0
    return pattern[best_off:best_off + best_len], best_off


def find_pattern(data: bytes, pattern: str):
    """Return the offset of the first match, or None."""
    hits = find_all_patterns(data, pattern, limit=1)
    return hits[0] if hits else None


def find_all_patterns(data: bytes, pattern: str, limit: int = 0):
    """Return every offset where `pattern` matches. limit=0 means unlimited."""
    pat, mask = parse_pattern(pattern)
    plen = len(pat)
    if plen > len(data):
        return []

    anchor, aoff = _anchor(pat, mask)
    hits: list[int] = []

    if anchor is None:  # all wildcards: nothing sensible to search for
        candidates = range(0, len(data) - plen + 1)
    else:
        candidates = []
        start = 0
        while True:
            i = data.find(anchor, start)
            if i < 0:
                break
            base = i - aoff
            if base >= 0 and base + plen <= len(data):
                candidates.append(base)
            start = i + 1

    for base in candidates:
        ok = True
        for k in range(plen):
            if mask[k] and data[base + k] != pat[k]:
                ok = False
                break
        if ok:
            hits.append(base)
            if limit and len(hits) >= limit:
                break
    return hits
