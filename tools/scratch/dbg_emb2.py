import fitz
d = fitz.open(); d.new_page()
d.embfile_add("pdfstudio_doccontrol.json", b"DC1", filename="pdfstudio_doccontrol.json")
d.embfile_add("pdfstudio_qa.json", b"QA1", filename="pdfstudio_qa.json")
info = d.embfile_info("pdfstudio_qa.json")
print(info)
x = info["xref"]
print("obj:", d.xref_object(x)[:200], "is_stream", d.xref_is_stream(x))
for i in range(3):
    d.update_stream(x, b"QA-new-%d" % i)
print([d.embfile_get(n) for n in d.embfile_names()])
d2 = fitz.open("pdf", d.tobytes(garbage=3, deflate=True))
print("reopened", d2.embfile_names(), [d2.embfile_get(n) for n in d2.embfile_names()])
print(d2.embfile_info("pdfstudio_qa.json"))
# also: del of the last entry, then add with a NEW name order
d3 = fitz.open(); d3.new_page()
for n in ("pdfstudio_a.json", "pdfstudio_b.json", "pdfstudio_c.json"):
    d3.embfile_add(n, n.encode(), filename=n)
d3.embfile_del("pdfstudio_b.json")
print("after del b", [(n, d3.embfile_get(n)) for n in d3.embfile_names()])
d3.embfile_add("pdfstudio_b.json", b"B2", filename="pdfstudio_b.json")
print("after add b", [(n, d3.embfile_get(n)) for n in d3.embfile_names()])
