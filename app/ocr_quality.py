"""How readable a scanned page is, before anyone trusts the text from it.

Three checks, each usable on its own:

* per-page confidence from Tesseract's TSV output
* the scan's DPI, and a skew estimate, from the image
* which Tesseract language packs are installed

`assess` puts them together and returns flags for a poor scan, each with
a plain-language reason. This module does not run OCR and does not
change the image. Confidence numbers are Tesseract's own 0-100 scores,
averaged over the words on the page.

DPI below is dots per inch. A scan under 200 DPI is flagged. 300 DPI is
the figure to scan at. A tilt of 2 degrees or more is flagged. The skew
estimate only looks within 12 degrees of level; a worse tilt is reported
as at least 12. Positive skew means the lines run up toward the right
(the ink is rotated counter-clockwise). Zero is level.
"""
import os
import re
import subprocess

# Same optional-import pattern as autocount and autotakeoff: a PC without
# OpenCV can still import this module. Functions that measure a scan say
# so in plain language instead of dying with a missing name.
try:
    import cv2
except ImportError:
    cv2 = None
try:
    import numpy as np
except ImportError:
    np = None
try:
    from PIL import Image
except ImportError:
    Image = None

POOR_CONFIDENCE = 70        # mean word score under this is a poor scan
LOW_WORD_CONFIDENCE = 50    # a single word this low is mentioned in the reason
POOR_DPI = 200
TARGET_DPI = 300
POOR_SKEW_DEGREES = 2.0
MAX_SKEW_DEGREES = 12.0
INK_TOO_LOW = 0.002         # share of dark pixels: blank below this
INK_TOO_HIGH = 0.90         # solid black above this

_HEADER = ["level", "page_num", "block_num", "par_num", "line_num",
           "word_num", "left", "top", "width", "height", "conf", "text"]
_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
# Names for the packs a drawing set is likely to need. Anything else is
# shown as the pack code Tesseract uses.
_LANG_NAMES = {
    "eng": "English",
    "spa": "Spanish",
    "fra": "French",
    "deu": "German",
    "por": "Portuguese",
    "ita": "Italian",
    "nld": "Dutch",
    "pol": "Polish",
    "rus": "Russian",
    "chi_sim": "Chinese (simplified)",
    "chi_tra": "Chinese (traditional)",
    "jpn": "Japanese",
    "kor": "Korean",
    "ara": "Arabic",
    "vie": "Vietnamese",
}

__all__ = [
    "POOR_CONFIDENCE",
    "LOW_WORD_CONFIDENCE",
    "POOR_DPI",
    "TARGET_DPI",
    "POOR_SKEW_DEGREES",
    "TSVError",
    "ScanError",
    "Flag",
    "PageScore",
    "ImageCheck",
    "PageReport",
    "LanguagePacks",
    "page_confidence",
    "check_image",
    "image_dpi",
    "estimate_skew_degrees",
    "installed_languages",
    "parse_list_langs",
    "language_flags",
    "assess",
]


class TSVError(ValueError):
    """The text is not Tesseract TSV."""


class ScanError(ValueError):
    """The scan image could not be read."""


class Flag:
    """One reason a scan is poor. `severity` is always 'poor'."""

    def __init__(self, code, reason):
        self.code = code
        self.severity = "poor"
        self.reason = reason

    def __eq__(self, other):
        if not isinstance(other, Flag):
            return NotImplemented
        return (self.code, self.reason) == (other.code, other.reason)

    def __repr__(self):
        return f"Flag({self.code})"


class PageScore:
    """Confidence for one page. `page` is Tesseract's number, starting at 1.

    `mean_confidence` is None when no words were read. `flags` is empty
    when the words that were read scored well enough.
    """

    def __init__(self, page, mean_confidence, word_count, low_word_count,
                 flags):
        self.page = page
        self.mean_confidence = mean_confidence
        self.word_count = word_count
        self.low_word_count = low_word_count
        self.flags = tuple(flags)

    @property
    def poor(self):
        return bool(self.flags)

    def __repr__(self):
        return f"PageScore(page {self.page}, {self.mean_confidence})"


class ImageCheck:
    """DPI and skew for one image. `dpi` and `skew_degrees` are None when
    they could not be measured. `flags` is empty when nothing looks poor."""

    def __init__(self, dpi, skew_degrees, flags):
        self.dpi = dpi
        self.skew_degrees = skew_degrees
        self.flags = tuple(flags)

    @property
    def poor(self):
        return bool(self.flags)

    def __repr__(self):
        return f"ImageCheck({self.dpi} DPI, skew {self.skew_degrees})"


class PageReport:
    """One page after every check that was asked for.

    `dpi` and `skew_degrees` stay None when no image or DPI was given.
    `flags` lists every problem found, confidence first, then the scan,
    then the language pack. Empty means nothing looked poor.
    """

    def __init__(self, page, mean_confidence, word_count, low_word_count,
                 dpi, skew_degrees, flags):
        self.page = page
        self.mean_confidence = mean_confidence
        self.word_count = word_count
        self.low_word_count = low_word_count
        self.dpi = dpi
        self.skew_degrees = skew_degrees
        self.flags = tuple(flags)

    @property
    def poor(self):
        return bool(self.flags)

    def __repr__(self):
        return f"PageReport(page {self.page}, {len(self.flags)} flags)"


class LanguagePacks:
    """Packs `tesseract --list-langs` reported.

    `tesseract_found` is False when the program itself is not installed
    (different from a program that is installed but has no packs).
    `codes` is sorted, like 'eng' and 'spa'.
    """

    def __init__(self, codes, tesseract_found):
        self.codes = tuple(codes)
        self.tesseract_found = bool(tesseract_found)

    def __repr__(self):
        return f"LanguagePacks({', '.join(self.codes) or 'none'})"


def page_confidence(tsv):
    """One PageScore per page in Tesseract TSV text.

    Word rows (level 5) with a score of 0 or more and some text are the
    only rows that count. A page that appears but has no such words is
    returned with a flag. Pages come out in page-number order. An empty
    string is no pages. A missing header raises TSVError.
    """
    if not isinstance(tsv, str):
        raise TSVError("Tesseract TSV has to be text.")
    lines = tsv.lstrip("\ufeff").splitlines()
    while lines and not lines[0].strip():
        del lines[0]
    if not lines:
        return []
    header = [part.strip().lower() for part in lines[0].split("\t")]
    if header[:len(_HEADER)] != _HEADER:
        raise TSVError("This isn't Tesseract TSV: the header row is missing.")
    pages = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        try:
            level = int(cols[0])
            page = int(cols[1])
            conf = float(cols[10])
        except ValueError:
            continue
        bucket = pages.get(page)
        if bucket is None:
            bucket = {"confs": [], "low": 0}
            pages[page] = bucket
        if level != 5 or conf < 0:
            continue
        if not cols[11].strip():
            continue
        bucket["confs"].append(conf)
        if conf < LOW_WORD_CONFIDENCE:
            bucket["low"] += 1
    scores = []
    for page in sorted(pages):
        confs = pages[page]["confs"]
        low = pages[page]["low"]
        if not confs:
            mean = None
            flag = _no_words_flag()
        else:
            mean = sum(confs) / len(confs)
            flag = _low_confidence_flag(mean, len(confs), low)
        flags = () if flag is None else (flag,)
        scores.append(PageScore(page, mean, len(confs), low, flags))
    return scores


def check_image(image, dpi=None):
    """DPI, skew, and poor-scan flags for one image.

    `image` is a file path, a Pillow image, or a grayscale or RGB array
    (Pillow channel order). `dpi`, when passed, is the number to judge;
    the number stored on the file is used only when `dpi` is omitted.
    An array has no DPI stored on it.
    """
    _need_opencv()
    gray, stored = _load(image)
    fraction = _ink_fraction(gray)
    skew = None
    if INK_TOO_LOW <= fraction <= INK_TOO_HIGH:
        skew = _skew_of(gray)
    use_dpi = _clean_dpi(dpi, strict=True) if dpi is not None else stored
    flags = list(_dpi_flags(use_dpi))
    if fraction < INK_TOO_LOW:
        flags.append(Flag(
            "blank_scan",
            "This scan looks blank, so there is nothing to read."))
    elif fraction > INK_TOO_HIGH:
        flags.append(Flag(
            "solid_scan",
            "This scan is nearly solid black, so the words aren't "
            "visible. Scan it again with the sheet lit evenly."))
    flags.extend(_skew_flags(skew))
    return ImageCheck(use_dpi, skew, flags)


def image_dpi(image):
    """DPI stored on a path or a Pillow image, or None.

    When the two directions differ, the lower one is returned (that is
    the one that limits the read). An array has no DPI stored on it.
    """
    _gray, stored = _load(image)
    return stored


def estimate_skew_degrees(image):
    """Degrees the ink is tilted, or None if tilt can't be measured.

    See the module note for the sign and the 12-degree limit. None means
    the picture is blank, solid, or otherwise has nothing to measure.
    """
    _need_opencv()
    gray, _stored = _load(image)
    fraction = _ink_fraction(gray)
    if fraction < INK_TOO_LOW or fraction > INK_TOO_HIGH:
        return None
    return _skew_of(gray)


def installed_languages(runner=None):
    """Language packs on this PC.

    `runner`, when passed, is called with no arguments and must return
    the text `tesseract --list-langs` prints. Tests pass made-up text.
    Without it, the installed program is asked (the same search the OCR
    command uses). An empty result with `tesseract_found` False means
    the program is not there.
    """
    if runner is not None:
        text = runner()
        if not isinstance(text, str):
            raise TypeError("runner must return the language list as text.")
        return LanguagePacks(parse_list_langs(text), True)
    from .ocr import find_tesseract
    exe = find_tesseract()
    if not exe:
        return LanguagePacks((), False)
    try:
        # no console flash on Windows; 0 elsewhere, where the flag is ignored
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run([exe, "--list-langs"], capture_output=True,
                             timeout=30, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired):
        return LanguagePacks((), True)
    # Tesseract prints this list on stderr. Keep stdout too, in case a
    # build puts it there instead.
    text = "\n".join(part.decode("utf-8", "ignore")
                     for part in (out.stdout, out.stderr))
    return LanguagePacks(parse_list_langs(text), True)


def parse_list_langs(text):
    """Pack codes from `tesseract --list-langs` output, sorted.

    The header line and any error line are ignored. The list is made up
    by the caller in tests; this only parses it.
    """
    if not isinstance(text, str):
        raise TypeError("language list has to be text.")
    found = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or any(ch in line for ch in " :/"):
            continue
        if _CODE.fullmatch(line):
            found.add(line.lower())
    return sorted(found)


def language_flags(languages, needed="eng"):
    """Flags when `needed` packs are not among `languages`.

    `languages` is a list of codes, or a LanguagePacks from
    `installed_languages`. `needed` is one code or several joined with
    '+' or ',' (the way Tesseract is given them), default 'eng'. An
    empty `needed` checks nothing. Pass LanguagePacks with
    `tesseract_found` False to get the not-installed flag; a plain empty
    list means the program was found but has no packs.
    """
    if isinstance(languages, LanguagePacks) and not languages.tesseract_found:
        return (Flag(
            "no_tesseract",
            "Tesseract OCR is not installed, so this page can't be read. "
            "Install Tesseract, including the English language pack, "
            "and try again."),)
    have = _pack_codes(languages)
    missing = [code for code in _needed_codes(needed) if code not in set(have)]
    if not missing:
        return ()
    installed = ", ".join(have) if have else "none"
    if len(missing) == 1:
        reason = (f"The {_friendly(missing[0])} language pack is not "
                  f"installed, so those words can't be read. "
                  f"Installed packs: {installed}.")
    else:
        names = ", ".join(_friendly(code) for code in missing)
        reason = (f"These language packs are not installed: {names}. "
                  f"Installed packs: {installed}.")
    return (Flag("missing_language", reason),)


def assess(tsv, image=None, dpi=None, languages=None, needed="eng"):
    """Confidence for each page, plus whatever else is passed in.

    `image` is allowed only when the TSV is a single page: pass each
    page's own image. `dpi` (a number) is used when the image has none,
    or on its own when the caller already measured it, and then it
    applies to every page. `languages` is the list or LanguagePacks from
    `installed_languages`; omit it to skip the language-pack check.
    None and an empty list are different: None skips the check, and an
    empty list means no packs are installed.
    """
    scores = page_confidence(tsv)
    image_check = None
    if image is not None:
        if len(scores) != 1:
            raise ValueError(
                "Pass one page's image at a time (this TSV has "
                f"{len(scores)} pages).")
        image_check = check_image(image, dpi=dpi)
    explicit_dpi = None
    dpi_flags = ()
    if image_check is None and dpi is not None:
        explicit_dpi = _clean_dpi(dpi, strict=True)
        dpi_flags = tuple(_dpi_flags(explicit_dpi))
    lang_flags = ()
    if languages is not None:
        lang_flags = language_flags(languages, needed)
    reports = []
    for score in scores:
        flags = list(score.flags)
        page_dpi = None
        page_skew = None
        if image_check is not None:
            flags.extend(image_check.flags)
            page_dpi = image_check.dpi
            page_skew = image_check.skew_degrees
        else:
            flags.extend(dpi_flags)
            page_dpi = explicit_dpi
        flags.extend(lang_flags)
        reports.append(PageReport(
            score.page, score.mean_confidence, score.word_count,
            score.low_word_count, page_dpi, page_skew, flags))
    return reports


def _no_words_flag():
    return Flag(
        "no_words",
        "No words were read on this page. It may be blank, or the scan "
        f"is too faint to read. Scan it again at {TARGET_DPI} DPI.")


def _low_confidence_flag(mean, words, low):
    if mean >= POOR_CONFIDENCE:
        return None
    if low == 1:
        detail = f", and 1 of {words} words was under {LOW_WORD_CONFIDENCE}"
    elif low:
        detail = (f", and {low} of {words} words were under "
                  f"{LOW_WORD_CONFIDENCE}")
    else:
        detail = ""
    return Flag(
        "low_confidence",
        f"This page read at {mean:.1f} out of 100{detail}. "
        f"That's too unclear to trust. Scan the sheet again at "
        f"{TARGET_DPI} DPI, lying flat, with the light even.")


def _dpi_flags(dpi):
    if dpi is None:
        return [Flag(
            "no_dpi",
            "This scan doesn't say how fine it is (no dots per inch are "
            f"stored). Text on a scan like that is unreliable. Scan it "
            f"again at {TARGET_DPI} DPI.")]
    if dpi < POOR_DPI:
        return [Flag(
            "low_dpi",
            f"This scan is {dpi:g} DPI (dots per inch). That's too coarse "
            f"for small drawing text. Scan it again at {TARGET_DPI} DPI.")]
    return []


def _skew_flags(angle):
    if angle is None or abs(angle) < POOR_SKEW_DEGREES:
        return []
    if abs(angle) >= MAX_SKEW_DEGREES - 0.05:
        how = f"at least {MAX_SKEW_DEGREES:.0f}"
    else:
        how = f"about {abs(angle):.1f}"
    return [Flag(
        "skew",
        f"This page is tilted by {how} degrees. Lay the sheet flat and "
        "scan it again, or the words will be read wrong.")]


def _friendly(code):
    name = _LANG_NAMES.get(code)
    if name:
        return f"{name} ({code})"
    return code


def _needed_codes(needed):
    if not isinstance(needed, str):
        raise TypeError("needed is a language pack name, like 'eng'.")
    return [part.strip().lower()
            for part in re.split(r"[+,]", needed) if part.strip()]


def _pack_codes(languages):
    if isinstance(languages, LanguagePacks):
        return list(languages.codes)
    if isinstance(languages, (str, bytes)):
        raise TypeError(
            "languages is a list of pack names, or the LanguagePacks "
            "from installed_languages().")
    try:
        codes = [str(code).strip().lower() for code in languages]
    except TypeError:
        raise TypeError(
            "languages is a list of pack names, or the LanguagePacks "
            "from installed_languages().") from None
    return codes


def _missing_library(name):
    raise ScanError(
        f"{name} isn't installed on this PC, so this scan can't be checked.")


def _need_opencv():
    if cv2 is None:
        _missing_library("OpenCV")
    if np is None:
        _missing_library("numpy")


def _need_pillow():
    if Image is None:
        _missing_library("Pillow")
    if np is None:
        _missing_library("numpy")


def _load(image):
    """(gray uint8 array, dpi or None). Closes a file it opened itself."""
    _need_pillow()
    if isinstance(image, np.ndarray):
        return _gray_array(image), None
    pil, close = _open_pil(image)
    try:
        dpi = _dpi_from_pil(pil)
        gray = np.asarray(pil.convert("L"))
        if gray.dtype != np.uint8:
            gray = np.clip(gray, 0, 255).astype(np.uint8)
        if gray.size == 0:
            raise ScanError("The scan image is empty.")
        return gray, dpi
    finally:
        if close:
            pil.close()


def _open_pil(image):
    if isinstance(image, Image.Image):
        return image, False
    try:
        path = os.fspath(image)
    except TypeError:
        raise ScanError(
            "The scan has to be a file path, a Pillow image, or an array."
        ) from None
    try:
        opened = Image.open(path)
        opened.load()
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise ScanError(f"Can't read this scan: {path}") from e
    return opened, True


def _dpi_from_pil(pil):
    info = getattr(pil, "info", None) or {}
    dpi = info.get("dpi")
    if not dpi:
        return None
    try:
        values = [float(v) for v in dpi]
    except (TypeError, ValueError):
        return None
    values = [v for v in values if v > 0]
    if not values:
        return None
    return _clean_dpi(min(values), strict=False)


def _clean_dpi(value, strict):
    if isinstance(value, bool):
        if strict:
            raise ScanError("DPI has to be a number.")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        if strict:
            raise ScanError("DPI has to be a number.")
        return None
    if number != number or number in (float("inf"), float("-inf")):
        if strict:
            raise ScanError("DPI has to be a number.")
        return None
    if number <= 0 or number > 10000:
        if strict:
            raise ScanError(
                "DPI has to be between 1 and 10000 "
                f"(got {number:g}).")
        return None
    nearest = round(number)
    if abs(number - nearest) <= 0.6:
        return float(nearest)
    return round(number, 1)


def _gray_array(arr):
    if np is None:
        _missing_library("numpy")
    if arr.ndim == 2:
        gray = arr
    elif arr.ndim == 3 and arr.shape[2] in (3, 4):
        if cv2 is None:
            _missing_library("OpenCV")
        rgb = arr[:, :, :3]
        if rgb.dtype != np.uint8:
            rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    else:
        raise ScanError(
            "The scan image has to be a grayscale or color picture.")
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    if gray.size == 0:
        raise ScanError("The scan image is empty.")
    return np.ascontiguousarray(gray)


def _ink_fraction(gray):
    if gray.size == 0:
        return 0.0
    return float((gray < 180).mean())


def _skew_of(gray):
    """Tilt in degrees. The caller has already rejected blank and solid."""
    _need_opencv()
    small = _downscale(gray)
    mask = _ink_mask(small)
    if mask is None:
        return None
    coarse = [index * 0.5 for index in range(-24, 25)]
    best = max(coarse, key=lambda angle: _projection_score(mask, angle))
    fine = []
    step = round(max(-MAX_SKEW_DEGREES, best - 0.5), 1)
    stop = min(MAX_SKEW_DEGREES, best + 0.5)
    while step <= stop + 1e-9:
        fine.append(round(step, 1))
        step = round(step + 0.1, 1)
    correction = max(fine, key=lambda angle: _projection_score(mask, angle))
    # `correction` is the counter-clockwise rotation that levels the
    # lines. The tilt of the page is the opposite of that.
    tilt = round(-correction, 1)
    if abs(tilt) < 0.05:
        return 0.0
    return tilt


def _downscale(gray):
    height, width = gray.shape[:2]
    long_side = max(height, width)
    if long_side <= 800:
        return gray
    scale = 800 / long_side
    size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return cv2.resize(gray, size, interpolation=cv2.INTER_AREA)


def _ink_mask(gray):
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _threshold, mask = cv2.threshold(
        blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if int(mask.max()) == 0:
        return None
    return mask


def _projection_score(mask, angle):
    height, width = mask.shape
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, 1.0)
    rotated = cv2.warpAffine(mask, matrix, (width, height),
                             flags=cv2.INTER_NEAREST, borderValue=0)
    projection = rotated.sum(axis=1, dtype=np.float64)
    return float(projection.var())
