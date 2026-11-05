"""Generate Set v1: a brief (and/or one sketch) -> a coordinated starter
construction-document set (PDF) - FOR REVIEW, NOT FOR SEALING.

One building-plan JSON (model.py) feeds every sheet. Modulor
(github.com/bcllcc/modulor, MIT, reviewed commit 40f6c2a) is the drafting
kernel: it builds the walls, openings and rooms, gives the plan outlines
with the openings cut, and projects each face for the elevations. QuantiSheet
composes the sheets (title block, tags, dimensions, schedules,
notes) and draws the building section, which Modulor has no op for.

The language model only fills form fields from the brief and writes
project note text; every number on a drawing comes from code.

    python -m app.genset --brief "1600 sf 3 bed 2 bath ranch, new" out.pdf
"""
VERSION = "1"
DISCLAIMER = "FOR REVIEW — NOT FOR SEALING"
CREATOR = "QuantiSheet Generate Set v1"


def build_set(plan, out_path, **kw):
    from .build import build_set as _b
    return _b(plan, out_path, **kw)
