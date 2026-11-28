"""Smaller installer (Nov 25): quantisheet.spec leaves out OpenCV's video
reader, Pillow's AVIF plugin and Qt's own translations - and nothing in
the program uses them."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _spec_keep():
    src = open(os.path.join(ROOT, "quantisheet.spec"), encoding="utf-8").read()
    i = src.index("DROP = ")
    j = src.index("a.binaries = ")
    ns = {"os": os}
    exec(src[i:j], ns)
    return ns["_keep"]


def test_unused_parts_are_left_out():
    keep = _spec_keep()
    sep = os.sep
    gone = [f"cv2{sep}opencv_videoio_ffmpeg500_64.dll",
            f"PIL{sep}_avif.cp312-win_amd64.pyd",
            f"PySide6{sep}translations{sep}qtbase_de.qm"]
    kept = [f"cv2{sep}cv2.pyd", f"PySide6{sep}Qt6Core.dll",
            f"PIL{sep}_imaging.cp312-win_amd64.pyd",
            f"PySide6{sep}plugins{sep}platforms{sep}qwindows.dll",
            f"app{sep}data{sep}help{sep}QuantiSheet-Features-and-How-To.pdf"]
    assert not any(keep((n, "", "BINARY")) for n in gone)
    assert all(keep((n, "", "BINARY")) for n in kept)


def test_nothing_uses_what_is_left_out():
    pat = re.compile(r"VideoCapture|VideoWriter|\bavif\b|QTranslator",
                     re.I)
    hits = []
    for base, _d, files in os.walk(os.path.join(ROOT, "app")):
        for f in files:
            if f.endswith(".py"):
                p = os.path.join(base, f)
                with open(p, encoding="utf-8", errors="replace") as fh:
                    if pat.search(fh.read()):
                        hits.append(os.path.relpath(p, ROOT))
    assert hits == []
