import base64
import struct
import zlib

import pytest

from northstar_api.branding_validation import decode_raster, normalize_raster


def png(width=2, height=2):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = b"\x00\xff\x00\x00\x00\xff\x00" * 2
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


def url(raw, kind="png"):
    return f"data:image/{kind};base64," + base64.b64encode(raw).decode()


def test_png_roundtrip():
    result = normalize_raster(url(png()))
    assert result.startswith("data:image/png;base64,")
    assert decode_raster(result).startswith(b"\x89PNG")
    assert normalize_raster("") == ""


@pytest.mark.parametrize("value", [
    "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=", "data:text/html;base64,PHNjcmlwdD4=", "javascript:alert(1)",
    "https://example.com/image.png", "data:image/png;base64,%%%", "data:image/png;base64,", url(b"<html>not png</html>"),
])
def test_active_or_malformed_content_rejected(value):
    with pytest.raises(ValueError):
        decode_raster(value)


@pytest.mark.parametrize("width,height", [(0, 2), (2, 0), (2049, 1), (1, 2049), (2000, 2000), (65535, 65535)])
def test_declared_pixel_bombs_rejected_before_decoding(width, height):
    with pytest.raises(ValueError):
        decode_raster(url(png(width, height)))


def test_large_payload_rejected():
    with pytest.raises(ValueError, match="350 KB"):
        decode_raster(url(png() + b"x" * 350_000))


def test_corrupt_raster_rejected_by_decoder():
    with pytest.raises(ValueError):
        normalize_raster(url(png()[:33]))


def test_real_jpeg_normalizes_to_safe_png():
    value = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAACAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDxuiiitjI//9k="
    assert normalize_raster(value).startswith("data:image/png;base64,")


def test_unconverted_webp_is_rejected_with_clear_wire_contract():
    value = "data:image/webp;base64,UklGRi4AAABXRUJQVlA4ICIAAABwAQCdASoCAAIAAUAmJZQCdAFAAAD++3sItRJUvJ+iMAAA"
    with pytest.raises(ValueError, match="dashboard converts WebP"):
        normalize_raster(value)


@pytest.mark.parametrize("transform", [lambda raw: raw[:-1], lambda raw: raw + b"trailing", lambda raw: raw[:40] + bytes([raw[40] ^ 1]) + raw[41:]])
def test_png_truncation_trailing_data_and_bad_crc_rejected(transform):
    with pytest.raises(ValueError):
        decode_raster(url(transform(png())))
