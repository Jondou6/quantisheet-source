"""Settings, ownership slice and submission records (no Qt).

Project setting "master_schedule" holds the module's configuration;
submissions are records of the "schedsub" collection in the project
store (synced like any record; not a Project Center page)."""
import base64
import copy
import secrets

SETTING = "master_schedule"
SUBS = "schedsub"

# Jon's decided rules + the defaults chosen for his open questions
# (each one configurable; see the patch notes' OPEN list).
DEFAULTS = {
    "enabled": True,
    "inbox": "",                        # the watched shared folder
    "inbox_layout": "per_sub",          # Q3 (Jon): Dropbox, <inbox>/<Company>/
    "cycle": {"every": "month", "weekday": "Thu", "nth": 3,
              "remind_days_before": 5},  # Q2 (Jon): 3rd Thursday
    "auto_accept": {"progress_only": True, "max_slip_workdays": 0},
    "rollup": "one_line",               # Q1 (Jon): one roll-up line per sub
    "approval": "whole",                # Q7: all-or-nothing per submission
    "approver_roles": ["admin", "pm"],  # Q7 (Jon): the PM approves
    "review_msp_xer": True,             # Q6 (Jon): no real samples
    "sub_links": False,                 # Q8 (Jon): subs can't change logic
    "manual_entry_review": True,        # Q11 (Jon): yes, not preferred
    "ownership": "csi",                 # Q4 (Jon): by CSI code
    "csi_owners": {},                   # {"03 30 00": company} by hand
    "upload_links": {},                 # Q3: {company: Dropbox link}
    "web_upload": False,                # Q5 (Jon): Dropbox, no web page
    "msp_field": "Text30",              # MS Project task field: master id
    "xer_code": "QuantiSheet ID",       # P6 activity code type: master id
    "mappings": {},                     # {company: {"msp:<UID>": _id}}
    "rev": 0,
    "issued": [],
}

STATUSES = ("Received", "Rejected", "Pending review", "Auto-accepted",
            "Approved", "Declined", "Superseded", "Reverted",
            "Apply failed")
OPEN_STATUSES = ("Pending review",)


def config(store):
    """The settings with defaults filled in (a copy; reading writes
    nothing)."""
    cur = store.setting(SETTING) or {}
    out = copy.deepcopy(DEFAULTS)
    for k, v in cur.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(copy.deepcopy(v))
        else:
            out[k] = copy.deepcopy(v)
    return out


def set_config(store, **changes):
    aa = changes.get("auto_accept")
    if aa is not None:
        try:
            slip = float(aa.get("max_slip_workdays", 0) or 0)
        except (TypeError, ValueError):
            slip = -1
        if slip != 0:
            raise ValueError("Auto-accept slip threshold is zero (Jon's "
                             "rule): any later finish goes to review.")
    cur = copy.deepcopy(store.setting(SETTING) or {})
    for k, v in changes.items():
        if isinstance(v, dict) and isinstance(cur.get(k), dict):
            cur[k].update(copy.deepcopy(v))
        else:
            cur[k] = copy.deepcopy(v)
    store.set_setting(SETTING, cur)
    return config(store)


def _own(store, key, make):
    cur = copy.deepcopy(store.setting(SETTING) or {})
    if not cur.get(key):
        cur[key] = make()
        store.set_setting(SETTING, cur)
    return cur[key]


def project_id(store):
    """A random id stamped into every template (catches a template
    returned to the wrong project)."""
    return _own(store, "project_id", lambda: secrets.token_hex(8))


def template_key(store):
    """32 random bytes for the template HMAC (kept in the project)."""
    k = _own(store, "template_key",
             lambda: base64.b64encode(secrets.token_bytes(32)).decode())
    return base64.b64decode(k)


def bump_rev(store):
    cur = copy.deepcopy(store.setting(SETTING) or {})
    cur["rev"] = int(cur.get("rev") or 0) + 1
    store.set_setting(SETTING, cur)
    return cur["rev"]


def _key(text):
    return " ".join(str(text or "").split()).casefold()


def same_company(a, b):
    return bool(_key(a)) and _key(a) == _key(b)


def owner_of(act):
    return str(act.get("owner_co") or "").strip()


def is_milestone(act):
    try:
        return float(act.get("duration") or 0) == 0
    except (TypeError, ValueError):
        return False


def slice_ids(store, company):
    """Ids of the activities `company` owns. Milestones and activities
    with no owner are the GC's and are never in a sub's slice."""
    return [a["_id"] for a in store.list("activity")
            if same_company(owner_of(a), company) and not is_milestone(a)]


def companies(store):
    """Subcontractor companies: the Directory's, plus any owner typed on
    an activity (sorted, case-insensitively unique)."""
    seen = {}
    for m in store.list("member"):
        c = str(m.get("company") or "").strip()
        if c:
            seen.setdefault(_key(c), c)
    for a in store.list("activity"):
        c = owner_of(a)
        if c:
            seen.setdefault(_key(c), c)
    return sorted(seen.values(), key=_key)


def csi_of(act):
    """The activity's CSI section: its Cost code, else a section number
    at the start of its name or id ("033000 Footings", "03 30 00 ...")."""
    from ..store import spec_number
    for v in (act.get("cost_code"), act.get("name"), act.get("ext_id"),
              act.get("id")):
        n = spec_number(str(v or ""))
        if n:
            return n.split(".")[0]
    return ""


def _company_for(store, who):
    """A commitment vendor / bidder: a Directory person's company, or the
    company name itself."""
    w = str(who or "").strip().lstrip("@")
    for m in store.list("member"):
        if _key(m.get("name")) == _key(w) or m.get("_id") == w:
            return str(m.get("company") or "").strip() or w
    return w


def csi_owners(store):
    """Q4 (Jon, Oct 28): who owns which CSI section. {section: [company]}
    from, in order of trust: the Settings table (by hand), subcontracts
    in Commitments (vendor + schedule-of-values cost codes; Draft counts,
    Void doesn't), then awarded Bid Packages. Concrete: '03 30 00' ->
    the concrete sub."""
    from ..store import spec_number
    out = {}

    def add(code, company, src):
        n = spec_number(str(code or "")).split(".")[0]
        company = str(company or "").strip()
        if not n or not company:
            return
        lst = out.setdefault(n, [])
        if not any(same_company(c, company) for c, _s in lst):
            lst.append((company, src))

    hand = {k: v for k, v in (config(store).get("csi_owners") or {}).items()
            if v}
    for code, company in hand.items():
        add(code, company, "Settings")
    for c in store.list("commitment"):
        if c.get("status") in ("Void",) or \
                (c.get("type") or "Subcontract") != "Subcontract":
            continue
        who = _company_for(store, c.get("vendor"))
        for ln in c.get("lines") or []:
            add(ln.get("cost_code"), who, c.get("_no") or "Commitment")
    for b in store.list("bidpkg"):
        if b.get("status") == "Awarded" and b.get("awarded_to"):
            add(b.get("trades"), b.get("awarded_to"),
                b.get("_no") or "Bid package")
    return out


def owner_by_csi(owners, section):
    """(company, why) for an activity's section, or (None, why).
    Exact section first (03 30 00); else the same group (03 3x xx, e.g.
    03 31 13 under a 03 30 00 sub); else the division (03) when only one
    sub has it. A section with two different subs isn't guessed.
    Settings entries win over Commitments / bids."""
    if not section:
        return None, "no CSI code"

    def pick(lst, how):
        hand = [c for c, s in lst if s == "Settings"]
        if hand:
            return hand[0], f"{how} (Settings)"
        names = {_key(c): c for c, _s in lst}
        if len(names) == 1:
            c, s = lst[0]
            return c, f"{how} ({s})"
        return None, f"{how}: more than one sub (" + \
            ", ".join(sorted(names.values())) + ") - pick by hand"

    if section in owners:
        return pick(owners[section], f"CSI {section}")
    d = section.replace(" ", "")
    for width, how in ((3, "same CSI group"), (2, "same division")):
        lst = []
        for code, l in owners.items():
            if code.replace(" ", "")[:width] == d[:width]:
                lst.extend(l)
        if lst:
            return pick(lst, f"{how} as {d[:2]} {d[2:4]} {d[4:6]}")
    return None, f"CSI {section}: no sub has this section"


def propose_owners(store):
    """'Assign subs' helper. Q4 (Jon): by CSI code - the activity's
    section matched to the sub holding that section (csi_owners); an
    activity with no CSI match falls back to its Responsible person's
    Directory company. Only a proposal - nothing is written until
    apply_owners(..., confirm=True)."""
    comp = {_key(m.get("name")): str(m.get("company") or "").strip()
            for m in store.list("member")}
    by_csi = config(store).get("ownership", "csi") == "csi"
    owners = csi_owners(store) if by_csi else {}
    out = []
    for a in store.list("activity"):
        if owner_of(a) or is_milestone(a):
            continue
        c, why = (owner_by_csi(owners, csi_of(a)) if by_csi
                  else (None, ""))
        if not c:
            c = comp.get(_key(a.get("responsible")), "")
            if c:
                why = "Responsible person's company"
        if c:
            out.append({"_id": a["_id"], "_no": a.get("_no"),
                        "name": a.get("name"), "csi": csi_of(a),
                        "responsible": a.get("responsible"), "company": c,
                        "why": why})
    return out


def unassigned(store):
    """Activities still without an owner after the CSI / Responsible
    proposal, with the reason (for the Assign subs list)."""
    have = {p["_id"] for p in propose_owners(store)}
    owners = csi_owners(store)
    out = []
    for a in store.list("activity"):
        if owner_of(a) or is_milestone(a) or a["_id"] in have:
            continue
        out.append({"_id": a["_id"], "_no": a.get("_no"),
                    "name": a.get("name"),
                    "why": owner_by_csi(owners, csi_of(a))[1]})
    return out


def apply_owners(store, proposals, confirm=False):
    if not confirm:
        raise PermissionError("Assigning owners needs Jon's confirmation.")
    n = 0
    for p in proposals:
        a = store.get("activity", p["_id"])
        if a is None or owner_of(a):
            continue
        a["owner_co"] = p["company"]
        store.save_record("activity", a)
        n += 1
    return n


def can_approve(store):
    """Q7 (Jon, Oct 28): the project manager approves a sub's update.
    On a shared project that's the Project manager (or Admin) login;
    a project on this PC alone has no logins and you are its admin."""
    return getattr(store, "role", "admin") in \
        (config(store).get("approver_roles") or ["admin", "pm"])


def need_approver(store):
    if not can_approve(store):
        raise PermissionError("Only the project manager approves, declines "
                              "or reverts a sub's schedule update.")


def label(sub):
    return f"SS-{int(sub.get('_n') or 0):04d}"


def submissions(store):
    return store.list(SUBS)
