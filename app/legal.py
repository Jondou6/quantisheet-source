"""About, Terms of Service, Privacy and third-party licenses.

The publisher details below are filled in once, before QuantiSheet is
handed to anyone outside your company. The texts are a plain-language
starting point for your attorney to review - not legal advice.
"""
import logging
import platform
import sys

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QHBoxLayout, QLabel, QPushButton, QTabWidget,
                               QTextBrowser, QVBoxLayout)

from . import __version__, settings

PUBLISHER = {
    "name": "QuantiSheet",                 # company that licenses the program
    "contact": "",                        # support email shown in About
    "website": "",
    "state": "",                          # governing-law state
}
# AGPL source for testers (Jon, Nov 4): a separate public repo with one
# clean snapshot per release. Kept OFF until that repo exists and Jon says
# so - then set SOURCE_PUBLISHED = True.
SOURCE_URL = "https://github.com/Jondou6/quantisheet-source"
SOURCE_PUBLISHED = True


def source_line():
    """The About line pointing at this release's source, or "" while the
    public repo doesn't exist yet."""
    if not SOURCE_PUBLISHED:
        return ""
    from . import __version__
    url = f"{SOURCE_URL}/tree/v{__version__}"
    return (f"<p>Source code (GNU AGPL): <a href='{url}'>{url}</a></p>")


TERMS_VERSION = "1.0"
TERMS_DATE = "October 15, 2026"


def _pub():
    p = dict(PUBLISHER)
    for k in p:
        v = settings.get(f"publisher_{k}")
        if v:
            p[k] = v
    return p


def _no_contact():
    """Where to ask when no support contact is set (Chief's r46 retest:
    the pages pointed at a contact Help > About didn't show)."""
    from . import betalicense
    if betalicense.is_store():
        return "the support contact on QuantiSheet's Microsoft Store page"
    return "the person or company who gave you QuantiSheet"


def terms_html():
    p = _pub()
    who = p["name"]
    law = (f"the laws of the State of {p['state']}" if p["state"] else
           "the laws of the state where the publisher has its principal "
           "place of business")
    contact = p["contact"] or _no_contact()
    return f"""
<h2>Terms of Service</h2>
<p style='color:#888'>Version {TERMS_VERSION} · effective {TERMS_DATE}</p>
<p>These terms are an agreement between you (and the company you use
QuantiSheet for) and {who} ("we"). By installing or using QuantiSheet you accept
them. If you don't accept them, don't use the program.</p>

<h3>1. Your license</h3>
<p>We grant you a non-exclusive, non-transferable license to install and
use QuantiSheet for your own business, on the number of computers your
license allows. You may not sell, rent, sublicense or redistribute the
program, or remove its notices. Parts of QuantiSheet are open-source
software under their own licenses (Help > Third-Party Licenses); nothing
here limits your rights under those licenses.</p>

<h3>2. Your files and data</h3>
<p>Your drawings, documents, takeoff, estimates and project records belong
to you. QuantiSheet keeps them on your computer, in your files, and on any
server you choose to connect it to. We do not receive them. See Privacy.</p>

<h3>3. Quantities, estimates and automatic tools</h3>
<p>QuantiSheet measures, counts, calculates and suggests - including with
automatic and AI-assisted tools (auto takeoff, trade takeoff, symbol
counts, AI review). <b>Results can be wrong.</b> Drawings may be
inaccurate, out of scale or incomplete, and automatic tools can miss or
misread items. You are responsible for checking every quantity, price,
schedule, code check and document before you rely on it, bid it, sign it or
send it. QuantiSheet is a tool for qualified professionals and does not
replace their judgment, a licensed design professional, or the contract
documents.</p>

<h3>4. Signatures, records and compliance</h3>
<p>Electronic signatures, certificates, pay applications, lien waivers,
compliance checks and other records you create are your responsibility to
use correctly under the laws and contracts that apply to you. Email you
send from QuantiSheet goes out through your own email account.</p>

<h3>5. Acceptable use</h3>
<p>Don't use QuantiSheet to break the law, infringe anyone's rights, or
access documents you aren't allowed to. Don't reverse-engineer the program
except as the law or an open-source license allows.</p>

<h3>6. Updates and support</h3>
<p>We may provide updates and support as described in your purchase or
subscription. We may change these terms for future versions; the version
in Help shows which terms apply to the copy you have.</p>

<h3>7. No warranty</h3>
<p>QUANTISHEET IS PROVIDED "AS IS" AND "AS AVAILABLE", WITHOUT WARRANTIES OF
ANY KIND, EXPRESS OR IMPLIED, INCLUDING MERCHANTABILITY, FITNESS FOR A
PARTICULAR PURPOSE, ACCURACY AND NON-INFRINGEMENT, TO THE FULLEST EXTENT
THE LAW ALLOWS.</p>

<h3>8. Limitation of liability</h3>
<p>TO THE FULLEST EXTENT THE LAW ALLOWS, WE ARE NOT LIABLE FOR INDIRECT,
INCIDENTAL, SPECIAL, CONSEQUENTIAL OR PUNITIVE DAMAGES, OR FOR LOST
PROFITS, LOST BIDS, LOST DATA OR BUSINESS INTERRUPTION, ARISING FROM YOUR
USE OF QUANTISHEET. OUR TOTAL LIABILITY IS LIMITED TO THE AMOUNT YOU PAID
FOR QUANTISHEET IN THE TWELVE MONTHS BEFORE THE CLAIM.</p>

<h3>9. Ending this agreement</h3>
<p>You may stop using QuantiSheet at any time. Your license ends if you
break these terms; then uninstall the program. Your files remain yours.</p>

<h3>10. General</h3>
<p>These terms are governed by {law}. If part of them can't be enforced,
the rest still applies. Questions: {contact}.</p>
"""


def license_rows():
    try:
        from . import betalicense
        info = betalicense.current()
    except Exception:
        info = None
    if not info:
        return ""
    who = info.get("n", "")
    if info.get("c"):
        who += f", {info['c']}"
    rows = [("Licensed to", who), ("License", f"Key {info.get('k')} - "
                                   f"ends {info.get('x')}"),
            ("", "Not for resale")]
    return "".join(f"<tr><td style='padding:2px 16px 2px 0;color:#888'>"
                   f"{html_escape(k)}</td><td>{html_escape(v)}</td></tr>"
                   for k, v in rows)


def privacy_html():
    p = _pub()
    contact = p["contact"] or _no_contact()
    return f"""
<h2>Privacy</h2>
<p><b>QuantiSheet does not send your documents or data to us.</b> It runs
on your computer and stores your work in your own files and folders.</p>
<h3>What stays on your computer</h3>
<ul>
<li>Your PDFs, markups, takeoff, estimates and job data (inside the PDFs
and in the folders you choose).</li>
<li>Settings, recent files, AutoSave recovery copies and the price database
(in {html_escape(settings.DIR)}).</li>
<li>AI features use a model running on this computer (Ollama); nothing is
sent to an outside AI service. Your IT department can point QuantiSheet at
an Ollama server on another computer (the AIHost setting); then the text
the AI reads goes to that server.</li>
</ul>
<h3>What leaves your computer - only when you use it</h3>
<ul>
<li><b>Project sharing, live collaboration and signature requests</b> go
through the server you or your company set up (the relay). Whoever runs
that server holds that data.</li>
<li><b>DocuSign</b>: documents you choose to send with DocuSign go to
DocuSign under its own terms.</li>
<li><b>Email</b> goes out through your own Outlook account.</li>
<li><b>Weather</b> for daily logs and <b>BLS price indexes</b> are fetched
from public services; only the location or index asked for is sent. A new
Owner Report fetches the weather and forecast (Open-Meteo) by itself when
the project has a location set.</li>
<li><b>Dropbox</b>: files you choose to send to or bring in from Dropbox go
through your own Dropbox account, under Dropbox's terms.</li>
<li><b>Site and address lookups</b> (aerial images, flood zones, wetlands,
addresses) send the address or map area you look up to public U.S.
government services (USGS, Census, FEMA, U.S. Fish and Wildlife).</li>
<li><b>Package status</b> (Package Tracker &gt; Check Status, only with a
carrier's keys you entered) sends just the tracking number to that
carrier (UPS, FedEx, USPS or DHL).</li>
<li><b>Report an Issue</b> writes an email in your own mail program with
what you typed, a screenshot you can drop, facts about the open drawing
(page count, sheet sizes, how many markups - never its content), and a
support summary (versions, settings summary, the recent log, crash and
freeze records) with email addresses, keys, your Windows user name and
network paths taken out. Nothing goes until you click Send; the drawing
itself goes only if you tick "Attach this drawing".</li>
</ul>
<p><b>Crash and freeze records</b> are written to your own data folder so
the next start can offer a report. They are never sent by themselves.</p>
<p><b>Backups</b> made with Tools &gt; Back Up My QuantiSheet Data (and the
weekly copy in Documents\\QuantiSheet Backups) hold your settings,
signing key, carrier keys and Back Office data. They stay where they are
saved; keep them somewhere private.</p>
{_updates_html()}
<p>IT can turn off the weather, site lookups, price indexes, DocuSign and
Dropbox for everyone (the OfflineMode setting){_updates_it()} and the AI
features (DisableAI).</p>
<h3>Deleting your data</h3>
<p>Your drawings and job folders are yours and stay where you put them.
QuantiSheet's own settings, recovery copies and price database are in
{html_escape(settings.DIR)}; delete that folder to remove them. When you
uninstall a copy installed with the QuantiSheet setup, it asks whether to
remove that folder too; a Microsoft Store copy leaves it for you to
delete.</p>
<p>Questions: {contact}.</p>
"""


def _updates_html():
    """The update paragraph: what this copy does about updates."""
    from . import betalicense, updatecheck
    if betalicense.is_store():
        return ("<p><b>Updates</b>: this copy is updated by the Microsoft "
                "Store - QuantiSheet never downloads or installs updates "
                "itself. Once a day (and when you choose Help &gt; Check for "
                "Updates Now) it asks the Microsoft Store on this PC whether "
                "an update is waiting, and if so shows a reminder; the Store "
                "does the download and install. Nothing is sent to us. Turn "
                "the reminder off with Help &gt; Check for Updates "
                "Automatically.</p>")
    if updatecheck.team_build():
        return ("<p><b>Update check (team copy)</b>: once a day, and when "
                "you choose Help &gt; Check for Updates Now, QuantiSheet "
                "downloads a small file that says which version is newest. "
                "It sends no documents, settings, names, email addresses, "
                "license or computer IDs - only a plain web request (which, "
                "like any web request, shows your internet address to the "
                "server). An update downloads and installs only when you "
                "click Update now; QuantiSheet then closes, updates and "
                "opens again by itself. Turn it off "
                "with Help &gt; Check for Updates Automatically.</p>")
    return ("<p><b>Updates</b>: this copy doesn't check for updates; ask "
            "the person or company who gave it to you.</p>")


def _updates_it():
    from . import betalicense, updatecheck
    if updatecheck.team_build():
        return ", the team copy's update check (DisableUpdateCheck)"
    if betalicense.is_store():
        return ", the update reminder (DisableUpdateCheck)"
    return ""


def html_escape(s):
    import html
    return html.escape(str(s))


# name, license, used for
THIRD_PARTY = [
    ("PyMuPDF / MuPDF (Artifex)", "GNU AGPL v3, or a commercial license "
     "from Artifex", "Reading, drawing and writing PDFs"),
    ("Qt for Python (PySide6)", "GNU LGPL v3", "The window and controls"),
    ("OpenCV", "Apache 2.0", "Auto takeoff, symbol counts, overlay"),
    ("NumPy", "BSD 3-Clause", "Image and grid calculations"),
    ("pyHanko", "MIT", "Digital signatures"),
    ("cryptography", "Apache 2.0 or BSD", "Certificates and encryption"),
    ("Pillow", "MIT-CMU (HPND)", "Images"),
    ("ezdxf", "MIT", "AutoCAD DXF import and export"),
    ("Modulor", "MIT", "Generate Set: walls, openings and rooms "
     "(the drawing kernel)"),
    ("manifold3d", "Apache 2.0", "Geometry used by Modulor"),
    ("websockets", "BSD 3-Clause", "Live collaboration and the relay"),
    ("pywin32 (Windows)", "PSF license", "Outlook email"),
    ("Tesseract OCR (optional)", "Apache 2.0", "Making scans searchable"),
    ("Ghostscript (optional)", "GNU AGPL v3", "PDF/A conversion"),
    ("Ollama and Llama 3.2 (optional)", "MIT; Llama 3.2 Community "
     "License", "Local AI features"),
    ("Liberation Sans 2.1.5 (Red Hat; Arimo digitized data, Google)",
     "SIL Open Font License 1.1 (text in app/data/fonts/OFL.txt)",
     "The font embedded in the Weekly Owner Report PDF"),
    ("Kargul Calender Design Prototype (Kargul Studio) - design only, "
     "no code included", "MIT (Copyright (c) 2026 Kargul Studio)",
     "The look of the project Calendar page"),
    ("Python", "PSF license", "The language QuantiSheet is written in"),
]


def third_party_html():
    rows = "".join(f"<tr><td style='padding:4px 14px 4px 0'><b>"
                   f"{html_escape(n)}</b></td><td style='padding:4px 14px "
                   f"4px 0'>{html_escape(l)}</td><td>{html_escape(u)}</td>"
                   "</tr>" for n, l, u in THIRD_PARTY)
    return f"""
<h2>Third-party licenses</h2>
<p>QuantiSheet is built on these open-source components. Each is used under
its own license; their full texts come with each package.</p>
<table cellspacing=0><tr><th align=left>Component</th><th align=left>
License</th><th align=left>Used for</th></tr>{rows}</table>
<p style='color:#888'>Components under the GNU AGPL (MuPDF, Ghostscript)
require the program's source to be offered to its users, unless a
commercial license is obtained from Artifex.</p>
"""


def versions():
    out = [("QuantiSheet", __version__),
           ("Python", platform.python_version()),
           ("Windows" if sys.platform == "win32" else "System",
            platform.platform())]
    try:
        import fitz
        out.append(("PyMuPDF", getattr(fitz, "VersionBind", "")))
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    try:
        import PySide6
        from PySide6.QtCore import qVersion
        out.append(("Qt", f"{qVersion()} (PySide6 {PySide6.__version__})"))
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    try:
        import cv2
        out.append(("OpenCV", cv2.__version__))
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    return out


def update_status(now=None):
    """" · Up to date · last checked Nov 4, 2:10 PM" (Nov 4, review
    Part F), or "" when this copy doesn't check. The Microsoft Store
    copy says what the Store has for it, not "Up to date"."""
    import time
    from . import updatecheck
    try:
        if not (updatecheck.team_build() or _store()):
            return ""
        last = float(settings.get(updatecheck.S_LAST) or 0)
    except Exception:                                     # noqa: BLE001
        return ""
    if not last:
        return " · not checked yet (Help &gt; Check for Updates Now)"
    waiting = None
    try:
        waiting = updatecheck.waiting()
    except Exception:                                     # noqa: BLE001
        waiting = None
    when = time.strftime("%b %d, %I:%M %p", time.localtime(last)) \
        .replace(" 0", " ")
    if _store() and not updatecheck.team_build():
        # the Store copy only knows what the Microsoft Store has for it:
        # "Up to date" read as "the newest QuantiSheet there is" (Nov 12)
        state = ("an update is ready in the Microsoft Store" if waiting
                 else "No update is waiting in the Microsoft Store "
                      "(updates come through the Store)")
    else:
        state = (f"version {waiting['version']} is ready to install"
                 if waiting else "Up to date")
    auto = "" if updatecheck.enabled() else " · automatic checks are off"
    return f" · {state} · last checked {when}{auto}"


def _store():
    try:
        from . import betalicense
        return betalicense.is_store()
    except Exception:                                     # noqa: BLE001
        return False


def about_html():
    p = _pub()
    rows = "".join(f"<tr><td style='padding:2px 16px 2px 0;color:#888'>"
                   f"{html_escape(k)}</td><td>{html_escape(v)}</td></tr>"
                   for k, v in versions())
    contact = ""
    if p["contact"]:
        contact += f"<p>Support: <a href='mailto:{p['contact']}'>" \
                   f"{html_escape(p['contact'])}</a></p>"
    if p["website"]:
        contact += f"<p><a href='{p['website']}'>{html_escape(p['website'])}"\
                   "</a></p>"
    return f"""
<h1 style='margin-bottom:0'>QuantiSheet</h1>
<p style='margin-top:4px'>Version {__version__}{update_status()}</p>
<p>Drawings, PDF editing, markup, takeoff, estimating, scheduling and
project control in one program.</p>
{contact}
<table cellspacing=0>{license_rows()}{rows}
<tr><td style='padding:2px 16px 2px 0;color:#888'>Settings and data</td>
<td>{html_escape(settings.DIR)}</td></tr>
<tr><td style='padding:2px 16px 2px 0;color:#888'>Terms</td>
<td>Version {TERMS_VERSION}, {TERMS_DATE}</td></tr></table>
{source_line()}<p style='color:#888'>© 2026 {html_escape(p['name'])}. Built with
open-source software - see Third-Party Licenses.</p>
"""


class LegalDialog(QDialog):
    """About / Terms / Privacy / Third-party licenses, one tab each."""
    PAGES = (("About", about_html), ("Terms of Service", terms_html),
             ("Privacy", privacy_html),
             ("Third-Party Licenses", third_party_html))

    def __init__(self, parent=None, page="About"):
        super().__init__(parent)
        self.setWindowTitle("About QuantiSheet")
        self.resize(760, 620)
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.browsers = {}
        for name, fn in self.PAGES:
            b = QTextBrowser()
            b.setOpenExternalLinks(True)
            b.setHtml(fn())
            self.tabs.addTab(b, name)
            self.browsers[name] = b
        v.addWidget(self.tabs, 1)
        row = QHBoxLayout()
        copy = QPushButton("Copy System Info")
        copy.clicked.connect(self.copy_info)
        save = QPushButton("Save as PDF…")
        save.clicked.connect(lambda _c=False: self.save_pdf())
        for b in (copy, save):
            b.setAutoDefault(False)
        row.addWidget(copy)
        row.addWidget(save)
        row.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        v.addLayout(row)
        self.show_page(page)

    def show_page(self, name):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == name:
                self.tabs.setCurrentIndex(i)

    def info_text(self):
        lines = [f"{k}: {val}" for k, val in versions()]
        lines.append(f"Data folder: {settings.DIR}")
        return "\n".join(lines)

    def copy_info(self):
        QGuiApplication.clipboard().setText(self.info_text())
        return self.info_text()

    def save_pdf(self, path=None):
        name = self.tabs.tabText(self.tabs.currentIndex())
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save as PDF", f"QuantiSheet - {name}.pdf",
                "PDF (*.pdf)")
        if not path:
            return None
        import fitz
        html = dict(self.PAGES)[name]()
        doc = fitz.open()
        story = fitz.Story(html=html)
        writer = fitz.DocumentWriter(path)
        rect = fitz.paper_rect("letter")
        where = rect + (54, 54, -54, -54)
        more = True
        while more:
            dev = writer.begin_page(rect)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
        writer.close()
        doc.close()
        return path
