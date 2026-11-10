"""Subcontractor prequalification: a fillable PDF questionnaire you email
to a sub, read back when they return it, and a simple score to help you
approve them (and for how much work).

The answers go on the contact in your private Company Directory
(app/subdir.py): status, approved limit, expiry, insurance date, bonding
and certifications.
"""
import re
from datetime import date, timedelta

import fitz
from .dmoney import c2 as _c2

# (key, label, kind) - kind: text, long, yesno
QUESTIONS = [
    ("h_company", "COMPANY", "head"),
    ("legal_name", "Legal company name", "text"),
    ("address", "Address", "text"),
    ("contact", "Contact name and title", "text"),
    ("phone", "Phone", "text"),
    ("email", "Email", "text"),
    ("years", "Years in business", "text"),
    ("license", "Contractor license number(s) and states", "text"),
    ("trades", "Trades / CSI divisions you perform", "text"),
    ("certs", "Certifications (MBE, WBE, DBE, SBE, VOSB, SDVOSB, HUBZone, "
              "Section 3, Union)", "text"),
    ("h_fin", "FINANCIAL", "head"),
    ("revenue", "Average annual revenue, last 3 years ($)", "text"),
    ("largest", "Largest project completed in the last 5 years ($ and "
                "name)", "text"),
    ("backlog", "Current backlog ($)", "text"),
    ("bond_single", "Bonding capacity - single project ($)", "text"),
    ("bond_aggregate", "Bonding capacity - aggregate ($)", "text"),
    ("surety", "Surety company and agent", "text"),
    ("h_safety", "SAFETY", "head"),
    ("emr", "Experience Modification Rate (EMR), last 3 years", "text"),
    ("trir", "OSHA recordable incident rate (TRIR), last 3 years", "text"),
    ("safety_program", "Written safety program?", "yesno"),
    ("osha_citations", "Any OSHA serious or willful citations in the last "
                       "3 years?", "yesno"),
    ("h_ins", "INSURANCE", "head"),
    ("ins_carrier", "Insurance carrier and agent", "text"),
    ("gl_limits", "General liability limits (each occurrence / "
                  "aggregate)", "text"),
    ("umbrella", "Umbrella / excess limit ($)", "text"),
    ("ins_exp", "Insurance expiration date (MM/DD/YYYY)", "text"),
    ("h_legal", "HISTORY", "head"),
    ("litigation", "Any lawsuits, liens or claims in the last 5 years?",
     "yesno"),
    ("default", "Ever failed to complete a contract or been terminated?",
     "yesno"),
    ("explain", "If yes to any of the above, explain", "long"),
    ("references", "Three references (GC, project, contact, phone)",
     "long"),
    ("h_sign", "CERTIFICATION", "head"),
    ("signer", "Signed by (name and title) - I certify these answers are "
               "true", "text"),
    ("signed_on", "Date", "text"),
]


def make_form(path, company="", gc="", due=""):
    """The questionnaire as a fillable PDF at `path`."""
    doc = fitz.open()
    W, H = 612, 792
    page = doc.new_page(width=W, height=H)
    y = 54

    def head(p, text, y, size=10):
        p.insert_text((54, y), text, fontsize=size, fontname="hebo")
        return y + size + 6
    y = head(page, "SUBCONTRACTOR PREQUALIFICATION", y, 15)
    sub = (f"For {gc}. " if gc else "") + \
          (f"Please return by {due}. " if due else "") + \
          "Fill in the boxes, save the PDF and email it back."
    page.insert_text((54, y + 2), sub, fontsize=9)
    y += 16
    if company:
        page.insert_text((54, y + 2), f"Company: {company}", fontsize=9,
                         fontname="hebo")
        y += 16
    for key, label, kind in QUESTIONS:
        need = 70 if kind == "long" else 32
        if y + need > H - 54:
            page = doc.new_page(width=W, height=H)
            y = 54
        if kind == "head":
            y += 6
            y = head(page, label, y + 4)
            page.draw_line((54, y - 4), (W - 54, y - 4), width=0.6)
            continue
        page.insert_text((54, y + 8), label, fontsize=8.5)
        w = fitz.Widget()
        w.field_name = key
        w.text_fontsize = 9
        w.border_color = (0.6, 0.6, 0.6)
        if kind == "yesno":
            w.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
            w.choice_values = ["", "No", "Yes"]
            w.field_value = ""
            w.rect = fitz.Rect(W - 140, y - 2, W - 54, y + 12)
            page.add_widget(w)
            y += 22
            continue
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        if kind == "long":
            w.field_flags = fitz.PDF_TX_FIELD_IS_MULTILINE
            w.rect = fitz.Rect(54, y + 12, W - 54, y + 62)
            y += 70
        else:
            w.rect = fitz.Rect(54, y + 12, W - 54, y + 26)
            y += 32
        if key == "legal_name" and company:
            w.field_value = company
        page.add_widget(w)
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def read_form(path):
    """{key: answer} from a returned questionnaire."""
    out = {}
    with fitz.open(path) as doc:
        for page in doc:
            for w in page.widgets() or []:
                if w.field_name:
                    out[w.field_name] = str(w.field_value or "").strip()
    if not any(k in out for k, _l, _k in QUESTIONS):
        raise ValueError("That PDF isn't a QuantiSheet prequalification "
                         "form.")
    return out


def _nums(text):
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?",
                                          str(text or "").replace(",", ""))]


def _money(text):
    """$ amount in text: 2.5M, $500k, 1,200,000."""
    t = str(text or "").lower().replace(",", "").replace("$", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(m|mm|million|k|thousand)?\b", t)
    if not m:
        return None
    v = float(m.group(1))
    unit = m.group(2) or ""
    if unit in ("m", "mm", "million"):
        v *= 1e6
    elif unit in ("k", "thousand"):
        v *= 1e3
    return v


def score(ans):
    """(score 0-100, [notes], suggested status, suggested limit $)."""
    pts, notes = 100, []
    emr = [x for x in _nums(ans.get("emr")) if x < 5]
    if not emr:
        pts -= 15
        notes.append("No EMR given.")
    elif max(emr) > 1.2:
        pts -= 30
        notes.append(f"EMR as high as {_c2(max(emr)):.2f} (over 1.2).")
    elif max(emr) > 1.0:
        pts -= 12
        notes.append(f"EMR up to {_c2(max(emr)):.2f} (over 1.0).")
    yrs = _nums(ans.get("years"))
    if not yrs:
        pts -= 10
        notes.append("Years in business not given.")
    elif yrs[0] < 3:
        pts -= 15
        notes.append(f"Only {yrs[0]:g} year(s) in business.")
    if ans.get("safety_program") != "Yes":
        pts -= 10
        notes.append("No written safety program.")
    for k, why, n in (("osha_citations", "OSHA serious/willful citations",
                       15),
                      ("litigation", "Lawsuits, liens or claims", 10),
                      ("default", "Failed to complete / terminated", 30)):
        if ans.get(k) == "Yes":
            pts -= n
            notes.append(why + " - see the explanation.")
    bond = _money(ans.get("bond_single"))
    if not bond:
        pts -= 10
        notes.append("No bonding capacity given.")
    if not ans.get("ins_carrier") or not ans.get("ins_exp"):
        pts -= 10
        notes.append("Insurance details incomplete.")
    if not ans.get("references"):
        pts -= 5
        notes.append("No references.")
    if not ans.get("signer"):
        pts -= 5
        notes.append("Not signed.")
    pts = max(0, pts)
    status = "Approved" if pts >= 70 and ans.get("default") != "Yes" \
        else "Pending"
    # work you'd give them: their single bond, or a third of revenue
    rev = _money(ans.get("revenue"))
    limit = bond or (rev / 3 if rev else None)
    return pts, notes, status, limit


def apply(contact, ans, status=None, limit=None, months=12, today=None):
    """Put the answers on a directory contact (a dict, changed and
    returned)."""
    today = today or date.today()
    c = contact
    c["prequal_data"] = dict(ans, received=today.isoformat())
    if status:
        c["prequal"] = status
    if status == "Approved":
        c["prequal_exp"] = (today + timedelta(days=round(months * 30.44))) \
            .isoformat()
    if limit:
        c["prequal_limit"] = f"{limit:.0f}"
    if ans.get("bond_single"):
        b = _money(ans["bond_single"])
        c["bond_limit"] = f"{b:.0f}" if b else ans["bond_single"]
    if ans.get("license"):
        c["license"] = ans["license"]
    if ans.get("certs"):
        c["certs"] = ans["certs"]
    if ans.get("ins_exp"):
        from .subdir import _date
        d = _date(ans["ins_exp"])
        c["insurance_exp"] = d.isoformat() if d else ans["ins_exp"]
    for k in ("phone", "email"):
        if ans.get(k) and not c.get(k):
            c[k] = ans[k]
    return c
