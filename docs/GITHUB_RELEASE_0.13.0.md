# QuantiSheet 0.13.0 (beta)

QuantiSheet (formerly PDF Studio) is a PDF program for construction:
- drawing sets, markups and scaled takeoff;
- estimating and bid tools;
- a starter-set generator.

This is a **beta**: you need a license key to run it.

## Downloads

| File | For |
|---|---|
| `QuantiSheet-Public-Beta-Setup-0.13.0.exe` | One PC. Installs for the current user (no admin needed). |
| `QuantiSheet-Public-Beta-Server-Setup-0.13.0.exe` | IT departments: Windows Server, Remote Desktop, Intune/SCCM/PDQ. Installs for all users (admin). Includes the Group Policy template and the optional collaboration relay service. |
| `QuantiSheet-Public-Beta-0.13.0.msi` | IT departments that deploy MSI packages (Intune line-of-business, SCCM, Group Policy). All users, admin. |
| `SHA256SUMS.txt` | The SHA-256 of each installer |

The installers aren't code-signed yet, so Windows SmartScreen will warn about an unknown publisher. Before running one, check its hash:

```
Get-FileHash .\QuantiSheet-Public-Beta-Setup-0.13.0.exe
```

The hash must match the one in `SHA256SUMS.txt`.

**Requirements:** Windows 10/11 64-bit, or Windows Server 2016 or later with Desktop Experience. IT deployment, silent install switches, Group Policy settings and the network list are in `IT_DEPLOYMENT.md`.

## New in 0.13.0

- **New name: PDF Studio is now QuantiSheet.** The installer upgrades an existing PDF Studio install in place and keeps its folder, settings, data, price database and cost books. The program file is now `QuantiSheet.exe` (it was `PDFStudio.exe`): the upgrade removes the old file and re-points the shortcuts, "Open with", the printer helper and the relay's task and firewall rule at the new one; a taskbar icon pinned before the upgrade must be pinned again, and IT rules that name the file (file detection, AppLocker, hand-made firewall rules) should be updated. The settings/data folders, registry and Group Policy keys, ProgIDs and AppIds/UpgradeCode are unchanged, so registry detection rules and policies keep working. The print-to-PDF printer is renamed "QuantiSheet" (the old "PDF Studio" printer is removed on install). The relay's scheduled task and firewall rule are renamed (the old ones are removed).
- **Generate Set:** on small restaurant and strip lots the building moves back (inside its rear setback) so the full parking field fits in front; the self-check reports any shortfall.
- **Build Schedule From Plans:** starter production rates reviewed against public production figures (sources in the rate table); crews by area band on floor-wide trades (up to 3); tilt-up panels; warehouse bay MEP at bay density.
- **Weekly Owner Report:** copied pages stay vector unless they use a non-embedded font; key-plan pin numbers drawn with the embedded font.

## Earlier (0.12.39)

- **0.12.38 review fixes:** Build Schedule From Plans keeps Generate Set quantities (15% area tolerance, both areas noted; set door counts), Fit to Contract cuts only the driving path and names a driving lead-time row, inspection rows for station/plant/HVAC/sitework jobs, N.I.C. electrical removed from combined row names, roof trusses for small/wood/residential jobs, failed baseline snapshots reported, warehouse bay trim off the office path (measured on a made-up Generate Set 38,000 SF warehouse with the default settings and no contract dates: calendar days from NTP to the Substantial Completion finish went 317 -> 287; the NTP date of that run was not recorded, and a set with its own spec durations or calendar gives different numbers. Reproducible figure for this version: a Generate Set 38,000 SF warehouse, default settings, NTP Monday 2026-11-02, the default project calendar, counting calendar days from the NTP date to the Substantial Completion finish = 219 days; the test tests/test_productivity.py::test_review39_job_lengths_land_in_the_expected_ranges builds exactly this). Generate Set draws open paths open (drive-thru lane edges, door swings, section stair/roof lines, PEMB roof), self-checks lines across parking, draws only the stalls that fit with the shortfall reported. Weather place names without a comma, MS Project baselines and notes round-trip, licensed cost-data names refused by the ship check.
- **Tools:** the PC test runner writes output to a file and kills the process tree on timeout; the command sweep runs in parts and skips commands that start other programs.

## Earlier (0.12.38)

- **Fixes from an independent review:** Weekly Owner Report keeps recorded rain days across weeks, background jobs (weather, AI draft, new report, export) no longer overwrite edits or cross results and save on the GUI thread, US state names resolve correctly for weather. Project Center no longer slows down with saved schedule updates. Fit to Contract keeps notes and doesn't compress procurement lead times. MS Project XML element order. Ship check refuses private folders and review documents anywhere. Embedded files with /UF-only entries or /Kids name trees are edited safely. Date calculator range errors are shown. Generate Set parking spreads across the lot width on tight lots.

## Earlier (0.12.37)

- **Build Schedule From Plans:** submit / review / fabricate-and-deliver chains for each long-lead item a set counts (storefront, overhead doors, trusses or joists, roofing, doors & hardware) feeding its install row; every activity carries a SOURCE; no lags or leads (lags replaced by short real lead-in activities); finish-to-start share at or above 90% and no missing logic for every job type.
- **Generate Set:** elevation grade lines stay inside the drawing area for every building type.
- **IT:** commercial weather hosts in the firewall list.

## Earlier (0.12.36)

- **Stress-test fixes:** Build Schedule From Plans keeps MEP work when only MEP design is by others, sizes interiors from finished areas / Generate Set quantities, ignores abbreviation legends, adds permits and inspections, removes redundant links, reads Final Completion, and exports outline levels and holiday calendars to MS Project. Claim package uses one completion date (contract or baseline) with new Project Settings fields, an anchored update chain, refuses negative impacts, and tighter DCMA checks. Weekly Owner Report keeps typed rainfall, single-source weather totals, embedded Liberation Sans font, accurate size estimate, optional commercial weather key. Generate Set: parking out of front setbacks, walks off stalls, IPC 2902.2 Exc. 3 for strip restrooms, schedules continue across sheets, west drive-thru, area lots. Damaged scale attachments reset; aerial Cancel joins its thread; build refuses research files.
- **Findability:** Owner Report button on the Project tab; Claims & Recovery menu in the Scheduler window.

## Earlier (0.12.35)

- **Date and Time Calculators** (Estimate > Calculators, Project menu): between dates (calendar days, weeks, Y/M/D, workdays, optional end-date inclusion), date + time duration, add / subtract (years, months, weeks, days, workdays, hours, minutes), weekday, ISO and US week numbers. Workdays skip weekends, observed US federal holidays (optional) and the open project's schedule holidays.
- **Weekly Owner Report:** key-plan sheet picker, photo pins (rotation-aware), work-area polygons with print area, and before/after photo pairing.
- **Generate Set site plans (restaurant, strip):** collision-free labels, a 12 ft drive-thru lane that wraps the building past the window, street and service walks; quantities now take the drawn lane and walks.

## Earlier (0.12.34)

- **Claim-ready schedule:** hash-chained schedule update snapshots (Save Schedule Update; automatic on Set Baseline and recovery apply) with tamper detection; a Delay Log record type with time impact analysis on the prior update, concurrency, late-notice flags and a windows analysis; a DCMA 14-point Schedule Quality Check PDF; a Schedule Claim Package PDF combining them.

## Earlier (0.12.33)

- **Weekly Owner Report** (Project > Weekly Owner Report): page 1, 4-up photo pages, RFI log, Submittal Detail Report, rainfall log and forecast as one flattened PDF, filled from the job (Daily Logs, Project Center, weather). Optional local-AI progress draft that only rewrites logged facts; photo fit and email-size compression (~3 MB for 32 photos); forecast screenshot paste; editable rain days; weekly carry-over; optional sections all off by default.
- **Quantity-based durations** in Build Schedule From Plans: quantity / (rate x crews) from an editable production-rate table, takeoff quantities first; a basis on every activity. 40k/5k SF duration ratio 2.25 (was 4.38).
- **Generate Set:** restaurant (A-2, optional drive-thru) and strip retail center (M, tenant bays) types.
- **0.12.32 review fixes:** recovery AI checks, revert of an applied plan, per-round AI error handling, criticality to the target milestone; ambiguous project types ask; existing-conditions boilerplate; OFCI; multi-line exclusions; look-ahead past-planned-finish flags; aerial Cancel socket shutdown; Excel CSVs in four more importers; PyMuPDF pinned below 2.0.

## Earlier (0.12.32)

- **Recovery Schedule** (Gantt Chart > More): target vs forecast and the cause of the slip; crash / fast-track / resequence steps on the critical path with how, cost and sub agreement, recomputed on a what-if copy; Suggest Steps; an AI Helper (local model) whose proposals are checked against the schedule and refined over up to 3 rounds; Apply to Schedule (baseline kept, notes added); an owner's PDF with the revised Gantt.
- **2-week look-ahead for the weekly meeting:** Gantt Chart > Look-Ahead (1-4 weeks, 2 by default) prints each activity working Monday-Friday with a day-by-day grid, responsible company, dates, % complete, float, and Notes / meeting-notes lines to write on; activities behind baseline or past their finish come first in red. PDF (Letter landscape) or Excel.
- **Drag and drop:** drop PDFs (up to 20) onto the window to open them.
- **AI: Build Schedule From Plans knows the kind of job:** it reads the sheet list, spec sections and cover/general notes and picks new building, renovation, standby generator/ATS, electrical service, HVAC replacement, reroof, sitework only, pump/lift station or treatment-plant upgrade. It shows why it picked that type, lets you change it, and asks when it can't tell instead of assuming a building. Tagged equipment (GEN-1, ATS-1, RTU-3...) gets its own procurement, setting, startup and testing activities; long-lead weeks can be typed from the quote, and starting values are labelled "assumed".
- **Repair jobs scheduled from their own list:** a DESCRIPTION OF WORK / SCOPE OF WORK list on the cover becomes the activities (one per item, sequenced by trade and by "following completion of ..."), instead of generic fit-out trades. Notes saying work is NOT INCLUDED IN THIS CONTRACT keep that equipment out (a coordination activity instead); "... SCOPE ONLY" notes become activities. Scanned sheets with no text are listed so their work isn't silently missed.
- **Fixes:** Excel (Windows-1252) CSVs import for wages, price books and assemblies; 502/503 answers from USGS or the Census geocoder are reported as the service's trouble (one automatic retry); after a USGS timeout, OK asks before waiting again; an AI spec review keeps the parts that worked when one part fails; the log and crash file record the version and time.

## Earlier (0.12.31)

- **Takeoff items:** the Takeoff panel's **+ New Item** makes a named Count, Length or Area item with its own color. Click an item and click on the drawing - no questions - and its total updates as you go. Right-click to rename, recolor, duplicate or delete. Items are saved in the PDF.
- **Exports don't freeze the window:** Excel, Word, PowerPoint, web page, images and DXF export on a worker thread with a progress box.
- **Generate Set's "N sheets - k warnings" message** stays readable for 15 seconds.
- **Theme switch** shows a wait cursor.

## Earlier (0.12.30)

- **Generate Set: warehouse / industrial** (S-1 / F-1, 3,000-200,000 SF): office front, warehouse bay with a column grid and speed bay, dock and drive-in doors, tilt-up or metal building, truck court on the site plan, an enlarged office sheet and a dock-high section. Every default is labelled "assumed".
- **G-003 Code Summary** in office, retail and warehouse sets: occupant load, exits, approximate travel, plumbing fixtures - all from the program's IBC/IPC tables; anything outside them is marked UNVERIFIED.
- **Porch roof** on one-story houses now starts under the house eave (2:12, 6'-8" headroom; a note when it has to be flatter).
- **Aerial photo page:** OK reuses the download already running, the progress box shows at once, a clear message after 2 1/2 minutes instead of hanging, Cancel stops at once, and the page goes into the set where you clicked OK.
- **ClaimIT** starts from its installed program (the 0.12.29 ClaimIT setup failed to start).

## Earlier (0.12.29)

- **Takeoff markups:** counts are a see-through colored dot with a black number (yellow counts are readable now); measured lines are thicker and see-through; areas are filled see-through in their color.
- **Takeoff-style legend** (the new default): type icon, name, quantity in blue with 1 decimal and capital units (`408.3 FT`, `542.2 SQ FT`, counts `9.0`) and a color swatch; no wrapped or overlapping names. Markup > Legend Style > Classic keeps the old legend; Refresh Legends keeps each legend's style.
- **Roof Plan Takeoff** (Takeoff > Show Roof Plan Tools, then Takeoff > Roof Plan Takeoff): tag the facets, linework and counts you drew on a scaled roof plan with a roof type and pitch. True sloped quantities flow into the Quantities panel, estimate, legend and PDF Studio Claims; the summary has squares with and without waste, wall flashing, membrane, curb perimeter and counts, and exports to Excel/CSV. No default pitch (unpitched facets are flagged), and it is disabled on aerial photo pages: a plan takeoff only.
- **Sage 300 CRE Job Cost export** (Takeoff > Export to Sage 300 Job Cost): coded assembly lines as a budget import CSV; lines without a cost code or category are listed, not exported.
- **ClaimIT** (the insurance claim estimate program, formerly PDF Studio Claims): Module > ClaimIT now opens without a drawing; with one open it starts with that drawing's takeoff.
- **Concrete and brick / block calculators** (Estimate > Calculators): concrete yards, order quantity, trucks and bags for slabs, footings, walls, columns, piers and steps; brick and CMU counts, mortar and sand for a wall less openings; sizes can come from a takeoff group.
- **CivilBid:** the HeavyBid-coded assemblies and export are now named CivilBid.
- **Submittal look-ahead:** Project Center > Submittals > Look-Ahead lists submittals due in the next 2-4 weeks and overdue ones, as PDF or Excel.
- **Fixes:** the server setup and MSI have their own "Open with" ProgID (`PDFStudio.Server.pdf`), so uninstalling one edition no longer removes the other's entries; the public build is now scanned inside its files (and zip members) for private keys, sealed data and e-mail addresses before it's packaged.

## Earlier (0.12.28)

- **Insurance claim estimates (PDF Studio Claims):** a separate program for residential and commercial insurance claim estimates, started from Module > Insurance Claim Estimate with the drawing's takeoff. It exports to CSV, Excel and PDF, and keeps its claims in its own folder. It installs on its own (PDF Studio Claims setup); the menu item appears when it's installed.
- **Submittals moved to the Project tab** (Project > Submittal Log), where they belong.
- **Fixes:** the MSI package installs again (0.12.24-0.12.27 MSIs had two permission tables, which Windows refuses); a wide ribbon tab now scrolls instead of making the window wider.

## Earlier (0.12.27)

- **Module tab:** add-on references in one place on the ribbon.
  - **ADA:** the official 2010 ADA Standards PDF (figures and all, search with Ctrl+F), the section-by-section Look Up with "Show in the PDF", and the ADA Checker - all without a drawing open.
  - **Energy Code:** climate zone for every US county (2021 IECC, from the Department of Energy's county guide), a **Code Library** that indexes code books you own (IECC, IBC, IRC, state codes) on your PC so you can look requirements up by section or words, and links to read the IECC free at ICC and check state adoption.
- **Submittals for the architect and engineers:** Project tab > Submittals (Project Center's submittal log): **From Spec Book** reads the project manual's SUBMITTALS articles and builds the log by CSI section; **Make Submittal Package (PDF)** makes one PDF to send - a cover sheet with the spec section and CSI division, the contractor's review statement and a review stamp for each reviewer, then the attachments. Send for Review emails it.
- **Fixes:** ADA items no longer greyed out with no drawing open; tool-rail labels no longer cut off with large Windows text; tighter panel tabs.

## Earlier (0.12.26)

- **ADA Checker reads the drawings:** Fill From Drawings takes the counts from your takeoff by group name (parking, accessible and van parking, toilet fixtures by room, seats, entrances, fountains, guest rooms, dwelling units).
- **Measured sizes checked:** about 30 kinds of measurement (door clear width, accessible route, access aisle, toilet stall, grab bar height, counter height, turning space, ramp width...) against the Standards' minimum or maximum, with Mark Up Short Items to cloud the ones that fall short.
- **The PDF Studio printer, reworked:** its helper now runs as you, started when you sign in, instead of as SYSTEM from a start-up task. Microsoft Defender's automatic rules flagged the 0.12.24-0.12.25 helper as malware (a false positive on an unsigned build); this version removes the old task and folder. The server setup and the MSI no longer add the printer unless asked (`/TASKS=...,printer`, `PRINTER=1`).
- **Apartments:** dwelling units with mobility (5%) and communication (2%) features, and resident parking (208.2.3).

## Earlier (0.12.25)

- **ADA module:** the full 2010 ADA Standards for Accessible Design (US Department of Justice) inside the program, searchable by section number or words, with the advisories and links between sections (Project > ADA Standards).
- **ADA Checker for commercial projects:** type the counts (parking, entrances, stories, toilet rooms, seats, guest rooms...) and get what the Standards require, what you have, and the section for each line (Project > ADA Checker). The tables are checked against the Standards' own text by the test suite.
- **Generate Set:** office and retail sets get an Accessibility sheet (A-801), and their plans now use 3'-0" interior doors, 5 ft halls and restrooms with a 60 in. turning circle.

## Earlier (0.12.24)

- **The "PDF Studio" printer:** print from any program and the pages open in PDF Studio as a new PDF (Help > Add the PDF Studio Printer, or added by the server setup and the MSI). Uses Windows' own Microsoft Print to PDF driver.
- **One window:** opening a PDF while PDF Studio is running opens it in that window.
- **MSI package for IT** (`QuantiSheet-Public-Beta-0.12.24.msi`), same settings as the server setup, plus `PRINTER=0`.
- **Crash reports kept locally** and included in the support bundle, which now also removes keys, tokens, the Windows user name and server paths.
- **Fixes from an outside code review:** garage wall quantities, two-story room fitting, a garage door into the stair side, porch wording and depth, signed tester builds, a crash on foreign markups, log-folder fallback, per-user detection, and drawing fixes.

## Earlier (0.12.23)

- **Two-story houses on narrow lots:** when a floor is too narrow for rooms on both sides of a center stair hall, Generate Set draws a side-hall row house instead: the stair hall along one wall and the rooms in one wide wing. A 2,400 SF two-story house now fits a 40 ft lot.

## Earlier (0.12.22)

- **Narrow lots:** when the brief gives the lot and the house doesn't fit the setbacks, Generate Set reshapes it - deeper and narrower (or wider for a shallow lot) - as long as no room is lost and the self-check is no worse. Deep houses get rooms along a front-to-back hall, a back door at the end of the hall (for a deck) and a front gable (ridge north-south; east-west when there is a garage).
- **Garages** now go on a side that leaves every room a window when either side can.
- **Fixes from an independent review of 0.12.21:** bad prices (inf, nan, huge) no longer freeze the Quantities panel; the set's quantity lines follow the A-701 sheet when pages move; no negative front walk; the IT detection script works from 32-bit PowerShell; the winget manifests include each setup's ProductCode.

## Earlier (0.12.21)

- **Price the set's quantities:** a generated set carries its quantities inside the PDF. Open it and the Quantities panel lists every row as a *Set* line, ready for a unit cost, waste and multiplier; the totals export to CSV with the rest of the estimate.
- **Driveway and front walk** are now in the quantity summary.
- **IT:** `Detect-PDFStudio.ps1`, a read-only detection script for Intune, ConfigMgr and PDQ (checks both setups against a minimum version). Installed with the server setup under `C:\Program Files\PDF Studio\docs`.
- **IT:** `tools/make_winget.py` writes winget manifests for the release (private winget sources or `winget install --manifest`).

## Earlier (0.12.20)

- **Quantity summary** in Generate Set: an A-701 sheet and a `.quantities.csv` (slab, footing, walls, drywall, openings, finishes, roof, garage, porch and deck), measured from the drawings.
- **Front porch and rear deck** in Generate Set.
- **Security fixes from an independent review:**
  - the server install locks `C:\ProgramData\PDF Studio` to administrators and closes the relay's data folder to users;
  - sign-in and agreement overrides need real Group Policy;
  - the public build fails safe (always needs a key);
  - an IT-configured relay is trusted.
- **Brief-reading and garage fixes** from the same review.

## Earlier (0.12.19)

- **Attached garages** (1-3 cars) in Generate Set:
  - placed on the side with the best room to enter;
  - fire-rated house door and overhead doors;
  - on every sheet, the schedules and the DXF.
- **Two-story sections** are cut through the stair.

## Earlier (0.12.18)

- **Two-story houses** in Generate Set:
  - a center stair hall with a code-style straight stair (16R x 7 1/2", 15T x 10");
  - living rooms downstairs, bedrooms upstairs with an en-suite primary bath;
  - ten sheets, and both floors on the elevations, section, schedules and DXF;
  - a self-check for each floor.

## Also in this release (from 0.12.17)

- **Generate Set** now makes nine sheets, adding:
  - **AS-101 Site Plan:** lot, setbacks, buildable area, building placement and site data. Lot and setbacks are read from the brief; anything missing is labelled *assumed - verify with zoning*.
  - **A-102 Roof Plan:** gable or low-slope with drains.
  - The set's self-check reports whether the building fits the setbacks. The DXF gets the property line.
- **Server installer** for IT:
  - all-users install;
  - silent install with policy switches;
  - the collaboration relay as a low-rights background task with its own token, an optional TLS certificate and a firewall rule.
- **Group Policy** (ADMX/ADML) and `%ProgramData%\PDF Studio\policy.json`:
  - license key;
  - agreement and sign-in for managed PCs;
  - shared price database, relay address and token, AI server, log folder;
  - offline mode and per-feature internet switches.
- **Help › Support Bundle for IT** / `QuantiSheet.exe diagnostics`. Builds a help-desk zip with no keys, passwords or email addresses.
- **Command line:**
  - `sanitize` (with a proof report and exit code);
  - `genset`;
  - `policy`;
  - `diagnostics`;
  - `relay --token-file --data-dir --cert --key --log`.
- **Fix:** the Remove Hidden Information proof now really checks XML metadata.

## Known limits

- Generate Set draws rectangular one-story buildings (400–8,000 SF) and two-story houses (1,200–8,000 SF) and is a starting point **for review, not for sealing**.
- On Windows Server Core (no desktop), only the command line and relay are expected to run, and this hasn't been tested yet.
- Per-user memory on Remote Desktop servers hasn't been measured. Size the server from a pilot group.
