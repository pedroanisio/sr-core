"""A small PDF 1.4 writer: pages of text in the base-14 Helvetica fonts, filled rectangles, lines and images.

Standard library only. Text is encoded as Windows-1252 (WinAnsiEncoding); characters outside it print as '?'.
Images are PNG (8- or 16-bit, any colour type, not interlaced; alpha is composited over white) or baseline and
progressive JPEG (grey or RGB, embedded as is). Images wider than `max_width` are reduced: by an integer factor
(nearest sample) with the standard library, or resampled and embedded as JPEG when Pillow is installed, which
makes frames several times smaller. The output is byte-for-byte reproducible for the same inputs and the same
Pillow (or none): no dates, no ids.
"""
from __future__ import annotations

import io
import struct
import zlib

from .metrics import BOLD, REGULAR

FONTS = {"F1": ("Helvetica", REGULAR), "F2": ("Helvetica-Bold", BOLD)}


class ImageError(ValueError):
    pass


def encode(text: str) -> bytes:
    return text.encode("cp1252", errors="replace")


def text_width(text: str, size: float, font: str = "F1") -> float:
    table = FONTS[font][1]
    return sum(table[b] for b in encode(text)) * size / 1000


def wrap(text: str, width: float, size: float, font: str = "F1") -> list[str]:
    """Greedy word wrap to `width` points; a word longer than a line is broken by characters."""
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            trial = f"{line} {word}" if line else word
            if text_width(trial, size, font) <= width:
                line = trial
                continue
            if line:
                lines.append(line)
            while text_width(word, size, font) > width and len(word) > 1:
                n = len(word)
                while n > 1 and text_width(word[:n], size, font) > width:
                    n -= 1
                lines.append(word[:n])
                word = word[n:]
            line = word
        lines.append(line)
    return lines


def _literal(text: str) -> bytes:
    out = bytearray(b"(")
    for b in encode(text):
        if b in b"()\\":
            out += b"\\" + bytes([b])
        elif b < 32 or b == 127:
            out += b"\\%03o" % b
        else:
            out.append(b)
    return bytes(out + b")")


def _num(v: float) -> bytes:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return (s if s not in ("-0", "") else "0").encode()


# ----------------------------------------------------------------------------------------------- images
class Image:
    def __init__(self, width: int, height: int, colors: int, data: bytes, filter_: str, params: bytes = b""):
        self.width, self.height, self.colors, self.data, self.filter, self.params = (
            width, height, colors, data, filter_, params)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def _unfilter(raw: bytes, height: int, stride: int, bpp: int) -> bytearray:
    out = bytearray(height * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        kind = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if kind == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif kind == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, prev))
        elif kind == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif kind == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                upleft = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], upleft)) & 255
        elif kind != 0:
            raise ImageError(f"PNG: unknown filter type {kind}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def _decimate(pixels: bytearray, width: int, height: int, channels: int, step: int) -> bytearray:
    """Every step-th pixel of every step-th row."""
    stride, w2 = width * channels, -(-width // step)
    out = bytearray()
    for y in range(0, height, step):
        row, line = pixels[y * stride:(y + 1) * stride], bytearray(w2 * channels)
        for c in range(channels):
            line[c::channels] = row[c::channels * step]
        out += line
    return out


def _with_pillow(data: bytes, max_width: int) -> Image | None:
    try:
        from PIL import Image as PILImage
    except ImportError:
        return None
    try:
        im = PILImage.open(io.BytesIO(data))
        im.load()
    except Exception:          # noqa: BLE001 - anything Pillow cannot read falls back to the built-in readers
        return None
    if im.mode in ("RGBA", "LA", "P", "PA"):
        im = im.convert("RGBA")
        flat = PILImage.new("RGB", im.size, (255, 255, 255))
        flat.paste(im, mask=im.getchannel("A"))
        im = flat
    elif im.mode != "L":
        im = im.convert("RGB")
    if max_width and im.width > max_width:
        im = im.resize((max_width, max(1, round(im.height * max_width / im.width))), PILImage.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85, optimize=True)
    return Image(im.width, im.height, 1 if im.mode == "L" else 3, buf.getvalue(), "DCTDecode")


def read_png(data: bytes, max_width: int = 0) -> Image:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ImageError("not a PNG file")
    pos, idat, palette = 8, bytearray(), None
    ihdr = None
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    if not ihdr:
        raise ImageError("PNG: no IHDR")
    width, height, depth, ctype, _, _, interlace = ihdr
    if interlace:
        raise ImageError("PNG: interlaced images are not supported")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None or depth not in (8, 16) and not (ctype == 3 and depth == 8):
        raise ImageError(f"PNG: colour type {ctype} at {depth} bits is not supported")
    step = -(-width // max_width) if max_width and width > max_width else 1
    if ctype in (0, 2) and depth == 8 and step == 1:
        # rows are already in PDF's PNG-predictor form: embed the compressed data as it is
        params = b"<< /Predictor 15 /Colors %d /BitsPerComponent 8 /Columns %d >>" % (channels, width)
        return Image(width, height, channels, bytes(idat), "FlateDecode", params)
    size = depth // 8
    pixels = _unfilter(zlib.decompress(bytes(idat)), height, width * channels * size, channels * size)
    if size == 2:
        pixels = pixels[0::2]
    if step > 1:
        pixels, width, height = _decimate(pixels, width, height, channels, step), -(-width // step), -(-height // step)
    if ctype == 3:
        if palette is None:
            raise ImageError("PNG: palette image without PLTE")
        rgb = bytearray(len(pixels) * 3)
        for i, idx in enumerate(pixels):
            rgb[3 * i:3 * i + 3] = palette[3 * idx:3 * idx + 3]
        return Image(width, height, 3, zlib.compress(bytes(rgb), 9), "FlateDecode")
    if ctype in (0, 2):
        return Image(width, height, channels, zlib.compress(bytes(pixels), 9), "FlateDecode")
    colour = channels - 1
    if pixels[colour::channels].count(255) == width * height:     # opaque: drop the alpha channel
        out = bytearray(width * height * colour)
        for c in range(colour):
            out[c::colour] = pixels[c::channels]
        return Image(width, height, colour, zlib.compress(bytes(out), 9), "FlateDecode")
    out = bytearray(width * height * colour)
    for i in range(width * height):
        a = pixels[i * channels + colour]
        base = i * channels
        for c in range(colour):
            out[i * colour + c] = (pixels[base + c] * a + 255 * (255 - a) + 127) // 255
    return Image(width, height, colour, zlib.compress(bytes(out), 9), "FlateDecode")


def read_jpeg(data: bytes) -> Image:
    if data[:2] != b"\xff\xd8":
        raise ImageError("not a JPEG file")
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise ImageError("JPEG: bad marker")
        marker = data[pos + 1]
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width, comps = struct.unpack(">HHB", data[pos + 5:pos + 10])
            if comps not in (1, 3):
                raise ImageError(f"JPEG: {comps} components are not supported")
            return Image(width, height, comps, data, "DCTDecode")
        pos += 2 + length
    raise ImageError("JPEG: no frame header")


def read_image(path: str, max_width: int = 0, pillow: bool = True) -> Image:
    with open(path, "rb") as f:
        data = f.read()
    if pillow:
        img = _with_pillow(data, max_width)
        if img:
            return img
    return read_jpeg(data) if data[:2] == b"\xff\xd8" else read_png(data, max_width)


# ------------------------------------------------------------------------------------------------ pages
class Page:
    def __init__(self, width: float, height: float):
        self.width, self.height = width, height
        self.ops: list[bytes] = []
        self.images: dict[str, Image] = {}

    def text(self, x: float, y: float, text: str, size: float = 10, font: str = "F1", grey: float = 0) -> None:
        """Draw one line with its baseline at (x, y), y measured down from the top of the page."""
        self.ops.append(b"BT %s g /%s %s Tf %s %s Td %s Tj ET" % (
            _num(grey), font.encode(), _num(size), _num(x), _num(self.height - y), _literal(text)))

    def rect(self, x: float, y: float, w: float, h: float, grey: float) -> None:
        self.ops.append(b"%s g %s %s %s %s re f" % (_num(grey), _num(x), _num(self.height - y - h), _num(w), _num(h)))

    def line(self, x1: float, y1: float, x2: float, y2: float, grey: float = 0.7, width: float = 0.5) -> None:
        self.ops.append(b"%s G %s w %s %s m %s %s l S" % (
            _num(grey), _num(width), _num(x1), _num(self.height - y1), _num(x2), _num(self.height - y2)))

    def image(self, img: Image, x: float, y: float, w: float, h: float) -> None:
        name = f"Im{len(self.images) + 1}"
        self.images[name] = img
        self.ops.append(b"q %s 0 0 %s %s %s cm /%s Do Q" % (
            _num(w), _num(h), _num(x), _num(self.height - y - h), name.encode()))


class Document:
    def __init__(self, title: str = "", producer: str = ""):
        self.title, self.producer = title, producer
        self.pages: list[Page] = []

    def page(self, width: float, height: float) -> Page:
        p = Page(width, height)
        self.pages.append(p)
        return p

    def tobytes(self) -> bytes:
        objs: list[bytes] = []

        def add(body: bytes) -> int:
            objs.append(body)
            return len(objs)

        def stream(dict_: bytes, data: bytes) -> bytes:
            return b"<< %s /Length %d >>\nstream\n%s\nendstream" % (dict_, len(data), data)

        catalog, pages = add(b""), add(b"")
        fonts = {k: add(b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>" % v[0].encode())
                 for k, v in FONTS.items()}
        font_res = b" ".join(b"/%s %d 0 R" % (k.encode(), n) for k, n in fonts.items())
        kids = []
        for p in self.pages:
            xobj = []
            for name, img in p.images.items():
                space = b"/DeviceGray" if img.colors == 1 else b"/DeviceRGB"
                d = b"/Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s /BitsPerComponent 8 /Filter /%s" % (
                    img.width, img.height, space, img.filter.encode())
                if img.params:
                    d += b" /DecodeParms " + img.params
                xobj.append(b"/%s %d 0 R" % (name.encode(), add(stream(d, img.data))))
            content = add(stream(b"/Filter /FlateDecode", zlib.compress(b"\n".join(p.ops), 9)))
            res = b"<< /Font << %s >>%s >>" % (font_res, (b" /XObject << " + b" ".join(xobj) + b" >>") if xobj else b"")
            kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %s %s] /Resources %s /Contents %d 0 R >>" % (
                pages, _num(p.width), _num(p.height), res, content)))
        objs[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages
        objs[pages - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
            b" ".join(b"%d 0 R" % k for k in kids), len(kids))
        info = add(b"<< /Title %s /Producer %s >>" % (_literal(self.title), _literal(self.producer)))

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(objs, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objs) + 1, catalog, info, xref)
        return bytes(out)
