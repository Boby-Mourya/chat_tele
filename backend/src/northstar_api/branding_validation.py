"""Bounded raster-only branding validation. SVG/HTML and arbitrary URLs are not accepted."""
from __future__ import annotations

import base64
import binascii
import re
import struct
import zlib

MAX_BYTES = 350_000
MAX_SIDE = 2048
MAX_PIXELS = 2_000_000


def _dimensions(raw: bytes, kind: str) -> list[tuple[int, int]]:
    if kind == "png":
        if len(raw) < 33 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
            raise ValueError("Invalid PNG image")
        position = 8
        seen_header = False
        seen_data = False
        ended_data = False
        seen_palette = False
        while position + 12 <= len(raw):
            size = int.from_bytes(raw[position:position + 4], "big")
            tag = raw[position + 4:position + 8]
            end = position + 12 + size
            if end > len(raw) or not re.fullmatch(rb"[A-Za-z]{4}", tag):
                raise ValueError("Invalid PNG chunk")
            data = raw[position + 8:position + 8 + size]
            checksum = int.from_bytes(raw[position + 8 + size:end], "big")
            if zlib.crc32(tag + data) & 0xFFFFFFFF != checksum:
                raise ValueError("Invalid PNG checksum")
            if tag == b"IHDR":
                if seen_header or position != 8 or size != 13:
                    raise ValueError("Invalid PNG header")
                seen_header = True
                depth, color, compression, filtering, interlace = data[8:13]
                depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
                if depth not in depths.get(color, set()) or compression or filtering or interlace not in {0, 1}:
                    raise ValueError("Unsupported PNG header")
            elif tag in {b"acTL", b"fcTL", b"fdAT"}:
                raise ValueError("Use a non-animated PNG image")
            elif tag == b"PLTE":
                if seen_palette or seen_data or not size or size > 768 or size % 3:
                    raise ValueError("Invalid PNG palette")
                seen_palette = True
            elif tag == b"IDAT":
                if not seen_header or ended_data:
                    raise ValueError("Invalid PNG data order")
                seen_data = True
            elif tag == b"IEND":
                if size or not seen_data or end != len(raw):
                    raise ValueError("Invalid PNG end")
                return [struct.unpack(">II", raw[16:24])]
            elif tag[0] & 32 == 0:
                raise ValueError("Unsupported PNG critical chunk")
            if seen_data and tag != b"IDAT":
                ended_data = True
            position = end
        raise ValueError("Incomplete PNG image")
    if kind == "jpeg":
        if raw[:2] != b"\xff\xd8" or raw[-2:] != b"\xff\xd9":
            raise ValueError("Invalid JPEG image")
        position = 2
        found: list[tuple[int, int]] = []
        while position < len(raw):
            if raw[position] != 255:
                raise ValueError("Invalid JPEG marker")
            while position < len(raw) and raw[position] == 255:
                position += 1
            if position >= len(raw):
                break
            marker = raw[position]
            position += 1
            if marker == 0xDA:
                break
            if marker in {0xD8, 0xD9, 0x01, *range(0xD0, 0xD8)}:
                continue
            if position + 2 > len(raw):
                break
            length = int.from_bytes(raw[position:position + 2], "big")
            if length < 2 or position + length > len(raw):
                raise ValueError("Invalid JPEG segment")
            if marker in {0xC0, 0xC1, 0xC2}:
                if length < 8:
                    raise ValueError("Invalid JPEG dimensions")
                height, width = struct.unpack(">HH", raw[position + 3:position + 7])
                found.append((width, height))
            position += length
        if len(found) != 1:
            raise ValueError("Use a single-frame JPEG image")
        return found
    raise ValueError("Use a PNG or JPEG image; the dashboard converts WebP before upload")


def decode_raster(value: str) -> bytes:
    match = re.fullmatch(r"data:image/(png|jpeg);base64,([A-Za-z0-9+/]*={0,2})", value)
    if match is None:
        raise ValueError("Use a PNG or JPEG data URL; the dashboard converts WebP before upload")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid image encoding") from exc
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Brand images must be 350 KB or smaller")
    for width, height in _dimensions(raw, match.group(1)):
        if not 0 < width <= MAX_SIDE or not 0 < height <= MAX_SIDE or width * height > MAX_PIXELS:
            raise ValueError("Brand images must be at most 2048 pixels per side and 2 megapixels")
    return raw


def normalize_raster(value: str) -> str:
    if not value:
        return value
    import fitz
    raw = decode_raster(value)
    try:
        image = fitz.Pixmap(raw)
        if image.width * image.height > MAX_PIXELS or max(image.width, image.height) > MAX_SIDE:
            raise ValueError("Image exceeds the pixel limit")
        if image.colorspace and image.colorspace.n != 3:
            image = fitz.Pixmap(fitz.csRGB, image)
        clean = image.tobytes("png")
    except Exception as exc:
        raise ValueError("Image could not be safely decoded") from exc
    if len(clean) > MAX_BYTES:
        raise ValueError("Re-encoded image exceeds 350 KB; resize it before uploading")
    return "data:image/png;base64," + base64.b64encode(clean).decode("ascii")
