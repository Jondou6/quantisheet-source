"""Fold extracted facts into one list with citations.

The same item from two pages is one fact, and every page stays on it.
Two different lead times for one item are a conflict: both values are
kept and neither is chosen here.
"""


def _key(fact):
    item = " ".join(str(fact.get("item") or "").lower().split())
    return (fact.get("kind") or "", item)


def merge(facts):
    groups = {}
    order = []
    for fact in facts or ():
        if not fact.get("item") and fact.get("kind") not in ("contract",):
            continue
        k = _key(fact)
        if k not in groups:
            groups[k] = {
                "kind": fact.get("kind"),
                "item": fact.get("item") or "",
                "division": fact.get("division") or "",
                "consumer": fact.get("consumer") or "",
                "values": [],
                "citations": [],
                "texts": [],
                "sources": [],
                "unit": fact.get("unit") or "",
                "basis": fact.get("basis") or "",
                "lead_source": fact.get("lead_source") or "",
            }
            order.append(k)
        g = groups[k]
        if fact.get("division") and not g["division"]:
            g["division"] = fact["division"]
        if fact.get("consumer") and not g["consumer"]:
            g["consumer"] = fact["consumer"]
        if fact.get("value") not in (None, ""):
            same = next((v for v in g["values"] if v["value"] == fact["value"]),
                        None)
            if same is None:
                g["values"].append({
                    "value": fact["value"],
                    "unit": fact.get("unit") or "",
                    "source": fact.get("source") or "",
                    "basis": fact.get("basis") or "",
                    "page": fact.get("page"),
                    "spec_section": fact.get("spec_section") or "",
                    "lead_source": fact.get("lead_source") or "",
                })
            elif fact.get("lead_source") == "spec":
                # The same number written in the spec outranks a dictionary
                # default that happened to match it.
                same["lead_source"] = "spec"
                same["spec_section"] = fact.get("spec_section") or same.get("spec_section")
                same["page"] = fact.get("page")
        cite = {"spec_section": fact.get("spec_section") or "",
                "page": fact.get("page"),
                "source": fact.get("source") or ""}
        if cite["page"] is not None and cite not in g["citations"]:
            g["citations"].append(cite)
        text = fact.get("text") or ""
        if text and text not in g["texts"]:
            g["texts"].append(text)
        if fact.get("source") and fact["source"] not in g["sources"]:
            g["sources"].append(fact["source"])
        if fact.get("lead_source") == "spec":
            g["lead_source"] = "spec"
    conflicts = []
    out = []
    for k in order:
        g = groups[k]
        # A stated lead time wins over the dictionary default when they
        # differ, but two stated values are a conflict and are not merged.
        stated = [v for v in g["values"]
                  if v.get("lead_source") == "spec" or
                  (g["kind"] == "long_lead" and v.get("basis") == "spec")]
        # lead_source lives on the value for spec hits.
        stated = [v for v in g["values"] if v.get("lead_source") == "spec"
                  or (g["kind"] != "long_lead" and v.get("source") != "dictionary")]
        if g["kind"] == "long_lead":
            stated = [v for v in g["values"] if v.get("lead_source") == "spec"]
            defaults = [v for v in g["values"] if v.get("lead_source") != "spec"]
            if len({v["value"] for v in stated}) > 1:
                g["conflict"] = True
                g["value"] = None
                conflicts.append(g)
            elif stated:
                g["conflict"] = False
                g["value"] = stated[0]["value"]
                g["unit"] = stated[0].get("unit") or g["unit"]
                g["basis"] = "stated in the spec"
                g["lead_source"] = "spec"
            elif defaults:
                g["conflict"] = False
                g["value"] = defaults[0]["value"]
                g["unit"] = defaults[0].get("unit") or "calendar"
                g["basis"] = "dictionary default"
                g["lead_source"] = "dictionary"
            else:
                g["conflict"] = False
                g["value"] = None
        else:
            vals = [v["value"] for v in g["values"]]
            if len(set(map(_norm, vals))) > 1:
                g["conflict"] = True
                g["value"] = None
                conflicts.append(g)
            elif vals:
                g["conflict"] = False
                g["value"] = g["values"][0]["value"]
                g["unit"] = g["values"][0].get("unit") or g["unit"]
            else:
                g["conflict"] = False
                g["value"] = None
        out.append(g)
    return out, conflicts


def _norm(value):
    if isinstance(value, float) and value == int(value):
        return int(value)
    return value


def of_kind(facts, kind):
    return [f for f in facts if f.get("kind") == kind]
