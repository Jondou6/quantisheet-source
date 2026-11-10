"""Builder's risk quote request (Nov 4, Jon): for every project, a one-page
summary an insurance company can price builder's risk from - project
name, address, summary of the work, the estimated amount - plus the
builder's risk requirements read from the spec book (form, deductible),
emailed straight from QuantiSheet with the spec pages attached.

Nothing is sent without the person clicking Send (Outlook shows it first
when Mail > Review Before Sending is on - mail.review_first)."""
import datetime
import re
from decimal import Decimal
from .dmoney import c2 as _c2

S_AGENT = "builders_risk_agent"       # the insurance contact, remembered


def values(doc, spec_items=None):
    """What goes on the request, prefilled from the job (all editable)."""
    from . import bidform_auto, formlib, proposal
    jv = formlib.job_values(doc)
    pr = proposal.read(doc) if doc is not None else {}
    try:
        amount = bidform_auto.base_bid(doc)
    except Exception:                                     # noqa: BLE001
        amount = Decimal("0.00")
    reqs = []
    for it in spec_items or []:
        if it.get("kind") == "builders_risk" and not it.get("missing"):
            reqs.append(f"{it.get('where') or 'Spec book'}, page(s) "
                        f"{it['pages'][0] + 1}-{it['pages'][-1] + 1}: " +
                        ("; ".join(it.get("terms") or []) or "see pages"))
    return {"project": jv.get("project") or pr.get("project", ""),
            "address": jv.get("project_address") or
            pr.get("project_address", ""),
            "owner": jv.get("owner") or pr.get("client", ""),
            "work": work_summary(doc, pr),
            "amount": amount,
            "start": "", "finish": "",
            "requirements": "\n".join(reqs),
            "contractor": jv.get("contractor", ""),
            "contractor_phone": jv.get("contractor_phone", ""),
            "contractor_email": jv.get("contractor_email", "")}


def work_summary(doc, pr=None):
    """The proposal's scope when there is one, else the estimate's main
    trades by amount ("Concrete, Masonry, Metals ... (12 trades)")."""
    pr = pr or {}
    desc = str(pr.get("description") or "").strip()
    if desc:
        return desc
    try:
        from . import estimate_export
        divs = [d for d in estimate_export.summary(doc)["divisions"]
                if d["total"]]
        divs.sort(key=lambda d: -d["total"])
        names = [d["title"] for d in divs if d.get("division")][:8]
        if names:
            more = len(divs) - len(names)
            return ("Work includes " + ", ".join(names) +
                    (f" and {more} other trade(s)" if more > 0 else "") + ".")
    except Exception:                                     # noqa: BLE001
        pass
    return str(pr.get("scope") or "").strip()


def _wrap(text, width=95):
    out = []
    for para in str(text or "").splitlines() or [""]:
        line = ""
        for w in para.split():
            if len(line) + len(w) + 1 > width:
                out.append(line)
                line = w
            else:
                line = f"{line} {w}".strip()
        out.append(line)
    return out


def request_pdf(v, path, spec_doc=None, spec_items=None):
    """The one-page request; the builder's risk spec pages follow it when
    given. Returns path."""
    import fitz
    out = fitz.open()
    pg = out.new_page(width=612, height=792)
    y = [56]

    def t(text, size=10, bold=False, x=50):
        pg.insert_text((x, y[0]), text[:110], fontsize=size,
                       fontname="hebo" if bold else "helv")
        y[0] += size + 6
    t("BUILDER'S RISK - REQUEST FOR QUOTE", 15, True)
    t(datetime.date.today().strftime("%B %d, %Y"), 9)
    y[0] += 6
    amt = v.get("amount")
    try:
        amt_s = f"${_c2(Decimal(str(amt))):,.2f}"
    except Exception:                                     # noqa: BLE001
        amt_s = str(amt or "")
    for label, val in (("Project", v.get("project")),
                       ("Project address", v.get("address")),
                       ("Owner", v.get("owner")),
                       ("Estimated construction amount", amt_s),
                       ("Estimated start", v.get("start")),
                       ("Estimated completion", v.get("finish"))):
        if not val:
            continue
        pg.insert_text((50, y[0]), label + ":", fontsize=10, fontname="hebo")
        pg.insert_text((235, y[0]), str(val)[:70], fontsize=10)
        y[0] += 17
    y[0] += 6
    t("Summary of work", 11, True)
    for ln in _wrap(v.get("work"))[:14]:
        t(ln, 9.5)
    if v.get("requirements"):
        y[0] += 6
        t("Builder's risk requirements in the contract documents", 11, True)
        for ln in _wrap(v["requirements"])[:14]:
            t(ln, 9)
        t("(The specification pages are attached after this page.)", 8)
    y[0] += 10
    t("Requested by", 11, True)
    for val in (v.get("contractor"), v.get("contractor_phone"),
                v.get("contractor_email")):
        if val:
            t(str(val), 9.5)
    if spec_doc is not None:
        for it in spec_items or []:
            if it.get("kind") == "builders_risk" and not it.get("missing"):
                out.insert_pdf(spec_doc, from_page=it["pages"][0],
                               to_page=it["pages"][-1], annots=False)
    out.save(path, garbage=3, deflate=True)
    out.close()
    return path


def file_name(v):
    name = re.sub(r'[\\/:*?"<>|]+', " ", str(v.get("project") or
                                             "Project")).strip()
    return f"{name} - Builder's Risk Quote Request.pdf"


def email(v, pdf, to, note="", send=None):
    """Email the request to the insurance contact (mail.py: Outlook, else
    the default mail program). Returns how it went out."""
    from . import mail, settings
    send = send or mail.send
    body = (f"Please quote builder's risk insurance for {v.get('project') or 'this project'}"
            + (f" at {v['address']}" if v.get("address") else "") + ".\n\n"
            + (note.strip() + "\n\n" if note.strip() else "")
            + "The project summary and the contract's builder's risk "
            "requirements are attached.\n\nThank you,\n"
            + str(v.get("contractor") or ""))
    how = send(to, f"Builder's risk quote request - {v.get('project') or ''}"
               .strip(" -"), body, attachments=[pdf])
    try:
        settings.set(S_AGENT, str(to))
    except Exception:                                     # noqa: BLE001
        pass
    return how


def agent():
    try:
        from . import settings
        return settings.get(S_AGENT, "") or ""
    except Exception:                                     # noqa: BLE001
        return ""

