"""Ask the local model to fill a closed fact schema. Never to write a schedule.

One spec section (or a short slice of one) per request. The answer has to
be JSON with a fixed set of keys. A malformed answer is rejected and the
slice is tried once more. Durations in the answer are notes, not numbers
the schedule will use.

The request goes through the program's existing local path
(``app.ai.review._ollama``), which only talks to localhost unless an
administrator has set a host. Tests pass ``ask`` and never open a socket.
"""
import json

SCHEMA_KEYS = (
    "activities", "long_lead", "submittals", "inspections", "tests",
    "phasing", "sequencing", "milestones", "duration_hints",
    "owner_furnished", "commissioning", "by_others",
)

_LISTS = {
    "activities": ("name", "division", "spec_section"),
    "long_lead": ("item", "lead_time_days"),
    "submittals": ("item", "review_days"),
    "inspections": ("name",),
    "tests": ("name",),
    "phasing": ("name", "note"),
    "sequencing": ("before", "after"),
    "milestones": ("name",),
    "duration_hints": ("activity", "note"),
    "owner_furnished": ("item",),
    "commissioning": ("name",),
    "by_others": ("item",),
}

PROMPT = """You extract scheduling FACTS from one specification section.
Reply with JSON only. Do not write a schedule, do not invent durations, and do not summarize the section.
Use only what this text says. Unknown lists must be empty.
The JSON object must have exactly these keys:
activities, long_lead, submittals, inspections, tests, phasing, sequencing, milestones, duration_hints, owner_furnished, commissioning, by_others.
activities items are {{"name", "division", "spec_section"}}.
long_lead items are {{"item", "lead_time_days"}} and lead_time_days is a number only when the text states one, otherwise null.
duration_hints items are {{"activity", "note"}} and the note is words, not a duration to schedule.
sequencing items are {{"before", "after"}} meaning before finishes before after starts.
Section {section}, page {page}.
TEXT:
{text}
"""


class SchemaError(ValueError):
    pass


def _num_or_null(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise SchemaError("number was a boolean")
    if isinstance(value, (int, float)):
        return value
    raise SchemaError("number was not a number")


def validate(payload):
    """Raise SchemaError when the payload is not the closed schema."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as exc:
            raise SchemaError("not JSON") from exc
    if not isinstance(payload, dict):
        raise SchemaError("not an object")
    extra = set(payload) - set(SCHEMA_KEYS)
    missing = set(SCHEMA_KEYS) - set(payload)
    if extra or missing:
        raise SchemaError(
            "keys must be exactly the schema "
            f"(extra {sorted(extra)}, missing {sorted(missing)})")
    for key, fields in _LISTS.items():
        rows = payload[key]
        if not isinstance(rows, list):
            raise SchemaError(f"{key} is not a list")
        for row in rows:
            if not isinstance(row, dict):
                raise SchemaError(f"{key} item is not an object")
            if set(row) - set(fields):
                raise SchemaError(f"{key} item has unknown fields")
            for field in fields:
                if field not in row:
                    raise SchemaError(f"{key} item missing {field}")
                value = row[field]
                if field in ("lead_time_days", "review_days"):
                    _num_or_null(value)
                elif not isinstance(value, str):
                    raise SchemaError(f"{key}.{field} is not text")
    return payload


def _chunks(text, size):
    text = text or ""
    if len(text) <= size:
        return [text] if text.strip() else []
    parts, buf = [], ""
    for para in text.split("\n"):
        if buf and len(buf) + len(para) + 1 > size:
            parts.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf.strip():
        parts.append(buf)
    return parts or [text[:size]]


def facts_from_payload(payload, section, page):
    """Model output becomes facts. Duration hints stay notes.

    A section or page the model names that is not THIS slice is dropped,
    so a citation cannot point at a page the slice did not contain.
    """
    out = []
    sec = section or ""
    for row in payload.get("long_lead") or []:
        if row.get("lead_time_days") is None:
            continue
        out.append(_ai("long_lead", row["item"], sec, page,
                       value=row["lead_time_days"], unit="calendar",
                       basis="model extracted a stated lead time"))
    for row in payload.get("submittals") or []:
        out.append(_ai("submittal", row["item"], sec, page,
                       value=row.get("review_days"), unit="calendar"))
    for row in payload.get("inspections") or []:
        out.append(_ai("inspection", row["name"], sec, page))
    for row in payload.get("tests") or []:
        out.append(_ai("test", row["name"], sec, page))
    for row in payload.get("phasing") or []:
        out.append(_ai("phasing", row["name"], sec, page, text=row.get("note")))
    for row in payload.get("sequencing") or []:
        out.append(_ai("sequence", row["before"], sec, page, value=row["after"]))
    for row in payload.get("milestones") or []:
        out.append(_ai("milestone", row["name"], sec, page))
    for row in payload.get("owner_furnished") or []:
        out.append(_ai("owner_furnished", row["item"], sec, page))
    for row in payload.get("commissioning") or []:
        out.append(_ai("commissioning", row["name"], sec, page))
    for row in payload.get("by_others") or []:
        out.append(_ai("by_others", row["item"], sec, page))
    for row in payload.get("duration_hints") or []:
        out.append(_ai("duration_hint", row["activity"], sec, page,
                       text=row.get("note") or ""))
    for row in payload.get("activities") or []:
        named = (row.get("spec_section") or "").strip()
        if named and named != sec:
            continue
        div = (row.get("division") or "")[:2]
        if div and sec and not sec.startswith(div):
            continue
        out.append(_ai("activity_name", row["name"], sec, page, division=div))
    return out


def _ai(kind, item, section, page, **kw):
    return {
        "kind": kind,
        "item": " ".join(str(item or "").split())[:120],
        "spec_section": section,
        "page": page,
        "source": "model",
        "text": " ".join(str(kw.get("text") or item or "").split())[:240],
        "division": kw.get("division") or (section[:2] if section else ""),
        "value": kw.get("value"),
        "unit": kw.get("unit") or "",
        "consumer": "",
        "basis": kw.get("basis") or "model",
    }


def extract_sections(sections, ask, model, fallback, chunk_chars, progress=None,
                     allow=True):
    """``ask(prompt, model) -> str``. Returns ``(facts, errors)``.

    Each slice is validated. One retry on a bad answer. If the recommended
    model is not installed, the slice is tried on the fallback model.
    """
    if not allow or ask is None:
        return [], []
    facts, errors = [], []
    jobs = []
    for sec in sections or ():
        for piece in _chunks(sec.get("text") or "", int(chunk_chars or 3500)):
            jobs.append((sec, piece))
    total = len(jobs)
    for i, (sec, piece) in enumerate(jobs, 1):
        page = (sec.get("pages") or [None])[0]
        prompt = PROMPT.format(section=sec.get("number") or "",
                               page=page if page is not None else "",
                               text=piece[:chunk_chars])
        if progress:
            progress({"stage": "model", "index": i, "total": total,
                      "message": f"Reading section {sec.get('number') or ''} "
                                 f"({i} of {total})"})
        payload, err = _call(ask, prompt, model, fallback)
        if err:
            errors.append({"section": sec.get("number"), "page": page,
                           "error": err})
            continue
        facts.extend(facts_from_payload(payload, sec.get("number") or "", page))
    return facts, errors


def _call(ask, prompt, model, fallback):
    last = ""
    models = [model] if model == fallback or not fallback else [model, fallback]
    # Retry a malformed answer once on the same model before falling back.
    tried_fallback = False
    for use in models:
        attempts = 2 if use == model else 1
        for _ in range(attempts):
            try:
                raw = ask(prompt, use)
            except Exception as exc:                    # noqa: BLE001
                last = str(exc)[:300]
                missing = "isn't installed" in last or "not found" in last.lower()
                if missing and use != fallback and not tried_fallback:
                    tried_fallback = True
                    break
                return None, last
            try:
                return validate(raw), ""
            except SchemaError as exc:
                last = str(exc)
        else:
            continue
        continue
    return None, last or "no answer"
