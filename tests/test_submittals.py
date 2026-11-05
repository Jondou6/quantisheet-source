"""Submittals for the architect and engineers (0.12.27): the package PDF
(cover sheet with the CSI section, review stamps, attachments) and the
register read from the spec book."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                                     # noqa: E402
from app.pm import actions, schema, submittals               # noqa: E402
from app.pm.store import ProjectStore                        # noqa: E402

SPEC = """SECTION 08 71 00 - DOOR HARDWARE
PART 1 - GENERAL
1.1 RELATED DOCUMENTS
A. Drawings and general provisions of the Contract apply.
1.3 ACTION SUBMITTALS
A. Product Data: For each type of product.
B. Shop Drawings: Details of electrified door hardware, with wiring
diagrams.
C. Samples: For each exposed product in each finish specified.
D. Door Hardware Schedule: Prepared by or under the supervision of the
Architectural Hardware Consultant.
1.4 INFORMATIONAL SUBMITTALS
A. Qualification Data: For Installer and Architectural Hardware
Consultant.
B. Product Certificates: For electrified door hardware.
1.5 CLOSEOUT SUBMITTALS
A. Maintenance Data: For each type of door hardware to include in
maintenance manuals.
1.6 QUALITY ASSURANCE
A. Installer Qualifications: Supplier of products.
PART 2 - PRODUCTS
2.1 HINGES
A. Butts: Five-knuckle.
END OF SECTION 08 71 00
"""
SPEC2 = """SECTION 033000
CAST-IN-PLACE CONCRETE
PART 1 - GENERAL
1.2 SUBMITTALS
A. Product Data: For each type of product.
B. Design Mixtures: For each concrete mixture.
C. Steel Reinforcement Shop Drawings: Placing drawings.
PART 2 - PRODUCTS
END OF SECTION
"""


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    return ProjectStore(str(tmp_path / "Job"))


def test_register_from_the_spec_book():
    props = submittals.from_spec_text([SPEC, SPEC2])
    got = [(p["spec"], p["title"], p["type"]) for p in props]
    assert ("08 71 00", "Door Hardware - Product Data", "Product Data") in got
    assert ("08 71 00", "Door Hardware - Shop Drawings", "Shop Drawings") \
        in got
    assert ("08 71 00", "Door Hardware - Samples", "Samples") in got
    assert ("08 71 00", "Door Hardware - Qualification Data",
            "Certificates") in got
    assert ("08 71 00", "Door Hardware - Maintenance Data", "O&M Manuals") \
        in got
    # quality assurance (not a submittals article) and PART 2 are left out
    assert not [g for g in got if "Installer Qualifications" in g[1] or
                "Butts" in g[1]]
    sd = [p for p in props if p["title"].endswith("Shop Drawings")][0]
    assert "wiring diagrams" in sd["description"]
    concrete = [g for g in got if g[0] == "03 30 00"]
    assert ("03 30 00", "Cast-In-Place Concrete - Design Mixtures",
            "Other") in concrete or \
        ("03 30 00", "Cast-In-Place Concrete - Design Mixtures",
         "Design Data") in concrete
    assert len(concrete) == 3


def test_import_numbers_by_spec_section_and_skips_repeats(store):
    props = submittals.from_spec_text([SPEC])
    made = submittals.import_register(store, props, responsible="Acme Doors")
    assert len(made) == len(props) and made[0]["_no"] == "08 71 00-001"
    assert all(r["status"] == "Not Submitted" for r in made)
    assert all(r["type"] in schema.SUBMITTAL_TYPES for r in made)
    assert submittals.import_register(store, props) == []     # already in
    assert store.setting("spec_titles")["08 71 00"] == "Door Hardware"


def test_package_pdf(store, tmp_path):
    fitz = pytest.importorskip("fitz")
    att = tmp_path / "cut sheet.pdf"
    d = fitz.open()
    for i in range(2):
        d.new_page().insert_text((72, 72), f"Hinge cut sheet {i + 1}")
    d.save(str(att))
    store.set_setting("default_reviewer", "Ann Arch")
    rec = store.save_record("submittal", {
        "title": "Door Hardware - Product Data",
        "spec": "08 71 00 Door Hardware", "type": "Product Data",
        "responsible": "Acme Doors", "status": "Not Submitted",
        "review_days": 10,
        "workflow": [{"reviewer": "Ann Arch"}, {"reviewer": "Ed Engineer"}],
        "attachments": [store.attach(str(att))]})
    path = submittals.package_pdf(store, rec, today="2026-10-20")
    assert os.path.dirname(path).endswith("Submittals")
    out = fitz.open(path)
    assert out.page_count == 3
    cover = out[0].get_text()
    for s in ("SUBMITTAL", "08 71 00-001 Rev 0", "08 71 00 Door Hardware",
              "08 Openings", "Product Data", "Acme Doors",
              "Ann Arch, Ed Engineer", "cut sheet.pdf (2 pages)",
              "CONTRACTOR'S REVIEW", "REVIEW - ANN ARCH",
              "REVIEW - ED ENGINEER", "Revise and Resubmit"):
        assert s in cover, s
    assert "Hinge cut sheet 2" in out[2].get_text()
    assert [t[1] for t in out.get_toc()] == ["Submittal 08 71 00-001 Rev 0",
                                             "cut sheet.pdf"]


def test_package_action_attaches_it_once_per_revision(store, tmp_path):
    pytest.importorskip("fitz")
    rec = store.save_record("submittal", {
        "title": "Door Hardware - Samples", "spec": "08 71 00",
        "type": "Samples", "status": "Not Submitted"})
    opened = []
    ctx = actions.Ctx(store, open_file=opened.append, mail=False)
    labels = [a[0] for a in actions.available("submittal", rec)]
    assert "Make Submittal Package (PDF)" in labels
    rec = actions.run(ctx, "submittal", rec, "Make Submittal Package (PDF)")
    rec = actions.run(ctx, "submittal", rec, "Make Submittal Package (PDF)")
    pk = [a for a in rec["attachments"]
          if a["name"].startswith("Submittal package ")]
    assert len(pk) == 1 and opened and opened[0].endswith(".pdf")
    # the package isn't put inside the next package
    assert submittals._attachments(store, rec) == []
