"""Schedule compiler for release 1.1.1.

The live "Build Schedule From Plans" path (``app/pm/autoschedule.py`` and
``BuildFromPlansDialog`` in ``app/pm/scheduler.py``) is left untouched.
This package is the accuracy redesign: it compiles a schedule from specs,
drawings, takeoff quantities and company templates, and can write the
result into the existing activity records.

Nothing here is wired into the ribbon or the Scheduler window. The other
developer does that. See ``WIRING`` below and ``apply_to_store``.

User-facing text in this package does not name or compare this program
to any other scheduling product. Product names that appear in comments
are implementation notes for the data model.

WIRING (do not apply these edits from this branch; another developer owns
the live files):

1. ``app/pm/scheduler.py``, ``BuildFromPlansDialog.build``, after the
   project type is known and instead of (or beside) ``autoschedule.build``::

       from app.pm.schedacc import compile_schedule, apply_to_store
       draft = compile_schedule(
           spec_pdf=self.spec.text().strip() or None,
           drawings_pdf=self.plans.text().strip() or None,
           project_type=TYPE_MAP.get(picked),
           ntp=ntp, project_name=st.data.get("name") or "Project",
           progress=self._progress)
       if draft["status"] != "finished":
           # show draft["rubric"]["gaps"] and draft["health"]; do not
           # tell the user the schedule is finished
           ...
       apply_to_store(st, draft, replace=True)

   ``TYPE_MAP`` from the dialog's schedule_types key:
   new_building -> ground_up_commercial, renovation -> tenant_improvement,
   hvac_replacement -> mep_retrofit. Service work has no schedule_types
   key; pass plumbing_hvac_service when the user picks it.

2. ``app/pm/scheduler.py`` ``build_from_plans`` / the dialog: add a
   progress label. ``compile_schedule(..., progress=cb)`` calls
   ``cb({"stage", "index", "total", "message"})`` on the calling thread.
   Chunks stay near 3,500 characters because the office PC has 16 GB of
   RAM and no usable GPU.

3. Model choice: a settings action (not in this branch) reads and writes
   ``app.pm.schedacc.options``. Recommended model is a 7B-class instruct
   model; ``llama3.2`` stays the fallback. The checkbox for "no local
   model" sets ``allow_ai`` false. The compiler still returns a full
   schedule.

4. Company templates and trade rules live under the per-user data folder
   (``settings.DIR / "schedacc"``). An editor can call
   ``templates.save_library`` and ``rules.save_rules``. Confirming a row
   in the review queue calls ``reviewq.confirm``, which updates the
   matching template slot.

5. ``app/pm/schedule.py`` ``Calendar.is_work`` and ``compute`` know one
   Monday-Friday calendar. Per-activity calendars (7-day cure, weather)
   are honored by ``schedacc.cpm``. ``apply_to_store`` writes ``duration``
   as Monday-Friday workdays spanning the compiled early dates, and stores
   the real calendar duration on ``sch_duration_days`` / ``sch_calendar``.
   Until ``compute`` grows a per-activity calendar, the Gantt matches the
   compiled dates only when every activity uses the project calendar.
   Do not delete ``schedule.compute`` or ``schedule_check.check``; the
   health report calls ``schedule_check.check`` when a store is passed.

6. Exports (no UI in this branch). From a compiled draft::

       export_pdf(draft, path)       # Gantt + table + basis narrative
       export_pmxml(draft, path)     # PMXML schedule (.xml)
       export_mspdi(draft, path)     # MSPDI schedule (.xml)
       export_xlsx(draft, path)      # activities, float, WBS

7. ``app/main_window.py`` ``ai_schedule`` can keep calling
   ``build_from_plans``. No change is required there if step 1 is done
   inside the dialog.
"""

def compile_schedule(*a, **k):
    from .engine import compile_schedule as _fn
    return _fn(*a, **k)


def apply_to_store(*a, **k):
    from .apply import apply_to_store as _fn
    return _fn(*a, **k)


def export_pdf(*a, **k):
    from .export_pdf import export_pdf as _fn
    return _fn(*a, **k)


def export_pmxml(*a, **k):
    from .export_xml import export_pmxml as _fn
    return _fn(*a, **k)


def export_mspdi(*a, **k):
    from .export_xml import export_mspdi as _fn
    return _fn(*a, **k)


def export_xlsx(*a, **k):
    from .export_xlsx import export_xlsx as _fn
    return _fn(*a, **k)


__all__ = [
    "compile_schedule",
    "apply_to_store",
    "export_pdf",
    "export_pmxml",
    "export_mspdi",
    "export_xlsx",
]
