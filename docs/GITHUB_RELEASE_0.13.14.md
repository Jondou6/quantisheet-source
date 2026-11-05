# QuantiSheet 0.13.14 (beta)

QuantiSheet is a PDF program for construction:
- drawing sets, markups and scaled takeoff;
- estimating and bid tools;
- a starter-set generator.

This is a **beta**: you need a license key to run it.

## Downloads

| File | For |
|---|---|
| `QuantiSheet-Public-Beta-Setup-0.13.14.exe` | One PC. Installs for the current user (no admin needed). |
| `QuantiSheet-Public-Beta-Server-Setup-0.13.14.exe` | IT departments: Windows Server, Remote Desktop, Intune/SCCM/PDQ. Installs for all users (admin). Includes the Group Policy template and the optional collaboration relay service. |
| `QuantiSheet-Public-Beta-0.13.14.msi` | IT departments that deploy MSI packages (Intune line-of-business, SCCM, Group Policy). All users, admin. |
| `SHA256SUMS.txt` | The SHA-256 of each installer |

The installers aren't code-signed yet, so Windows SmartScreen will warn about an unknown publisher. Before running one, check its hash:

```
Get-FileHash .\QuantiSheet-Public-Beta-Setup-0.13.14.exe
```

The hash must match the one in `SHA256SUMS.txt`.

**Requirements:** Windows 10/11 64-bit, or Windows Server 2016 or later with Desktop Experience. IT deployment, silent install switches, Group Policy settings and the network list are in `IT_DEPLOYMENT.md`.

## New in 0.13.14

### Security
- **Back Office payroll and HR data is encrypted on disk**: employee contact details and pay rates, every payroll line and register amount, and the audit log's details. The audit log is now signed with a key kept outside the database. The database and its key file are limited to your Windows user, and you're warned when the company file is on a network drive.
- **Create PDF from Word, Excel or PowerPoint** opens the file with macros turned off.
- **Links in a PDF to other files** always ask first; links to network paths, web addresses or files that aren't PDFs are blocked.
- IT policy files are read only when an administrator owns them. Ghostscript, Tesseract and PowerShell are only ever run from their installed folders. XML and Excel files that try known file tricks are refused. Back Office restores need permission and keep a copy of what they replace.

### Takeoff and estimating
- **Price These** (Estimate menu and ribbon): every takeoff line with a quantity and no price, in one list, with suggestions from your own price books.
- Area and Length ask **"What are you measuring?"**; Fit Page keeps the whole sheet above the page bar.
- **Scale review**: set any page to a scale from the list. A page whose scale matches a different written scale is marked "check".
- **Award the estimate** into the job: the budget by cost code (it ties to the estimate to the cent) and a draft subcontract for each division.
- **Drawing log** (Sets panel): every sheet's current revision and the revisions it replaced, as a CSV.
- Counting legend symbols across a set is faster.

### Project Center
- **Sub pay apps**: subs bill their schedule-of-values progress; you approve or send it back; the approved amounts roll into your owner pay application by cost code and are marked Billed, so nothing is billed twice.
- **Retainage rules** from the owner contract (for example 10% dropping to 5% at 50% complete) are applied to each pay application.
- **Notice deadlines**: each delay shows when its notice is due, with a "Delay notices due" card.
- **Money history**: every change to budget, contract, commitments, change events, costs and pay apps is kept in a tamper-evident history (Project > History).
- **Back up and restore a job** with a checked manifest: a damaged backup is refused, never half-restored.
- **One billing ledger**: bring a PDF's Contract & Billing into the job once.
- **Roles**: Accountant (money records; may certify pay apps) and Superintendent (field records; no pay apps).
- **Project photos**: albums by date, area and tag, a pin on the drawing where you click, and a timeline. Location data in photos is never read or sent.
- **Allowances** editor (Project > Allowances), a name for each long-lead item, and the report number on every page of the owner report.
- Pay applications use our own wording ("Application for Payment").

### Back Office
- **Compliance watch**: subcontractor insurance and licenses expiring in the next 30 days.

### ClaimIT
- **Your own line-item library**: your codes and categories, CSV import and export, and "Add from my library" on the line items. No outside codes are included.

## Earlier (0.13.13)

### Master Schedule
- **Dropbox inbox:** the inbox can be a Dropbox folder (Settings > Dropbox…). Subs upload through a Dropbox link - a file request needs no Dropbox account - into their own folder, and QuantiSheet reads it with your Dropbox sign-in. The Dropbox desktop app isn't needed. Handled files move to that sub's Processed or Rejected folder in Dropbox (nothing is deleted), and the update sheets QuantiSheet makes are uploaded to each sub's Outbox folder.
- **Sub upload links:** paste each sub's Dropbox link once; it goes in that sub's reminder draft.
- **Owners by CSI code:** Assign subs now matches an activity's CSI code (its Cost code, or a section number at the start of its name, such as 033000) to the sub that holds that section. The list fills itself from Commitments and awarded Bid Packages; codes typed in Settings > CSI codes for each sub win. A section held by two subs is listed for you instead of guessed. Activities with no code fall back to the Responsible person's company. Nothing is assigned until you say yes.
- **The project manager approves:** on a shared project only the Project manager or Admin login can approve, decline or revert an update, and only the PM's QuantiSheet checks the inbox. Progress-only updates that move no finish later are still accepted on their own and can be reverted.
- **Due the 3rd Thursday** of the month by default (still changeable in Settings).
- **MS Project and P6 files** always wait for the project manager's review.
- Subs still can't change schedule logic, sub detail is still one roll-up line per sub, and typing an update for a sub is still there, with a note that the sub sending their own is better.
- The Excel update sheet was checked with real Microsoft Excel: opened, filled in, saved and read back unchanged.
- **Master Schedule button** on the ribbon's **Module** tab (before, it was only in the menu, which the ribbon hides).

### Window
- QuantiSheet, Project Center and the Master Schedule window now check that they really fill the screen when they open. Before, a window could show as maximized but be smaller than the screen.

### Editing PDF text
- In dark mode, editing a paragraph showed it in a black box with grey text that was hard to read. The edit box is white with the text's own colour again, as on the page. Some Project Center warning colours had the same fault and are fixed.

## Earlier (0.13.12)

### Master Schedule
- **Schedule printouts:** a sub's update can be a schedule printed to PDF (Primavera P6 or MS Project layouts). The activity table is read from the printout: IDs, names, durations, start and finish, and actual dates. % complete is worked out from the original and remaining durations. A PDF update always waits for review.
- **.mpp files** are rejected with a note telling the sub to save as XML in MS Project (File > Save As > XML) or print to PDF.
- **Before / after:** bars showing what an update moves, before you approve it.
- **Approve lines:** take only the activities you tick; the rest keep the master's values (recorded as your overrides).
- **To Delay Log:** an approved update that made work finish later becomes an Open Delay Log entry listing each activity and its added workdays.
- **P6 calendars:** a sub's P6 holidays are compared with the master's, as MS Project calendars already were (warned, never changed).
- **Help Center:** new tutorials for the Master Schedule and the Project Calendar; a Help button in the Master Schedule window.

### AI Takeoff
- A duct piece with no size tag near it no longer takes a size from a tag far away (another drawing on the sheet, an equipment cabinet).

## Earlier (0.13.11)
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
