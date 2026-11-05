"""Reading text files people make in Excel: UTF-8 (with or without the
BOM Excel adds), else Windows-1252 - what Excel's plain "CSV" saves on
Windows, with en dashes and curly quotes (review 0.12.30 N2)."""
import io


def read_text(path):
    with open(path, "rb") as f:
        data = f.read()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def open_csv(path):
    """A text stream for csv.reader / DictReader (newline="" semantics)."""
    return io.StringIO(read_text(path), newline="")
