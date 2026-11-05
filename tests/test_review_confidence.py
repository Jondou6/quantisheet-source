"""Review CHECK Items, Oct 31 2026: every item gets a score (0-100, how
sure the AI is), the review screen can go least sure first, a deletion
or fix can say why (not there, wrong shape, misidentified) and a person
can log what the AI missed. Reasons are kept on this PC only, to tune the
takeoff later; nothing is sent anywhere. Made-up items only."""
import json

from app import review


def _res():
    return {"quantities": [], "review": [
        {"engine": "rooms", "name": "OFFICE 101", "qty": 207.0,
         "unit": "sq ft", "sheet": "A101", "page": 4, "confidence": 0.62,
         "why": "no area in the tag - size check only"},
        {"engine": "envelope", "name": "CMU back-up", "qty": 4164.9,
         "unit": "SF", "sheet": "set", "page": None,
         "why": "AI-derived, confidence 0.55 - top wall mark"},
        {"engine": "ducts", "name": "Duct 8in wide", "qty": 102.0,
         "unit": "ft", "sheet": "M101", "page": 18,
         "why": "no size tag at this duct - measure it by hand"},
        {"engine": "rooms", "name": "STORAGE 9", "qty": 80.0,
         "unit": "sq ft", "sheet": "A1", "page": 1, "source": "scan",
         "confidence": 0.62, "why": "room trace not sure"},
        {"engine": "devices", "name": "EXAMPLE PANEL", "qty": 1,
         "unit": "ea", "sheet": "E-201", "page": 2,
         "why": "the same symbol is drawn on another plan of the same "
                "floor - counted once"}]}


def test_score_uses_the_engines_confidence_or_the_reason():
    r = _res()["review"]
    assert review.score(r[0]) == 62
    assert review.score(r[1]) == 55             # "confidence 0.55" in why
    assert 0 < review.score(r[2]) < 50          # nothing to go on but a flag
    assert review.score(r[3]) < review.score(r[0])   # a scan: less sure


def test_least_sure_first_keeps_repeats_last():
    q = review.queue(_res(), order="least_sure")
    scores = [review.score(x) for x in q[:-1]]
    assert scores == sorted(scores)
    assert q[-1]["name"] == "EXAMPLE PANEL"
    # the old order is still the default
    assert review.queue(_res())[0]["name"] == "CMU back-up"


def test_delete_with_a_reason_and_log_a_miss(tmp_path):
    res = _res()
    log = tmp_path / "ai_feedback.jsonl"
    office, cmu, duct = res["review"][:3]
    review.delete(res, duct, who="Estimator", reason="not there",
                  log_path=log)
    review.accept(res, office, qty=255.0, who="Estimator",
                  reason="wrong shape", log_path=log)
    review.missed(res, "WOMEN'S SHOWER 109", sheet="A101", page=4,
                  qty=151.7, unit="sq ft", who="Estimator", log_path=log)
    acts = [(d["action"], d.get("reason")) for d in review.decisions(res)]
    assert acts == [("deleted", "not there"), ("fixed", "wrong shape"),
                    ("missed", "missed")]
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert [x["reason"] for x in lines] == ["not there", "wrong shape",
                                            "missed"]
    assert lines[1]["qty_found"] == 207.0 and lines[1]["qty"] == 255.0
    assert all("Estimator" not in json.dumps(x) for x in lines)  # no names
    assert sum(1 for d in review.removed_and_missed(res)
               if d["action"] == "missed") == 1


def test_unknown_reason_is_refused():
    res = _res()
    try:
        review.delete(res, res["review"][0], reason="because")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown reason was accepted")


def test_removed_and_missed_view():
    res = _res()
    review.delete(res, res["review"][2], reason="misidentified",
                  log_path=None)
    review.missed(res, "HALL 106", sheet="A101", qty=139.5,
                  unit="sq ft", log_path=None)
    rows = review.removed_and_missed(res)
    assert [(r["action"], r["name"]) for r in rows] == [
        ("deleted", "Duct 8in wide"), ("missed", "HALL 106")]
