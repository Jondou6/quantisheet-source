# PDF Studio 0.12.22 (beta)

PDF Studio is a PDF program for construction:
- drawing sets, markups and scaled takeoff;
- estimating and bid tools;
- a starter-set generator.

This is a **beta**: you need a license key to run it.

## Downloads

| File | For |
|---|---|
| `PDFStudio-Public-Beta-Setup-0.12.22.exe` | One PC. Installs for the current user (no admin needed). |
| `PDFStudio-Public-Beta-Server-Setup-0.12.22.exe` | IT departments: Windows Server, Remote Desktop, Intune/SCCM/PDQ. Installs for all users (admin). Includes the Group Policy template and the optional collaboration relay service. |
| `SHA256SUMS.txt` | The SHA-256 of each installer |

The installers aren't code-signed yet, so Windows SmartScreen will warn about an unknown publisher. Before running one, check its hash:

```
Get-FileHash .\PDFStudio-Public-Beta-Setup-0.12.22.exe
```

The hash must match the one in `SHA256SUMS.txt`.

**Requirements:** Windows 10/11 64-bit, or Windows Server 2016 or later with Desktop Experience. IT deployment, silent install switches, Group Policy settings and the network list are in `IT_DEPLOYMENT.md`.

## New in 0.12.22

- **Narrow lots:** when the brief gives the lot and the house doesn't fit the setbacks, Generate Set reshapes it - deeper and narrower (or wider for a shallow lot) - as long as no room is lost and the self-check is no worse. Deep houses get rooms along a front-to-back hall and a front gable (ridge north-south).
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
- **Help › Support Bundle for IT** / `PDFStudio.exe diagnostics`. Builds a help-desk zip with no keys, passwords or email addresses.
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
