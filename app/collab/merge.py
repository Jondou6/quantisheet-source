"""Apply a collaboration op log to a document.

All the drawing lives in app.annotate; this module adds the parts that only
matter when several people's ops are combined: a shared apply order and
tombstones for deleted annotations.
"""
from ..annotate import apply_op, KINDS  # noqa: F401  (re-exported)

# ops that only add something, so order does not matter
COMMUTATIVE = {"add_highlight", "add_underline", "add_strike", "add_rect",
               "add_ellipse", "add_cloud", "add_count", "add_stamp",
               "add_text", "add_note"}
# ops that change or remove existing content
OVERWRITE = {"replace_span", "add_redact", "delete_annot"}


def order_key(d):
    """The apply order every client agrees on (Lamport time, then author)."""
    return (d.get("lamport", 0), str(d.get("client_id", "")), d.get("seq", 0))


def tombstones(ops):
    """Ids of ops whose annotation a delete_annot op has removed.

    Skipping these means a deleted mark does not come back when the op that
    created it arrives late.
    """
    return {d["payload"]["target"] for d in ops
            if d.get("kind") == "delete_annot"
            and isinstance((d.get("payload") or {}).get("target"), str)}


_IDENT = ("target", "xref")


def _target(d):
    p = d.get("payload") or {}
    t = p.get("target")
    if isinstance(t, str):
        return (d.get("page"), "t", t)
    if isinstance(p.get("xref"), int):
        return (d.get("page"), "x", p["xref"])
    return None


def latest_fields(ops):
    """{(target, field): order key of the last set_annot that sets it}.
    Changes to one markup are last-writer-wins per property, in the shared
    order - so it doesn't matter in which order two people's edits arrive."""
    out = {}
    for d in ops:
        if d.get("kind") != "set_annot":
            continue
        t = _target(d)
        if t is None:
            continue
        k = order_key(d)
        for f in (d.get("payload") or {}):
            if f in _IDENT:
                continue
            if (t, f) not in out or k > out[(t, f)]:
                out[(t, f)] = k
    return out


def effective(d, latest):
    """The op to apply: a set_annot loses the properties a later edit of
    the same markup has already set (None if nothing is left)."""
    if d.get("kind") != "set_annot":
        return d
    t = _target(d)
    if t is None:
        return d
    k = order_key(d)
    p = d.get("payload") or {}
    keep = {f: v for f, v in p.items()
            if f in _IDENT or latest.get((t, f), k) <= k}
    if all(f in _IDENT for f in keep):
        return None
    if len(keep) == len(p):
        return d
    return dict(d, payload=keep)


def apply_merged(view, ops):
    """Apply a whole op set in the shared order. Safe to call repeatedly:
    ops already on the page are skipped, so nothing is ever duplicated."""
    dead = tombstones(ops)
    latest = latest_fields(ops)
    changed = 0
    for o in sorted(ops, key=order_key):
        if o.get("id") in dead:
            continue
        o = effective(o, latest)
        if o is not None:
            changed += apply_op(view.doc, o)
    if changed:
        if hasattr(view, "_pf_forget"):
            view._pf_forget()
        view._render()
    return changed
