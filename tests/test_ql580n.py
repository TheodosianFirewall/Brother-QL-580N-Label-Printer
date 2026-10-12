"""Structural tests for the QL-580N encoder. Run: python3 -m unittest discover tests"""

import os
import random
import struct
import sys
import unittest

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ql580n"))
import ql580n  # noqa: E402


def unpackbits(data):
    out, i = bytearray(), 0
    while i < len(data):
        n = data[i]
        i += 1
        if n < 128:
            out += data[i:i + n + 1]
            i += n + 1
        elif n > 128:
            out += bytes([data[i]]) * (257 - n)
            i += 1
    return bytes(out)


def parse_job(data):
    """Minimal decoder for the subset of commands the encoder emits."""
    assert data[:ql580n.INVALIDATE_NULLS] == b"\x00" * ql580n.INVALIDATE_NULLS
    i = ql580n.INVALIDATE_NULLS
    assert data[i:i + 2] == b"\x1b@"
    i += 2
    pages, page, compress = [], None, False
    while i < len(data):
        if data[i:i + 4] == b"\x1bia\x01":
            page = {"lines": []}
            i += 4
        elif data[i:i + 3] == b"\x1biz":
            page["z"] = data[i + 3:i + 13]
            i += 13
        elif data[i:i + 3] in (b"\x1biM", b"\x1biA", b"\x1biK"):
            page[data[i + 2:i + 3].decode()] = data[i + 3]
            i += 4
        elif data[i:i + 3] == b"\x1bid":
            page["d"] = struct.unpack_from("<H", data, i + 3)[0]
            i += 5
        elif data[i] == ord("M"):
            compress = data[i + 1] == 0x02
            i += 2
        elif data[i] == ord("Z"):
            page["lines"].append(bytes(ql580n.LINE_BYTES))
            i += 1
        elif data[i] == ord("g"):
            n = data[i + 2]
            payload = data[i + 3:i + 3 + n]
            page["lines"].append(unpackbits(payload) if compress else payload)
            i += 3 + n
        elif data[i] in (0x0C, 0x1A):
            page["end"] = data[i]
            pages.append(page)
            i += 1
        else:
            raise AssertionError(f"unexpected byte 0x{data[i]:02x} at {i}")
    return pages


class EncoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = ql580n.load_media()

    def test_media_table_matches_known_geometry(self):
        m = self.media
        self.assertEqual(len(m), 18)
        self.assertEqual((m["62"]["printable_width_dots"], m["62"]["left_offset_dots"]), (696, 12))
        self.assertEqual((m["29x90"]["printable_width_dots"], m["29x90"]["printable_length_dots"]), (306, 991))
        self.assertEqual(m["62"]["media_type"], ql580n.MEDIA_CONTINUOUS)
        self.assertEqual(m["62x29"]["media_type"], ql580n.MEDIA_DIE_CUT)
        for r in m.values():
            self.assertLessEqual(r["left_offset_dots"] + r["printable_width_dots"], ql580n.HEAD_DOTS)

    def test_packbits_round_trip(self):
        rng = random.Random(1)
        samples = [bytes(90), b"\xff" * 90, bytes(range(90)),
                   bytes(rng.choice([0, 0, 255, rng.randrange(256)]) for _ in range(90))]
        samples += [bytes(rng.randrange(256) for _ in range(rng.randrange(1, 300))) for _ in range(200)]
        for s in samples:
            self.assertEqual(unpackbits(ql580n.packbits(s)), s)

    def _job(self, media_name, size, compress=True, pages=1):
        media = self.media[media_name]
        img = Image.new("L", size, 255)
        ImageDraw.Draw(img).rectangle((0, 0, size[0] // 4, size[1] - 1), fill=0)  # left-edge bar
        fitted = [ql580n.fit_image(img, media) for _ in range(pages)]
        return media, fitted, parse_job(ql580n.encode_job(fitted, media, compress=compress))

    def test_continuous_header(self):
        media, fitted, pages = self._job("62", (696, 100))
        p = pages[0]
        self.assertEqual(p["z"][:4], bytes([0x86, 0x0A, 62, 0]))
        self.assertEqual(struct.unpack_from("<I", p["z"], 4)[0], fitted[0].height)
        self.assertEqual(p["z"][8], 0)       # first page
        self.assertEqual(p["M"], 0x40)       # auto-cut
        self.assertEqual(p["K"], 0x08)       # cut at end
        self.assertEqual(p["d"], 35)         # 3 mm feed margin on continuous tape
        self.assertEqual(p["end"], 0x1A)
        self.assertEqual(len(p["lines"]), fitted[0].height)

    def test_die_cut_header_and_size(self):
        media, fitted, pages = self._job("62x29", (400, 150))
        p = pages[0]
        self.assertEqual(p["z"][:4], bytes([0x8E, 0x0B, 62, 29]))
        self.assertEqual(p["d"], 0)
        self.assertEqual(len(p["lines"]), media["printable_length_dots"])

    def test_mirroring_and_offset(self):
        # A bar on the artwork's left edge must land on the high-numbered head
        # columns after mirroring, inside the media's printable window.
        for compress in (True, False):
            media, fitted, pages = self._job("29", (306, 20), compress=compress)
            line = pages[0]["lines"][0]
            bits = "".join(f"{b:08b}" for b in line)
            dots = [i for i, c in enumerate(bits) if c == "1"]
            lo = ql580n.HEAD_DOTS - media["left_offset_dots"] - media["printable_width_dots"]
            hi = ql580n.HEAD_DOTS - media["left_offset_dots"]
            self.assertTrue(dots)
            self.assertGreaterEqual(min(dots), lo)
            self.assertEqual(max(dots), hi - 1)

    def test_multi_page_terminators(self):
        _, _, pages = self._job("62", (696, 50), pages=3)
        self.assertEqual([p["end"] for p in pages], [0x0C, 0x0C, 0x1A])
        self.assertEqual([p["z"][8] for p in pages], [0, 1, 1])


if __name__ == "__main__":
    unittest.main()
