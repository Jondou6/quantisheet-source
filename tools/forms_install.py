"""Add the blank forms from Desktop\\PDF Attachments to the Form Library."""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import formlib
SRC = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "PDF Attachments")
A = "1. Blank AIA Forms"
M = [
 (f"{A}/AIA A101 Stipulated Sum/A101- 2017.docx", "AIA Agreements", "AIA A101-2017 Owner-Contractor, Stipulated Sum", ""),
 (f"{A}/AIA A102 Owner & Contractor GMP/A102-2021.11.16 - Owner_Contractor_GMP.pdf", "AIA Agreements", "AIA A102 Owner-Contractor, Cost Plus Fee with GMP", ""),
 (f"{A}/AIA A105-2017 Short Form Owner & Contractor/AIA A105 2.pdf", "AIA Agreements", "AIA A105-2017 Short Form Owner-Contractor", ""),
 (f"{A}/AIA A107 Standard Agreement Insurance/Unlock-A107 Determination of Work.pdf", "AIA Agreements", "AIA A107 Owner-Contractor, Limited Scope", ""),
 (f"{A}/AIA A107 Standard Agreement Insurance/A107-2007_Insurance Cancellation Requirements.pdf", "AIA Agreements", "AIA A107-2007 Limited Scope (fillable) + Insurance Cancellation Memo", "Saved with a past job's entries (Coastal Palms) - open with Clear checked"),
 (f"{A}/AIA A132 Construction Manager/AIA A132 Agreement between Owner Contractor.pdf", "AIA Agreements", "AIA A132 Owner-Contractor, CM as Adviser", ""),
 (f"{A}/AIA A132 Construction Manager/A132-2009_2008722911_11042013032524_5e59440c-dcc2-46b7-894e-ab3e4f2c476e.pdf", "AIA Agreements", "AIA A132-2009 Owner-Contractor, CM as Adviser (fillable)", "Saved with a past job's entries - open with Clear checked"),
 (f"{A}/AIA A132 Construction Manager/A132-2009_ExhA_2008722911_11042013032524_edb99081-9e8e-4b5a-ba9a-6dd56bc3a3c5.pdf", "AIA Agreements", "AIA A132-2009 Exhibit A, Determination of the Cost of the Work", "Saved with a past job's entries - open with Clear checked"),
 (f"{A}/AIA A134 CM and Owner No Guar Max/A134-2009.pdf", "AIA Agreements", "AIA A134-2009 Owner-CM Constructor, Cost Plus without GMP", ""),
 (f"{A}/AIA A141 Owner & Design Builder/A141-2004.pdf", "AIA Agreements", "AIA A141-2004 Owner-Design-Builder", "The first pages are the A107 insurance cancellation memo"),
 (f"{A}/AIA A201 General Conditions/2023.08.15 A201-2017.pdf", "AIA Agreements", "AIA A201-2017 General Conditions of the Contract", ""),
 (f"{A}/AIA B101 Owner & Architect/B101-2017 - Working Draft - 001.docx", "AIA Agreements", "AIA B101-2017 Owner-Architect (working draft)", ""),
 (f"{A}/AIA A132 Construction Manager/A132-2009_Instr.pdf", "AIA Instructions", "AIA A132-2009 Instructions", ""),
 (f"{A}/AIA A134 CM and Owner No Guar Max/A134-2009_Instr.pdf", "AIA Instructions", "AIA A134-2009 Instructions", ""),
 (f"{A}/AIA G701 & G701S Change Order/AIA Change Order.pdf", "AIA Contract Administration", "AIA G701 Change Order", "Your company name and address are filled in"),
 (f"{A}/AIA G701 & G701S Change Order/G701 Subcontractor Change Order.pdf", "AIA Contract Administration", "AIA G701S Subcontractor Change Order", ""),
 (f"{A}/AIA G702 & G703 Pay Applications/2.7.13 Blank AIA 702 & 703 Pay Application.pdf", "AIA Contract Administration", "AIA G702-G703 Pay Application", "Your company name and address are filled in"),
 (f"{A}/AIA G702 & G703 Pay Applications/AIA G702 G703 CCC.pdf", "AIA Contract Administration", "AIA G702-G703 Pay Application (3 pages, CCC)", ""),
 (f"{A}/AIA G704 Subtantial Completion/AIA G 704 Substantial Completion.pdf", "AIA Contract Administration", "AIA G704 Certificate of Substantial Completion", "Your company name is filled in"),
 (f"{A}/AIA G706 A Release of Liens/G706A Release of Liens.pdf", "AIA Contract Administration", "AIA G706A Contractor's Affidavit of Release of Liens", ""),
 (f"{A}/AIA G707 Consent of Surety/G707 Consent of Surety.pdf", "AIA Contract Administration", "AIA G707 Consent of Surety to Final Payment", ""),
 (f"{A}/AIA G714 Change Directive/AIA-G714-2007 Change Directive.pdf", "AIA Contract Administration", "AIA G714 Construction Change Directive", ""),
 ("4. ITB Form - CCC/ITB Form (BLANK) REV2.pdf", "Bidding", "Invitation to Bid (CCC)", ""),
 ("Accident Reports/accident report_CCC_updated.pdf", "Safety", "Incident and Accident Report (CCC)", ""),
 ("Accident Reports/accident report_Allstate_updated.pdf", "Safety", "Incident and Accident Report (Allstate Services)", ""),
 ("3. Action Item List/2026/Action Item List Blank Template/2026.05.15_Blank Action Item List.xlsx", "Project Management", "Action Item List", ""),
]
have = {e["name"] for e in formlib.entries()}
res = []
for rel, cat, name, notes in M:
    if name in have:
        res.append((name, "already in library")); continue
    p = os.path.join(SRC, *rel.split("/"))
    try:
        e = formlib.add(p, cat, name, notes)
        res.append((name, f"{e['pages']} pages, {e['fields']} fields, {e['filled']} filled"))
    except Exception as ex:
        res.append((name, f"FAILED: {type(ex).__name__}: {ex}"))
for r in res:
    print(" | ".join(r))
print("library:", formlib.folder(), len(formlib.entries()), "forms")
