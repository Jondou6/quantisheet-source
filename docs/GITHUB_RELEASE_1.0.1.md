# QuantiSheet 1.0.1

QuantiSheet is a PDF program for construction:
- drawing sets, markups and scaled takeoff;
- estimating and bid tools;
- a starter-set generator.

This copy needs a license key to run. The Microsoft Store copy needs none.

## Downloads

| File | For |
|---|---|
| `QuantiSheet-Public-Beta-Setup-1.0.1.exe` | One PC. Installs for the current user (no admin needed). |
| `QuantiSheet-Public-Beta-Server-Setup-1.0.1.exe` | IT departments: Windows Server, Remote Desktop, Intune/SCCM/PDQ. Installs for all users (admin). Includes the Group Policy template and the optional collaboration relay service. |
| `QuantiSheet-Public-Beta-1.0.1.msi` | IT departments that deploy MSI packages (Intune line-of-business, SCCM, Group Policy). All users, admin. |
| `SHA256SUMS.txt` | The SHA-256 of each installer |

The installers aren't code-signed yet, so Windows SmartScreen will warn about an unknown publisher. Before running one, check its hash:

```
Get-FileHash .\QuantiSheet-Public-Beta-Setup-1.0.1.exe
```

The hash must match the one in `SHA256SUMS.txt`.

**Requirements:** Windows 10/11 64-bit, or Windows Server 2016 or later with Desktop Experience. IT deployment, silent install switches, Group Policy settings and the network list are in `IT_DEPLOYMENT.md`.

## New in 1.0.1

- **Start page text fits.** With larger Windows text, the cards and the title grow instead of cutting off the bottoms of letters; the tip under the recent files wraps.
- **Privacy page** names every outside service (Dropbox, site and address lookups, the Owner Report forecast, an AI server on another computer) and says how to delete your data.
- **Uninstall can remove your QuantiSheet data.** The uninstaller asks whether to delete QuantiSheet's own settings, recovery copies and price database. No is the default; drawings and job folders are never touched.
- **No Beta Agreement.** The agreement page, its Start menu shortcut and file are gone (an update removes the old ones).
- **Support contact:** the Terms and Privacy pages say where to ask (the Store page for the Microsoft Store copy).
- **Unpriced takeoff:** an estimate export with unpriced items points to Estimate > Price These.
- The uninstaller stops the print helper first, so no files are left behind.
