---
title: "QuantiSheet — Generate Set v1 Build Plan (for Claude)"
subtitle: "Brief or sketch → coordinated starter CD set (PDF). Jon, Oct 19 2026. Target: QuantiSheet 0.12.11. Modulor is the v1 drafting kernel."
---

# The answer

Build **File › Generate Set…** as a new `app/genset/` package that turns a brief and/or one sketch into a JSON building plan. **Modulor** (`github.com/bcllcc/modulor`, MIT, v1.0.0rc3) is the **v1 drafting kernel**: it builds the 3D model and exports DXF/SVG for the floor plan and elevations. PyMuPDF composites those drawings onto ARCH D sheets, draws the title block, schedules, notes, cover, disclaimer, and — because Modulor has no vertical section op — the building section sheet from plan JSON. The app opens the finished PDF in the viewer with page scales already set.

I ran the Modulor spike on the box (Oct 19 2026). It works for a 20×40 ft room (DXF → QuantiSheet `dxf.to_pdf` cleanly). The three gaps (m² labels, no vertical section, bare elevation outlines) are **v1 workarounds Claude must implement**, not reasons to skip Modulor. Jon locked Modulor in for v1 on Oct 19. Estimated effort for Claude is **about 28–32 hours** of focused work in 10 steps (0–9). Step 0 is a hard gate: install Modulor on Windows, re-run the spike, confirm the win_amd64 manifold3d wheel. If Modulor fails on Windows, **STOP and report** — do not silently switch to a full PyMuPDF fallback.

> **Liability rule that applies to everything below:** every sheet, the PDF metadata and the dialog say **FOR REVIEW — NOT FOR SEALING**. There is no stamp or seal feature. The LLM never places geometry.

# Facts (verified on the box, Oct 19 2026, 11:00 AM EDT)

- **Codebase.** QuantiSheet source under `/workspace/r7/src` (box mirror). Live Windows install is separate — Claude builds against Jon's Windows tree and ships as **0.12.11**. `app/main_window.py` is 5,111 lines, and the File menu is built in `_build_menus()` (line 372).
- **Opening files.** `MainWindow.open_path(path)` (line 2482) opens a PDF into a tab.
- **Existing pattern to copy.** `new_from_form(self, choice=None)` (line 4708) shows how to build an action that tests can drive without a dialog, by injecting `choice`.
- **All Tools.** `app/simple_menu.py` builds All Tools from every registered QAction (`MainWindow.command(name)`). A new File-menu action shows up in All Tools automatically. Adding it to a `TREE` group is optional.
- **Ollama.** `app/ai/review.py` has `_ollama(prompt, model, host, json_mode)`.
  - Model is `QUANTISHEET_OLLAMA_MODEL`, default `llama3.2`. Host is `QUANTISHEET_OLLAMA_HOST`, default `localhost:11434`.
  - Default timeout is 900 s. Failures raise `AIError`.
  - It has no quick health check, and llama3.2 is text-only (no vision).
- **Background work.** `app/bg.py` has `run(fn, on_done, on_error, owner)` for work off the GUI thread.
- **Page scale.** Scale is written per page with `annotate.apply_op(doc, annotate.new_op("set_scale", pno, ppu=…, unit="ft", name=…))`. Per-viewport scale uses `viewport={"name","rect","ppu","unit","label"}`. `app/dxf.py` lines 611 and 709 already do both. After this, takeoff works the moment the set opens.
- **Reusable code.**
  - `app/dxf.py` already turns a DXF into a scaled ARCH D (2592×1728 pt) PDF — **reuse this for Modulor DXF → plan/elevation pages**.
  - `app/autowalls.py` and `app/autotakeoff.py` already find walls, doors and room tags on plan pages. They are useful for checking the output.
- **Dependencies already present.** pymupdf, numpy, opencv-python-headless, ezdxf, PySide6 6.12.0, pillow. Tests run with pytest, and `tests/test_gui.py` runs Qt offscreen (`QT_QPA_PLATFORM=offscreen`).
- **Modulor** (`github.com/bcllcc/modulor`, MIT) — **v1 kernel (Jon locked Oct 19 2026):**
  - Status: v1.0.0rc3, 24 commits, last commit Jun 13 2026, 0 stars and 0 forks.
  - Dependencies: numpy and manifold3d. manifold3d ships a cp312 win_amd64 wheel.
  - API: 77 JSON ops, including `add_wall`, `add_opening`, `add_room`, `project`, `slice` (horizontal only), and export to SVG, DXF, IFC and PNG.
- **Modulor spike result** (`/tmp/spike` on the box) — evidence; conclusion is **use Modulor with the workarounds below**:
  - What worked: `set_units ft` → 40×20 ft wall loop with 0.5 ft thickness and 9 ft height → room "OFFICE" = 800.0 ft² → `project` axis y (elevation outline) → DXF ($INSUNITS = 2, ft) and SVG. It ran in 0.17 s.
  - DXF path: the DXF opened through QuantiSheet's own `dxf.to_pdf()` at 3/4" = 1'-0" with 0 skipped entities.
  - SVG path: SVG → PDF through PyMuPDF works, but the SVG is in drawing units (44.55 pt wide), so it must be rescaled.
  - Gap (workaround required): the room label printed **"74.3 m2"** on a drawing in feet → strip/override Modulor area labels; print US ft² from plan JSON ourselves.
  - Gap (workaround required): there is no vertical section op → draw A-301 with PyMuPDF from plan JSON (transverse mid-length cut).
  - Gap (workaround required): elevations come back as a bare outline region → post-process: overlay door/window openings from plan JSON onto Modulor elevation SVG/DXF before compositing onto ARCH D sheets.

# Assumptions

- **Platform.** v1 runs on Jon's Windows build (Python 3.12, PyInstaller). **New pip deps required:** `modulor` and `manifold3d`. Both go in `requirements.txt` and PyInstaller hidden-imports / binary collection notes. Step 0 must prove the win_amd64 manifold3d wheel before any genset code lands.
- **Units.** US units only. The plan JSON is in decimal feet, and sheets print feet-and-inches.
- **Sheet.** One sheet size: ARCH D 36×24 in landscape (2592×1728 pt), the same as `dxf.py`'s default.
- **Footprint.** Rectangles only, at most 120×80 ft, one story, 400 to 8,000 SF gross.
- **Building types.** "Single-family" means a single-story house (no garage in v1). "Small commercial" means a one-story box with a flat roof and parapet, occupancy B or M.
- **Occupancy.** The occupancy group is printed as a label only. Nothing is checked against code.
- **Sketch input.** The sketch only gives the footprint outline and proportions, plus room names if they are typed or legible as PDF text. A hand-drawn interior layout is not traced in v1.
- **Viewing.** Jon will review the output in QuantiSheet and in Acrobat. Plain vector PDF is enough; no layers are needed beyond optional OCGs.

# Recommendations

- **Kernel decision (locked).** **Modulor is the v1 drafting kernel.** It produces the 3D model and exports DXF/SVG for A-101 (floor plan) and A-201 (elevations). PyMuPDF still composites sheets, titles, schedules, cover, notes, and disclaimer text.
  - Keep a **thin PyMuPDF fallback only** for: (1) the vertical section sheet A-301 (Modulor has no vertical section op), and (2) schedules / cover / notes sheets (tables and text — no geometry engine needed).
  - Do **not** silently replace Modulor with a full PyMuPDF geometry kernel if Windows install fails. Step 0 STOP-and-report is mandatory.
- **Modulor gaps → required v1 workarounds (Claude implements these):**
  1. **Room labels print m² on feet drawings.** Strip or suppress Modulor area labels in the exported DXF/SVG. Print US ft² room tags from plan JSON ourselves via `draw.room_tag()`.
  2. **No vertical section.** Draw A-301 with PyMuPDF from plan JSON: transverse cut at mid-length (same section logic as the old PyMuPDF plan). Put this in `kernel_section.py` or in `sheets.py` / `views.section()`.
  3. **Elevations as bare outline.** After Modulor `project`, overlay door/window openings from plan JSON onto the elevation SVG/DXF (sill/head, width, wall `along`) before compositing onto the ARCH D sheet.
- **Single source of truth.** One building-plan JSON feeds every sheet **and** the Modulor op list. Plan, elevations, section and schedules all read from it, so they can't disagree. That is the coordination.
- **Division of labor.** The LLM does two jobs only: brief → JSON fields, and project-specific note text. Every number on a drawing comes from code (layout + Modulor + our overlays).
- **Graceful degradation.** Ollama down, an unreadable sketch, or an SF mismatch never blocks output. Each one degrades to form fields or defaults and adds a line to a **Warnings** box on the cover sheet. Modulor itself is **not** optional in v1.

## Elon's build order, applied

1. **Question requirements.**
   - "Floor plan(s)" means one plan for one story.
   - "4 elevations" fit on one sheet.
   - Room, door and window schedules are tables, not drawings, so they need no geometry engine.
   - Sketch input only has to give a footprint. A wall-by-wall trace is not needed.
2. **Delete.**
   - Interior sketch tracing, stairs, garages, multiple roof types (keep gable and flat), multiple sheet sizes, and metric units.
   - Full IFC export UI in v1 (Modulor can export IFC later; not a sheet).
   - Revision clouds and a sheet editor.
   - The vision model: llama3.2 can't see, and OpenCV finds a rectangle.
   - Golden-PDF checksums.
3. **Simplify.**
   - Rooms come from a squarified-treemap split of the footprint, then are snapped to a 1 ft grid. Plan JSON drives Modulor `add_wall` / `add_room` / `add_opening`.
   - Every interior door opens onto the "hub" room (Living or Open Office), with no corridor solver.
   - Windows follow a rule: one per 12 ft of exterior wall in each habitable room.
   - The section is a transverse cut at mid-length (PyMuPDF).
4. **Speed up.**
   - Use a pure function `build_set(plan, out_path)` with no Qt, tested with pytest in under 5 s (Modulor export included).
   - Add a CLI entry, `python -m app.genset brief.txt out.pdf`, so Claude can iterate without the GUI.
5. **Automate.**
   - Only after the set looks right: a pytest that builds 3 sample briefs, plus a self-check that runs QuantiSheet's own `autowalls`/`autotakeoff` on A-101 and compares the result to the JSON.

# Sheet list (v1, fixed)

| # | Sheet | Content | Scale | Drawn by |
|-|----|-------------|---|----|
| 1 | G-001 Cover | Project data, sheet index, code-data placeholders ("by design professional"), Warnings box, disclaimer band | NTS | PyMuPDF |
| 2 | G-002 General Notes | Template notes plus LLM project notes (or template only) | NTS | PyMuPDF |
| 3 | A-101 Floor Plan | Walls (poché), doors with swings, windows, room tags with name, number and SF (our ft²), door/window marks, overall and string dimensions, north arrow | 1/4", 3/16" or 1/8" auto | Modulor DXF/SVG → composite; tags/dims/openings overlay from JSON |
| 4 | A-201 Exterior Elevations | North, South, East and West in a 2×2 grid; openings overlaid from JSON; grade, floor, plate and ridge/parapet level lines | same as plan | Modulor `project` outline + openings overlay |
| 5 | A-301 Building Section | Transverse section: slab, walls, plate, roof (gable or flat + parapet), level markers | 1/4" or 1/8" | **PyMuPDF only** (Modulor has no vertical section) |
| 6 | A-601 Room Schedule | No., name, area (computed), floor/base/wall/ceiling finish (defaults by room type), ceiling height | NTS | PyMuPDF |
| 7 | A-602 Door & Window Schedules | Mark, type, W×H, count, location (from/to room or wall), sill/head | NTS | PyMuPDF |

**Title block.** It runs as a right-hand strip, 4.5 in wide, on every sheet. Fields, top to bottom:

- `[FIRM NAME]`
- `[FIRM ADDRESS]`
- Project name
- Address, or "ADDRESS TBD"
- Sheet title
- Sheet number
- Scale
- Date
- "Drawn: QuantiSheet Generate Set v1"
- Revision box (empty)
- **FOR REVIEW — NOT FOR SEALING**, in red, 14 pt bold

There is also a light-gray diagonal watermark, "FOR REVIEW — NOT FOR SEALING", on every sheet.

# Data model — building plan JSON (`genset_plan` v1)

Geometry, schedules, notes, **and the Modulor op list** all read this one object. Units are decimal feet. The origin is the southwest exterior corner of the footprint. +X points east and +Y points north. Walls are stored as centerlines.

```json
{
  "schema": "quantisheet.genset_plan/1",
  "units": "ft",
  "disclaimer": "FOR REVIEW — NOT FOR SEALING",
  "project": {
    "name": "Smith Residence", "address": null, "firm": "[FIRM NAME]",
    "date": "2026-10-19", "building_type": "single_family",
    "work": "new", "occupancy": "R-3", "gross_sf_target": 1600
  },
  "source": {
    "brief": "3 bed 2 bath ranch, about 1600 sf, new", "sketch": null,
    "ai_used": true, "ai_model": "llama3.2",
    "kernel": "modulor", "modulor_version": "1.0.0rc3"
  },
  "footprint": { "width": 50.0, "depth": 32.0, "from": "brief" },
  "level": { "name": "L1", "floor_elev": 0.0, "plate_height": 9.0, "slab": 0.33 },
  "roof": { "type": "gable", "pitch": 6, "ridge_dir": "x",
            "overhang": 1.5, "parapet": 0 },
  "walls": [
    { "id": "W1", "a": [0, 0], "b": [50, 0], "thickness": 0.5,
      "kind": "exterior", "face": "S" },
    { "id": "W9", "a": [20, 0], "b": [20, 14], "thickness": 0.375,
      "kind": "interior", "face": null }
  ],
  "rooms": [
    { "id": "R101", "number": "101", "name": "LIVING", "type": "living",
      "rect": [0.25, 0.25, 19.8, 14.0], "area": 277.0, "target_sf": 280,
      "finishes": { "floor": "LVP", "base": "WD", "walls": "GWB-PT",
                    "ceiling": "GWB-PT" }, "ceiling_ht": 9.0 }
  ],
  "openings": [
    { "id": "D1", "kind": "door", "mark": "101", "type": "A",
      "wall": "W1", "along": 10.0, "width": 3.0, "height": 6.67,
      "swing": "in-left", "from_room": "EXT", "to_room": "R101" },
    { "id": "N1", "kind": "window", "mark": "A", "type": "A",
      "wall": "W1", "along": 4.0, "width": 3.0, "height": 4.0, "sill": 3.0 }
  ],
  "door_types":   { "A": "3'-0\" x 6'-8\" ext. insulated", "B": "2'-8\" x 6'-8\" int. hollow core" },
  "window_types": { "A": "3'-0\" x 4'-0\" single hung", "B": "2'-0\" x 3'-0\" (bath, obscure)" },
  "notes": { "general": ["..."], "project": ["..."], "from_ai": true },
  "warnings": ["Program total 1,720 SF exceeds net area 1,536 SF; rooms scaled 0.89."]
}
```

**Rules that `model.validate()` enforces.** Each one raises `PlanError` or appends a warning.

- Every room `rect` lies inside the footprint.
- Rooms don't overlap: pairwise intersection area must be under 0.01 ft².
- Every opening's `along ± width/2` lies within its wall length minus 0.5 ft at each end.
- Each room `area` equals the computed rect area within 0.5 ft².
- Every interior door connects two existing rooms.
- Every habitable room (bed, living, office) has at least one window, or a warning.
- `disclaimer` is exactly the string above.
- `source.kernel` is `"modulor"` for v1 builds.

# Files to add or change (all under Jon's Windows QuantiSheet source; box mirror is `/workspace/r7/src` — do not edit live `app/` from this plan alone)

| Path | Status | Purpose |
|----------|----|--------------------|
| `app/genset/__init__.py` | new | Version, `DISCLAIMER` constant, `build_set` re-export |
| `app/genset/model.py` | new | Dataclasses `Plan/Wall/Room/Opening`, `to_json/from_json`, `validate()`, `PlanError` |
| `app/genset/brief.py` | new | `ai_up(timeout=2)` (GET `/api/tags`); `parse(text, form) -> dict` via `review._ollama(json_mode=True)` plus a regex fallback; form fields always win |
| `app/genset/sketch.py` | new | `footprint_from(path, page=0) -> (w_ratio, d_ratio, room_names)`: OpenCV largest closed contour; PDF text via `autotakeoff.room_labels` |
| `app/genset/program.py` | new | Default programs by type and SF; `reconcile(program, net_sf)` scales areas and returns warnings |
| `app/genset/layout.py` | new | Footprint sizing, squarified treemap → room rects (1 ft snap), interior walls from shared edges, doors and windows by rule |
| `app/genset/kernel_modulor.py` | new | **Primary kernel.** Plan JSON → Modulor op list (`set_units`, `add_wall`, `add_room`, `add_opening`, `project`, `export`). Strip m² labels. Return DXF/SVG paths for plan + 4 elevations. |
| `app/genset/kernel_section.py` | new | **Thin PyMuPDF section.** Transverse mid-length cut from plan JSON → drawing commands for A-301. (May live in `views.py` / `sheets.py` instead; one place is enough.) |
| `app/genset/adapters.py` | new | DXF/SVG → scaled ARCH D page content; reuse `app/dxf.py` for DXF; rescale Modulor SVG drawing-units → page points; openings overlay helper for elevations |
| `app/genset/draw.py` | new | PyMuPDF primitives: `wall()`, `door()` (leaf and 90° arc), `window()`, `dim()`, `room_tag()` (US ft²), `level_line()`, `north_arrow()`, `table()`, `fmt_ftin()`, elevation opening overlay |
| `app/genset/titleblock.py` | new | `titleblock(page, plan, sheet_no, title, scale_label)` plus watermark |
| `app/genset/views.py` | new | Orchestrates plan_view (Modulor), elevation(face) (Modulor + overlay), section() (PyMuPDF) |
| `app/genset/schedules.py` | new | Row builders for rooms, doors and windows (pure data), plus table rendering through `draw.table` |
| `app/genset/notes.py` | new | Template general notes; `project_notes(plan)` via Ollama with template fallback |
| `app/genset/build.py` | new | `build_set(plan, out_path) -> summary`: call Modulor kernel, composite 7 pages, `set_scale` per page or viewport, metadata, `safeio.atomic_save`; also saves `<out>.genset.json` beside the PDF |
| `app/genset/__main__.py` | new | CLI: `python -m app.genset --brief "..." [--sketch f] out.pdf` |
| `app/genset_ui.py` | new | `GenerateSetDialog` (QDialog), described in Step 7 |
| `app/main_window.py` | change | In `_build_menus()`, after "New From Form Library…": `self._act(f, "Generate Set…", None, lambda: self.generate_set(), False)`; new method `generate_set(self, request=None, out=None)` |
| `app/simple_menu.py` | change (1 line) | Add "Generate Set" to the `("Project","More",…)` group; All Tools picks it up anyway |
| `app/helpcenter.py` | change | One topic: "Generate Set (starter CD set) — for review, not for sealing" |
| `requirements.txt` | change | Add `modulor` and `manifold3d` |
| `quantisheet.spec` | change | Hidden imports / collect for `modulor`, `manifold3d` (and any native `.pyd` / DLLs the win_amd64 wheel needs) |
| `BACKLOG.md` | change | Modulor Windows spike result (Step 0), workarounds, later-phase list |
| `tests/test_genset_*.py` | new | Described in the Test plan section |

# Steps for Claude (numbered, with acceptance tests)

Work in Jon's Windows QuantiSheet source (ship as **0.12.11**). The box mirror at `/workspace/r7/src` is for reference only — do not treat the box as the live install. Run `pytest -q tests/test_genset_*.py` after every step.

**Step 0 — Modulor Windows install + spike gate (1–2 h).** Hard go/no-go. Install Modulor on Windows Python 3.12, confirm manifold3d win_amd64 wheel, re-run the checklist below, and document results in `BACKLOG.md`. Add `modulor` and `manifold3d` to `requirements.txt` and draft PyInstaller notes in `quantisheet.spec` only after the spike passes.
*Accept:* `BACKLOG.md` has a "Modulor spike Windows 2026-10" entry with pass/fail per checklist line. **If install or import fails inside a frozen-exe smoke, STOP and report to Jon. Do not implement a full PyMuPDF geometry kernel as a silent substitute.**

**Step 1 — `model.py` (2 h).** Build the dataclasses, JSON round-trip and `validate()` with every rule listed above. Add `fmt_ftin(9.5) == "9'-6\""` and rounding to 1/2". Include `source.kernel == "modulor"`.
*Accept:* `test_genset_model.py` passes. The sample JSON above (completed) round-trips byte-identical. An overlapping room raises `PlanError`. An out-of-wall door raises `PlanError`.

**Step 2 — `program.py` + `layout.py` (4 h).**
- **Footprint.** Width × depth from SF and aspect ratio: 1.6 for single-family, 2.0 for commercial, rounded to 2 ft. When a sketch is given, use the sketch ratio instead.
- **Net area.** Gross minus exterior wall area. Run `reconcile()`.
- **Rooms.** Squarified treemap, with the hub room placed on the south side.
- **Interior walls.** Built from shared rect edges and de-duplicated.
- **Exterior doors.** Front door centered on the hub's south wall. A rear door on the north wall for single-family.
- **Interior doors.** Each non-hub room gets one door on the wall it shares with the hub or the nearest room that reaches the hub. If none exists, add a warning and put the door on the longest shared edge.
- **Windows.** One per 12 ft of exterior wall per habitable room; type B in baths.
*Accept:*
- A 1,600 SF 3-bed/2-bath plan validates.
- Sum of room areas is between net × 0.97 and net × 1.0.
- Every room is reachable from the front door (BFS over doors).
- A 4,000 SF "retail M" plan validates.
- Running it twice gives identical JSON (no randomness).

**Step 3 — `kernel_modulor.py` + adapters (4–5 h).** Wire plan JSON → Modulor ops → DXF/SVG.
- Build ops: `set_units ft`, exterior + interior `add_wall`, `add_room`, `add_opening` for each door/window, `export` plan DXF and SVG, `project` for N/S/E/W elevations then export each.
- **Strip/override Modulor area labels** (m² bug). Room tags come only from our `draw.room_tag` using plan JSON ft².
- Reuse `app/dxf.py` to place Modulor DXF onto ARCH D drawing area; rescale SVG drawing-units → page points.
- **Elevation openings overlay:** from plan JSON, for each face, draw door/window rectangles at sill/head on the Modulor outline before compositing.
*Accept:*
- A 40×20 ft office plan produces DXF that `dxf.to_pdf` opens with 0 skipped entities.
- Exported plan drawing text does **not** contain "m2" / "m²" from Modulor; our room tag shows e.g. `800 SF`.
- Each elevation export exists; after overlay, window count on South matches openings on S walls.

**Step 4 — `draw.py` + `titleblock.py` + `kernel_section.py` (3–4 h).**
- Shared primitives for tags, dims, north arrow, tables, title block, watermark.
- A door drawn by us (for overlays / section / takeoff-friendly plan marks) is a leaf line plus a 90° arc made of 4 Béziers — use the arc form `autotakeoff.door_swings` already detects.
- A window overlay is 3 parallel lines (plan) or a sill–head rectangle (elevation).
- **Section (PyMuPDF):** cut at x = width/2 through depth: slab, both exterior walls (poché), any interior walls cut, ceiling line, roof. Level markers for T.O. Slab, Plate and Ridge/Parapet.
- Use Helvetica (base-14). **Check that the em dash survives:** `page.get_text()` must contain "FOR REVIEW — NOT FOR SEALING". If it doesn't, embed the font with `insert_font` from a TTF, or use `page.insert_htmlbox`.
*Accept:*
- Unit test draws one title-block page; text contains disclaimer, sheet number, scale; `len(page.get_drawings()) > 20`.
- Section math: a 50×32 ft 6:12 gable over 32 ft depth puts the ridge at plate + 8.0 ft (pytest on the math function, not the PDF).

**Step 5 — `views.py` orchestration + schedules + notes (2.5 h).**
- **Plan scale.** Choose the largest of 1/4", 3/16" or 1/8" at which the footprint plus 6 ft of dimension margin fits the drawing area (2592 − 324 − 72 by 1728 − 144 pt). `ppu` is points per ft (1/4" → 18.0).
- `plan_view` / `elevation` call Modulor + adapters; `section` calls `kernel_section`.
- Schedule rows are generated only from `plan`. Doors are grouped by mark, and windows by type with counts.
- `notes.py` holds about 15 template general notes. The first note is: "These drawings are a computer-generated starting point FOR REVIEW — NOT FOR SEALING. A licensed design professional must verify all information."
- Project notes come from Ollama, with prompt = plan summary JSON and the instruction "≤8 short notes, no code citations, no dimensions". If `ai_up()` is False or `AIError` is raised, use template project notes and set `from_ai=false`.
*Accept:*
- The room schedule total SF equals the sum of `rooms[].area`.
- The door schedule count equals the number of door openings.
- With `QUANTISHEET_OLLAMA_HOST=http://127.0.0.1:9`, notes still come back in under 3 s.
- A window's x on the S elevation equals its `along` (±0.01 ft) after overlay.

**Step 6 — `brief.py`, `sketch.py`, `build.py`, `__main__.py` (3 h).**
- **`brief.parse`.**
  1. Regex pass for SF, beds/baths, new/existing, occupancy letters, and the words "retail/office/house".
  2. If `ai_up()`, call `_ollama(json_mode=True)` with a fixed schema prompt. The LLM may fill *only* `project.*` and `program` (room list with names, types and target SF).
  3. Clamp and validate. Form fields override both.
- **`sketch.footprint_from`.**
  - Inputs: PNG/JPG, or a PDF page rendered at 150 dpi.
  - Process: Canny + contours, keep the largest 4-point approximation that covers at least 15% of the image, and return its aspect ratio.
  - Failure: nothing found → `None` plus a warning.
  - PDF pages also return room names found by `autotakeoff.room_labels`.
- **`build_set`.**
  - Requires Modulor (import/run). Writes the 7 pages: Modulor for A-101/A-201, PyMuPDF section for A-301, PyMuPDF for G-001/G-002/A-601/A-602.
  - `set_scale` is applied per page for A-101/A-201/A-301, as a viewport on the drawing rect so the title-block area is excluded.
  - Metadata: `subject` = disclaimer, `creator` = "QuantiSheet Generate Set v1".
  - Writes `<out>.genset.json` next to the PDF (includes `source.kernel`).
- **CLI.** `python -m app.genset --brief "1600 sf 3 bed 2 bath ranch new" /tmp/g.pdf`.
*Accept:*
- The CLI makes a 7-page PDF in under 5 s without Ollama (Modulor included).
- Every page's text contains the disclaimer.
- Page 3 has a scale op recorded (read it back through annotate, the way `test_dxf` does).
- A blank white PNG as sketch still builds, using the brief proportions, with a warning on G-001.
- If `modulor` is not importable, `build_set` raises a clear error (no silent full-PyMuPDF path).

**Step 7 — `genset_ui.py` + wiring (2.5 h).**
- **Dialog layout.**
  - Top: a red banner, "FOR REVIEW — NOT FOR SEALING. Generates a starting point, not a permit set."
  - Fields: Brief (QPlainTextEdit); Type (Single-family / Small commercial); New / Existing; Gross SF (spin, 400–8000); Occupancy (combo: R-3, B, M, auto); Project name; Address (optional); Firm name (optional, default `[FIRM NAME]`); Sketch (file picker: png, jpg, pdf, plus a page spin).
  - Status line showing "AI: on (llama3.2)" or "AI: off — using form fields".
  - Buttons: Generate and Cancel.
- **Generate.** Runs `brief.parse → layout → build_set` through `bg.run` so the GUI never freezes. A Save As dialog defaults to `<project>_GenSet_v1.pdf`.
- **`MainWindow.generate_set(request=None, out=None)`.** If `request` is None, show the dialog. Otherwise build directly (the test path). Then call `self.open_path(out)` and show a status-bar message with the warning count.
- Add the File menu action and the `simple_menu` entry.
*Accept:*
- With `QT_QPA_PLATFORM=offscreen`, `test_genset_ui.py` calls `win.generate_set(request={...}, out=tmp)`. A new tab is open on that path with 7 pages, and `win.command("Generate Set")` is not None.
- The dialog text contains the disclaimer.

**Step 8 — Self-check with QuantiSheet's own takeoff (1 h).** On A-101, run `autowalls.doors(page, ppu)` and `autotakeoff.room_labels(page)`.
*Accept:* the detected door count equals the door openings ±1, and every room name is found (our ft² tags, not Modulor m²). If not, fix overlays / `draw.py` (usually arc form or text size). This proves "takeoff tools work on it immediately".

**Step 9 — Polish, bundling, docs (2–3 h).**
- Finalize PyInstaller: hidden imports for `modulor` and `manifold3d`; collect binary wheels / DLLs so the frozen exe imports Modulor.
- Add the Help Center topic and `BACKLOG.md` later phases.
- Render each page of 3 sample sets (house 1,600 SF; office 2,400 SF B; retail 4,000 SF M) to PNG with `pdftoppm -r 40`.
- Look at each page and fix overlaps: text over walls, dimensions colliding, elevation openings misaligned.
- Bump / ship as **QuantiSheet 0.12.11**.
*Accept:* the 3 sample PDFs and PNG contact sheets are in a `genset_samples/` folder next to the build, frozen-exe smoke imports Modulor, and the full test suite is still green.

# Modulor spike checklist (Step 0)

Already run on the Linux box (evidence below). Claude **repeats it on Windows Python 3.12 and in the PyInstaller build**. Decision is already **go Modulor for v1**; Step 0 only confirms Windows + bundle.

- [x] `pip install modulor` (or `pip install git+https://github.com/bcllcc/modulor`). Pulls numpy + manifold3d; a win_amd64 cp312 wheel exists. *(box: pass; Windows: Claude)*
- [x] `modulor ops` lists 77 ops. *(box)*
- [x] A 20×40 ft room, run with `modulor run m.json s.json`:
  `[{"op":"set_units","units":"ft"}, {"op":"add_wall","path":[[0,0],[40,0],[40,20],[0,20],[0,0]],"thickness":0.5,"height":9}, {"op":"add_room","name":"OFFICE","points":[[0,0],[40,0],[40,20],[0,20]]}, {"op":"export","path":"plan.dxf"}, {"op":"export","path":"plan.svg"}]`
  Result: area 800.0 ft², DXF $INSUNITS=2. *(box)*
- [x] DXF → PDF page: `app.dxf.to_pdf("plan.dxf", "plan.pdf")` gave ARCH D at 3/4" = 1'-0" with 0 skipped entities. *(box)*
- [x] SVG → PDF page: `pymupdf.open("plan.svg").convert_to_pdf()` gave one page, but it is 44.55×24.55 pt (drawing units), so it needs rescaling. *(box)*
- [ ] **KNOWN GAP — workaround:** the room label says "74.3 m2" in a ft document → strip/override; print US ft² from plan JSON.
- [ ] **KNOWN GAP — workaround:** no vertical section op (`slice` is horizontal only) → PyMuPDF A-301 from plan JSON.
- [ ] **KNOWN GAP — workaround:** `project` axis y returns only an outline region; openings don't appear → overlay openings from plan JSON.
- [ ] Windows: `import modulor` inside the frozen exe (PyInstaller hidden imports for manifold3d). *Claude tests in Step 0 / Step 9.*
- [ ] Maturity note: rc3, a single maintainer, 0 stars — accepted for v1 with workarounds; revisit IFC polish in Phase 2.
- **Decision (Jon, Oct 19 2026):** v1 **depends on Modulor**. Workarounds above are required. If Windows install fails, STOP and report — do not silently switch to full PyMuPDF.

# Failure modes

| Failure | Detection | Behavior (never blocks output unless noted) |
|--------|----------|--------------|
| Ollama down, not installed, or model missing | `ai_up()` 2 s GET `/api/tags`; `AIError` | Regex + form fields only. Template notes. UI says "AI: off". G-001 Warnings: "AI unavailable — brief parsed from form fields." |
| Ollama slow | 60 s cap per genset call (wrap `_ollama` in a thread with a timeout; don't change the global 900 s) | Same as down |
| LLM returns bad JSON, or a value out of range | `json.loads`, schema clamp (SF 400–8000; rooms ≤ 20; type in enum) | Drop the bad fields, keep the rest, add a warning |
| Sketch unreadable (blank, photo, no closed outline) | No 4-point contour ≥ 15% of area | Use the brief or default aspect ratio. Warning: "Sketch not readable — footprint from SF." |
| Sketch is a multi-page PDF | Page spin in the dialog | Use the chosen page; default 0 |
| SF vs room areas mismatch > 3% | `reconcile()` | Scale every target SF proportionally to net SF. Warning lists the factor. If the program is missing, use the default program. |
| No SF and no sketch | Validation | **Block** with a dialog message: "Enter gross SF or attach a sketch." |
| Footprint > 120×80 ft, or SF > 8,000 | Validation | **Block**: "v1 covers one-story buildings up to 8,000 SF." |
| Multi-story or "two story" in the brief | Regex / LLM `stories > 1` | Build one story. Warning: "Multi-story is a later phase." |
| Room unreachable after layout | BFS in `layout` | Add a door on the longest shared edge and a warning |
| Modulor not installed / import fails | `import modulor` at build start | **Block** with clear message: "Generate Set requires Modulor. See BACKLOG.md Step 0." Never fall back to full PyMuPDF geometry. |
| Modulor export / project fails mid-build | Exception from kernel | **Block**; show error; leave no half-written PDF (`safeio`) |
| Output path locked (open in Acrobat) | `safeio.atomic_save` raises | Message box; nothing is half-written |

# Test plan

- **`tests/test_genset_model.py`.** JSON round-trip; each `validate()` rule (overlap, out-of-wall opening, area mismatch, missing disclaimer); `fmt_ftin` cases (0, 0.5, 9.5, 12.0417, 100); `source.kernel`.
- **`tests/test_genset_layout.py`.**
  - Footprint from SF and aspect ratio.
  - Treemap areas within 1% before the 1 ft snap and 3% after.
  - Rooms don't overlap; doors make every room reachable.
  - Window rule counts.
  - Deterministic output.
  - `reconcile` scaling and warning text.
- **`tests/test_genset_modulor.py`.** Op-list shape from a sample plan; export produces DXF/SVG; stripped labels contain no Modulor m²; elevation overlay window positions; skip or xfail only if Modulor missing *in CI without the dep* — on Jon's machine Modulor is required.
- **`tests/test_genset_views.py`.** Gable ridge height math (section); elevation opening x-positions, including E/W mirroring; section cut finds both exterior walls; scale picker (40×20 → 1/4", 120×80 → 1/8").
- **`tests/test_genset_build.py`.**
  - `build_set` on the 3 sample briefs gives 7 pages.
  - The disclaimer is on every page.
  - The sheet numbers G-001…A-602 are present.
  - The scale op is on pages 3–5.
  - The sidecar JSON exists with `kernel: modulor`.
  - It runs with Ollama pointed at a dead port and finishes in under 8 s total.
  - Self-check: the door count from `autowalls.doors` matches.
- **`tests/test_genset_ui.py`** (one GUI smoke, offscreen). The menu action exists; `generate_set(request, out)` opens a 7-page tab; the dialog shows the disclaimer.
- No golden-PDF checksums. No live-Ollama test in CI. Mark one test `@pytest.mark.ollama` to run by hand.

# Rough effort (Claude hours)

| Step | Hours |
|---|---|
| 0 Modulor Windows install + spike gate + requirements/spec draft | 1–2 |
| 1 Model + validate | 2.0 |
| 2 Program + layout | 4.0 |
| 3 kernel_modulor + DXF/SVG adapters + label strip + elevation openings overlay | 4–5 |
| 4 Draw + title block + PyMuPDF section | 3–4 |
| 5 Views orchestration + schedules + notes | 2.5 |
| 6 Brief, sketch, build, CLI | 3.0 |
| 7 Dialog + wiring | 2.5 |
| 8 Takeoff self-check | 1.0 |
| 9 Polish, PyInstaller bundling, samples, docs, ship 0.12.11 | 2–3 |
| **Total** | **~28–32 h** (Modulor install/bundle + three workarounds vs ~24 h PyMuPDF-only) |

# Out of scope for v1 (later phases, in order)

1. **Phase 2:** multi-story (levels, stairs, floor-to-floor); polish Modulor IFC/DXF export for handoff; optional vertical-section contribution if Modulor gains it.
2. **Phase 3:** chat revisions ("make the kitchen 2 ft wider" → edit plan JSON → regenerate).
3. **Phase 4:** firm Knowledge Base (title-block template, standard notes, door/window libraries).
4. **Phase 5:** structural, MEP and fire/life-safety sheets.
5. **Phase 6:** IBC auto-compliance engine (egress, occupant load, fire separation). Reuse `codecheck.py` only as a reviewer, never as certification.
6. **Phase 7:** civil/site plan (setbacks, grading, utilities).
7. **Phase 8:** Blueprints AI white-label or partnership.

No stamp or seal feature in any phase without a separate legal review.

# Locked decisions (Jon, Oct 19 2026) — do not re-ask

1. **Kernel.** Modulor in v1 (with the three workarounds). Not deferred to Phase 2.
2. **Disclaimer.** Exact text **FOR REVIEW — NOT FOR SEALING** on every sheet, metadata, and dialog.
3. **v1 limits.** One story, rectangle only, 400–8,000 SF, ARCH D only, US units, no garage, sketch = footprint outline only (no interior tracing).
4. **Firm name.** Stay `[FIRM NAME]` placeholder.
5. **Release.** Ships as **QuantiSheet 0.12.11**. Claude builds in the Windows source tree; nothing lands in the live install until Jon runs the new installer.
