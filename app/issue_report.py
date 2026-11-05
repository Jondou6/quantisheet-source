"""Help > Report an Issue (Nov 3, Jon): a tester describes what went wrong,
checks a screenshot of the window, and an email to support opens in their
Outlook with everything attached - they click Send. Nothing is sent
without that click.

What goes with it:
  * their words, and the screenshot if they keep it;
  * facts about the open drawing, none of its content: pages, each
    sheet's size and rotation, how many markups and pictures, the program
    that made the PDF, the file size;
  * the support bundle (versions, settings summary, the recent log and
    freeze/crash records), scrubbed of emails, secrets, the Windows user
    name and network paths (diagnostics.scrub);
  * the drawing itself only when they tick "Attach this drawing".
Without Outlook the email is written as an .eml file and opened, so the
default mail program shows it ready to send (mail.py).
"""
import datetime
import json
import os
import tempfile
import zipfile

SUPPORT_EMAIL = "jondou6@hotmail.com"
MAX_ATTACH_MB = 20            # a bigger drawing isn't offered as attachment


def doc_facts(doc, path=None, max_pages=400):
    """Facts about a drawing, none of its content (dict)."""
    out = {"pages": 0}
    if doc is None:
        return out
    try:
        out["pages"] = doc.page_count
        meta = doc.metadata or {}
        out["made_by"] = " / ".join(x for x in (meta.get("creator"),
                                                  meta.get("producer"))
                                    if x)[:120]
        out["pdf_version"] = meta.get("format", "")
        out["encrypted"] = bool(doc.is_encrypted)
        if path and os.path.isfile(path):
            out["file_mb"] = round(os.path.getsize(path) / 1e6, 1)
        sizes, annots, images = {}, 0, 0
        for i in range(min(doc.page_count, max_pages)):
            pg = doc[i]
            r = pg.rect
            key = (f"{min(r.width, r.height) / 72:.0f}x"
                   f"{max(r.width, r.height) / 72:.0f} in rot "
                   f"{pg.rotation}")
            sizes[key] = sizes.get(key, 0) + 1
            try:
                annots += len(pg.annot_xrefs())
                images += len(pg.get_images())
            except Exception:                             # noqa: BLE001
                pass
        out["sheets"] = sizes
        out["markups"] = annots
        out["pictures"] = images
    except Exception as e:                                # noqa: BLE001
        out["error"] = f"{type(e).__name__}"
    return out


def facts_text(f):
    lines = [f"Pages: {f.get('pages', 0)}"]
    for k, n in (f.get("sheets") or {}).items():
        lines.append(f"  {n} sheet(s) {k}")
    for k, label in (("markups", "Markups"), ("pictures", "Pictures"),
                     ("file_mb", "File size (MB)"), ("made_by", "Made by"),
                     ("pdf_version", "PDF version"),
                     ("encrypted", "Encrypted")):
        if k in f:
            lines.append(f"{label}: {f[k]}")
    return "\n".join(lines)


def build(text, screenshot_png=None, doc=None, doc_path=None,
          attach_doc=False, view_page=None, folder=None, crashes=True):
    """Write the report zip; returns (zip path, list of attachments)."""
    from . import __version__, diagnostics
    folder = folder or tempfile.mkdtemp(prefix="qs_issue_")
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    zpath = os.path.join(folder, f"QuantiSheet-issue-{stamp}.zip")
    bundle = diagnostics.bundle(os.path.join(folder, "bundle.zip"),
                                crashes=crashes)
    facts = doc_facts(doc, doc_path)
    if view_page is not None:
        facts["page_on_screen"] = view_page + 1
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("what_happened.txt", (text or "").strip() + "\n")
        z.writestr("drawing_facts.json", json.dumps(facts, indent=2))
        z.writestr("version.txt", f"QuantiSheet {__version__}\n")
        with zipfile.ZipFile(bundle) as b:
            for n in b.namelist():
                z.writestr("support/" + n, b.read(n))
        if screenshot_png:
            z.writestr("screenshot.png", screenshot_png)
    try:
        os.remove(bundle)
    except OSError:
        pass
    attach = [zpath]
    if screenshot_png:
        shot = os.path.join(folder, "screenshot.png")
        with open(shot, "wb") as f:
            f.write(screenshot_png)
        attach.append(shot)          # seen in the email without unzipping
    if attach_doc and doc_path and os.path.isfile(doc_path) and \
            os.path.getsize(doc_path) <= MAX_ATTACH_MB * 1e6:
        attach.append(doc_path)
    return zpath, attach, facts


def message(text, facts, attachments):
    """The email (mail.py's dict)."""
    from . import __version__
    first = " ".join((text or "").split())[:60] or "an issue"
    body = ("What happened:\n" + ((text or "").strip() or "(not said)") +
            "\n\n--- About the drawing (no content) ---\n" +
            facts_text(facts) +
            f"\n\nQuantiSheet {__version__}\n"
            "The attached zip has the program's logs (names, emails and "
            "network paths removed).\n")
    return {"to": [SUPPORT_EMAIL], "cc": [],
            "subject": f"QuantiSheet issue: {first}", "body": body,
            "attachments": list(attachments)}


def open_email(msg):
    """Open the email ready to send (Outlook, else an .eml in the default
    mail program); never sends it by itself. Returns how (mail.send)."""
    from . import mail
    return mail.send(msg["to"], msg["subject"], msg["body"],
                     attachments=msg["attachments"], display=True)
