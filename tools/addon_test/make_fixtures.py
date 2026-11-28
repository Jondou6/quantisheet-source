"""Made-up PDFs and a picture for tools/addon_test (no PDF library needed):
text.pdf (two lines of words), rot.pdf (a page stored sideways),
lines.pdf (a few drawn lines, some inside a scaled group), stamp.png."""
import struct
import sys
import zlib


def pdf(stream, page_extra=b"", font=True):
    objs = [b"<</Type/Catalog/Pages 2 0 R>>",
            b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]" + page_extra +
            b"/Contents 4 0 R" + (b"/Resources<</Font<</F1 5 0 R>>>>"
                                  if font else b"") + b">>",
            b"<</Length %d>>stream\n" % len(stream) + stream +
            b"\nendstream"]
    if font:
        objs.append(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj" % i + o + b"endobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1, x)
    return out


def png():
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data +
                struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    raw = b"".join(b"\x00" + b"\xb8\x31\x2b" * 16 for _ in range(16))
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    out = sys.argv[1]
    files = {
        "text.pdf": pdf(b"BT /F1 24 Tf 72 700 Td (Made-up Plan A-101 "
                        b"General Notes) Tj 0 -40 Td (Roof drain at grid "
                        b"C-4 to be confirmed) Tj ET"),
        "rot.pdf": pdf(b"BT /F1 24 Tf 72 700 Td (Made-up sideways sheet) "
                       b"Tj ET", b"/Rotate 90"),
        "lines.pdf": pdf(b"1 w q 2 0 0 2 100 500 cm 0 0 m 50 0 l S "
                         b"10 10 30 20 re S Q 72 700 m 300 700 l S",
                         font=False),
        "stamp.png": png(),
    }
    for name, data in files.items():
        with open(out + "/" + name, "wb") as f:
            f.write(data)
