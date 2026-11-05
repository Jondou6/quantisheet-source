# Generate Set v1 - build notes

Plan: `docs/GENERATE_SET_V1_PLAN.md`. Shipped in 0.12.14.

## Kernel (Step 0 spike, Windows)
- Modulor 1.0.0rc3, MIT, commit 40f6c2a, installed from the reviewed source
  zip (`tools/install_modulor.py` checks its SHA-256 first). Needs numpy and
  manifold3d 3.5.4 (cp312 win_amd64 wheel).
- 77 ops for an 800 SF test room; DXF $INSUNITS = 2; `dxf.to_pdf` drew at
  3/4" with nothing skipped; works in a plain PyInstaller build.
- Known gaps worked around: Modulor's labels are m2 (we draw our own SF
  tags); the elevation is a bare outline (openings drawn from the plan).

## What v1 does
- One-story rectangle, 400 - 8,000 SF; single-family (R-3) or small
  commercial (B / M label only).
- Seven sheets: G-001, G-002, A-101, A-201, A-301, A-601, A-602, every one
  marked FOR REVIEW - NOT FOR SEALING; plan JSON saved as `.genset.json`.
- Local AI (if running) reads the brief and writes project notes; it never
  places geometry. Without it: text rules and template notes.

## Checks (`tools/genset_samples.py`)
- house 1,600 / office 2,400 / retail 4,000: 7 pages, disclaimer and sheet
  number on each, no m2, scales on the drawn sheets, door count read back by
  `autowalls.doors` equals the door schedule.

## Fixed during the build
- Page objects go stale once more pages are added: pages are fetched by
  number for each step, and scale viewports are written after drawing.
- Embedded Arial read back as no-break spaces / soft hyphens (Find and
  takeoff broke); built-in Helvetica is used instead.
- West dimension strings were drawn inside the plan.

## 0.12.17
- AS-101 Site Plan: lot and setbacks from the brief ("lot 80 x 120",
  "10,000 sf lot", "0.25 acre", "setbacks 25 front, 10 side, 20 rear");
  anything missing is drawn and labelled ASSUMED - verify with zoning. The
  self-check says whether the building is inside the setbacks.
- A-102 Roof Plan: gable (ridge, pitch arrows, eaves, rakes) or low-slope
  (parapet, drains, slope arrows).
- DXF gets C-PROP / C-PROP-SBCK.
- Bedrooms: every bedroom door opens onto the hall (12,676 bedroom doors
  in a 3,744-plan sweep; locked in by a test).

## 0.12.18 - two-story houses (decisions to confirm with Jon)
- Up to two stories, houses only; two-story office/retail is drawn as one
  story with a warning (second exit stair, elevator).
- The brief's SF is the whole house; each floor gets half. 1,200 SF minimum.
- A center stair hall 7 ft wide front to back on both floors; a straight
  stair 3'-6" wide, 16 risers x 7 1/2", 15 treads x 10" (10'-0" floor to
  floor: 9 ft plate + 1 ft framing), 4 ft clear at the bottom, 3 ft at the
  top. Every room opens onto the hall; no door opens into the side of the
  stair (the layout reorders rooms, mirrors the wings or moves the stair
  until that holds).
- Level 1: living (west), kitchen (east), dining, a powder room by the
  hall with the laundry/mech beside it off the kitchen. Level 2: the
  bedrooms, a hall bath and the primary bath off the primary bedroom.
  The laundry moves upstairs before it is left out.
- Ten sheets: A-101 Level 1, A-102 Level 2, A-103 Roof Plan; elevations
  and the section show both floors; schedules list both (201... upstairs);
  the DXF puts level 2 30 ft east of level 1. The self-check runs on each
  floor (level 2 reached from the stair).
- Sweep: 120 plans 1,600-8,000 SF, no FAIL; 1,200-1,800 SF houses leave
  rooms out (shown on the cover).

## 0.12.19 - attached garage, section through the stair
- "garage" in the brief (or GARAGE on a sketch): 2-car unless it says 1-
  or 3-car; 12 / 22 / 32 ft wide x 22 ft deep (centrelines), flush with
  the front. It goes on the side whose room is best to enter from it
  (laundry, kitchen, mech, hall, dining, living - never a bedroom or
  bath), unless covering that wall would leave a bedroom with no window.
- One door into the house (type C, fire-rated, self-closing - verify);
  overhead doors 9 ft (1 car), 16 ft (2), 16 + 9 ft (3), 7 ft high.
  House windows under the garage are taken out and put back on the
  room's other outside walls where they fit.
- Drawn on the floor plan, site plan (with a drive), roof plan (its own
  lower gable), elevations (beside the house, or its gable in front),
  room and door schedules (not heated, not in the gross), cover, DXF.
  Self-check: the garage door opens into a proper room; no window looks
  into the garage. 963-plan sweep: every garage placed, no FAIL.
- Two-story sections are cut through the stair: the stair profile and
  the stairwell opening in the second floor show.

## 0.12.20 - front porch and rear deck
- "porch" / "covered porch" / "front porch": 6 ft deep (8 ft for "wide",
  "wraparound", "farmhouse" - drawn as a front porch), as wide as the room
  the front door opens into (10-24 ft), centred on the door, never over
  the garage; posts every ~8 ft, a shed roof 8'-0" to 9'-6".
- "deck" / "rear deck" / "back deck": 10 ft deep behind the rear door (on
  the back wall), 12 or 16 ft wide, at floor level, 36" guard. No rear
  door on the back wall: no deck (a warning says so).
- Not heated, not in the gross. On the floor plan (level 1), site plan,
  roof plan (porch roof), elevations, cover and DXF (A-FLOR-OTLN). A
  porch or deck in a setback is noted - towns often allow it; verify.

## 0.12.21 - quantities into the estimate, paving
- The A-701 rows are stored inside the set's PDF
  (quantisheet_set_quantities.json). The Quantities panel lists them as
  "Set" lines, priced and exported like takeoff lines. Rows from a PDF are
  data: bad ones are skipped, at most 500 are read.
- Paving drawn on AS-101 is counted: the driveway (the overhead doors plus
  1 ft each side, to the front lot line) and a 4 ft front walk (to the
  porch's front edge when there is a porch - the walk is no longer drawn
  under the porch).

## 0.12.22 - narrow lots (Claude, Oct 19 - for Jon to confirm)
- When the brief gives the lot and the house doesn't fit its setbacks,
  other proportions are tried (narrower and deeper for a tight width,
  wider for a shallow lot, from 2.4:1 to 1:2). The first that fits the
  setbacks without leaving out more rooms and without a worse self-check
  is used, and a warning says so ("Proportions changed to fit the lot").
  A shape that makes a living room or bedroom more than 2.5 times as long
  as it is wide doesn't count as better - two-story houses on lots under
  about 45 ft kept their shape in 0.12.22 - see 0.12.23.
  A sketch's proportions are never changed; without a lot nothing
  changes.
- A deep, narrow one-story house uses the same zoning turned a quarter:
  living/kitchen/dining across the front, a hall running back with the
  bedrooms and baths on both sides. The front door stays on the street.
- A house deeper than it is wide gets its ridge north-south (a front
  gable to the street), on the roof plan, elevations and in the roof
  quantities; a one-story one is cut across (through the gable) on A-301.
- A deep house's back door goes at the end of the hall (where a deck can
  go). With a garage the ridge stays east-west (the garage roof meets a
  gable wall). A garage now takes a side that leaves every room a window
  when there is one, and the cover names the room its door really opens
  into. (A second independent check, of 0.12.22.)
- Known, for later: a front porch's shed roof under an east-west eave is
  drawn 8'-0" to 9'-6" - above the 8'-3" eave; tie it into the main roof
  or lower it when the porch design is settled.
- Review fixes (an independent check of 0.12.21): prices of inf / nan /
  1e30 are refused (they froze the Quantities panel); the set's rows find
  the A-701 sheet by its label after pages move; no negative front walk
  when the porch reaches the lot line; the IT detection script reads the
  64-bit registry from 32-bit PowerShell and refuses a bad version; winget
  manifests carry each setup's ProductCode.

## 0.12.23 - two-story houses on narrow lots (Claude, Oct 20 - for Jon to confirm)
- A floor too narrow for a good wing on each side of the center stair hall
  (under 10'-6" each) gets a side hall: the stair hall along the west
  wall with the stair against that wall, and every room in one wide wing
  east of it - a side-hall row house. Level 1 runs living, dining,
  powder + laundry, kitchen from front to back; level 2 the bedrooms and
  baths. Houses wide enough for two wings are unchanged.
- So a 2,400 SF two-story house on a 40 ft lot (5 ft sides) becomes
  28' x 42' and fits, where 0.12.22 kept it 44' x 28' and over the side
  setbacks.

## 0.12.24 - fixes from the Venice review (verified first)
- Garage walls in the quantities: 2 x width + depth (was 2 x depth + width).
- Two-story wings: every band order is tried before a room is dropped.
- The garage door keeps 3'-6" clear of the stair (side-hall houses), and a
  garage that takes the back door says so.
- "no covered porch" draws none; "8 ft deep porch" sets the depth (4-12 ft).
- The dimension check fails a gap along the front; plan dimensions clear a
  west garage, and a side hall's room breaks go on the east side.
- A side hall gets a window on each floor; the section shows the ridge
  beyond the cut, dashed.
- Rooms left out are stored in the plan (plan["dropped"]).
- Not changed (checked, the finding didn't hold): HKCU\Software\Policies
  can't be written by users (read-only ACL on Jon's PC); the A-701 label was
  already passed in 0.12.22; plan generation is fast (worst brief tried:
  0.2 s).
- Known, for later: a front porch's shed roof under an east-west eave.

## 0.12.25 - accessibility for office and retail sets
- New sheet A-801 Accessibility (office and retail only): door clear width,
  maneuvering depth and latch-side wall, restroom turning space, route
  width, a route from the entrance to every room, and the chapter 2
  scoping lines (app/genset/ada_plan.py, docs/ADA.md).
- Office and retail plans: 3'-0" interior doors (2'-8" is under 32 in.
  clear), a 5 ft hall, restrooms 5'-9" wide minimum, 18 in. of wall beside
  the latch where the wall allows. Houses unchanged.

## Later
- Non-rectangular footprints; a basement; wraparound porches.
- Site: parking for commercial; side-entry houses on very narrow lots.
- Read more from a sketch than its proportions and typed room names.
