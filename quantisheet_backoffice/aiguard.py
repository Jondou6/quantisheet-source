"""Keeps personal data away from the local model (P3-01 / P3-05 / P3-06).

prepare(office, text) is called on every prompt before it is sent:
1. pattern scrub: SSN-shaped numbers, tax IDs, long digit runs (bank,
   routing, card and phone numbers), e-mail addresses;
2. this company's own protected values, decrypted in memory only to
   compare: every employee SSN, date of birth, routing and account number,
   phone, e-mail and address; every vendor tax ID and bank number;
3. people's names - every time-entry worker (workers.name) and employee -
   matched on word boundaries, case-insensitive, in the forms 'First Last',
   'Last, First', 'Last First', 'LAST F', 'F. Last' and 'F Last' (so 'Ann'
   never touches 'ANNUAL');
4. a final check: if any protected value or name is still in the text the
   prompt is refused (PIIBlocked) and nothing is sent.
"""
from __future__ import annotations

import re


class PIIBlocked(RuntimeError):
    """A prompt still held personal data after scrubbing; not sent."""


SSN = re.compile(r"(?<!\d)\d{3}[- ]\d{2}[- ]\d{4}(?!\d)")
EIN = re.compile(r"(?<!\d)\d{2}-\d{7}(?!\d)")
LONG_DIGITS = re.compile(r"(?<![\d.,$])\d[\d -]{5,}\d(?![\d]|\.\d\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}/\d{1,2}/\d{2,4}$")
SENSITIVE_EMP = ("ssn", "dob", "bank_routing", "bank_account")
PLAIN_EMP = ("phone", "email", "address")
EDGE_L, EDGE_R = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"


def _digits(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def name_forms(name: str) -> list[str]:
    """The ways a person's name shows up in bank lines and notes."""
    toks = [t for t in re.split(r"[\s,]+", (name or "").strip()) if t]
    if not toks:
        return []
    if len(toks) == 1:
        return [toks[0]] if len(toks[0]) >= 2 else []
    first, last = toks[0].rstrip("."), toks[-1].rstrip(".")
    i = first[0]
    forms = {" ".join(toks), f"{first} {last}", f"{last}, {first}",
             f"{last} {first}", f"{last} {i}", f"{i}. {last}",
             f"{i} {last}", f"{last}, {i}"}
    return sorted((f for f in forms if len(f.replace(" ", "")) >= 3),
                  key=len, reverse=True)


def _name_re(form: str):
    parts = [re.escape(p) for p in re.split(r"\s+", form.strip())]
    body = r"[\s,]+".join(p.replace(r"\.", r"\.?") for p in parts)
    return re.compile(EDGE_L + body + EDGE_R, re.I)


def protected_values(office) -> dict:
    """{'numbers': digit strings, 'texts': exact strings, 'names': regex
    list}."""
    nums, texts, names = set(), set(), []
    c = office.crypto

    def add(v):
        v = (v or "").strip()
        if not v:
            return
        if len(v) >= 4:
            texts.add(v)
        d = _digits(v)
        if len(d) >= 6:
            nums.add(d)

    people = {r["name"] for r in office.db.rows(
        "SELECT name FROM workers WHERE name IS NOT NULL")}
    for e in office.db.rows("SELECT * FROM employees"):
        people.add(e["name"])
        for f in SENSITIVE_EMP:
            add(c.decrypt(e[f]) if e[f] else "")
        for f in PLAIN_EMP:
            v = e.get(f) or ""
            if f == "address":
                for ln in v.splitlines():
                    add(ln)
            else:
                add(v)
    for v in office.db.rows("SELECT tax_id, bank FROM vendors"):
        for f in ("tax_id", "bank"):
            add(c.decrypt(v[f]) if v[f] else "")
    seen = set()
    for p in people:
        for f in name_forms(p or ""):
            if f.lower() not in seen:
                seen.add(f.lower())
                names.append(_name_re(f))
    return {"numbers": nums, "texts": texts, "names": names}


def scrub(text: str, values: dict | None = None) -> str:
    out = text or ""
    if values:
        for t in sorted(values["texts"], key=len, reverse=True):
            out = re.sub(EDGE_L + re.escape(t) + EDGE_R, "[protected]", out,
                         flags=re.I) if t[0].isalnum() and \
                t[-1].isalnum() else out.replace(t, "[protected]")
        for rx in values["names"]:
            out = rx.sub("[person]", out)
    out = SSN.sub("[id]", out)
    out = EIN.sub("[id]", out)
    out = EMAIL.sub("[email]", out)
    out = LONG_DIGITS.sub(
        lambda m: m.group(0) if DATE_LIKE.match(m.group(0)) else "[number]",
        out)
    return out


def check(text: str, values: dict) -> None:
    joined = re.sub(r"(?<=\d)[ -](?=\d)", "", text)
    for d in values["numbers"]:
        if re.search(r"(?<!\d)" + re.escape(d) + r"(?!\d)", joined):
            raise PIIBlocked("A protected number was found in an AI prompt; "
                             "nothing was sent.")
    low = text.lower()
    for t in values["texts"]:
        if t.lower() in low and (not t[0].isalnum() or re.search(
                EDGE_L + re.escape(t) + EDGE_R, text, re.I)):
            raise PIIBlocked("Protected personal data was found in an AI "
                             "prompt; nothing was sent.")
    for rx in values["names"]:
        if rx.search(text):
            raise PIIBlocked("A person's name was found in an AI prompt; "
                             "nothing was sent.")
    if SSN.search(text):
        raise PIIBlocked("An SSN-shaped number was found in an AI prompt; "
                         "nothing was sent.")


def prepare(office, text: str) -> str:
    vals = protected_values(office)
    out = scrub(text, vals)
    check(out, vals)
    return out


def scrub_for_log(office, text: str) -> str:
    """The same scrub, for text Back Office stores (never raises)."""
    try:
        return scrub(text, protected_values(office))
    except Exception:                                     # noqa: BLE001
        return scrub(text)
