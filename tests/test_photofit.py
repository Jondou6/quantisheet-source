"""Owner-report photos (app/pm/photofit.py): upright loading, the date a
photo was taken, fill/contain fitting, and re-encoding at the printed size
(AT-06, AT-07, AT-n1 photo part, AT-n2). Test images are made here with
Pillow - no real photos, no real places."""
import io
import os
import random
from datetime import datetime

import pytest
from PIL import Image, ImageChops, ImageOps

from app.pm import photofit as pf

# the 4-up photo cells of the form (spec 1.2), PDF points
TOP_LEFT = (9.0, 65.3, 388.7, 317.0)            # 379.7 x 251.7
BOTTOM_LEFT = (9.0, 334.0, 388.7, 596.6)        # 379.7 x 262.6


def site_photo(w, h, seed=0, detail=0.35, grain=6):
    """A synthetic photo that compresses like a construction-site photo:
    random structure at every octave of the frame (so the same 'scene' at
    any resolution looks alike, as with real cameras), colour in the coarse
    octaves, texture - gravel, rebar, formwork - in the fine ones, light
    sensor grain. 4032x3024 -> ~4.8 MB at q92, ~95 KB in an email cell."""
    rnd = random.Random(seed)
    img, k, cells = None, 0, 3
    while cells < max(w, h) / 1.5:
        cw = max(2, round(cells * w / max(w, h)))
        ch = max(2, round(cells * h / max(w, h)))
        mode = "RGB" if cells < 40 else "L"
        lay = Image.frombytes(mode, (cw, ch),
                              rnd.randbytes(cw * ch * len(mode)))
        lay = lay.resize((w, h), Image.BICUBIC).convert("RGB")
        k += 1
        a = 1.0 / k if cells < 40 else min(1.0, detail / k * 1.6)
        img = lay if img is None else Image.blend(img, lay, a)
        cells *= 2
    img = ImageOps.autocontrast(img, cutoff=1)
    img = Image.blend(img, ImageOps.grayscale(img).convert("RGB"), 0.5)
    # grain from Python's seeded random (Image.effect_noise uses the C
    # library's rand(), which differs between Windows and Linux)
    noise = Image.frombytes("L", (w, h), rnd.randbytes(w * h))
    noise = Image.blend(Image.new("L", (w, h), 128), noise, grain / 74)
    return ImageChops.add(img, noise.convert("RGB"), offset=-128)


def _exif(orientation=None, taken=None, edited=None, gps=False):
    ex = Image.Exif()
    if orientation:
        ex[0x0112] = orientation
    if edited:
        ex[0x0132] = edited
    if taken:
        ex.get_ifd(0x8769)[0x9003] = taken
    if gps:
        ex.get_ifd(0x8825)[1] = "N"                   # GPSLatitudeRef
        ex.get_ifd(0x8825)[3] = "W"                   # GPSLongitudeRef
    return ex.tobytes()


def _save(img, path, **exif):
    img.save(path, "JPEG", quality=92, exif=_exif(**exif) if exif else b"")
    return str(path)


def _close(a, b, tol=0.5):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# ---- fit (AT-06) ----------------------------------------------------------

def test_landscape_phone_photo_fills_the_cell():
    for cell in (TOP_LEFT, BOTTOM_LEFT):
        rect, box = pf.fit(cell, 4032, 3024)
        assert _close(rect, cell)
        # the cell is wider than 4:3 -> top and bottom trimmed, centred
        assert box[0] == 0 and box[2] == 1
        ia, ca = 4032 / 3024, (cell[2] - cell[0]) / (cell[3] - cell[1])
        assert abs((box[3] - box[1]) - ia / ca) < 1e-9
        assert abs(box[1] - (1 - box[3])) < 1e-9
    # the crop is 11.6 % for the top cell (the spec's "9.4 %" is off, but
    # still under max_crop 12 %, so the fill decision stands)
    c = 1 - (4032 / 3024) / (379.7 / 251.7)
    assert 0.115 < c < 0.117


def test_portrait_phone_photo_is_contained_and_centred():
    rect, box = pf.fit(TOP_LEFT, 3024, 4032)
    x0, y0, x1, y1 = TOP_LEFT
    assert box == (0.0, 0.0, 1.0, 1.0)
    assert abs((rect[3] - rect[1]) - (y1 - y0)) < 0.5      # full height
    assert abs((rect[2] - rect[0]) - (y1 - y0) * 0.75) < 0.5
    assert abs((rect[0] + rect[2]) / 2 - (x0 + x1) / 2) < 0.5
    assert rect[0] > x0 and rect[2] < x1


def test_fit_modes_crop_and_threshold():
    cell = (0, 0, 300, 200)                                 # 3:2
    # 16:9 in 3:2 -> c = 15.6 % > 12 % -> contain, letterboxed, centred
    rect, box = pf.fit(cell, 1920, 1080)
    assert box == (0, 0, 1, 1)
    assert _close(rect, (0, 15.625, 300, 184.375))
    # forced fill: sides trimmed
    rect, box = pf.fit(cell, 1920, 1080, mode="fill")
    assert rect == cell and box[1] == 0 and box[3] == 1
    assert abs((box[2] - box[0]) - 1.5 / (16 / 9)) < 1e-9
    # forced contain even when auto would fill
    rect, _ = pf.fit(cell, 4032, 3024, mode="contain")
    assert _close(rect, (16.667, 0, 283.333, 200), 0.01)
    # a larger max_crop lets 16:9 fill
    assert pf.fit(cell, 1920, 1080, max_crop=0.2)[0] == cell
    # the user's crop wins: that part, whole, centred
    rect, box = pf.fit(cell, 4000, 3000, crop=(0.1, 0.2, 0.7, 0.6))
    assert box == (0.1, 0.2, 0.7, 0.6)                      # 2400 x 1200
    assert _close(rect, (0, 25, 300, 175))
    with pytest.raises(ValueError):
        pf.fit(cell, 100, 100, mode="stretch")
    with pytest.raises(ValueError):
        pf.fit(cell, 0, 100)


# ---- load + EXIF (AT-07, AT-a2 data) --------------------------------------

def test_orientation_6_loads_upright_and_places_upright(tmp_path):
    raw = Image.new("RGB", (400, 300), (200, 200, 200))
    raw.paste((255, 0, 0), (0, 0, 40, 40))         # red: stored top-left
    p = _save(raw, tmp_path / "rot.jpg", orientation=6,
              taken="2026:10:14 09:30:00")
    img = pf.load(p)
    assert img.size == (300, 400) and img.mode == "RGB"
    # orientation 6 = rotate 90 deg clockwise to view: top-left -> top-right
    r, g, b = img.getpixel((280, 20))
    assert r > 200 and g < 80 and b < 80
    assert pf.upright_size(p) == (300, 400)
    # placed: the frame and the encoded picture have the upright aspect
    rect, box = pf.fit(TOP_LEFT, *img.size)
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    assert abs(w / h - 300 / 400) < 0.01
    out = Image.open(io.BytesIO(pf.encode(img, w, h, "email", box)))
    assert abs(out.width / out.height - 0.75) < 0.01
    assert dict(out.getexif()) == {}                 # nothing to re-rotate


def test_exif_taken_original_then_edit_date_then_file_date(tmp_path):
    img = Image.new("RGB", (64, 48), "gray")
    p = _save(img, tmp_path / "a.jpg", taken="2026:10:14 09:30:00",
              edited="2026:10:16 17:00:00")
    assert pf.exif_taken(p) == (datetime(2026, 10, 14, 9, 30), "exif")
    p = _save(img, tmp_path / "b.jpg", edited="2026:10:16 17:00:00")
    assert pf.exif_taken(p) == (datetime(2026, 10, 16, 17, 0), "exif")
    p = _save(img, tmp_path / "c.jpg")                  # no EXIF at all
    t = datetime(2026, 10, 12, 8, 15).timestamp()
    os.utime(p, (t, t))
    assert pf.exif_taken(p) == (datetime(2026, 10, 12, 8, 15), "file")
    p = _save(img, tmp_path / "d.jpg", taken="0000:00:00 00:00:00")
    os.utime(p, (t, t))
    assert pf.exif_taken(p)[1] == "file"               # blank camera clock
    q = tmp_path / "notes.txt"
    q.write_text("not a photo")
    os.utime(q, (t, t))
    assert pf.exif_taken(str(q)) == (datetime(2026, 10, 12, 8, 15), "file")
    assert pf.exif_taken(str(tmp_path / "gone.jpg")) == (None, "file")


def test_load_png_with_transparency_and_heic_message(tmp_path):
    im = Image.new("RGBA", (50, 40), (0, 0, 0, 0))
    im.paste((0, 0, 255, 255), (0, 0, 10, 10))
    p = str(tmp_path / "shot.png")
    im.save(p)
    out = pf.load(p)
    assert out.mode == "RGB"
    assert out.getpixel((40, 30)) == (255, 255, 255)   # transparent -> white
    assert out.getpixel((2, 2)) == (0, 0, 255)
    try:
        import pillow_heif  # noqa: F401
    except ImportError:
        h = tmp_path / "IMG_0001.HEIC"
        h.write_bytes(b"\0\0\0\x18ftypheic")
        with pytest.raises(ValueError, match="pillow-heif"):
            pf.load(str(h))


# ---- encode (AT-n2, privacy) ----------------------------------------------

def test_encode_never_upscales_a_small_photo():
    img = site_photo(600, 450, seed=1)
    rect, box = pf.fit(TOP_LEFT, *img.size)
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    for preset in ("print", "email", "small"):
        out = Image.open(io.BytesIO(pf.encode(img, w, h, preset, box)))
        # print wants 1055 px, the cropped photo has 600 x 398: kept as is
        assert out.width == 600 and out.height <= 450
        assert out.height == pf.target_px(600, 450, w, h, preset, box)[1]
    # small even for the small preset in a big cell: 600 px stays 600 px
    out = Image.open(io.BytesIO(pf.encode(img, 500, 375, "small")))
    assert out.size == (600, 450)


def test_encode_size_per_preset_and_no_exif(tmp_path):
    p = _save(site_photo(4032, 3024, seed=2), tmp_path / "big.jpg",
              taken="2026:10:14 09:30:00", gps=True)
    with Image.open(p) as raw:
        assert raw.getexif().get_ifd(0x8825)            # the source has GPS
    img = pf.load(p)
    rect, box = pf.fit(TOP_LEFT, *img.size)
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    sizes = {}
    for preset in ("print", "email", "small"):
        ppi = pf.PRESETS[preset][0]
        data = pf.encode(img, w, h, preset, box)
        out = Image.open(io.BytesIO(data))
        assert out.format == "JPEG" and out.info.get("progressive")
        assert out.width == round(w / 72 * ppi)             # 1055/791/633
        assert abs(out.width / out.height - w / h) < 0.01
        assert dict(out.getexif()) == {}
        assert b"Exif" not in data[:4096] and b"GPS" not in data
        assert "icc_profile" not in out.info
        sizes[preset] = len(data)
    assert sizes["print"] > sizes["email"] > sizes["small"]
    assert os.path.getsize(p) > sizes["print"]
    # site-photo-like sizes (spec 6n: ~100 KB a photo at email)
    assert 60_000 < sizes["email"] < 160_000
    with pytest.raises(ValueError, match="original"):
        pf.encode(img, w, h, "original")
    with pytest.raises(ValueError):
        pf.encode(img, w, h, "huge")


# ---- estimate (calibrated model) -------------------------------------------

def test_estimate_within_10_percent_of_encode():
    cells = [TOP_LEFT, BOTTOM_LEFT, (9, 65, 262, 317), (9, 65, 200, 180)]
    sources = [(4032, 3024, 11), (3024, 4032, 12), (2016, 1512, 13),
               (1512, 2016, 14), (4000, 2250, 15), (800, 600, 16),
               (600, 450, 17)]
    est = real = 0
    worst = 0.0
    for w, h, seed in sources:
        img = site_photo(w, h, seed=seed)
        for cell in cells:
            rect, box = pf.fit(cell, w, h)
            pw, ph = rect[2] - rect[0], rect[3] - rect[1]
            for preset in ("print", "email", "small"):
                n = len(pf.encode(img, pw, ph, preset, box))
                e = pf.estimate(w, h, pw, ph, preset, box)
                worst = max(worst, abs(e - n) / n)
                est, real = est + e, real + n
    assert worst <= 0.10, f"worst photo off by {worst:.1%}"
    assert abs(est / real - 1) <= 0.05
    # the camera original: ~0.4 bytes a pixel
    assert 4_000_000 < pf.estimate(4032, 3024, 1, 1, "original") < 6_000_000


def test_32_photos_ordering_and_email_budget():
    """AT-n1 photo part: 32 photos in 4-up cells (24 landscape, 8 portrait;
    2016 px sources - the generator is scale-free, so a 12 MP photo lands
    within a few % of these sizes, and is 4x slower to make)."""
    totals = {"original": 0, "print": 0, "email": 0, "small": 0}
    est = 0
    for i in range(32):
        w, h = (2016, 1512) if i % 4 else (1512, 2016)
        img = site_photo(w, h, seed=100 + i)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=92)
        totals["original"] += buf.tell()
        cell = TOP_LEFT if i % 4 < 2 else BOTTOM_LEFT
        rect, box = pf.fit(cell, w, h)
        pw, ph = rect[2] - rect[0], rect[3] - rect[1]
        for preset in ("print", "email", "small"):
            totals[preset] += len(pf.encode(img, pw, ph, preset, box))
        est += pf.estimate(w, h, pw, ph, "email", box)
    assert totals["original"] > totals["print"] > totals["email"] \
        > totals["small"]
    # 19 pages with logs and text add well under 1 MB on top of the photos
    assert totals["email"] <= 4_000_000
    assert abs(est / totals["email"] - 1) <= 0.10


# ---- cache ------------------------------------------------------------------

class _Store:
    def __init__(self, folder):
        self.folder = folder

    def att_dir(self):
        d = os.path.join(self.folder, "att")
        os.makedirs(d, exist_ok=True)
        return d

    def attachment_path(self, ref):
        return os.path.join(self.att_dir(), ref["sha256"] + ref["ext"])


def test_cached_encode_reuses_the_cache(tmp_path):
    store = _Store(str(tmp_path))
    ref = {"sha256": "ab" * 32, "ext": ".jpg"}
    src = _save(site_photo(1200, 900, seed=5), store.attachment_path(ref),
                orientation=6)
    calls = []
    real = pf.encode

    def spy(*a, **k):
        calls.append(a[1:])
        return real(*a, **k)
    pf.encode = spy
    try:
        a = pf.cached_encode(store, ref, 200, 260, "email")
        b = pf.cached_encode(store, ref, 200, 260, "email")
        c = pf.cached_encode(store, ref, 200, 260, "small")
    finally:
        pf.encode = real
    assert a == b and len(calls) == 2 and len(c) < len(a)
    cached = os.listdir(os.path.join(store.att_dir(), "cache"))
    assert len(cached) == 2 and all(n.startswith("ab" * 32) for n in cached)
    assert Image.open(io.BytesIO(a)).size == (417, 556)      # upright
    with open(src, "rb") as f:
        assert pf.cached_encode(store, ref, 200, 260, "original") == f.read()
