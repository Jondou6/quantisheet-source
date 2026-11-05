"""E-signature requests: fields, sending through the hub, signing order,
the signed copy with certificate and seal, DocuSign, and the dialogs."""
import base64
import json
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import esign, mail, settings                         # noqa: E402
from app.collab import hub as hubmod                          # noqa: E402

PNG = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 12), 0)
PNG.clear_with(40)
SIG = base64.b64encode(PNG.tobytes("png")).decode()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan",
                                             "email": "jon@example.com"})
    monkeypatch.setattr(mail, "OUTBOX", [])
    H = hubmod.Hub(str(tmp_path / "hub"))

    class Client:
        url, token = "wss://relay.example.com/", "tok"

        def __init__(self, *a, **k):
            pass

        def call(self, op, **args):
            return H.call(op, json.loads(json.dumps(args)),
                          {"ip": "203.0.113.9", "agent": "test"}, True)
    from app.collab import hubclient
    monkeypatch.setattr(hubclient, "HubClient", Client)
    return tmp_path, H, Client


def _contract(path, rotate=0):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 80), "SUBCONTRACT AGREEMENT", fontsize=16)
    p.insert_text((72, 600), "Signature ____________________", fontsize=11)
    p.insert_text((330, 600), "Date ______________", fontsize=11)
    p.insert_text((72, 650), "Signature ____________________", fontsize=11)
    if rotate:
        p.set_rotation(rotate)
    d.save(str(path))
    return path


def _fields(path, layout):
    d = fitz.open(str(path))
    for pno, kind, signer, rect in layout:
        from app import annotate
        annotate.apply_op(d, annotate.new_op(
            "add_rect", pno, **esign.field_payload(kind, signer, rect)))
    d.saveIncr()
    d.close()


def test_two_signers_in_order(env):
    tmp, H, Client = env
    path = _contract(tmp / "SC-002.pdf")
    _fields(path, [(0, "signature", 0, (120, 576, 260, 604)),
                   (0, "date", 0, (360, 588, 450, 604)),
                   (0, "signature", 1, (120, 626, 260, 654))])
    doc = fitz.open(str(path))
    fl = esign.fields(doc)
    assert [(f["kind"], f["signer"]) for f in fl] == \
        [("signature", 0), ("date", 0), ("signature", 1)]
    doc.close()
    signers = [{"name": "Lee Volt", "email": "lee@volt.example", "order": 1},
               {"name": "Pat Morgan", "email": "jon@example.com",
                "order": 2}]
    e = esign.send(str(path), signers, "Electrical subcontract",
                   "Please sign by Friday.", client=Client())
    assert e["signers"][0]["link"].startswith(
        "https://relay.example.com/sign.html?t=")
    assert [m["to"] for m in mail.OUTBOX] == [["lee@volt.example"]]
    t1, t2 = (s["token"] for s in e["signers"])
    # the second signer waits for the first
    o2 = H.call("sign.open", {"token": t2}, {}, authed=False)
    assert not o2["can_sign"] and "before you" in o2["why"]
    o1 = H.call("sign.open", {"token": t1}, {"ip": "198.51.100.4"},
                authed=False)
    assert o1["can_sign"] and len(o1["fields"]) == 2
    st, ctype, png = H.get(f"/hub/env/{e['id']}/p0.png?t={t1}")
    assert st == 200 and png.startswith(b"\x89PNG")
    assert H.get(f"/hub/env/{e['id']}/p0.png?t=nope")[0] == 403
    with pytest.raises(hubmod.HubError, match="agree"):
        H.call("sign.submit", {"token": t1, "values": {"f1": SIG}}, {},
               authed=False)
    H.call("sign.submit", {"token": t1, "values": {"f1": SIG},
                           "consent": True}, {"ip": "198.51.100.4"},
           authed=False)
    st = esign.status(e, Client())
    assert st["status"] == "sent"
    assert esign.notify_ready(e, st) == 1          # now Jon's turn
    assert mail.OUTBOX[-1]["to"] == ["jon@example.com"]
    with pytest.raises(esign.ESignError, match="Not everyone"):
        esign.finish(e, st=st)
    H.call("sign.submit", {"token": t2, "values": {"f3": SIG},
                           "consent": True}, {}, authed=False)
    out = esign.finish(e, st=esign.status(e, Client()), seal=False)
    signed = fitz.open(out)
    assert signed.page_count == 2
    assert len(signed[0].get_images()) == 2         # both signatures
    assert not esign.fields(signed)                 # boxes are gone
    import datetime
    assert datetime.date.today().isoformat()[:4] in signed[0].get_text()
    cert = signed[1].get_text()
    for want in ("Certificate of Completion", "Lee Volt", "Pat Morgan",
                 e["sha256"], "198.51.100.4", "signed"):
        assert want in cert, want


def test_changed_pdf_and_decline(env):
    tmp, H, Client = env
    path = _contract(tmp / "c.pdf")
    _fields(path, [(0, "signature", 0, (120, 576, 260, 604))])
    e = esign.send(str(path), [{"name": "A", "email": "a@x.example"}],
                   client=Client())
    t = e["signers"][0]["token"]
    H.call("sign.submit", {"token": t, "values": {"f1": SIG},
                           "consent": True}, {}, authed=False)
    d = fitz.open(str(path))
    d[0].insert_text((72, 700), "changed after sending")
    d.saveIncr()
    d.close()
    with pytest.raises(esign.ESignError, match="changed after"):
        esign.finish(e, st=esign.status(e, Client()))
    path2 = _contract(tmp / "d.pdf")
    _fields(path2, [(0, "signature", 0, (120, 576, 260, 604))])
    e2 = esign.send(str(path2), [{"name": "B", "email": "b@x.example"}],
                    client=Client())
    H.call("sign.decline", {"token": e2["signers"][0]["token"],
                            "reason": "Wrong amount"}, {}, authed=False)
    st = esign.status(e2, Client())
    assert st["status"] == "declined"
    assert st["signers"][0]["decline_reason"] == "Wrong amount"
    # a signer with no signature box is refused before anything is sent
    path3 = _contract(tmp / "e.pdf")
    _fields(path3, [(0, "date", 0, (360, 588, 450, 604))])
    with pytest.raises(esign.ESignError, match="no signature"):
        esign.send(str(path3), [{"name": "C", "email": "c@x.example"}],
                   client=Client())


def test_rotated_page_fields_line_up(env):
    tmp, H, Client = env
    path = _contract(tmp / "r.pdf", rotate=90)
    d = fitz.open(str(path))
    from app import annotate
    shown = fitz.Rect(500, 100, 560, 240)           # as seen on screen
    op_rect = annotate.to_page(d[0], shown)
    d.close()
    _fields(path, [(0, "signature", 0, op_rect)])
    e = esign.send(str(path), [{"name": "R", "email": "r@x.example"}],
                   client=Client())
    o = H.call("sign.open", {"token": e["signers"][0]["token"]}, {},
               authed=False)
    assert o["pages"][0]["w"] == 842                 # A4 landscape as shown
    r = o["fields"][0]["rect"]
    assert abs(r[0] - 500) < 1 and abs(r[3] - 240) < 1


def test_auto_place_finds_signature_lines(env):
    tmp, H, Client = env
    d = fitz.open(str(_contract(tmp / "a.pdf")))
    marks = esign.auto_place(d)
    kinds = sorted(json.loads(json.dumps(m[2]))["subject"].split(":")[1]
                   for m in marks)
    assert kinds == ["date", "signature", "signature"]


def test_docusign(env, monkeypatch):
    tmp, H, Client = env
    from app import esign_docusign as ds
    settings.set("docusign_base", "https://demo.docusign.net/restapi")
    settings.set("docusign_account", "acct-1")
    settings.set("docusign_token", "tkn")
    calls = []

    class Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake(req, timeout=60):
        calls.append((req.get_method(), req.full_url,
                      json.loads(req.data) if req.data else None,
                      req.headers.get("Authorization")))
        if req.get_method() == "POST":
            return Resp(b'{"envelopeId": "ds-env-9", "status": "sent"}')
        if "documents/combined" in req.full_url:
            return Resp(b"%PDF-1.7 signed by docusign")
        return Resp(json.dumps({"status": "completed", "recipients": {
            "signers": [{"name": "Lee Volt", "email": "lee@volt.example",
                         "status": "completed",
                         "signedDateTime": "2026-10-16T14:00:00Z"}]}})
            .encode())
    monkeypatch.setattr(ds.urllib.request, "urlopen", fake)
    path = _contract(tmp / "ds.pdf")
    _fields(path, [(0, "signature", 0, (120, 576, 260, 604)),
                   (0, "date", 0, (360, 588, 450, 604))])
    e = esign.send(str(path), [{"name": "Lee Volt",
                                "email": "lee@volt.example"}],
                   provider="docusign")
    method, url, body, auth = calls[0]
    assert method == "POST" and url.endswith("/v2.1/accounts/acct-1/"
                                             "envelopes")
    assert auth == "Bearer tkn"
    tabs = body["recipients"]["signers"][0]["tabs"]
    assert tabs["signHereTabs"][0]["xPosition"] == "120"
    assert tabs["signHereTabs"][0]["yPosition"] == "576"
    assert "dateSignedTabs" in tabs
    assert e["id"] == "ds-env-9" and not mail.OUTBOX   # DocuSign emails
    st = esign.status(e)
    assert st["status"] == "completed" and \
        st["signers"][0]["status"] == "signed"
    out = esign.finish(e)
    assert open(out, "rb").read().startswith(b"%PDF")


def test_dialog_places_fields(qapp, win, tmp_path, monkeypatch):
    monkeypatch.setattr(mail, "OUTBOX", [])
    from app.esign_ui import RequestDialog, TrackerDialog
    path = _contract(tmp_path / "w.pdf")
    win.open_path(str(path))
    d = RequestDialog(win)
    d.show()
    d._auto()
    assert "3 field" in d.count.text()
    d.kind.setCurrentIndex(1)                        # initials
    d.who.setCurrentIndex(1)
    d._draw()
    v = win._view
    assert v.tool == "esign_field" and v.esign_spec == ("initials", 1)
    v.commit_rect("esign_field", fitz.Rect(100, 100, 180, 130))
    fl = esign.fields(v.doc)
    assert ("initials", 1) in [(f["kind"], f["signer"]) for f in fl]
    win.undo()
    assert len(esign.fields(v.doc)) == 3
    d.close()
    t = TrackerDialog(win)
    assert t.table.rowCount() == 0
    t.close()


from test_gui import win, qapp                                   # noqa
