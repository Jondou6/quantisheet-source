"""Customer leave-behind report (QuantiSheet 1.2, #15 / QW7): one PDF for
the customer at the end of a visit - the work done, the readings taken
(with how each moved since the unit's earlier visits), photos, and the
work recommended but not yet done. No costs (the invoice carries those);
the invoice total is shown when there is one."""
import os

from .. import dmoney
from . import checklists, workorder


def _open_recs(rec_store, wo):
    out = []
    for r in (rec_store or {}).get("items", []):
        if r.get("status", "open") != "open":
            continue
        if wo.get("equipment_id") and r["equipment_id"] == \
                wo["equipment_id"]:
            out.append(r)
        elif not wo.get("equipment_id") and wo.get("property_id") and \
                r.get("property_id") == wo["property_id"]:
            out.append(r)
    return out


def pdf(store, wo_id, path, checklist_store=None, rec_store=None,
        comp=None):
    from .pdfdoc import Sheet, fit
    wo = workorder.get(store, wo_id)
    if checklist_store is None:
        checklist_store = checklists.load()
    if rec_store is None:
        from . import recommend
        rec_store = recommend.load()
    sheet = Sheet("Service Visit Report", comp, subtitle=wo["number"])
    sheet.section("01", "Visit")
    y = sheet.y + 12
    sheet.text(36, y, wo["customer"], 11, True)
    sheet.text(36, y + 14, " ".join(p for p in (wo["site"],
                                                wo.get("address")) if p), 9)
    when = wo.get("closed") or (wo["time"][-1]["date"] if wo["time"]
                                else wo["opened"])
    sheet.text(400, y, f"Date: {when}", 9)
    techs = sorted({t["tech"] for t in wo["time"]} | (
        {wo["tech"]} if wo.get("tech") else set()))
    sheet.text(400, y + 14, "Technician: " + (", ".join(techs) or "-"), 9)
    if wo.get("unit"):
        sheet.text(36, y + 28, f"Equipment: {wo['unit']}", 9)
    sheet.y = y + 40
    sheet.section("02", "What we found and did")
    sheet.y += 4
    for line in (f"Reason for the visit: {wo['complaint']}",
                 *((wo.get("notes") or "No notes.").splitlines())):
        for chunk in _wrap(line, 100):
            sheet.need(14)
            sheet.y += 12
            sheet.text(36, sheet.y, fit(chunk, 540, 9), 9)
    if wo["parts"]:
        sheet.y += 8
        sheet.text(36, sheet.y + 6, "Parts used", 9, True)
        sheet.y += 6
        for p in wo["parts"]:
            sheet.need(14)
            sheet.y += 12
            sheet.text(48, sheet.y, fit(f"{p['qty']} {p['unit']}  {p['desc']}",
                                        520, 9), 9)
    inv = next((i for i in store.get("invoices", [])
                if i["id"] == wo.get("invoice_id")), None)
    if inv:
        sheet.y += 14
        sheet.text(36, sheet.y, f"Invoice {inv['number']}: "
                                f"{dmoney.fmt(inv['total'])}", 9, True)
    done = checklists.for_work_order(checklist_store, wo_id)
    if done:
        sheet.section("03", "Readings and checks")
        for c in done:
            sheet.need(18)
            sheet.y += 16
            sheet.text(36, sheet.y, f"{c['name']} ({c['date']})", 9, True)
            for it in c["items"]:
                if not it["value"]:
                    continue
                sheet.need(14)
                sheet.y += 12
                if it["kind"] == "check":
                    txt = f"{it['label']}: {it['value']}"
                else:
                    txt = f"{it['label']}: {it['value']} {it.get('unit', '')}"
                    if c["equipment_id"]:
                        ch = checklists.change_text(checklists.trend(
                            checklist_store, c["equipment_id"], it["key"]))
                        if ch:
                            txt += f"   ({ch})"
                    if it.get("watch"):
                        txt += "   - your technician flagged this reading"
                sheet.text(48, sheet.y, fit(txt, 520, 8.5), 8.5)
    photos = [ph for ph in wo.get("photos") or []
              if os.path.isfile(ph.get("path") or "")]
    if photos:
        sheet.section("04", "Photos")
        import fitz
        for ph in photos:
            sheet.need(170)
            sheet.y += 10
            try:
                sheet.page.insert_image(
                    fitz.Rect(36, sheet.y, 276, sheet.y + 150),
                    filename=ph["path"], keep_proportion=True)
            except Exception:                             # noqa: BLE001
                continue
            if ph.get("caption"):
                sheet.text(290, sheet.y + 14, fit(ph["caption"], 280, 9), 9)
            sheet.y += 156
    recs = _open_recs(rec_store, wo)
    if recs:
        sheet.section("05", "Recommended")
        for r in recs:
            sheet.need(14)
            sheet.y += 12
            price = f"   {dmoney.fmt(r['price'])}" if r.get("price") else ""
            sheet.text(36, sheet.y, fit(f"{r.get('unit') or ''}: "
                                        f"{r['note'] or 'Recommended work'}"
                                        f"{price}", 540, 9), 9)
    sheet.need(30)
    sheet.y += 26
    sheet.text(36, sheet.y, "Thank you. Questions about this visit: call "
                            "the office.", 8.5)
    return sheet.save(path)


def _wrap(text, n):
    words, out, cur = str(text).split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n and cur:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(cur)
    return out or [""]
