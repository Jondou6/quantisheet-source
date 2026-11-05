# QuantiSheet 1.0.0 (beta)

QuantiSheet is a PDF program for construction:
- drawing sets, markups and scaled takeoff;
- estimating and bid tools;
- a starter-set generator.

This is a **beta**: you need a license key to run it.

## Downloads

| File | For |
|---|---|
| `QuantiSheet-Public-Beta-Setup-1.0.0.exe` | One PC. Installs for the current user (no admin needed). |
| `QuantiSheet-Public-Beta-Server-Setup-1.0.0.exe` | IT departments: Windows Server, Remote Desktop, Intune/SCCM/PDQ. Installs for all users (admin). Includes the Group Policy template and the optional collaboration relay service. |
| `QuantiSheet-Public-Beta-1.0.0.msi` | IT departments that deploy MSI packages (Intune line-of-business, SCCM, Group Policy). All users, admin. |
| `SHA256SUMS.txt` | The SHA-256 of each installer |

The installers aren't code-signed yet, so Windows SmartScreen will warn about an unknown publisher. Before running one, check its hash:

```
Get-FileHash .\QuantiSheet-Public-Beta-Setup-1.0.0.exe
```

The hash must match the one in `SHA256SUMS.txt`.

**Requirements:** Windows 10/11 64-bit, or Windows Server 2016 or later with Desktop Experience. IT deployment, silent install switches, Group Policy settings and the network list are in `IT_DEPLOYMENT.md`.

## New in 1.0.0

- **Version 1.0.0.** The first number no longer starts with 0, which the Microsoft Store requires.
- **One name everywhere.** Everything QuantiSheet saves, installs and registers uses the QuantiSheet name. Files saved by earlier versions still open; they switch to the new names the first time they're opened.
- **IT: new policy key.** The policy registry key, the Group Policy template's namespace and the "Open with" entries carry the QuantiSheet name. If you set QuantiSheet policies before, set them again under `Software\Policies\QuantiSheet` and load the new template (see `IT_DEPLOYMENT.md`).
- **Microsoft Store copy.** A Store version is on the way. It needs no license key, has no QuantiSheet printer (a Store app can't add a Windows printer), and shows no Beta wording.
- Help, menus and messages no longer compare QuantiSheet with other programs.
