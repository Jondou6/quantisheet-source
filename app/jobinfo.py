"""Job info: a description, a website (or owner / contact link), the job
ZIP and an optional project image, saved in the PDF with the proposal
details (quantisheet_proposal.json; the image is its own embedded file).

The job ZIP picks the job's location region from your Location Factors
table (locfactors.py) unless a region was picked for the job by hand.
The image (PNG or JPG, at most 10 MB) and the description go on the
proposal's cover page.
"""
import logging
import os

from . import embfiles

log = logging.getLogger(__name__)

IMAGE_FILE = "quantisheet_job_image"
MAX_IMAGE = 10 * 1024 * 1024
FIELDS = ("description", "website", "job_zip", "location_region",
          "image_name")


class ImageError(ValueError):
    pass


def _proposal():
    from . import proposal
    return proposal


def read(doc):
    """{"description", "website", "job_zip", "location_region",
    "image_name", "has_image"} for the job."""
    data = _proposal().read(doc)
    out = {k: str(data.get(k) or "") for k in FIELDS}
    out["has_image"] = bool(image_bytes(doc))
    return out


def write(doc, **values):
    """Save some of the job info fields with the proposal details."""
    prop = _proposal()
    data = prop.read(doc)
    for k, v in values.items():
        if k in FIELDS:
            data[k] = "" if v is None else str(v).strip() \
                if k != "description" else str(v).rstrip()
    if "job_zip" in values:
        data["job_zip"] = clean_zip(values["job_zip"])
    prop.write(doc, data)
    return data


def clean_zip(z):
    """'99903', '99903-1234' -> '99903'; other text as typed (trimmed)."""
    t = str(z or "").strip()
    head = t.split("-")[0].strip()
    return head if head.isdigit() and len(head) == 5 else t


def _kind(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    return ""


def check_image(path):
    """Raise ImageError (with the message to show) when the file can't be
    the project image: missing, over 10 MB, or not a PNG / JPG."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise ImageError(f"Can't read {os.path.basename(str(path))}: {e}")
    if size > MAX_IMAGE:
        raise ImageError(
            f"{os.path.basename(path)} is {size / (1024 * 1024):.1f} MB; "
            "the project image can be at most 10 MB. Pick a smaller image "
            "(or save it smaller) - nothing was added.")
    with open(path, "rb") as f:
        head = f.read(16)
    if not _kind(head):
        raise ImageError(f"{os.path.basename(path)} isn't a PNG or JPG "
                         "image - nothing was added.")
    return size


def set_image(doc, path):
    """Embed the project image (checked first: nothing is embedded when
    it's refused). Returns its size in bytes."""
    check_image(path)
    with open(path, "rb") as f:
        data = f.read()
    if len(data) > MAX_IMAGE or not _kind(data):        # changed meanwhile
        raise ImageError(f"{os.path.basename(path)} can't be used - "
                         "nothing was added.")
    embfiles.put(doc, IMAGE_FILE, data, "QuantiSheet project image")
    write(doc, image_name=os.path.basename(path))
    return len(data)


def clear_image(doc):
    """No project image (the embedded file is emptied)."""
    if IMAGE_FILE in embfiles.names(doc):
        embfiles.put(doc, IMAGE_FILE, b"", "QuantiSheet project image")
    write(doc, image_name="")


def image_bytes(doc):
    """The project image's bytes, or None."""
    try:
        if IMAGE_FILE not in embfiles.names(doc):
            return None
        data = bytes(embfiles.get(doc, IMAGE_FILE))
    except Exception:
        log.warning("could not read the project image", exc_info=True)
        return None
    return data if data and _kind(data) else None


def zip_region(zip_code):
    """The Location Factors region of a ZIP, or None."""
    z = clean_zip(zip_code)
    if not (z.isdigit() and len(z) == 5):
        return None
    from . import locfactors
    row = locfactors.find_region(z)
    return row["region"] if row else None


def region(doc, data=None):
    """The job's location region: picked by hand, else from the job ZIP,
    else the job's cost book region; None when there's none."""
    data = data if data is not None else _proposal().read(doc)
    picked = str(data.get("location_region") or "").strip()
    if picked:
        return picked
    r = zip_region(data.get("job_zip"))
    if r:
        return r
    try:
        from . import assemblies
        cb = assemblies.read_job(doc).get("costbook") or {}
        return cb.get("region") or None
    except Exception:
        return None


def region_source(doc, data=None):
    """(region, how): how is "picked", "zip" or "cost book" ("" if none)."""
    data = data if data is not None else _proposal().read(doc)
    if str(data.get("location_region") or "").strip():
        return data["location_region"].strip(), "picked"
    r = zip_region(data.get("job_zip"))
    if r:
        return r, "zip"
    r = region(doc, data)
    return (r, "cost book") if r else (None, "")
