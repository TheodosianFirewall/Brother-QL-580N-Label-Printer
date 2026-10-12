#!/usr/bin/env python3
"""Decode the media table (ql58nad.ptd) shipped in Brother's Windows QL-580N driver.

Usage:
    python3 -I tools/ptd_dump.py path/to/ql58nad.ptd            # human-readable table
    python3 -I tools/ptd_dump.py path/to/ql58nad.ptd --json     # JSON (what media.json is built from)

File layout (reverse engineered from driver version 1.04.00.00, see docs/RE-FINDINGS.md):

    0x00  char[4]  magic "PTDF"
    0x0C  u32      record count            (36 for the QL-580N)
    0x14  u32      offset of first record  (0x96)
    0x18  u32      record size             (377 bytes)

Each record:
    +0x00  UTF-16LE  media name, e.g. "62mm x 29mm"
    +0xC0  13 x u16  geometry block, decoded below

Units: "tenths" = 0.1 mm, "dots" = 300 dpi print-head dots.
"""

import json
import re
import struct
import sys

FIELDS = [
    "media_type",            # 0x0A continuous tape, 0x0B die-cut label (same codes as ESC i z n2)
    "media_id",              # Brother-internal ID; driver special-cases 362 (12mm round)
    "width_tenths",
    "printable_width_tenths",
    "width_dots",
    "printable_width_dots",
    "length_tenths",         # 0 for continuous tape
    "printable_length_tenths",
    "length_dots",
    "printable_length_dots",
    "unknown_0x14",          # 18/23/24/35; meaning not yet confirmed
    "feed_margin_dots",      # 35 dots = 3 mm, matches ESC i d default
    "left_offset_dots",      # first printable column in a 720-dot line (before mirroring)
]


def parse(data):
    if data[:4] != b"PTDF":
        raise ValueError("not a PTDF file")
    count, = struct.unpack_from("<I", data, 0x0C)
    first, = struct.unpack_from("<I", data, 0x14)
    size, = struct.unpack_from("<I", data, 0x18)
    records = []
    for i in range(count):
        base = first + i * size
        name = data[base:base + 0xC0].decode("utf-16le").split("\0")[0]
        values = struct.unpack_from("<13H", data, base + 0xC0)
        rec = {"name": name}
        rec.update(zip(FIELDS, values))
        # Entries like "62mm x 2" are Windows paper sizes for long banners on
        # continuous tape, not distinct physical rolls.
        rec["virtual"] = re.search(r"mm x \d+$", name) is not None
        records.append(rec)
    return records


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    with open(argv[1], "rb") as f:
        records = parse(f.read())
    if "--json" in argv:
        json.dump(records, sys.stdout, indent=2)
        print()
        return 0
    print(f"{'name':13} type  id   width(dots) printable  length(dots) printable  offset")
    for r in records:
        print(f"{r['name']:13} 0x{r['media_type']:02X} {r['media_id']:4} "
              f"{r['width_dots']:10} {r['printable_width_dots']:10} "
              f"{r['length_dots']:12} {r['printable_length_dots']:10} {r['left_offset_dots']:7}"
              f"{'  (virtual)' if r['virtual'] else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
