# QuantiSheet 0.13.11 (beta)

QuantiSheet (formerly PDF Studio) is a PDF program for construction:
- drawing sets, markups and scaled takeoff;
- estimating and bid tools;
- a starter-set generator.

This is a **beta**: you need a license key to run it.

## Downloads

| File | For |
|---|---|
| `QuantiSheet-Public-Beta-Setup-0.13.11.exe` | One PC. Installs for the current user (no admin needed). |
| `QuantiSheet-Public-Beta-Server-Setup-0.13.11.exe` | IT departments: Windows Server, Remote Desktop, Intune/SCCM/PDQ. Installs for all users (admin). Includes the Group Policy template and the optional collaboration relay service. |
| `QuantiSheet-Public-Beta-0.13.11.msi` | IT departments that deploy MSI packages (Intune line-of-business, SCCM, Group Policy). All users, admin. |
| `SHA256SUMS.txt` | The SHA-256 of each installer |

The installers aren't code-signed yet, so Windows SmartScreen will warn about an unknown publisher. Before running one, check its hash:

```
Get-FileHash .\QuantiSheet-Public-Beta-Setup-0.13.11.exe
```

The hash must match the one in `SHA256SUMS.txt`.

**Requirements:** Windows 10/11 64-bit, or Windows Server 2016 or later with Desktop Experience. IT deployment, silent install switches, Group Policy settings and the network list are in `IT_DEPLOYMENT.md`.

## New in 0.13.11
- QuantiSheet always opens maximized and on the **Home** ribbon tab, instead of the last window size and the last tab used. Un-maximizing still goes back to the size the window had before.
- Project Center and the Master Schedule window also open maximized.

## Earlier (0.13.10)
### Master Schedule (sub updates)
- **Module > Master Schedule (Sub Updates)** keeps the GC's master schedule current from the subcontractors' monthly updates.
- Each sub gets an Excel update sheet listing only their own activities, with the neighbouring trades' activities shown locked for context. Subs can also send an MS Project XML or P6 XER file.
- Returned files are picked up from a watched folder, or added by hand. Each file is checked as a whole, and a file with any error is rejected with every reason listed. Nothing from a rejected file is applied.
- Each update shows its impact before it's accepted: activities that finish later, any shift in the project finish and Substantial Completion, and new schedule problems. Updates that only report progress (percent complete, actual dates, notes) and move nothing later can be accepted automatically; everything else waits for review. Approved and auto-accepted updates can be reverted.
- The baseline can be locked. While it is, Set Baseline is refused, and a new baseline is made with Re-baseline.
- Reminder and result e-mails are written as drafts only. Nothing is sent.

### Project Calendar (Project Center)
- A new **Calendar** page in Project Center shows the job by month or week. It covers schedule activities and milestones (critical-path items marked ●), inspections, meetings and expected deliveries, with a checkbox to show or hide each kind.
- Drag a meeting, inspection or delivery to another day to move it. Drag across days, or double-click a day, to add a meeting or inspection. Click any item to open it.
- Schedule activities are shown but not moved here: they move in the Gantt chart, where their links and float are shown.
- The page's look follows the MIT-licensed Kargul calendar design (credited in Help > Third-Party Licenses). The code is our own.

### Release files
- Every build now writes the files that go beside the installers: `SHA256SUMS.txt` made again from the installers actually in the public folder, the release notes for this version (an old version's notes are removed), and `READ ME FIRST.txt` with this installer's hash.
- The ClaimIT installer carries its own version number.
- The relay server's data folder (its secret is made on first start) is left out of source backups and the repository.

### AI Takeoff - accuracy (checked against two real human takeoffs)
0.13.10 is scored against a second job as well as the first, so fixes have to hold on both sets of drawings.
- **Wall types:**
  - Wall-type tags drawn as loose lines (a diamond made of four separate strokes) are read.
  - Section, elevation and detail markers in a sheet's graphics legend are no longer read as wall types.
  - Walls are taken from the floor plan that carries the wall-type tags (an "information" floor plan) when the dimensioned plan doesn't.
- **Scale check:** dimensions belonging to a detail drawn at another scale on the same sheet no longer fail the plan's scale check. Before, a 1/8" plan with a 3/8" detail beside it could be skipped.
- **Exterior wall:** outlines inside a mezzanine plan, a detail or the title block drawn on the same sheet are no longer counted as extra buildings.
- **Legend symbols:**
  - A symbol shown in the legend as just a word or a few capital letters is counted by those letters on the plans.
  - Each symbol is counted on its own plan: fire alarm devices on the fire alarm plan, fixtures and sensors on the lighting plan, outlets on the power plan.
  - Wall-mounted dual-technology occupancy sensors are counted.
- **Schedules:**
  - Equipment listed in two schedules is counted once, with a note.
  - Equipment tagged only on a mezzanine plan is counted.
  - Mechanical schedules with two-row headers have their marks read.
  - A schedule beside dimensioned plans keeps its own column width.
  - More HVAC schedule titles are recognised (furnace, fan coil, unit heater, boiler, chiller, ductless / mini-split, kitchen and exhaust hood).
  - Tags are given to the drawing they sit in on a sheet with several drawings, not to the nearest title.

### AI Takeoff - other
- A mezzanine sheet that also carries another plan ("MEZZANINE AND ROOF PLAN") keeps its exterior wall; "LEVEL 2 MEZZANINE PLAN" is read as the mezzanine plan.

### Items 0.13.9 shipped but its notes didn't describe
- **Estimate Workbook:** AI Takeoff writes an Excel workbook (Summary, Base Bid, Units & Wastage) with every quantity by CSI division, CHECK lines marked, and the Division 01 lines at 1 LS - rates and markups left blank for the estimator.
- **Spec Book materials:** with the project manual open, pipe and duct lines say what the specs make them of (for example copper Type L) and which pipes and ducts are insulated and how thick, naming the section read. Nothing is guessed when the spec doesn't say.
- **Footing rebar:** wall footings named with their bars ("(3) #5 CONT") get the rebar weight as well as the concrete.
- **Limits of disturbance:** a reader for LOD lines and silt-fence markers is in the program; 0.13.9 uses it for silt fence only (the disturbed area is not taken off yet).
- **New dependency:** shapely (BSD licence), used for roof, wall-area and site areas.

### How the accuracy figure is measured
The AI Takeoff figures are scored against a human takeoff of one real job with a map from AI line names to the human takeoff's rows (tools/aiken_map.json). Lines that are new in a release need new map rules, so the map changes with the program. 0.13.9's figure - 355 of 728 items found, 153 groups within 2% - was scored with the map as of that release (map v5, 375 rules, sha256 44630e2a19d8). Scored on 0.13.8's frozen map (v3, 168 rules, sha256 b6c438d67120; kept as tools/aiken_map_0.13.8.json) the same 0.13.9 takeoff gives 212 items found and 101 groups within 2%: most of the difference is new kinds of lines (fittings, door finishes, envelope, ceilings, site) that the old map has no rows for. The scorecard now prints the map's version, rule count and fingerprint, and each release's notes give both figures.
