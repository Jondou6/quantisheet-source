import json

from . import annotate


class Recorder:
    def __init__(self):
        self.ops = []
        self.on = False

    def start(self):
        self.ops = []
        self.on = True

    def stop(self):
        self.on = False
        return list(self.ops)

    def record(self, op):
        if self.on:
            self.ops.append(dict(op))


# what a macro may add: new markups only (review 2, Nov 4 - Venice #2). Not
# redaction, text or image edits, form fields, scales, edits to existing
# markups or deletes - before, anything in annotate.KINDS but delete_annot
# was replayed.
MACRO_KINDS = frozenset({
    "add_highlight", "add_underline", "add_strike", "add_rect",
    "add_ellipse", "add_cloud", "add_stamp", "add_textbox", "add_callout",
    "add_count", "add_text", "add_note", "add_line", "add_polyline",
    "add_polygon", "add_ink", "add_legend"})


def _clean(op):
    """Validate one recorded op from a (possibly hand-edited) macro file."""
    if not isinstance(op, dict):
        return None
    kind, page = op.get("kind"), op.get("page")
    if kind not in MACRO_KINDS:
        return None
    if not isinstance(page, int) or isinstance(page, bool) or page < 0:
        return None
    payload = {k: v for k, v in op.items() if k not in ("kind", "page")}
    return page, kind, payload


def replay(view, ops):
    """Re-apply recorded ops. Returns how many were applied.

    Goes through the view, so replayed marks look like hand-made ones, keep
    their recorded colours, are shared with collaborators and can be undone.
    """
    marks = [m for m in map(_clean, ops or []) if m]
    marks = [m for m in marks if m[0] < view.doc.page_count]
    if hasattr(view, "apply_marks"):
        return view.apply_marks(marks)
    n = sum(annotate.apply_op(view.doc, annotate.new_op(k, p, **pl))
            for p, k, pl in marks)
    view._render()
    return n


FORMAT = 1              # macro file version (review QS-026, Nov 4)


def _signing_key():
    """This user's macro-signing key (Ed25519), made on first use, kept in
    the data folder; the public half is what others trust."""
    import os
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import \
        Ed25519PrivateKey
    from . import settings
    p = os.path.join(settings.DIR, "macro_signing.key")
    if os.path.isfile(p):
        with open(p, "rb") as f:
            return serialization.load_pem_private_key(f.read(), None)
    k = Ed25519PrivateKey.generate()
    os.makedirs(settings.DIR, exist_ok=True)
    with open(p, "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()))
    return k


def _canonical(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")


def my_signer_id():
    """The public key others add to their trusted list (base64)."""
    import base64
    from cryptography.hazmat.primitives import serialization
    pub = _signing_key().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(pub).decode("ascii")


def save_macro(path, ops, name="macro", sign=True):
    """Write the macro; signed with this user's macro key (Venice #2)."""
    import base64
    import getpass
    from . import __version__
    body = {"format": FORMAT, "app": __version__, "name": name, "ops": ops}
    if sign:
        try:
            who = getpass.getuser()
        except Exception:                                 # noqa: BLE001
            who = ""
        body["signer"] = {"name": who, "key": my_signer_id()}
        body["sig"] = base64.b64encode(_signing_key().sign(
            _canonical({k: v for k, v in body.items() if k != "sig"}))
        ).decode("ascii")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2)


def trusted_keys():
    from . import settings
    return set(settings.get("macro_trusted_keys") or [])


def trust(key):
    from . import settings
    settings.set("macro_trusted_keys", sorted(trusted_keys() | {key}))


def signature(data):
    """("trusted" | "signed" | "bad" | "unsigned", signer name)."""
    import base64
    if not isinstance(data, dict) or "sig" not in data:
        return "unsigned", ""
    signer = data.get("signer") or {}
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import \
            Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(
            signer.get("key", "")))
        pub.verify(base64.b64decode(data["sig"]), _canonical(
            {k: v for k, v in data.items() if k != "sig"}))
    except Exception:                                     # noqa: BLE001
        return "bad", str(signer.get("name") or "")
    key = signer.get("key")
    mine = False
    try:
        mine = key == my_signer_id()
    except Exception:                                     # noqa: BLE001
        pass
    return ("trusted" if mine or key in trusted_keys() else "signed"), \
        str(signer.get("name") or "")


def preflight(ops, doc):
    """What a macro will do here before it runs: {"ok": n, "skipped":
    [(index, why)], "newer": bool}. Only markups are ever replayed (no
    deletes, no commands); anything else is listed and left out."""
    ok, skipped = 0, []
    for i, op in enumerate(ops or []):
        m = _clean(op)
        if m is None:
            kind = op.get("kind") if isinstance(op, dict) else None
            skipped.append((i, "deleting isn't replayed" if
                            kind == "delete_annot" else
                            "only new markups are replayed (not "
                            f"{kind!r})" if kind in annotate.KINDS else
                            f"unknown step {kind!r}" if kind else
                            "not a markup step"))
        elif m[0] >= doc.page_count:
            skipped.append((i, f"page {m[0] + 1} isn't in this file"))
        else:
            ok += 1
    return {"ok": ok, "skipped": skipped}


def load_macro_info(path):
    """(ops, {"signature": "trusted" | "signed" | "bad" | "unsigned",
    "signer": name, "dropped": n}). Only new-markup steps come back -
    the rest are dropped right here, not only in the preflight."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    raw = load_macro(path)
    keep = [op for op in raw if _clean(op) is not None]
    state, who = signature(data)
    if state == "bad":
        raise ValueError("the macro's signature doesn't match - it was "
                         "changed after it was signed; not played")
    return keep, {"signature": state, "signer": who,
                  "key": (data.get("signer") or {}).get("key", "")
                  if isinstance(data, dict) else "",
                  "dropped": len(raw) - len(keep)}


def load_macro(path):
    """Returns the list of ops in a macro file (raises ValueError if bad)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ops = data.get("ops") if isinstance(data, dict) else data
    if not isinstance(ops, list):
        raise ValueError("not a QuantiSheet macro file")
    fmt = data.get("format", 1) if isinstance(data, dict) else 1
    if isinstance(fmt, int) and fmt > FORMAT:
        raise ValueError(f"made by a newer QuantiSheet "
                         f"({data.get('app') or 'unknown'}) - update to "
                         "play it")
    return ops
