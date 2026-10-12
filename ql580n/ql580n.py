#!/usr/bin/env python3
"""Reference encoder for the Brother QL-580N raster protocol.

Pure Python + Pillow, so it runs unchanged on ARM (Raspberry Pi, ARM64 Linux,
Windows on ARM with Python installed). The byte stream it produces mirrors what
Brother's Windows driver (ql58nv.dll v1.04) emits; see docs/RE-FINDINGS.md for
the disassembly each step is based on.

Examples:
    # Write the job to a file and inspect it (no printer needed)
    python3 ql580n.py --media 62 --out job.bin label.png

    # Print over the network (QL-580N listens on raw TCP port 9100)
    python3 ql580n.py --media 62x29 --host 192.0.2.50 label.png

    # Print over USB on Linux (usblp kernel driver)
    python3 ql580n.py --media 29 --out /dev/usb/lp0 label.png

STATUS: protocol details are cross-checked against the Windows driver and the
media table it ships, but this script has not been run against real hardware
in this repository yet. Test with a cheap roll first.
"""

import argparse
import json
import os
import socket
import struct
import sys

from PIL import Image, ImageOps

HEAD_DOTS = 720                 # print-head width; 90 bytes per raster line
LINE_BYTES = HEAD_DOTS // 8
INVALIDATE_NULLS = 200          # CmdNull1=200 in ql58nl.ini
MEDIA_CONTINUOUS = 0x0A
MEDIA_DIE_CUT = 0x0B
MEDIA_ID_12MM_ROUND = 362       # driver special-cases this ID for the feed margin

_MEDIA_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media.json")


def short_name(name):
    """'62mm x 29mm' -> '62x29', '62mm' -> '62', '12mm Dia' -> 'd12'."""
    n = name.replace(" ", "")
    if n.endswith("Dia"):
        return "d" + n[:-3].replace("mm", "")
    return n.replace("mm", "")


def load_media(path=_MEDIA_JSON):
    with open(path) as f:
        records = json.load(f)
    return {short_name(r["name"]): r for r in records if not r["virtual"]}


def packbits(data):
    """TIFF PackBits, the scheme selected by the 'M 0x02' command."""
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        run = 1
        while i + run < n and run < 128 and data[i + run] == data[i]:
            run += 1
        if run > 1:
            out += bytes([257 - run, data[i]])
            i += run
            continue
        j = i + 1
        while j < n and j - i < 128 and not (j + 1 < n and data[j] == data[j + 1]):
            j += 1
        out += bytes([j - i - 1]) + data[i:j]
        i = j
    return bytes(out)


def fit_image(img, media, threshold=128, dither=False):
    """Scale the image to the label's printable area and convert to 1-bit."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGBA", img.size, "white")
        img = Image.alpha_composite(bg, img.convert("RGBA"))
    img = img.convert("L")

    width = media["printable_width_dots"]
    if media["media_type"] == MEDIA_DIE_CUT:
        box = (width, media["printable_length_dots"])
        # Rotate landscape artwork onto portrait labels (and vice versa) if it fits better.
        if (img.width > img.height) != (box[0] > box[1]):
            img = img.rotate(90, expand=True)
        img = ImageOps.contain(img, box)
        canvas = Image.new("L", box, 255)
        canvas.paste(img, ((box[0] - img.width) // 2, (box[1] - img.height) // 2))
        img = canvas
    else:
        if img.width != width:
            img = img.resize((width, max(1, round(img.height * width / img.width))))

    if dither:
        return img.convert("1")  # Floyd-Steinberg
    return img.point(lambda v: 255 if v >= threshold else 0, mode="1")


def raster_lines(img, media):
    """Yield 90-byte raster lines, black = 1, MSB first, horizontally mirrored.

    The driver reads source pixels right-to-left while packing bits from 0x80
    down, so the line is mirrored relative to the artwork.
    """
    canvas = Image.new("1", (HEAD_DOTS, img.height), 1)
    canvas.paste(img, (media["left_offset_dots"], 0))
    canvas = ImageOps.mirror(canvas)
    raw = canvas.tobytes()  # PIL packs mode "1" MSB-first with 1 = white
    for y in range(img.height):
        row = raw[y * LINE_BYTES:(y + 1) * LINE_BYTES]
        yield bytes(b ^ 0xFF for b in row)


def page_header(media, line_count, first_page, autocut=True, cut_at_end=True, feed_margin=None):
    """ESC i a / ESC i z / ESC i M / ESC i A / ESC i K / ESC i d, in driver order."""
    die_cut = media["media_type"] == MEDIA_DIE_CUT
    out = bytearray(b"\x1bia\x01")                       # switch to raster mode

    flags = 0x80 | 0x02 | 0x04 | (0x08 if die_cut else 0)  # recover | kind | width | length
    out += b"\x1biz" + bytes([
        flags,
        media["media_type"],
        round(media["width_tenths"] / 10),
        round(media["length_tenths"] / 10),
    ]) + struct.pack("<I", line_count) + bytes([0 if first_page else 1, 0])

    out += b"\x1biM" + bytes([0x40 if autocut else 0x00])  # bit 6 auto-cut (bit 7 = mirror)
    if autocut:
        out += b"\x1biA\x01"                              # cut every 1 label
    out += b"\x1biK" + bytes([0x08 if cut_at_end else 0x00])  # bit 3 cut at end (bit 6 = 600 dpi)

    if feed_margin is None:
        if media["media_id"] == MEDIA_ID_12MM_ROUND:
            feed_margin = 35
        elif die_cut:
            feed_margin = 0
        else:
            feed_margin = media["feed_margin_dots"]
    out += b"\x1bid" + struct.pack("<H", feed_margin)
    return bytes(out)


def encode_job(images, media, compress=True, **header_opts):
    """Build the complete byte stream for one or more already-fitted 1-bit images."""
    out = bytearray(b"\x00" * INVALIDATE_NULLS)
    out += b"\x1b@"                                       # initialize
    for index, img in enumerate(images):
        out += page_header(media, img.height, first_page=(index == 0), **header_opts)
        out += b"M\x02" if compress else b"M\x00"
        for line in raster_lines(img, media):
            if compress and not any(line):
                out += b"Z"                               # blank line (compressed mode only)
            elif compress:
                packed = packbits(line)
                out += b"g\x00" + bytes([len(packed)]) + packed
            else:
                out += b"g\x00" + bytes([LINE_BYTES]) + line
        out += b"\x1a" if index == len(images) - 1 else b"\x0c"  # print+feed / print
    return bytes(out)


def send(data, host=None, port=9100, out=None):
    if host:
        with socket.create_connection((host, port), timeout=10) as s:
            s.sendall(data)
    else:
        with open(out, "wb") as f:
            f.write(data)


def main(argv=None):
    media_table = load_media()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("images", nargs="+", help="one image per label/page")
    p.add_argument("--media", required=True, choices=sorted(media_table), help="loaded roll")
    dest = p.add_mutually_exclusive_group(required=True)
    dest.add_argument("--host", help="printer IP/hostname (raw TCP 9100)")
    dest.add_argument("--out", help="output file or device, e.g. job.bin or /dev/usb/lp0")
    p.add_argument("--port", type=int, default=9100)
    p.add_argument("--threshold", type=int, default=128, help="0-255 black/white cut-off")
    p.add_argument("--dither", action="store_true", help="dither photos instead of thresholding")
    p.add_argument("--no-compress", action="store_true")
    p.add_argument("--no-cut", action="store_true")
    args = p.parse_args(argv)

    media = media_table[args.media]
    pages = [fit_image(Image.open(path), media, args.threshold, args.dither) for path in args.images]
    data = encode_job(pages, media, compress=not args.no_compress,
                      autocut=not args.no_cut, cut_at_end=not args.no_cut)
    send(data, host=args.host, port=args.port, out=args.out)
    print(f"sent {len(data)} bytes, {len(pages)} page(s), media {args.media}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
