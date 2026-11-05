import fitz
print(fitz.VersionBind)
def t(mode):
    d = fitz.open(); d.new_page()
    d.embfile_add("pdfstudio_doccontrol.json", b"DC1", filename="pdfstudio_doccontrol.json")
    d.embfile_add("pdfstudio_qa.json", b"QA1", filename="pdfstudio_qa.json")
    for i in range(3):
        if mode == "del":
            d.embfile_del("pdfstudio_qa.json")
            d.embfile_add("pdfstudio_qa.json", b"QA%d" % (i + 2), filename="pdfstudio_qa.json")
        else:
            d.embfile_upd("pdfstudio_qa.json", b"QA%d" % (i + 2))
    print(mode, d.embfile_names(), [d.embfile_get(n) for n in d.embfile_names()])
    import io
    b = d.tobytes(); d2 = fitz.open("pdf", b)
    print(" reopened", [d2.embfile_get(n) for n in d2.embfile_names()])
t("del"); t("upd")
