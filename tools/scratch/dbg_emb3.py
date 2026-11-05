import fitz, re

def stream_xref(doc, name):
    cat = doc.pdf_catalog()
    def walk(xref_or_key, base):
        t, v = doc.xref_get_key(base, xref_or_key)
        return t, v
    t, v = doc.xref_get_key(cat, "Names/EmbeddedFiles")
    print("EmbeddedFiles:", t, v)
    t, v = doc.xref_get_key(cat, "Names/EmbeddedFiles/Names")
    print("Names:", t, v)

d = fitz.open(); d.new_page()
for n in ("pdfstudio_a.json", "pdfstudio_b.json", "pdfstudio_c.json"):
    d.embfile_add(n, n.encode(), filename=n)
stream_xref(d, "x")
d.embfile_del("pdfstudio_b.json")
print("after del b", [(n, d.embfile_get(n)) for n in d.embfile_names()])
stream_xref(d, "x")
d.embfile_add("pdfstudio_b.json", b"B2", filename="pdfstudio_b.json")
print("after add b", [(n, d.embfile_get(n)) for n in d.embfile_names()])
stream_xref(d, "x")
for i in range(1, d.xref_length()):
    o = d.xref_object(i)
    if "EmbeddedFile" in o or "Filespec" in o:
        print(i, o.replace("\n", " ")[:160])
