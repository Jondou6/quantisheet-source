"""Which way of writing text reads back exactly (spaces, hyphens, em dash)?"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz  # noqa: E402

S = "FOR REVIEW \u2014 NOT FOR SEALING 2'-8\" A-101 GWB-PT"
ARIAL = r"C:\Windows\Fonts\arial.ttf"


def show(name, fn):
    doc = fitz.open()
    pg = doc.new_page()
    try:
        fn(pg)
        doc2 = fitz.open("pdf", doc.tobytes(garbage=3, deflate=True))
        got = doc2[0].get_text().strip()
        print(f"{name:28s} {'SAME' if got == S else 'DIFF'} {got!r}")
    except Exception as e:                               # noqa: BLE001
        print(f"{name:28s} ERROR {e}")


def tw(font):
    def f(pg):
        w = fitz.TextWriter(pg.rect)
        w.append((50, 100), S, font=font, fontsize=12)
        w.write_text(pg)
    return f


show("insert_text helv", lambda pg: pg.insert_text((50, 100), S))
show("insert_text arial file", lambda pg: pg.insert_text(
    (50, 100), S, fontname="Arial", fontfile=ARIAL))
show("textwriter arial", tw(fitz.Font(fontfile=ARIAL)))
show("textwriter helv", tw(fitz.Font("helv")))
for fn in ("segoeui.ttf", "calibri.ttf", "tahoma.ttf", "verdana.ttf"):
    p = os.path.join(r"C:\Windows\Fonts", fn)
    if os.path.isfile(p):
        show("insert_text " + fn, lambda pg, p=p: pg.insert_text(
            (50, 100), S, fontname="F" + fn[:4], fontfile=p))
show("htmlbox", lambda pg: pg.insert_htmlbox(fitz.Rect(50, 80, 500, 200),
                                             S))
