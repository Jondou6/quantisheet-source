import fitz
print(fitz.VersionBind)
for name, html, css in [
    ("plain", "<p>Verify in field office</p>", ""),
    ("css", "<p>Verify in field office</p>", "p{font-variant-ligatures:none}"),
    ("css2", "<p>Verify in field office</p>", "*{font-feature-settings:'liga' 0}"),
    ("zwnj", "<p>Verify in f‌ield of‌fice</p>", ""),
]:
    d = fitz.open(); p = d.new_page()
    p.insert_htmlbox(fitz.Rect(50, 50, 400, 100), html, css=css)
    t = p.get_text()
    t2 = p.get_text(flags=0)
    print(name, ascii(t), ascii(t2), len(p.search_for("field")), len(p.search_for("office")))
