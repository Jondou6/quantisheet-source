# QuantiSheet 1.0.3

QuantiSheet is a PDF program for construction:
- drawing sets, markups and scaled takeoff;
- estimating and bid tools;
- a starter-set generator.

This copy needs a license key to run. The Microsoft Store copy needs none.

## Downloads

| File | For |
|---|---|
| `QuantiSheet-Public-Beta-Setup-1.0.3.exe` | One PC. Installs for the current user (no admin needed). |
| `QuantiSheet-Public-Beta-Server-Setup-1.0.3.exe` | IT departments: Windows Server, Remote Desktop, Intune/SCCM/PDQ. Installs for all users (admin). Includes the Group Policy template and the optional collaboration relay service. |
| `QuantiSheet-Public-Beta-1.0.3.msi` | IT departments that deploy MSI packages (Intune line-of-business, SCCM, Group Policy). All users, admin. |
| `SHA256SUMS.txt` | The SHA-256 of each installer |

The installers aren't code-signed yet, so Windows SmartScreen will warn about an unknown publisher. Before running one, check its hash:

```
Get-FileHash .\QuantiSheet-Public-Beta-Setup-1.0.3.exe
```

The hash must match the one in `SHA256SUMS.txt`.

**Requirements:** Windows 10/11 64-bit, or Windows Server 2016 or later with Desktop Experience. IT deployment, silent install switches, Group Policy settings and the network list are in `IT_DEPLOYMENT.md`.

## New in 1.0.3

- **AI Takeoff rooms:** the floor beside a shower bench, a door swing or a grab bar is now counted - those lines used to be treated like a doorway, so rooms such as showers measured short. The floor under a built-in bench itself still isn't counted; those rooms are flagged for review.
- Everything new in 1.0.2 is included: review tools on the drawing (A / D to accept or deny, reshape by corners, select several), the Count Library, Count by Label with wildcards, AI Takeoff zones and learned item names, and update reminders.
