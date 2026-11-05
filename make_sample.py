import fitz


def make(path="sample.pdf"):
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page(width=612, height=792)
        page.insert_text((40, 60), f"SAMPLE PLAN — SHEET {i+1}", fontsize=14)
        page.insert_text((40, 100), "General notes:", fontsize=11)
        notes = [
            "1. All partitions shall be 2-hour fire rating.",
            "2. Minimum ceiling height shall be 9'-0\".",
            "3. Door hardware shall meet ADA.",
            "4. Fire rating assemblies must be listed.",
            "5. Minimum clear width shall be 44 inches.",
        ]
        y = 120
        for n in notes:
            page.insert_text((50, y), n, fontsize=10)
            y += 16

        # a few boxes so symbol-count has something to find
        for bx in range(3):
            r = fitz.Rect(60 + bx * 120, 240, 110 + bx * 120, 280)
            page.draw_rect(r, color=(0, 0, 0), width=1)
            page.insert_text((r.x0 + 4, r.y0 + 14), "EXIT", fontsize=8)

        # a couple of dimension lines for takeoff practice
        page.draw_line(fitz.Point(60, 400), fitz.Point(300, 400), width=1)
        page.insert_text((170, 395), "24'-0\"", fontsize=8)
        page.draw_line(fitz.Point(60, 430), fitz.Point(60, 620), width=1)
        page.insert_text((64, 520), "18'-0\"", fontsize=8)

    doc.save(path)
    doc.close()
    print(f"wrote {path}")


if __name__ == "__main__":
    import sys
    make(sys.argv[1] if len(sys.argv) > 1 else "sample.pdf")
