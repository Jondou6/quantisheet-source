"""PM review NW-16: damage photos on a claim - attached to the claim or a
line, kept on save/reload (hash-checked), printed with captions and dates
(made-up claim and made-up images)."""
import os

from quantisheet_claims import model as m
from quantisheet_claims import photos, store
from quantisheet_claims.export import build_model, to_pdf
from .helpers import t1_claim


def _png(path, rgb):
    from PIL import Image
    Image.new("RGB", (64, 48), rgb).save(path)
    return str(path)


def test_three_photos_saved_reloaded_and_printed(tmp_path):
    folder = str(tmp_path / "claims")
    os.makedirs(folder)
    c = t1_claim()
    srcs = [_png(tmp_path / f"p{i}.png", (60 * i, 90, 120)) for i in (1, 2, 3)]
    c = photos.add(c, srcs[0], "Ceiling stain", folder=folder)
    c = photos.add(c, srcs[1], "Wet drywall", line_id="L1", folder=folder)
    c = photos.add(c, srcs[2], "", folder=folder)
    assert len(c.photos) == 3
    p = store.save(c, folder=folder)
    back, _r = store.load(p)
    assert [x.sha256 for x in back.photos] == [x.sha256 for x in c.photos]
    assert photos.verify(back, folder) == []
    assert photos.where(back, back.photos[1]).startswith("Line ")
    assert back.photos[0].taken            # a date (file date: no EXIF)
    out = to_pdf(build_model(back, photo_folder=folder),
                 str(tmp_path / "claim.pdf"))
    import pymupdf as fitz
    d = fitz.open(out)
    text = "".join(pg.get_text() for pg in d)
    assert "Photo 1: Ceiling stain" in text and "Photo 3: p3.png" in text
    assert "Taken " in text
    assert sum(len(pg.get_images()) for pg in d) == 3


def test_changed_or_missing_photo_is_reported(tmp_path):
    folder = str(tmp_path / "claims")
    os.makedirs(folder)
    c = photos.add(t1_claim(), _png(tmp_path / "a.png", (1, 2, 3)), "A",
                   folder=folder)
    f = photos.path_of(c, c.photos[0], folder)
    with open(f, "ab") as fh:
        fh.write(b"x")
    assert "changed" in photos.verify(c, folder)[0]
    os.remove(f)
    assert "missing" in photos.verify(c, folder)[0]
    assert photos.for_export(c, folder) == ()


def test_not_a_photo_refused(tmp_path):
    t = tmp_path / "notes.txt"
    t.write_text("x")
    try:
        photos.add(t1_claim(), str(t), folder=str(tmp_path))
    except ValueError as e:
        assert "not a photo" in str(e)
    else:
        raise AssertionError("refused")


def test_old_claim_without_photos_loads(tmp_path):
    c = t1_claim()
    p = store.save(c, folder=str(tmp_path))
    import json
    raw = json.load(open(p, encoding="utf-8"))
    raw["claim"].pop("photos", None)
    json.dump(raw, open(p, "w", encoding="utf-8"))
    back, _r = store.load(p)
    assert back.photos == ()
    assert m.Claim is type(back)
