"""Accuracy round 5 (Oct 26): pavement section layers. Made-up drawings."""
import pytest

fitz = pytest.importorskip("fitz")


def _section(page, x=300, y=300):
    for i, t in enumerate(["TACK COATING", '1 1/2" 9.5 MM SUPERPAVE',
                           '2" 12.5 MM SUPERPAVE', "(HOT PLANT MIX) BINDER",
                           '8" GRADED AGGREGATE BASE (COMPACT',
                           "SUBGRADE COMPACTED TO 100% MAX."]):
        page.insert_text((x, y + 14 * i), t, fontsize=7)


def test_pavement_section_layers_are_read_top_down():
    from app import sitework
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    _section(pg)
    got = [(l["layer"], l["thickness_in"]) for l in
           sitework.pavement_layers(pg)]
    assert got == [("tack coat", None), ("surface course", 1.5),
                   ("binder course", 2.0), ("aggregate base", 8.0),
                   ("compacted subgrade", None)]


def test_scattered_notes_are_not_a_pavement_section():
    from app import sitework
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    pg.insert_text((100, 100), "USE OF A TACKIFIER IS REQUIRED", fontsize=7)
    pg.insert_text((900, 700), "LOOSEN THE SUBGRADE BEFORE TOPSOIL",
                   fontsize=7)
    pg.insert_text((1500, 200), '2" 12.5 MM SUPERPAVE', fontsize=7)
    assert sitework.pavement_layers(pg) == []


# ---- wall assemblies from the wall-type legend ------------------------------

def test_partition_assembly_from_its_legend_text():
    from app import wall_assembly as wa
    desc = ('DEFLECTION TRACK BATT INSULATION WHERE REQUIRED FOR SOUND '
            '3 5/8" MTL. STUDS @ 16" O.C. 5/8" TYPE X GYPBOARD, TYP BOTH '
            'SIDES BASE AS SCHEDULED')
    comps = wa.components(desc)
    kinds = [c["kind"] for c in comps]
    assert kinds == ["studs", "gwb", "batt"]
    by = {l["name"]: l for l in wa.lines("2A", 100.0, 10.0, comps)}
    assert by['Wall Type 2A - 3-5/8" metal studs @ 16" OC']["qty"] == \
        pytest.approx((75 + 1) * 10.0)
    assert by['Wall Type 2A - 3-5/8" top & bottom track']["qty"] == 200.0
    assert by['Wall Type 2A - 5/8" type X gypsum board']["qty"] == 2000.0
    assert by["Wall Type 2A - gypsum board 4'x8' sheets"]["qty"] == 63
    assert "where required" in by["Wall Type 2A - batt insulation"]["basis"]


def test_cmu_wall_type_gives_wall_area_and_blocks():
    from app import wall_assembly as wa
    comps = wa.components('8" CMU VERTICAL REINFORCEMENT HORIZONTAL '
                          'REINFORCEMENT 7/8" MTL FURRING CHANNEL 5/8" TYPE '
                          'X GYPBOARD')
    by = {l["name"]: l for l in wa.lines("3B", 40.0, 10.0, comps)}
    assert by['Wall Type 3B - 8" CMU wall']["qty"] == 400.0
    assert by['Wall Type 3B - 8" CMU block']["qty"] == 450
    assert by['Wall Type 3B - 5/8" type X gypsum board']["qty"] == 400.0
    assert 'Wall Type 3B - 7/8" metal furring channels' in by


def test_no_height_no_lines():
    from app import wall_assembly as wa
    assert wa.lines("2A", 100.0, None, wa.components(
        '3 5/8" MTL. STUDS @ 16" O.C.')) == []


def test_roof_layers_beside_the_roofing_callout():
    from app import envelope
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    for i, t in enumerate(["STANDING SEAM METAL ROOF", "UNDERLAYMENT",
                           '2" RIGID INSULATION', "ICE & WATER SHIELD"]):
        pg.insert_text((400, 300 + 12 * i), t, fontsize=7)
    pg.insert_text((1500, 900), '1 1/2" RIGID INSUL', fontsize=7)  # far off
    got = [(l["layer"], l["thickness_in"]) for l in envelope.roof_layers(pg)]
    assert got == [("underlayment", None), ("rigid insulation", 2.0),
                   ("ice & water shield", None)]


def test_a_hydrant_named_at_its_symbol_and_in_its_callout_is_one():
    from app import civiltakeoff as ct
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    pg.insert_text((500, 500), "FIRE HYDRANT", fontsize=6)
    pg.insert_text((520, 540), "1 - FIRE HYDRANT ASSEMBLY PER DETAIL",
                   fontsize=6)
    pg.insert_text((1300, 500), "FIRE HYDRANT", fontsize=6)   # another one
    hyd = [t for t in ct.structure_tags(pg) if t["kind"] == "hydrant"]
    assert len(hyd) == 2
