"""DocuSign for signature requests, for owners who require it.

Settings (Document > Request Signatures asks the first time):
  docusign_base     e.g. https://na3.docusign.net/restapi
                    (https://demo.docusign.net/restapi for a sandbox)
  docusign_account  your API account ID
  docusign_token    an OAuth access token for that account

The same fields drawn in QuantiSheet become DocuSign tabs at the same
places; DocuSign emails the signers and keeps its own audit trail, and the
signed PDF comes back with DocuSign's certificate.
"""
import base64
import json
import os
import urllib.error
import urllib.request

from . import annotate, settings

TAB = {"signature": "signHereTabs", "initials": "initialHereTabs",
       "date": "dateSignedTabs", "name": "fullNameTabs",
       "text": "textTabs", "checkbox": "checkboxTabs"}
STATUS = {"completed": "signed", "delivered": "viewed", "sent": "sent",
          "created": "sent", "declined": "declined",
          "autoresponded": "sent", "signed": "signed"}


class DocuSignError(RuntimeError):
    pass


def _token():
    """The access token, kept DPAPI-encrypted (see secretstore)."""
    from . import secretstore
    return secretstore.get_secret("docusign_token")


def configured():
    return all(settings.get(k) for k in ("docusign_base", "docusign_account",
                                         "docusign_token"))


def _api(method, path, body=None, raw=False):
    if not configured():
        raise DocuSignError("Set up DocuSign first (base URL, account ID "
                            "and access token).")
    from . import policy
    policy.check("docusign", settings.get("docusign_base") or "")
    url = (settings.get("docusign_base").rstrip("/") +
           f"/v2.1/accounts/{settings.get('docusign_account')}" + path)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = r.read()
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("message")
        except Exception:
            msg = ""
        if e.code == 401:
            msg = "DocuSign refused the access token - it may have expired."
        raise DocuSignError(f"DocuSign: {msg or e.reason} ({e.code})")
    except urllib.error.URLError as e:
        raise DocuSignError(f"Can't reach DocuSign ({e.reason}).")
    if raw:
        return payload
    return json.loads(payload.decode("utf-8")) if payload else {}


def tabs_for(doc, fields, signer):
    out = {}
    for f in fields:
        if f["signer"] != signer:
            continue
        page = doc[f["page"]]
        r = annotate.from_page(page, __import__("fitz").Rect(f["rect"]))
        tab = {"documentId": "1", "pageNumber": str(f["page"] + 1),
               "xPosition": str(round(r.x0)), "yPosition": str(round(r.y0)),
               "tabLabel": f["id"]}
        if f["kind"] in ("text",):
            tab.update({"width": str(round(r.width)),
                        "height": str(round(r.height)),
                        "required": "true" if f["required"] else "false"})
        if f["kind"] == "checkbox":
            tab["required"] = "false"
        out.setdefault(TAB[f["kind"]], []).append(tab)
    return out


def send(path, env, doc):
    with open(path, "rb") as fh:
        pdf = base64.b64encode(fh.read()).decode("ascii")
    signers = []
    for i, s in enumerate(env["signers"]):
        signers.append({"email": s["email"], "name": s["name"],
                        "recipientId": str(i + 1),
                        "routingOrder": str(s["order"]),
                        "tabs": tabs_for(doc, env["fields"], i)})
    body = {"emailSubject": f"Please sign: {env['title']}"[:100],
            "emailBlurb": env.get("message") or "",
            "status": "sent",
            "documents": [{"documentBase64": pdf, "documentId": "1",
                           "name": os.path.basename(path),
                           "fileExtension": "pdf"}],
            "recipients": {"signers": signers}}
    r = _api("POST", "/envelopes", body)
    return {"id": r["envelopeId"], "status": "sent"}


def _env_id(env):
    """Setup first, then the envelope id - each with a clear message."""
    if not configured():
        raise DocuSignError("Set up DocuSign first (base URL, account ID "
                            "and access token).")
    eid = (env or {}).get("id") if isinstance(env, dict) else None
    if not eid or not str(eid).replace("-", "").isalnum():
        raise DocuSignError("This request has no DocuSign envelope id - "
                            "it was never sent through DocuSign.")
    return str(eid)


def status(env):
    r = _api("GET", f"/envelopes/{_env_id(env)}?include=recipients")
    st = r.get("status", "sent")
    signers = []
    for s in (r.get("recipients") or {}).get("signers") or []:
        signers.append({"name": s.get("name"), "email": s.get("email"),
                        "status": STATUS.get(s.get("status"), "sent"),
                        "signed": s.get("signedDateTime") or "",
                        "viewed": s.get("deliveredDateTime") or "",
                        "ip": "", "values": {}})
    return {"status": {"completed": "completed", "declined": "declined",
                       "voided": "voided"}.get(st, "sent"),
            "signers": signers, "events": []}


def void(env, reason=""):
    _api("PUT", f"/envelopes/{_env_id(env)}",
         {"status": "voided", "voidedReason": reason or "Cancelled"})


def download(env, out_path):
    pdf = _api("GET", f"/envelopes/{_env_id(env)}/documents/combined"
                      "?certificate=true", raw=True)
    if not pdf.startswith(b"%PDF"):
        raise DocuSignError("DocuSign didn't return a PDF.")
    with open(out_path, "wb") as f:
        f.write(pdf)
    return out_path
