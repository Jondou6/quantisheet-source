"""Photos for the Weekly Owner Report: load them upright, fit them in a
cell (fill or contain), and re-encode them at the size they print so a
32-photo report stays small enough to email.

Pure Pillow - no PyMuPDF here. Coordinates are PDF points (1/72 in),
(x0, y0, x1, y1) with y down, as fitz.Rect uses them. A src_box is the part
of the (upright) image to use, as fractions 0-1 of its width and height.

PRESETS: name -> (ppi, JPEG quality); "original" (None) means the caller
embeds the uploaded file's bytes untouched (no re-encode, EXIF kept).
"""
import io
import os
from datetime import datetime

PRESETS = {"original": None, "print": (200, 85), "email": (150, 75),
           "small": (120, 65)}

_HEIC = (".heic", ".heif")
_TAG_DATETIME = 0x0132           # IFD0 DateTime (last edit / camera clock)
_TAG_ORIGINAL = 0x9003           # Exif IFD DateTimeOriginal (shutter)
_EXIF_IFD = 0x8769


def _heif():
    """Register the HEIC opener if pillow-heif is installed."""
    try:
        import pillow_heif
    except ImportError:
        return False
    pillow_heif.register_heif_opener()
    return True


def _open(path):
    from PIL import Image
    if os.path.splitext(path)[1].lower() in _HEIC and not _heif():
        raise ValueError(
            f"Can't read '{os.path.basename(path)}': iPhone HEIC photos "
            "need the pillow-heif package. Save the photo as JPEG, or "
            "install pillow-heif.")
    return Image.open(path)


def load(path):
    """The photo upright (EXIF orientation applied) as an RGB image.
    Transparent areas (PNG screenshots) go on white."""
    from PIL import Image, ImageOps
    with _open(path) as im:
        im.load()
        img = ImageOps.exif_transpose(im)
    if img.mode in ("RGBA", "LA", "PA") or (
            img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.getchannel("A"))
        return bg
    return img.convert("RGB") if img.mode != "RGB" else img


def upright_size(path):
    """(w, h) of the photo as load() returns it, read from the header
    only (EXIF orientations 5-8 swap width and height)."""
    with _open(path) as im:
        w, h = im.size
        if im.getexif().get(0x0112) in (5, 6, 7, 8):
            w, h = h, w
    return w, h


def _parse_exif_date(v):
    if isinstance(v, bytes):
        v = v.decode("ascii", "ignore")
    v = (v or "").strip().rstrip("\x00").strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d"):
        try:
            return datetime.strptime(v[:19], fmt)
        except ValueError:
            continue
    return None


def exif_taken(path):
    """When the photo was taken: (datetime, "exif") from DateTimeOriginal,
    else IFD0 DateTime; otherwise (file modified time, "file") - the
    caption then says "(file date)". (None, "file") if the file is gone."""
    try:
        with _open(path) as im:
            ex = im.getexif()
            for v in (ex.get_ifd(_EXIF_IFD).get(_TAG_ORIGINAL),
                      ex.get(_TAG_ORIGINAL), ex.get(_TAG_DATETIME)):
                dt = _parse_exif_date(v) if v else None
                if dt:
                    return dt, "exif"
    except Exception:                    # not an image / no EXIF reader
        pass
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)), "file"
    except OSError:
        return None, "file"


def _contain(cell, aw, ah):
    x0, y0, x1, y1 = cell
    cw, ch = x1 - x0, y1 - y0
    s = min(cw / aw, ch / ah)
    w, h = aw * s, ah * s
    cx, cy = x0 + (cw - w) / 2, y0 + (ch - h) / 2
    return (cx, cy, cx + w, cy + h)


def _fill_box(ia, ca):
    """Centre crop (fractions) of an image of aspect ia to aspect ca."""
    if ia > ca:                          # image wider: trim the sides
        f = ca / ia
        return ((1 - f) / 2, 0.0, (1 + f) / 2, 1.0)
    f = ia / ca                          # image taller: trim top/bottom
    return (0.0, (1 - f) / 2, 1.0, (1 + f) / 2)


def fit(cell, iw, ih, mode="auto", max_crop=0.12, crop=None):
    """Where a photo of iw x ih pixels goes in cell -> (rect, src_box).

    auto: c = 1 - min(ia, ca) / max(ia, ca) (ia image aspect, ca cell
    aspect). c <= max_crop -> fill: centre-crop to the cell aspect,
    rect == cell. Else contain: whole photo, centred, rect hugs it.
    "fill" / "contain" force that mode. crop = the user's own rectangle
    (fractions of the image) - it replaces the automatic centre crop: that
    part of the photo is placed whole (contained, centred) in the cell, so
    the user's framing is never cut further."""
    x0, y0, x1, y1 = cell
    cw, ch = x1 - x0, y1 - y0
    if iw <= 0 or ih <= 0 or cw <= 0 or ch <= 0:
        raise ValueError("fit() needs a non-empty image and cell.")
    if crop is not None:
        cx0, cy0, cx1, cy1 = (min(max(float(v), 0.0), 1.0) for v in crop)
        if cx1 - cx0 <= 0 or cy1 - cy0 <= 0:
            raise ValueError("The crop rectangle is empty.")
        aw, ah = iw * (cx1 - cx0), ih * (cy1 - cy0)
        return _contain(cell, aw, ah), (cx0, cy0, cx1, cy1)
    ia, ca = iw / ih, cw / ch
    if mode == "auto":
        c = 1 - min(ia, ca) / max(ia, ca)
        mode = "fill" if c <= max_crop else "contain"
    if mode == "fill":
        return (x0, y0, x1, y1), _fill_box(ia, ca)
    if mode == "contain":
        return _contain(cell, iw, ih), (0.0, 0.0, 1.0, 1.0)
    raise ValueError(f"Unknown fit mode '{mode}' (auto, fill, contain).")


def _preset(preset):
    if preset not in PRESETS:
        raise ValueError(f"Unknown photo size '{preset}' "
                         f"({', '.join(PRESETS)}).")
    return PRESETS[preset]


def _box_px(iw, ih, src_box):
    bx0, by0, bx1, by1 = src_box
    l, t = round(bx0 * iw), round(by0 * ih)
    r, b = round(bx1 * iw), round(by1 * ih)
    r, b = max(r, l + 1), max(b, t + 1)
    return (l, t, min(r, iw), min(b, ih))


def target_px(iw, ih, w_pt, h_pt, preset, src_box=(0, 0, 1, 1)):
    """Pixel size encode() writes: the printed size at the preset's ppi,
    never more than the source pixels of src_box (no upscaling)."""
    ppi, _q = _preset(preset) or (None, None)
    l, t, r, b = _box_px(iw, ih, src_box)
    sw, sh = r - l, b - t
    if ppi is None:
        return sw, sh
    tw, th = w_pt / 72 * ppi, h_pt / 72 * ppi
    s = min(1.0, max(tw / sw, th / sh))
    return max(1, round(sw * s)), max(1, round(sh * s))


def encode(img, w_pt, h_pt, preset, src_box=(0, 0, 1, 1)):
    """JPEG bytes of src_box of img for a w_pt x h_pt rect at the preset's
    ppi/quality: LANCZOS downscale only (a small photo keeps its pixels),
    progressive, optimized, 4:2:0, no EXIF/XMP/ICC/comment (GPS privacy).
    "original" is not re-encoded - the caller embeds the file's bytes."""
    p = _preset(preset)
    if p is None:
        raise ValueError("'original' isn't re-encoded: embed the file's "
                         "own bytes (cached_encode does).")
    from PIL import Image
    ppi, q = p
    if img.mode != "RGB":
        img = img.convert("RGB")
    box = _box_px(img.width, img.height, src_box)
    out = img.crop(box) if box != (0, 0, img.width, img.height) else img
    tw, th = target_px(img.width, img.height, w_pt, h_pt, preset, src_box)
    if (tw, th) != out.size:
        out = out.resize((tw, th), Image.LANCZOS)
    else:
        out = out.copy()
    out.info = {}                        # nothing of the source's metadata
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=q, optimize=True, progressive=True,
             subsampling=2, exif=b"")
    return buf.getvalue()


# estimate(): bytes = HEADER + px * RATE[preset] * px**EXP * down**DOWN
#   px   = output pixels (target_px)
#   down = source pixels of src_box / px, capped at DOWN_CAP: a photo
#          shrunk a lot packs more detail into each output pixel; one
#          printed at its own size (no upscaling) costs less per pixel.
# Fitted (least squares on log bytes/px) against encode() on 144 encodes
# of synthetic site photos made to compress like real ones (random
# structure at every octave of the frame, colour in the coarse octaves,
# gravel/rebar texture in the fine ones, light grain; see site_photo() in
# tests/test_photofit.py): 12 sources 600x450 .. 4032x3024, both
# orientations and 16:9, four cell sizes, three presets. On these a 12 MP
# photo in a 4-up cell is ~95 KB at "email" and ~4.8 MB as a q92 camera
# file - the per-photo figures the spec measured on real site photos.
# Fit: rms 3 %, worst 7 %; on fresh test photos worst < 10 %, total
# within 3 %. Real photos vary more one by one (blue sky vs. gravel
# close-up, +/-30 %); a report's 20-40 photos average much of that out,
# but a job's photos can be busier or plainer than these overall - check
# against a real export before trusting the last 10 %.
# "original" models a camera JPEG (~0.40 bytes/px); callers should use
# the file's real size instead.
HEADER = 620
RATE = {"print": 0.6915, "email": 0.5131, "small": 0.4223}
EXP = -0.0663
DOWN, DOWN_CAP = 0.0332, 4.0
ORIGINAL_BPP = 0.40


def estimate(iw, ih, w_pt, h_pt, preset, src_box=(0, 0, 1, 1)):
    """Cheap guess of len(encode(...)) without encoding (int bytes)."""
    if _preset(preset) is None:
        return int(iw * ih * ORIGINAL_BPP)
    tw, th = target_px(iw, ih, w_pt, h_pt, preset, src_box)
    l, t, r, b = _box_px(iw, ih, src_box)
    px = tw * th
    down = min(DOWN_CAP, (r - l) * (b - t) / px)
    return int(HEADER + px * RATE[preset] * px ** EXP * down ** DOWN)


def cached_encode(store, ref, w_pt, h_pt, preset, src_box=(0, 0, 1, 1)):
    """encode() for a store attachment, cached on disk in
    att_dir()/cache by (sha256, pixel size, src_box, preset).
    "original" returns the attachment's own bytes unchanged."""
    path = store.attachment_path(ref)
    if _preset(preset) is None:
        with open(path, "rb") as f:
            return f.read()
    cache = os.path.join(store.att_dir(), "cache")
    box = "-".join(f"{v:.4f}" for v in src_box)
    size = upright_size(path)            # header only - no decode
    tw, th = target_px(size[0], size[1], w_pt, h_pt, preset, src_box)
    key = f"{ref['sha256']}_{tw}x{th}_{box}_{preset}.jpg"
    hit = os.path.join(cache, key)
    if os.path.exists(hit):
        with open(hit, "rb") as f:
            return f.read()
    data = encode(load(path), w_pt, h_pt, preset, src_box)
    os.makedirs(cache, exist_ok=True)
    tmp = hit + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, hit)
    return data
