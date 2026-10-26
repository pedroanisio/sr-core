"""Writes the kit cases of the star-fields draft and measures an engine's renders of them.

The draft (srep/srep-0000-star-fields.md, Kit cases) describes nine cases that join conformance/srep_cases/ once
the SREP has a number. `--write DIR` writes them now as srep-0000-stars-*.xml, with the catalogue fixture and two
synthetic catalogues under DIR/assets/; `--engine BIN` writes them, renders each with scene-render and measures
the frames. A case that compares two settings (point size, epoch, magnitude limit, a sky or none) has a companion
document named with a suffix. Radiance is read from linear EXR frames (`scene-render encode`, the document's
exr-sequence output); the seek case compares PNG frames of `scene-render render`. Every expectation comes
from star_fields_reference.py (and physical_sky_reference.py for the transmittance toward a star), none is
written here as a number.
"""
import argparse
import gzip
import hashlib
import io
import math
import os
import shutil
import struct
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import physical_sky_reference as ps  # noqa: E402
import star_fields_reference as sf  # noqa: E402

NAMES = ["stars-sirius", "stars-scale", "stars-colour", "stars-motion", "stars-space", "stars-labels",
         "stars-boundaries", "stars-sky", "stars-seek"]
# the documents of each case: the case's own and its companions (suffix: what differs)
DOCUMENTS = {
    "stars-sirius": ["stars-sirius"],
    "stars-scale": ["stars-scale", "stars-scale-4px"],
    "stars-colour": ["stars-colour"],
    "stars-motion": ["stars-motion", "stars-motion-2100"],
    "stars-space": ["stars-space"],
    "stars-labels": ["stars-labels", "stars-labels-ori", "stars-labels-umi", "stars-labels-limit3"],
    "stars-boundaries": ["stars-boundaries", "stars-boundaries-2100", "stars-boundaries-none"],
    "stars-sky": ["stars-sky", "stars-sky-noon", "stars-sky-none"],
    "stars-seek": ["stars-seek"],
}
FRAME = {"stars-sirius": (320, 240), "stars-scale": (480, 240), "stars-colour": (480, 240),
         "stars-motion": (640, 480), "stars-space": (640, 480), "stars-labels": (480, 480),
         "stars-boundaries": (320, 240), "stars-sky": (320, 240), "stars-seek": (640, 360)}
FOV = {"stars-sirius": 20.0, "stars-scale": 10.0, "stars-colour": 10.0, "stars-motion": 4.0, "stars-space": 4.0,
       "stars-labels": 16.0, "stars-boundaries": 10.0, "stars-sky": 10.0, "stars-seek": 60.0}
CATALOGUE = "assets/bsc5-compact.csv.gz"
DIGEST = "sha256:" + sf.CATALOGUE_DIGEST
SIRIUS, GROOMBRIDGE, VEGA = 2491, 4550, 7001
LABELS = {"stars-labels": "CMa", "stars-labels-ori": "Ori", "stars-labels-umi": "UMi", "stars-labels-limit3": "CMa"}
ORION_ARC = (81.875, -11.0)          # the middle of Orion's southern arc at 1875, the draft's boundary row
MOTION_YEARS = 100.0                 # epoch="2100" against epoch="2000"
SPACE_EPOCH_TT = "2488069.5"         # 2100-01-01T00:00:00 TT as a Julian day: J2000 + 100 Julian years
SEEK_FRAMES = 600                    # a century of proper motion over 600 frames at 24 fps
SEEK_RATE = MOTION_YEARS * sf.JULIAN_YEAR_S / (SEEK_FRAMES / 24.0)
SKY_NIGHT = "2026-06-21T00:00:00Z"   # the sun 67 degrees below the horizon at latitude 0, longitude 0
SKY_NOON = "2026-06-21T12:00:00Z"    # the sun 67 degrees up
SKY_ZERO = 1e-4                      # magnitudeZero of the sky case: a star far below the noon sky
SIRIUS_ZERO = 0.2                    # magnitudeZero of the Sirius case: its blue channel stays below 1 (the engine's
                                     # exr-sequence output clips at 1.0)
LABEL_ZERO = 1e-3                    # magnitudeZero of the limit-3 label frame: stars far below the label grey
SCALE_MAGNITUDES = (0.0, 5.0)
COLOUR_BV = (0.0, 0.65, 1.85)
SYNTHETIC_RA, SYNTHETIC_SPACING = 90.0, 1.0
CENTRE_TOL = 0.5
FLUX_TOL = 0.01
RATIO_TOL = 0.01
COLOUR_TOL = 0.02
LABEL_TOL_DEG = 1.0
LABEL_SAME_TOL = 1.0
LINE_TOL = 1.0
SKY_TOL = 0.05
SKY_INVISIBLE = 0.01
INK = 0.05                           # a label or boundary pixel: grey at or above this, before the dome's gain
LIT = 1e-4                           # a star pixel: luminance above this
GREY = 0.01                          # a pixel is grey when its channels differ by less
WINDOW = 4                           # half-width of the window a star's radiance is summed over
LUMA = (0.2126, 0.7152, 0.0722)


# ------------------------------------------------------------------------------------ the camera


def aim(d):
    """Camera yaw and pitch (degrees) that look along the scene direction d: the engine's camera looks along +z
    with y down, yaw turns about y toward +x and positive pitch looks up (toward -y)."""
    x, y, z = d
    return (math.degrees(math.atan2(x, z)), math.degrees(math.asin(max(-1.0, min(1.0, -y)))))


def zoom(name):
    w, _ = FRAME[name]
    return (w / 2.0) / math.tan(math.radians(FOV[name]) / 2.0)


def project(name, yaw, pitch, d):
    """Continuous frame coordinates (pixel i covers [i, i + 1)) of the scene direction d seen by the camera."""
    w, h = FRAME[name]
    ya, pa = math.radians(yaw), math.radians(pitch)
    x, y, z = d
    # the inverse of Ry(yaw) Rx(pitch): Rx(-pitch) Ry(-yaw)
    x1, z1 = math.cos(ya) * x - math.sin(ya) * z, math.sin(ya) * x + math.cos(ya) * z
    y2, z2 = math.cos(pa) * y + math.sin(pa) * z1, -math.sin(pa) * y + math.cos(pa) * z1
    if z2 <= 0.0:
        return (math.nan, math.nan)
    k = zoom(name)
    return (w / 2.0 + k * x1 / z2, h / 2.0 + k * y2 / z2)


def pixels_per_degree(name):
    return zoom(name) * math.tan(math.radians(1.0))


# ------------------------------------------------------------------------------------ catalogues and documents


def _catalogue():
    return sf.load_catalogue()


def _hr(catalogue, hr):
    return next(s for s in catalogue if s.hr == hr)


def synthetic_catalogue(rows):
    """A gzipped compact catalogue of (HR, RA, Dec, V, B-V) rows at the J2000 equator, without proper motion;
    deterministic bytes (no gzip name or time) so its digest is fixed."""
    text = ",".join(sf.COLUMNS) + "\n" + "".join(f"{hr},,{ra:.5f},{dec:.5f},{v:.2f},{bv:.2f},0.000,0.000,G2V\n"
                                                 for hr, ra, dec, v, bv in rows)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as f:
        f.write(text.encode("ascii"))
    return buf.getvalue()


def synthetic_catalogues():
    scale = synthetic_catalogue([(i + 1, SYNTHETIC_RA + (i - 0.5) * SYNTHETIC_SPACING, 0.0, v, 0.65)
                                 for i, v in enumerate(SCALE_MAGNITUDES)])
    colour = synthetic_catalogue([(i + 1, SYNTHETIC_RA + (i - 1) * SYNTHETIC_SPACING, 0.0, 0.0, bv)
                                  for i, bv in enumerate(COLOUR_BV)])
    return {"assets/stars-scale.csv.gz": scale, "assets/stars-colour.csv.gz": colour}


def _digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _doc(name, key, direction, star_attrs="", light_attrs="", catalogue=CATALOGUE, digest=DIGEST, fps=1,
         duration=1, space=None):
    w, h = FRAME[name]
    yaw, pitch = aim(direction)
    tail = f'<physics pixelsPerMeter="1"/>\n<space {space}/>\n' if space else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="1.8"><project width="{w}" height="{h}" fps="{fps}" duration="{duration}" '
            f'background="#000000FF"/>\n'
            f'<output id="exr" path="out/{key}_%04d.exr" codec="exr-sequence"/>\n'
            f'<assets><catalogue id="cat" src="{catalogue}" digest="{digest}"/></assets>\n'
            f'<composition><camera id="cam" fov="{FOV[name]}" yaw="{yaw:.7f}" pitch="{pitch:.7f}"/></composition>\n'
            f'<lights><light id="dome" type="dome"{light_attrs}><starField catalogue="cat"{star_attrs}/></light></lights>\n'
            f'{tail}</scene>\n')


def directions(catalogue):
    """The scene direction each case's camera looks along."""
    scene = lambda ra, dec: sf.scene_direction(sf.direction(ra, dec))  # noqa: E731
    sirius, groom, vega = (_hr(catalogue, hr) for hr in (SIRIUS, GROOMBRIDGE, VEGA))
    out = {"stars-sirius": scene(sirius.ra, sirius.dec), "stars-scale": scene(SYNTHETIC_RA, 0.0),
           "stars-colour": scene(SYNTHETIC_RA, 0.0), "stars-motion": scene(groom.ra, groom.dec),
           "stars-space": scene(groom.ra, groom.dec), "stars-boundaries": sf.scene_direction(sf.boundary_direction(*ORION_ARC)),
           "stars-sky": scene(vega.ra, vega.dec), "stars-seek": (0.0, 0.0, 1.0)}
    for key, abbreviation in LABELS.items():
        out[key] = scene(*sf.label_centroid(catalogue, abbreviation, 0.0))
    return out


def documents(catalogue=None):
    """The eighteen documents of the nine cases, by document key."""
    catalogue = catalogue or _catalogue()
    d = directions(catalogue)
    synth = synthetic_catalogues()
    scale_src, colour_src = "assets/stars-scale.csv.gz", "assets/stars-colour.csv.gz"
    scale_digest, colour_digest = _digest(synth[scale_src]), _digest(synth[colour_src])
    sky = f' sky="physical" latitude="0" longitude="0" moon="false"'
    docs = {
        "stars-sirius": _doc("stars-sirius", "stars-sirius", d["stars-sirius"],
                             f' limitMagnitude="-1" magnitudeZero="{SIRIUS_ZERO}"'),
        "stars-scale": _doc("stars-scale", "stars-scale", d["stars-scale"], ' limitMagnitude="6.5"',
                            catalogue=scale_src, digest=scale_digest),
        "stars-scale-4px": _doc("stars-scale", "stars-scale-4px", d["stars-scale"], ' limitMagnitude="6.5" pointSize="4"',
                                catalogue=scale_src, digest=scale_digest),
        "stars-colour": _doc("stars-colour", "stars-colour", d["stars-colour"], ' limitMagnitude="6.5"',
                             catalogue=colour_src, digest=colour_digest),
        "stars-motion": _doc("stars-motion", "stars-motion", d["stars-motion"], ' limitMagnitude="6.5" epoch="2000"'),
        "stars-motion-2100": _doc("stars-motion", "stars-motion-2100", d["stars-motion"],
                                  ' limitMagnitude="6.5" epoch="2100"'),
        "stars-space": _doc("stars-space", "stars-space", d["stars-space"], ' limitMagnitude="6.5"',
                            space=f'epoch="{SPACE_EPOCH_TT}" timeScale="tt"'),
        "stars-boundaries": _doc("stars-boundaries", "stars-boundaries", d["stars-boundaries"],
                                 ' limitMagnitude="-5" constellations="boundaries" epoch="2000"'),
        "stars-boundaries-2100": _doc("stars-boundaries", "stars-boundaries-2100", d["stars-boundaries"],
                                      ' limitMagnitude="-5" constellations="boundaries" epoch="2100"'),
        "stars-boundaries-none": _doc("stars-boundaries", "stars-boundaries-none", d["stars-boundaries"],
                                      ' limitMagnitude="-5" constellations="none"'),
        "stars-sky": _doc("stars-sky", "stars-sky", d["stars-sky"], f' limitMagnitude="1" magnitudeZero="{SKY_ZERO}"',
                          light_attrs=sky + f' date="{SKY_NIGHT}"'),
        "stars-sky-noon": _doc("stars-sky", "stars-sky-noon", d["stars-sky"],
                               f' limitMagnitude="1" magnitudeZero="{SKY_ZERO}"', light_attrs=sky + f' date="{SKY_NOON}"'),
        "stars-sky-none": _doc("stars-sky", "stars-sky-none", d["stars-sky"], f' limitMagnitude="1" magnitudeZero="{SKY_ZERO}"'),
        "stars-seek": _doc("stars-seek", "stars-seek", d["stars-seek"], ' limitMagnitude="6.5"', fps=24,
                           duration=(SEEK_FRAMES + 2) / 24.0, space=f'epoch="2451545.0" timeScale="tdb" rate="{SEEK_RATE:.0f}"'),
    }
    for key, abbreviation in LABELS.items():
        limit = ' limitMagnitude="3"' + f' magnitudeZero="{LABEL_ZERO}"' if key == "stars-labels-limit3" else ' limitMagnitude="-5"'
        docs[key] = _doc("stars-labels", key, d[key], limit + ' constellations="labels"')
    return docs


# ------------------------------------------------------------------------------------ expectations


def expectations(catalogue=None):
    catalogue = catalogue or _catalogue()
    d = directions(catalogue)
    sirius, groom, vega = (_hr(catalogue, hr) for hr in (SIRIUS, GROOMBRIDGE, VEGA))
    yaw_m, pitch_m = aim(d["stars-motion"])
    at = {years: project("stars-motion", yaw_m, pitch_m, sf.scene_direction(sf.moved(groom, years)))
          for years in (0.0, MOTION_YEARS)}
    a = ps.atmosphere()
    e = math.radians(vega.dec)        # the sky's up is scene -y, the ICRF pole: a star's elevation is its declination
    labels = {}
    for key, abbreviation in LABELS.items():
        yaw, pitch = aim(d[key])
        centre = project("stars-labels", yaw, pitch, sf.scene_direction(sf.direction(*sf.label_centroid(catalogue, abbreviation, 0.0))))
        labels[key] = centre
    w, h = FRAME["stars-sirius"]
    yaw_s, pitch_s = aim(d["stars-scale"])
    scale_at = [project("stars-scale", yaw_s, pitch_s, sf.scene_direction(sf.direction(SYNTHETIC_RA + (i - 0.5) * SYNTHETIC_SPACING, 0.0)))
                for i in range(len(SCALE_MAGNITUDES))]
    colour_at = [project("stars-colour", yaw_s, pitch_s, sf.scene_direction(sf.direction(SYNTHETIC_RA + (i - 1) * SYNTHETIC_SPACING, 0.0)))
                 for i in range(len(COLOUR_BV))]
    return {
        "stars-sirius": {"flux": sf.flux(sirius.vmag, SIRIUS_ZERO), "centre": (w / 2.0, h / 2.0)},
        "stars-scale": {"ratio": sf.flux(SCALE_MAGNITUDES[0]) / sf.flux(SCALE_MAGNITUDES[1]), "at": scale_at},
        "stars-colour": {"colours": [sf.colour(sf.temperature(bv)) for bv in COLOUR_BV], "at": colour_at},
        "stars-motion": {"at": at, "shift_px": math.dist(at[0.0], at[MOTION_YEARS]),
                         "shift_deg": math.degrees(math.acos(max(-1.0, min(1.0, sum(
                             p * q for p, q in zip(sf.moved(groom, 0.0), sf.moved(groom, MOTION_YEARS)))))))},
        "stars-space": {},
        "stars-labels": {"centres": labels, "px_per_deg": pixels_per_degree("stars-labels")},
        "stars-boundaries": {},
        "stars-sky": {"transmittance": ps.transmittance(a, ps._ground_observer(a), (math.cos(e), 0.0, math.sin(e)))},
        "stars-seek": {},
    }


# ------------------------------------------------------------------------------------ frames


def read_exr(path):
    """A scanline OpenEXR frame without compression (what ffmpeg's exr-sequence writes) as an (h, w, 3) float64
    array of linear R, G, B; half or float channels."""
    data = open(path, "rb").read()
    if data[:4] != b"\x76\x2f\x31\x01":
        raise ValueError(f"{path} is not an OpenEXR file")
    pos = 8
    channels, compression, window = [], None, None

    def cstr(p):
        end = data.index(b"\0", p)
        return data[p:end].decode("latin-1"), end + 1

    while data[pos] != 0:
        name, pos = cstr(pos)
        _, pos = cstr(pos)
        size = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        value = data[pos:pos + size]
        pos += size
        if name == "channels":
            q = 0
            while value[q] != 0:
                end = value.index(b"\0", q)
                cname = value[q:end].decode("latin-1")
                kind = struct.unpack_from("<i", value, end + 1)[0]
                q = end + 1 + 16
                channels.append((cname, kind))
        elif name == "compression":
            compression = value[0]
        elif name == "dataWindow":
            window = struct.unpack("<4i", value)
    pos += 1
    if compression != 0:
        raise ValueError(f"{path} is compressed ({compression}); the kit reads uncompressed scanlines")
    xmin, ymin, xmax, ymax = window
    w, h = xmax - xmin + 1, ymax - ymin + 1
    offsets = struct.unpack_from(f"<{h}Q", data, pos)
    out = np.zeros((h, w, 3), np.float64)
    index = {"R": 0, "G": 1, "B": 2}
    for off in offsets:
        y = struct.unpack_from("<i", data, off)[0] - ymin
        p = off + 8
        for cname, kind in channels:
            dtype, size = {0: ("<u4", 4), 1: ("<f2", 2), 2: ("<f4", 4)}[kind]
            row = np.frombuffer(data, dtype, w, p).astype(np.float64)
            p += w * size
            if cname in index:
                out[y, :, index[cname]] = row
    return out


def write_exr(path, rgb):
    """The inverse of read_exr for tests and fixtures: uncompressed float scanlines, channels B, G, R."""
    rgb = np.asarray(rgb, np.float32)
    h, w, _ = rgb.shape

    def attr(name, kind, value):
        return name.encode() + b"\0" + kind.encode() + b"\0" + struct.pack("<i", len(value)) + value

    chlist = b"".join(c.encode() + b"\0" + struct.pack("<iBBBBii", 2, 0, 0, 0, 0, 1, 1) for c in "BGR") + b"\0"
    box = struct.pack("<4i", 0, 0, w - 1, h - 1)
    header = (b"\x76\x2f\x31\x01" + struct.pack("<i", 2) + attr("channels", "chlist", chlist)
              + attr("compression", "compression", b"\0") + attr("dataWindow", "box2i", box)
              + attr("displayWindow", "box2i", box) + attr("lineOrder", "lineOrder", b"\0")
              + attr("pixelAspectRatio", "float", struct.pack("<f", 1.0))
              + attr("screenWindowCenter", "v2f", struct.pack("<2f", 0.0, 0.0))
              + attr("screenWindowWidth", "float", struct.pack("<f", 1.0)) + b"\0")
    line = 8 + 3 * 4 * w
    start = len(header) + 8 * h
    offsets = b"".join(struct.pack("<Q", start + y * line) for y in range(h))
    body = b"".join(struct.pack("<ii", y, 3 * 4 * w) + rgb[y, :, 2].tobytes() + rgb[y, :, 1].tobytes()
                    + rgb[y, :, 0].tobytes() for y in range(h))
    with open(path, "wb") as f:
        f.write(header + offsets + body)


def luminance(rgb):
    return rgb[..., 0] * LUMA[0] + rgb[..., 1] * LUMA[1] + rgb[..., 2] * LUMA[2]


def centroid(rgb, threshold=LIT):
    """The luminance-weighted centre of the lit pixels in continuous frame coordinates."""
    y = luminance(rgb)
    mask = y > threshold
    if not mask.any():
        return (math.nan, math.nan)
    ys, xs = np.nonzero(mask)
    weights = y[mask]
    return (float((xs * weights).sum() / weights.sum()) + 0.5, float((ys * weights).sum() / weights.sum()) + 0.5)


def window_sum(rgb, centre, half=WINDOW):
    """Per-channel sums over the (2 half + 1)-pixel square about a continuous frame position."""
    h, w, _ = rgb.shape
    cx, cy = int(math.floor(centre[0])), int(math.floor(centre[1]))
    x0, x1 = max(cx - half, 0), min(cx + half + 1, w)
    y0, y1 = max(cy - half, 0), min(cy + half + 1, h)
    return tuple(float(v) for v in rgb[y0:y1, x0:x1].sum(axis=(0, 1)))


def blobs(rgb, threshold=LIT):
    """Connected lit pixels (8-neighbourhood) as a list of luminance-weighted centroids, brightest first."""
    y = luminance(rgb)
    mask = y > threshold
    seen = np.zeros(mask.shape, bool)
    out = []
    h, w = mask.shape
    for sy, sx in zip(*np.nonzero(mask)):
        if seen[sy, sx]:
            continue
        stack, members = [(sy, sx)], []
        seen[sy, sx] = True
        while stack:
            py, px = stack.pop()
            members.append((py, px))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    qy, qx = py + dy, px + dx
                    if 0 <= qy < h and 0 <= qx < w and mask[qy, qx] and not seen[qy, qx]:
                        seen[qy, qx] = True
                        stack.append((qy, qx))
        weights = np.array([y[p] for p in members])
        xs = np.array([p[1] for p in members])
        ys = np.array([p[0] for p in members])
        out.append((float(weights.sum()), (float((xs * weights).sum() / weights.sum()) + 0.5,
                                           float((ys * weights).sum() / weights.sum()) + 0.5)))
    out.sort(reverse=True)
    return [c for _, c in out]


def ink(rgb):
    """Pixels of a label or boundary: grey (channels within GREY of each other) at or above INK."""
    lo, hi = rgb.min(axis=2), rgb.max(axis=2)
    return (lo >= INK) & (hi - lo <= GREY)


def ink_centre(rgb):
    """The centre of the ink's bounding box in continuous frame coordinates."""
    ys, xs = np.nonzero(ink(rgb))
    if len(xs) == 0:
        return (math.nan, math.nan)
    return ((float(xs.min()) + float(xs.max()) + 1.0) / 2.0, (float(ys.min()) + float(ys.max()) + 1.0) / 2.0)


def line_at_centre(rgb):
    """Whether a boundary pixel lies within a pixel of the frame's centre (the four central pixels)."""
    h, w, _ = rgb.shape
    block = ink(rgb)[h // 2 - 1:h // 2 + 1, w // 2 - 1:w // 2 + 1]
    return bool(block.any())


def identical(a, b):
    return a.shape == b.shape and bool(np.array_equal(a, b))


def psnr(a, b, peak):
    mse = float(np.mean((a - b) ** 2))
    return math.inf if mse == 0.0 else 10.0 * math.log10(peak ** 2 / mse)


def _load_png(png):
    return np.asarray(Image.open(png)).astype(np.float64)


def _r(v, n=3):
    return tuple(round(x, n) for x in v)


def _rel(measured, expected):
    return abs(measured - expected) / abs(expected) if expected else math.inf


# ------------------------------------------------------------------------------------ measurement


def measure(name, frames, exp):
    """Measure a rendered case: frames maps each document key (and "seek-alone", "seek-played") to its frame."""
    if name not in NAMES:
        raise ValueError(name)
    e = exp[name]
    if name == "stars-sirius":
        rgb = frames["stars-sirius"]
        total = float(luminance(rgb).sum())
        c = centroid(rgb)
        off = math.dist(c, e["centre"]) if all(map(math.isfinite, c)) else math.inf
        return {"pass": off <= CENTRE_TOL and _rel(total, e["flux"]) <= FLUX_TOL, "centre": _r(c), "off_px": round(off, 3),
                "radiance": round(total, 4), "expected": round(e["flux"], 4), "rel": round(_rel(total, e["flux"]), 4)}
    if name == "stars-scale":
        out, ok = {}, True
        sums = {}
        for key in ("stars-scale", "stars-scale-4px"):
            rgb = frames[key]
            bright, faint = (sum(v * k for v, k in zip(window_sum(rgb, at), LUMA)) for at in e["at"])
            sums[key] = (bright, faint)
            ratio = bright / faint if faint else math.inf
            out["ratio" if key == "stars-scale" else "ratio_4px"] = round(ratio, 3)
            ok = ok and _rel(ratio, e["ratio"]) <= RATIO_TOL
        size_rel = max(_rel(sums["stars-scale-4px"][i], sums["stars-scale"][i]) for i in range(2))
        out["size_rel"] = round(size_rel, 4)
        return {"pass": ok and size_rel <= RATIO_TOL, **out}
    if name == "stars-colour":
        rgb = frames["stars-colour"]
        worst = 0.0
        measured = []
        for at, expected in zip(e["at"], e["colours"]):
            s = window_sum(rgb, at)
            y = float(s[0] * LUMA[0] + s[1] * LUMA[1] + s[2] * LUMA[2])
            c = tuple(float(v) / y for v in s) if y > 0 else (math.nan,) * 3
            measured.append(_r(c))
            worst = max(worst, max(_rel(m, x) for m, x in zip(c, expected)))
        return {"pass": worst <= COLOUR_TOL, "colours": measured, "worst_rel": round(worst, 4)}
    if name == "stars-motion":
        found = {}
        for key, years in (("stars-motion", 0.0), ("stars-motion-2100", MOTION_YEARS)):
            expected = e["at"][years]
            candidates = blobs(frames[key])
            found[years] = min(candidates, key=lambda c: math.dist(c, expected)) if candidates else (math.nan, math.nan)
        offs = {years: (math.dist(found[years], e["at"][years]) if all(map(math.isfinite, found[years])) else math.inf)
                for years in found}
        shift = math.dist(found[0.0], found[MOTION_YEARS]) if all(map(math.isfinite, found[0.0] + found[MOTION_YEARS])) else math.inf
        return {"pass": max(offs.values()) <= CENTRE_TOL and abs(shift - e["shift_px"]) <= CENTRE_TOL,
                "at_2000": _r(found[0.0]), "at_2100": _r(found[MOTION_YEARS]), "off_px": round(max(offs.values()), 3),
                "shift_px": round(shift, 3), "expected_shift_px": round(e["shift_px"], 3),
                "shift_deg": round(e["shift_deg"], 4)}
    if name == "stars-space":
        a, b = frames["stars-space"], frames["stars-motion-2100"]
        same = identical(a, b)
        return {"pass": same, "identical": same, "psnr": round(psnr(a, b, 1.0), 2)}
    if name == "stars-labels":
        offs = {}
        for key in ("stars-labels", "stars-labels-ori", "stars-labels-umi"):
            c = ink_centre(frames[key])
            offs[LABELS[key]] = (math.dist(c, e["centres"][key]) if all(map(math.isfinite, c)) else math.inf) / e["px_per_deg"]
        c3, c0 = ink_centre(frames["stars-labels-limit3"]), ink_centre(frames["stars-labels"])
        same = math.dist(c3, c0) if all(map(math.isfinite, c3 + c0)) else math.inf
        return {"pass": max(offs.values()) <= LABEL_TOL_DEG and same <= LABEL_SAME_TOL,
                "off_deg": {k: round(v, 3) for k, v in offs.items()}, "limit3_off_px": round(same, 3)}
    if name == "stars-boundaries":
        at = {key: line_at_centre(frames[key]) for key in ("stars-boundaries", "stars-boundaries-2100")}
        none = bool(ink(frames["stars-boundaries-none"]).any())
        return {"pass": all(at.values()) and not none, "line_at_centre_2000": at["stars-boundaries"],
                "line_at_centre_2100": at["stars-boundaries-2100"], "ink_with_none": none}
    if name == "stars-sky":
        h, w, _ = frames["stars-sky"].shape
        centre = (w / 2.0, h / 2.0)
        area = (2 * WINDOW + 1) ** 2

        def excess(rgb):
            background = np.median(rgb.reshape(-1, 3), axis=0)
            return tuple(s - float(bg) * area for s, bg in zip(window_sum(rgb, centre), background)), background

        night, _ = excess(frames["stars-sky"])
        clear, _ = excess(frames["stars-sky-none"])
        noon, noon_bg = excess(frames["stars-sky-noon"])
        ratio = tuple(n / c if c else math.inf for n, c in zip(night, clear))
        worst = max(_rel(r, t) for r, t in zip(ratio, e["transmittance"]))
        noon_y = sum(v * k for v, k in zip(noon, LUMA))
        sky_y = float(sum(v * k for v, k in zip(noon_bg, LUMA))) * area
        visibility = abs(noon_y) / sky_y if sky_y > 0 else math.inf
        return {"pass": worst <= SKY_TOL and visibility <= SKY_INVISIBLE, "transmittance": _r(ratio),
                "expected": _r(e["transmittance"]), "worst_rel": round(worst, 4), "noon_visibility": round(visibility, 6)}
    if name == "stars-seek":
        alone, played = frames["seek-alone"], frames["seek-played"]
        same = identical(alone, played)
        return {"pass": same, "identical": same}
    raise ValueError(name)


# ------------------------------------------------------------------------------------ writing and running


def write(out_dir, catalogue=None):
    catalogue = catalogue or _catalogue()
    os.makedirs(os.path.join(out_dir, "assets"), exist_ok=True)
    shutil.copyfile(sf.CATALOGUE_PATH, os.path.join(out_dir, CATALOGUE))
    for rel, data in synthetic_catalogues().items():
        with open(os.path.join(out_dir, rel), "wb") as f:
            f.write(data)
    paths = {}
    for key, xml in documents(catalogue).items():
        path = os.path.join(out_dir, f"srep-0000-{key}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
        paths[key] = path
    return paths


def _run(cmd, exec):
    r = exec(cmd, capture_output=True, text=True)
    text = (r.stderr or "") + (r.stdout or "")
    if r.returncode != 0:
        err = text.strip().splitlines()
        return err[0] if err else f"exit {r.returncode}", text
    return None, text


def _encode(engine, doc, out_dir, exec):
    return _run([engine, "encode", doc, "--out-dir", out_dir], exec)


def _render(engine, doc, png, exec, frame=None, frames=None):
    cmd = [engine, "render", doc] + (["--frames", frames] if frames else ["-f", frame]) + ["-o", png]
    return _run(cmd, exec)


def run(engine, out_dir, exec=subprocess.run, catalogue=None):
    """Write the cases, render each document with the engine and measure every case; a case with a document the
    engine refuses reports that document's first diagnostic line under "error"."""
    catalogue = catalogue or _catalogue()
    exp = expectations(catalogue)
    paths = write(out_dir, catalogue)
    report = {}
    frames = {}
    errors = {}
    for key, doc in paths.items():
        if key == "stars-seek":
            continue
        err, _ = _encode(engine, doc, out_dir, exec)
        if err:
            errors[key] = err
            continue
        frames[key] = read_exr(os.path.join(out_dir, "out", f"{key}_0000.exr"))
    alone = os.path.join(out_dir, "stars-seek-alone.png")
    err, _ = _render(engine, paths["stars-seek"], alone, exec, frame=str(SEEK_FRAMES))
    if not err:
        pattern = os.path.join(out_dir, "stars-seek-seq-%04d.png")
        err, _ = _render(engine, paths["stars-seek"], pattern, exec, frames=f"0..={SEEK_FRAMES}")
        if not err:
            frames["seek-alone"], frames["seek-played"] = _load_png(alone), _load_png(pattern % SEEK_FRAMES)
    if err:
        errors["stars-seek"] = err
    for name in NAMES:
        needed = (["seek-alone", "seek-played"] if name == "stars-seek"
                  else DOCUMENTS[name] + (["stars-motion-2100"] if name == "stars-space" else []))
        missing = [k for k in needed if k not in frames]
        if missing:
            error = errors.get("stars-seek") if name == "stars-seek" else "; ".join(
                f"{k}: {errors.get(k, 'no frame')}" for k in missing)
            report[name] = {"pass": False, "error": error or "no frame"}
            continue
        report[name] = measure(name, frames, exp)
    return report


def table(report):
    rows = ["| Case | Measured | Pass |", "|---|---|---|"]
    for name, r in report.items():
        values = ", ".join(f"{k} {v}" for k, v in r.items() if k != "pass")
        rows.append(f"| {name} | {values} | {'yes' if r['pass'] else 'no'} |")
    return "\n".join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--engine", help="the scene-render binary to render with")
    ap.add_argument("--out", default=os.path.join(CONF, "out", "star-fields-kit"), help="where documents and frames go")
    ap.add_argument("--write", metavar="DIR", help="write the documents to DIR and stop")
    a = ap.parse_args(argv)
    if a.write:
        for p in write(a.write).values():
            print(p)
        return 0
    if not a.engine:
        ap.error("--engine BIN or --write DIR")
    report = run(a.engine, a.out)
    print(table(report))
    return 0 if all(r["pass"] for r in report.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
