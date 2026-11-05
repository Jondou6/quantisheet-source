"""QA checklist templates the office can edit.

Built-in lists are seeded once. Saving replaces the items on that
template and leaves every other record alone. Deleting hides the
template (the row stays). The screen that edits them is
r111.ui.QaTemplatePage.
"""
from __future__ import annotations

import json

from . import schema

DEFAULTS = {
    "Pre-pour": [
        "Forms match the drawings",
        "Rebar is tied and chaired",
        "Embeds are in place",
        "Sleeves are capped",
    ],
    "Weekly walk": [
        "Guardrails are up at open edges",
        "Cords are off the walkways",
        "Extinguishers are in the shack",
        "First aid kit is stocked",
    ],
}


class QAError(ValueError):
    pass


def _seed(office) -> None:
    if office.db.scalar("SELECT COUNT(*) FROM qa_templates"):
        return
    for name, items in DEFAULTS.items():
        office.db.insert("qa_templates", name=name, items=list(items),
                         active=1)


def _items(raw) -> list[str]:
    if isinstance(raw, list):
        data = raw
    elif not raw:
        return []
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
    return [str(x) for x in data]


def templates(office) -> list[dict]:
    schema.ensure(office.db)
    _seed(office)
    rows = office.db.rows("SELECT * FROM qa_templates WHERE deleted = 0 AND "
                          "active = 1 ORDER BY name")
    for r in rows:
        r["items"] = _items(r["items"])
    return rows


def items(office, name) -> list[str]:
    for row in templates(office):
        if row["name"] == name:
            return list(row["items"])
    raise QAError(f"No checklist named {name}.")


def save(office, name, lines) -> int:
    schema.need(office, "settings.edit", record_type="qa_template",
                record_id=name)
    cleaned = [str(x).strip() for x in lines if str(x).strip()]
    if not str(name).strip():
        raise QAError("Name the checklist.")
    if not cleaned:
        raise QAError("The checklist is empty.")
    schema.ensure(office.db)
    _seed(office)
    name = str(name).strip()
    row = office.db.one("SELECT * FROM qa_templates WHERE name = ? AND "
                        "deleted = 0", (name,))
    with office.db.tx():
        if row:
            before = _items(row["items"])
            office.db.update("qa_templates", row["id"], items=cleaned,
                             active=1)
            tid = row["id"]
            office.audit("change", "qa_template", tid, {"items": before},
                         {"items": cleaned})
        else:
            tid = office.db.insert("qa_templates", name=name, items=cleaned,
                                   active=1)
            office.audit("create", "qa_template", tid, None,
                         {"name": name, "items": cleaned})
    return tid


def delete(office, name) -> None:
    schema.need(office, "settings.edit", record_type="qa_template",
                record_id=name)
    schema.ensure(office.db)
    row = office.db.one("SELECT * FROM qa_templates WHERE name = ? AND "
                        "deleted = 0", (name,))
    if not row:
        raise QAError(f"No checklist named {name}.")
    with office.db.tx():
        office.db.soft_delete("qa_templates", row["id"])
        office.audit("delete", "qa_template", row["id"], {"name": name}, None)
