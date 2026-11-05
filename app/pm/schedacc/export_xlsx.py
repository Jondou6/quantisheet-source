"""Activity workbook. Uses openpyxl, which the program already depends on.

Columns: WBS, activity id, name, type, calendar, duration, how the
duration was set, early and late dates, total and free float, critical,
predecessors, successors, roles, spec section and page, template slot.
"""
from .model import TYPE_LABEL


def export_xlsx(doc, path):
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Schedule"
    headers = [
        "WBS", "Activity ID", "Name", "Type", "Calendar", "Duration (workdays)",
        "Duration basis", "Early start", "Early finish", "Late start",
        "Late finish", "Total float", "Free float", "Critical", "Longest path",
        "Predecessors", "Successors", "Roles", "Spec section", "Page",
        "Template slot", "Why",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    preds, succs = {}, {}
    for rel in doc.get("relationships") or []:
        bit = f"{rel.get('pred')} {rel.get('type')}"
        lag = float(rel.get("lag_hours") or 0)
        if lag:
            bit += f" {lag:.0f}h"
        preds.setdefault(rel.get("succ"), []).append(bit)
        succs.setdefault(rel.get("pred"), []).append(
            f"{rel.get('succ')} {rel.get('type')}")
    for a in doc.get("activities") or []:
        cite = (a.get("citations") or [{}])[0]
        ws.append([
            a.get("wbs") or "",
            a.get("code") or "",
            a.get("name") or "",
            TYPE_LABEL.get(a.get("type") or "", a.get("type") or ""),
            a.get("calendar") or "",
            a.get("dur_days") if a.get("dur_days") is not None else "",
            a.get("duration_kind") or "",
            a.get("es") or "",
            a.get("ef") or "",
            a.get("ls") or "",
            a.get("lf") or "",
            a.get("total_float_days") if a.get("total_float_days") is not None else "",
            a.get("free_float_days") if a.get("free_float_days") is not None else "",
            "Yes" if a.get("critical") else "",
            "Yes" if a.get("longest_path") else "",
            "; ".join(preds.get(a.get("code"), ())),
            "; ".join(succs.get(a.get("code"), ())),
            ", ".join(a.get("roles") or ()),
            cite.get("spec_section") or "",
            cite.get("page") if cite.get("page") is not None else "",
            a.get("template_slot") or "",
            a.get("why") or "",
        ])
    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"
    wb.save(path)
    return path
