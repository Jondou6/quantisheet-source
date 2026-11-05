"""E-signature requests: send a PDF out to be signed, track it, and get
back a signed copy with a certificate of completion.

Fields are boxes drawn on the PDF (subject "Sign Here:<kind>:<signer>:<req>"
on a rectangle markup, coloured per signer), so they can be moved, resized
and undone like any markup.

Two ways to send:
  * QuantiSheet hub (default) - signers get an emailed link to the relay's
    sign.html page; no account needed. The hub keeps the audit trail
    (opened, agreed, signed, from which address, when).
  * DocuSign - for owners who require it (esign_docusign.py).

When everyone has signed, ``finish()`` stamps the signatures and answers
into the PDF, adds a Certificate of Completion page with the audit trail
and the document's fingerprint, and seals the file with a digital
signature so any later change shows.
"""
import base64
import datetime
import hashlib
import html
import json
import logging
import os

import fitz

from . import annotate, settings

log = logging.getLogger(__name__)
SUBJECT = "Sign Here"
KINDS = ("signature", "initials", "date", "name", "text", "checkbox")
KIND_LABEL = {"signature": "Signature", "initials": "Initials",
              "date": "Date signed", "name": "Full name", "text": "Text",
              "checkbox": "Checkbox"}
SIGNER_COLORS = [(0.15, 0.39, 0.92), (0.85, 0.35, 0.05), (0.07, 0.53, 0.35),
                 (0.55, 0.2, 0.75), (0.8, 0.1, 0.35), (0.2, 0.55, 0.65)]
REGISTRY = "envelopes.json"


class ESignError(RuntimeError):
    pass


def color_for(signer):
    return SIGNER_COLORS[int(signer) % len(SIGNER_COLORS)]


def field_payload(kind, signer, rect, label="", required=True):
    """Payload for apply_marks(): a coloured box that is a field."""
    return {"rect": list(rect), "subject": f"{SUBJECT}:{kind}:{int(signer)}:"
                                           f"{1 if required else 0}",
            "note": label or f"{KIND_LABEL[kind]} - signer {int(signer) + 1}",
            "color": list(color_for(signer)), "width": 1.5}


def fields(doc):
    """[{id, page, rect (unrotated), kind, signer, required, label, xref}]"""
    out = []
    for pno, page in enumerate(doc):
        for a in annotate.iter_annots(page):
            subj = (a.info.get("subject") or "")
            if not subj.startswith(SUBJECT + ":"):
                continue
            parts = subj.split(":")
            try:
                kind, signer = parts[1], int(parts[2])
            except (IndexError, ValueError):
                continue
            if kind not in KINDS:
                continue
            req = parts[3] != "0" if len(parts) > 3 else True
            bw = ((a.border or {}).get("width") or 0) / 2
            r = fitz.Rect(a.rect) + (bw, bw, -bw, -bw)   # the drawn box
            out.append({"id": f"f{len(out) + 1}", "page": pno,
                        "rect": [round(v, 2) for v in r],
                        "kind": kind, "signer": signer, "required": req,
                        "label": a.info.get("content") or "",
                        "xref": a.xref})
    return out


_LABELS = [("signature", r"\b(signature|signed|sign here|sign)\b"),
           ("initials", r"\binitials?\b"),
           ("date", r"\bdate\b"),
           ("name", r"\b(print(ed)?\s+name|name)\b")]


def auto_place(doc, signers=1):
    """Find blanks next to 'Signature', 'Date', 'Initials', 'Name' and
    signature form fields; returns marks for apply_marks() (all for the
    first signer - change them after)."""
    import re
    from . import acrobat
    marks = []
    seen = set()
    for pno, page in enumerate(doc):
        for w in page.widgets() or []:
            if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                r = annotate.to_page(page, w.rect)
                marks.append((pno, "add_rect",
                              field_payload("signature", 0, r)))
                seen.add((pno, round(r.x0), round(r.y0)))
    for pno, kind_, payload in acrobat.detect_fields(doc):
        name = (payload.get("name") or "").lower()
        kind = None
        for k, rx in _LABELS:
            if re.search(rx, name):
                kind = k
                break
        if kind is None:
            continue
        r = fitz.Rect(payload["rect"])
        key = (pno, round(r.x0), round(r.y0))
        if key in seen:
            continue
        seen.add(key)
        if kind == "signature" and r.height < 24:
            r.y0 = r.y1 - 26
        marks.append((pno, "add_rect", field_payload(kind, 0, r)))
    return marks


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def render_pages(doc, dpi=110):
    """PNG of every page without the field boxes (the signing page draws
    its own), plus page sizes in points."""
    tmp = fitz.open("pdf", doc.tobytes())
    for pno, page in enumerate(tmp):
        for a in list(annotate.iter_annots(page)):
            if (a.info.get("subject") or "").startswith(SUBJECT + ":"):
                page.delete_annot(a)
    out = []
    for page in tmp:
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        r = page.rect
        out.append({"w": r.width, "h": r.height,
                    "png": base64.b64encode(pix.tobytes("png"))
                    .decode("ascii")})
    tmp.close()
    return out


def _display_rect(doc, f):
    """Field rect in the rotated page as shown (what the signer sees)."""
    page = doc[f["page"]]
    return list(annotate.from_page(page, fitz.Rect(f["rect"])))


# --------------------------------------------------------------- registry
def _reg_path():
    return os.path.join(settings.DIR, REGISTRY)


def registry():
    try:
        with open(_reg_path(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def _save_reg(reg):
    os.makedirs(settings.DIR, exist_ok=True)
    tmp = _reg_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=1)
    os.replace(tmp, _reg_path())


def remember(env):
    reg = registry()
    reg[env["id"]] = env
    _save_reg(reg)


# --------------------------------------------------------------- sending
def send(path, signers, title="", message="", expires_days=30,
         provider="hub", client=None, email=True):
    """Send the saved PDF at `path` for signature. signers: [{name, email,
    order}]. Returns the envelope record (also kept in the registry)."""
    if not os.path.isfile(path):
        raise ESignError("Save the PDF first.")
    doc = fitz.open(path)
    fl = fields(doc)
    if not fl:
        raise ESignError("Place at least one signature field first "
                         "(Request Signatures > Place Fields).")
    for i, s in enumerate(signers):
        if not any(f["signer"] == i and f["kind"] in ("signature",
                                                     "initials")
                   for f in fl):
            raise ESignError(f"{s.get('name') or f'Signer {i + 1}'} has no "
                             "signature or initials box.")
        if not s.get("name") or not s.get("email"):
            raise ESignError("Every signer needs a name and an email.")
    if any(f["signer"] >= len(signers) for f in fl):
        raise ESignError("Some fields belong to a signer you haven't "
                         "listed.")
    sha = file_sha(path)
    title = title or os.path.splitext(os.path.basename(path))[0]
    env = {"provider": provider, "path": os.path.abspath(path),
           "sha256": sha, "title": title, "message": message,
           "signers": [dict(s, order=int(s.get("order") or 1))
                       for s in signers],
           "fields": [{k: v for k, v in f.items() if k != "xref"}
                      for f in fl],
           "created": datetime.datetime.now().isoformat(timespec="seconds"),
           "status": "sent", "emailed": [], "signed_path": ""}
    if provider == "docusign":
        from . import esign_docusign as ds
        env.update(ds.send(path, env, doc))
        doc.close()
        remember(env)
        return env
    from .collab.hubclient import HubClient, web_base
    client = client or HubClient()
    pages = render_pages(doc)
    shown = [dict(f, rect=_display_rect(doc, f)) for f in fl]
    doc.close()
    me = settings.author()
    r = client.call("env.create", title=title, message=message,
                    sender={"name": me, "email": settings.get("email", "")},
                    signers=env["signers"], pages=pages,
                    fields=[{k: f[k] for k in ("id", "signer", "page",
                                                "rect", "kind", "required",
                                                "label")} for f in shown],
                    doc_sha256=sha, file_name=os.path.basename(path),
                    expires_days=expires_days)
    base = web_base(client.url)
    env.update({"id": r["env_id"], "sender_key": r["sender_key"],
                "url": client.url, "token": client.token,
                "expires": r["expires"]})
    for s, got in zip(env["signers"], r["signers"]):
        s["token"] = got["token"]
        s["link"] = base + got["link"]
    remember(env)
    if email:
        notify_ready(env)
    return env


def _client_for(env):
    from .collab.hubclient import HubClient
    return HubClient(env.get("url"), env.get("token"))


def status(env, client=None):
    """Fresh status from the hub (or DocuSign); updates the registry and
    emails signers whose turn has come."""
    if env["provider"] == "docusign":
        from . import esign_docusign as ds
        st = ds.status(env)
    else:
        client = client or _client_for(env)
        st = client.call("env.status", env_id=env["id"],
                         sender_key=env["sender_key"])
    env["status"] = st["status"]
    env["last_status"] = st
    remember(env)
    return st


def notify_ready(env, st=None, remind=False):
    """Email each signer whose turn it is (once, or again on remind)."""
    from . import mail
    first = min(s["order"] for s in env["signers"])
    sent = 0
    for i, s in enumerate(env["signers"]):
        if st is None:                 # just sent: the first in order
            ready = s["order"] == first
        else:                          # the hub says "waiting" for later
            cur = st["signers"][i]["status"] if i < len(st["signers"]) \
                else ""
            ready = cur in ("sent", "viewed")
        if not ready or (s["email"] in env["emailed"] and not remind):
            continue
        body = (f"{s['name']},\n\n{settings.author()} sent you "
                f"\"{env['title']}\" to sign.\n\n"
                f"{env.get('message') or ''}\n\n"
                f"Review and sign here (no account needed):\n{s['link']}\n")
        mail.send([s["email"]], ("Reminder: " if remind else "") +
                  f"Please sign: {env['title']}", body)
        if s["email"] not in env["emailed"]:
            env["emailed"].append(s["email"])
        sent += 1
    remember(env)
    return sent


def void(env, reason=""):
    if env["provider"] == "docusign":
        from . import esign_docusign as ds
        ds.void(env, reason)
    else:
        _client_for(env).call("env.void", env_id=env["id"],
                              sender_key=env["sender_key"], reason=reason)
    env["status"] = "voided"
    remember(env)


# --------------------------------------------------------------- finishing
def finish(env, out_path=None, st=None, seal=True):
    """The signed PDF: signatures and answers stamped in, a certificate of
    completion appended, sealed. Returns its path."""
    if env["provider"] == "docusign":
        from . import esign_docusign as ds
        if (st or status(env))["status"] != "completed":
            raise ESignError("Not everyone has signed yet.")
        out_path = out_path or _signed_name(env["path"])
        ds.download(env, out_path)
        env["signed_path"] = out_path
        remember(env)
        return out_path
    st = st or status(env)
    if st["status"] != "completed":
        raise ESignError("Not everyone has signed yet.")
    if file_sha(env["path"]) != env["sha256"]:
        raise ESignError("The PDF changed after it was sent, so the "
                         "signatures can't be put on it. Use the copy that "
                         "was sent, or send it again.")
    doc = fitz.open(env["path"])
    by_id = {f["id"]: f for f in env["fields"]}
    failed = []
    for page in doc:                       # the boxes go, the ink stays
        for a in list(annotate.iter_annots(page)):
            if (a.info.get("subject") or "").startswith(SUBJECT + ":"):
                page.delete_annot(a)
    for i, s in enumerate(st["signers"]):
        for fid, v in (s.get("values") or {}).items():
            f = by_id.get(fid)
            if not f:
                continue
            page = doc[f["page"]]
            r = annotate.from_page(page, fitz.Rect(f["rect"]))
            if v["kind"] in ("signature", "initials"):
                png = base64.b64decode(v["png"])
                page.insert_image(r, stream=png, keep_proportion=True,
                                  overlay=True)
            elif v["kind"] == "checkbox":
                if v.get("checked"):
                    page.insert_textbox(r, "X", fontsize=min(r.height * .8,
                                                             14),
                                        fontname="hebo", align=1)
            else:
                # wraps, shrinks down to 6 pt and falls back to a font that
                # has the character (insert_textbox wrote nothing when the
                # answer didn't fit, and helv printed "?" for Ω, Ł, ✓...)
                size = max(7, min(11, r.height * 0.62))
                text = str(v.get("text", ""))
                spare, _scale = page.insert_htmlbox(
                    r + (2, 0, 0, 2), html.escape(text).replace("\n", "<br>"),
                    css=f"* {{font-family: sans-serif; font-size: {size}px;"
                        " color: #0d1a59; line-height: 1.15}",
                    scale_low=6 / size)
                if text.strip() and spare < 0:
                    failed.append(f"{s['name']}: "
                                  f"{KIND_LABEL.get(v['kind'], 'Text')} on "
                                  f"page {f['page'] + 1}")
    if failed:          # never seal a contract with an answer missing
        doc.close()
        raise ESignError("These answers don't fit their boxes even at 6 pt, "
                         "so no signed copy was made: " + "; ".join(failed) +
                         ". Make the boxes bigger and send it again.")
    _certificate(doc, env, st)
    out_path = out_path or _signed_name(env["path"])
    tmp = out_path + ".tmp.pdf"
    doc.save(tmp, garbage=3, deflate=True)
    doc.close()
    if seal:
        try:
            from .sign.signer import sign_pdf
            sign_pdf(tmp, out_path, reason="Electronic signatures "
                     f"collected ({env['id']})", signer_name="QuantiSheet "
                     "e-signature seal")
            os.remove(tmp)
        except Exception as e:                 # pyhanko missing etc.
            log.warning("could not seal signed PDF: %s", e)
            os.replace(tmp, out_path)
    else:
        os.replace(tmp, out_path)
    env["signed_path"] = out_path
    env["status"] = "completed"
    remember(env)
    return out_path


def _signed_name(path):
    base, ext = os.path.splitext(path)
    return f"{base} - Signed{ext}"


def _certificate(doc, env, st):
    page = doc.new_page(width=612, height=792)
    ink, muted = (0.12, 0.13, 0.16), (0.42, 0.44, 0.49)
    y = 60

    def line(text, size=9.5, font="helv", color=ink, dy=None):
        nonlocal y
        page.insert_text((54, y), text, fontsize=size, fontname=font,
                         color=color)
        y += dy or size + 5
    page.draw_rect(fitz.Rect(0, 0, 612, 6), color=None,
                   fill=(0.15, 0.39, 0.92))
    line("Certificate of Completion", 18, "hebo", dy=28)
    line(f"Document: {env['title']}", 10)
    line(f"Envelope: {env['id']}", 9, color=muted)
    line(f"Original document SHA-256: {env['sha256']}", 8, color=muted)
    line(f"Sent by {settings.author()} on {env['created'].replace('T', ' ')}"
         f" through the QuantiSheet hub", 9, color=muted, dy=24)
    line("Signers", 11, "hebo", dy=18)
    for s in st["signers"]:
        line(f"{s['name']}  <{s['email']}>", 10, "hebo")
        line(f"Opened {(s.get('viewed') or '').replace('T', ' ')}   Signed "
             f"{(s.get('signed') or '').replace('T', ' ')}   from "
             f"{s.get('ip') or 'unknown address'}", 8.5, color=muted)
        for fid, v in (s.get("values") or {}).items():
            if v.get("sha256"):
                line(f"{v['kind'].title()} image SHA-256 {v['sha256']}", 7.5,
                     color=muted)
        y += 6
    y += 6
    line("Audit trail (UTC)", 11, "hebo", dy=18)
    for e in st.get("events") or []:
        if y > 740:
            page = doc.new_page(width=612, height=792)
            y = 60
        line(f"{e['at'].replace('T', ' ')}   {e['action']:<10}  "
             f"{e['who']}   {e.get('ip') or ''}   {e.get('detail') or ''}"
             [:150], 8)
    y += 10
    line("Each signer agreed to sign electronically before signing. This "
         "PDF is sealed with a digital signature;", 8, color=muted)
    line("any change after sealing shows as an invalid signature in "
         "QuantiSheet and other PDF readers.", 8, color=muted)
