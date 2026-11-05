"""Project > Allowances: the owner contract's allowances (name, amount,
spent so far), which the owner report pack prints with what's left
(owner_report_auto reads the "allowances" project setting)."""
from ..dmoney import bad

SETTING = "allowances"


class AllowanceError(ValueError):
    pass


def _money(v):
    t = str(v if v is not None else "").replace(",", "").replace(
        "$", "").strip()
    if not t:
        return 0.0
    if bad(t):
        raise AllowanceError(f"can't read {v!r} as an amount")
    return round(float(t), 2)


def read(store):
    out = []
    for a in store.setting(SETTING) or ():
        if isinstance(a, dict) and str(a.get("name") or "").strip():
            out.append({"name": str(a["name"]).strip(),
                        "amount": _money(a.get("amount")),
                        "spent": _money(a.get("spent"))})
    return out


def save(store, rows):
    """rows [{name, amount, spent}] (text or numbers); blank rows are
    dropped. Every problem is listed and nothing is saved."""
    clean, probs, seen = [], [], set()
    for i, r in enumerate(rows, 1):
        name = " ".join(str(r.get("name") or "").split())
        if not name and not str(r.get("amount") or "").strip() and \
                not str(r.get("spent") or "").strip():
            continue
        if not name:
            probs.append(f"row {i}: a name is needed")
            continue
        if name.lower() in seen:
            probs.append(f"row {i}: {name} is listed twice")
            continue
        seen.add(name.lower())
        try:
            amt, spent = _money(r.get("amount")), _money(r.get("spent"))
        except AllowanceError as e:
            probs.append(f"row {i}: {e}")
            continue
        if amt < 0 or spent < 0:
            probs.append(f"row {i}: amounts can't be negative")
            continue
        clean.append({"name": name[:80], "amount": amt, "spent": spent})
    if probs:
        raise AllowanceError("\n".join(probs))
    store.set_setting(SETTING, clean)
    return clean
