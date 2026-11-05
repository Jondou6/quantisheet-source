# QuantiSheet 1.0.2

QuantiSheet is a PDF program for construction:
- drawing sets, markups and scaled takeoff;
- estimating and bid tools;
- a starter-set generator.

This copy needs a license key to run. The Microsoft Store copy needs none.

## Downloads

| File | For |
|---|---|
| `QuantiSheet-Public-Beta-Setup-1.0.2.exe` | One PC. Installs for the current user (no admin needed). |
| `QuantiSheet-Public-Beta-Server-Setup-1.0.2.exe` | IT departments: Windows Server, Remote Desktop, Intune/SCCM/PDQ. Installs for all users (admin). Includes the Group Policy template and the optional collaboration relay service. |
| `QuantiSheet-Public-Beta-1.0.2.msi` | IT departments that deploy MSI packages (Intune line-of-business, SCCM, Group Policy). All users, admin. |
| `SHA256SUMS.txt` | The SHA-256 of each installer |

The installers aren't code-signed yet, so Windows SmartScreen will warn about an unknown publisher. Before running one, check its hash:

```
Get-FileHash .\QuantiSheet-Public-Beta-Setup-1.0.2.exe
```

The hash must match the one in `SHA256SUMS.txt`.

**Requirements:** Windows 10/11 64-bit, or Windows Server 2016 or later with Desktop Experience. IT deployment, silent install switches, Group Policy settings and the network list are in `IT_DEPLOYMENT.md`.

## New in 1.0.2

- **Team copy: update check.** Once a day (and Help > Check for Updates Now) the team copy looks for a newer team build and offers it; nothing installs until you click Install now. It sends no documents, names or IDs. Off with Help > Check for Updates Automatically, or IT's DisableUpdateCheck. The Microsoft Store copy never checks: the Store updates it.
- **AI Takeoff:** reads more door and window schedules, finds more rooms (including shower and toilet stalls), and gives a better gross floor area. AI items stay out of every total until you accept them in one Review Queue (least sure first, with Accept, Deny and Undo). Running it again never counts anything twice. AI marks show dashed with an "AI" badge until accepted, and a doubtful sheet scale is held for you to confirm.
- **Rooms don't overlap:** where two found rooms share floor, the shared part goes to one room, so no floor is counted twice. The bid check warns when AI items are still waiting for review.
- **Fixing takeoff:** reshape an outline by its corners (drag a corner, drag a side's dot to add one, Ctrl+click to remove one); select several markups with a box or Ctrl+click for a combined total, Move Selected to Item or Delete; an Origin column in the Markups List, including "AI, edited".
- **Finding missed counts:** right-click a count > Show Uncounted Copies outlines the copies with no count mark; Count the Uncounted Copies adds them. After Report Missed in the Review Queue, box one copy and the copies like it come in as counts in review.
- **Faster review:** select a dashed AI markup (or several) and press A to accept or D to deny. Count by Label lists every hit before counting, grouped by tag, with wildcards (P-# finds P-1 to P-12). A count library keeps the symbols you count on every job and tries them on the next plan set (found copies wait in review).
- **AI Takeoff zones and names:** draw Only Here or Leave Out boxes on a sheet (AI > AI Takeoff Zones), and AI Takeoff remembers the names you give its items. Fire extinguishers and other life-safety symbols are looked for on the life safety and floor plans.
- **ClaimIT 0.2.2:** a start page, a one-step new claim, rooms by size, odd-shaped rooms, line kits, edits that apply as you type, undo, autosave, a before-you-send checklist, a totals bar, a diary and payments, and room measurements and payments in the PDF, CSV and Excel exports.
