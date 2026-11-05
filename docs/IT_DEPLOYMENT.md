# QuantiSheet – IT deployment guide

This guide covers QuantiSheet, from 0.12.24 on. It is for the people who install and look after QuantiSheet across a company:
- single PCs;
- Remote Desktop / Windows Server;
- deployment tools (Intune, SCCM/ConfigMgr, PDQ Deploy).

## Names and places

| What | Where |
|---|---|
| Program | `QuantiSheet.exe` in `C:\Program Files\QuantiSheet` (all users) or `%LOCALAPPDATA%\Programs\QuantiSheet` (one user) |
| Each user's settings, logs | `%USERPROFILE%\.quantisheet` (log: `quantisheet.log`) - with roaming profiles or FSLogix, include it |
| Machine data (policy.json, relay, printer spool) | `C:\ProgramData\QuantiSheet` |
| Printer helper log, Code Library | `%LOCALAPPDATA%\QuantiSheet` |
| Printed PDFs | `Documents\QuantiSheet\Printed` |
| Policy registry key | `HKLM` / `HKCU\Software\Policies\QuantiSheet` |
| Group Policy template | `QuantiSheet.admx` / `QuantiSheet.adml`, namespace `QuantiSheet.Policies.QuantiSheet` |
| "Open with" ProgIDs | `QuantiSheet.pdf` (standalone setup), `QuantiSheet.Server.pdf` (server setup, MSI) |
| Printer sign-in value | `QuantiSheet Printer` under `…\CurrentVersion\Run` |
| Relay task and firewall rule | `QuantiSheet Relay` |
| Setup and MSI identity | AppIds `{375F90B3-…}` and `{6A0E2C4B-…}`, the MSI UpgradeCode |
| ClaimIT | `ClaimIT.exe` in a `ClaimIT` folder; data in `%APPDATA%\ClaimIT`, `Documents\ClaimIT` |

**From 1.0.0 the policy registry key, the Group Policy template's namespace and the "Open with" ProgIDs carry the QuantiSheet name.** If you set QuantiSheet policies before, set them again under `Software\Policies\QuantiSheet` (or load the new template in the Central Store - replace the old file, don't add beside it) and move a policy.json to `C:\ProgramData\QuantiSheet`.

## Which installer?

| File | For | Installs |
|---|---|---|
| `QuantiSheet-Beta-Setup-<ver>.exe` | One person's PC | For the current user (no admin needed), or for all users if they choose |
| `QuantiSheet-Beta-Server-Setup-<ver>.exe` | IT: Windows Server, Remote Desktop, mass deployment | For **all users** in `C:\Program Files\QuantiSheet` (admin) |
| `QuantiSheet-Beta-<ver>.msi` | IT: Intune line-of-business app, SCCM, GPO software installation | The same as the server setup, as an MSI |

Both installers contain the same program. The server setup adds:
- the Group Policy template;
- the optional collaboration relay service;
- command-line options that write policy settings.

Builds published outside the company (GitHub) are named `QuantiSheet-Public-Beta-…`. They always need a license key. They don't contain the in-house contact directory.

## Requirements

- **Windows:** Windows 10 or 11 (64-bit), or Windows Server 2016 (build 14393) and later, including 2019, 2022 and 2025.
- **Desktop Experience** is needed for the desktop program. On **Server Core** (no desktop), only the command-line tools and the collaboration relay run. That combination hasn't yet been tested on Server Core.
- **Disk:** about 1 GB for the program. The optional local AI needs about 2 GB more for its model.
- **Bundled:** Python, Qt, MuPDF and the drawing kernel are all inside the program. Nothing else needs installing.
- **Optional extras:**
  - Tesseract OCR, to make scans searchable.
  - Ollama, for the local AI.
  - Each one is a separate download, offered by the standalone setup. On a server, install them yourself or point every PC at one shared AI server (see `AIHost`).

## Silent install and uninstall

Server setup, all users, no questions:

```
QuantiSheet-Beta-Server-Setup-0.12.28.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="C:\Windows\Temp\quantisheet-setup.log"
```

Optional switches. Each one writes the matching policy value to `HKLM\Software\Policies\QuantiSheet`:

| Switch | Policy value |
|---|---|
| `/LICENSEKEY=<key>` | `LicenseKey` |
| `/PRICEDB=\\server\share\QuantiSheet\prices.db` | `PriceDatabasePath` |
| `/RELAYURL=ws://quantisheet-relay:8765` | `RelayURL` |
| `/AIHOST=http://ai-server:11434` | `AIHost` |
| `/LOGDIR=D:\Logs\QuantiSheet` | `LogDirectory` |
| `/ACCEPTAGREEMENT=1` | `AcceptAgreement` |
| `/SKIPSIGNIN=1` | `SkipEmailSignIn` |
| `/OFFLINE=1` | `OfflineMode` |
| `/NOAI=1` | `DisableAI` |

Tasks: `/TASKS="openwith,gpo"` is the default. Add `printer` for the "QuantiSheet" printer (below; off by default since 0.12.26). Add `relay` to run the collaboration relay on this machine. Add `desktopicon` for an all-users desktop shortcut.

QuantiSheet 1.0.0 and later have no agreement page; `/ACCEPTAGREEMENT=1` is still accepted and does nothing.

Uninstall:

```
"C:\Program Files\QuantiSheet\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

(The `UninstallString` under the detection key below always has the right path.)

Uninstalling removes the program, the relay task, the firewall rule and the policy values setup wrote. Each user's own files stay, in `%USERPROFILE%\.quantisheet` and in drawings.

**Standalone setup, silent, for the current user:**

```
QuantiSheet-Beta-Setup-0.12.28.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

### Detection rule (Intune / SCCM)

| Setup | Registry key | Value |
|---|---|---|
| Server | `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{6A0E2C4B-9F31-4D2B-8C55-3B1D2E7F9A40}_is1` | `DisplayVersion` = `0.12.28` |
| Standalone | `HKCU` (or `HKLM` for all users) `\…\Uninstall\{375F90B3-3B41-4FE9-B790-B29C6D30C75E}_is1` | `DisplayVersion` = `0.12.28 Beta` |

The file `QuantiSheet.exe` (its file version) in the install folder also works as a detection rule: `C:\Program Files\QuantiSheet\QuantiSheet.exe`. The registry rule above works for every version.

**Detection script:** `Detect-QuantiSheet.ps1` (in the install folder's `docs`, and in the source under `installer\it`) checks both setups against a minimum version and follows the Intune rule (writes a line and exits 0 when found). Set `$MinimumVersion` at the top before you upload it, or pass `-MinimumVersion 0.12.28 -Edition Server`. It only reads the registry. Intune runs detection as SYSTEM, so for a per-user standalone install use the server setup instead, or install the standalone for all users.

**Intune:** wrap the setup with the Win32 Content Prep Tool (`IntuneWinAppUtil.exe`), use the commands above, and set the return code 0 = success.

**winget:** `python tools/make_winget.py --repo OWNER/REPO` writes winget manifests for the public setups (per-user standalone and all-users server), with the hashes from `SHA256SUMS.txt` and the GitHub release URLs. Use them in a private winget source, or `winget install --manifest <folder>`.

## The "QuantiSheet" printer

Print from any program to the printer **QuantiSheet** and the pages open in QuantiSheet as a new PDF, the way "Adobe PDF" works. A copy is kept in each person's `Documents\QuantiSheet\Printed`.

- **Added by** the server setup (task `printer`, off by default), the MSI (`PRINTER=1`; off by default), or by hand: `QuantiSheet.exe printer --install --all-users` as administrator. Standalone users can use Help > Add the QuantiSheet Printer (Windows asks for an administrator).
- **Removed by** uninstalling, or `QuantiSheet.exe printer --remove`. `QuantiSheet.exe printer --status` shows what is there.
- **How it works:** the printer uses Windows' own *Microsoft Print To PDF* driver (no third-party driver), with a file port `C:\ProgramData\QuantiSheet\print\spool\job.pdf`. Windows writes each job there as the person printing; a small helper (`QuantiSheet.exe print-helper`) runs **as each signed-in person**, started at sign-in by the value *QuantiSheet Printer* under `HKLM` (all users, `--all-users`) or `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (one person, `printer --user-on`), and by QuantiSheet when it opens. It only touches that person's own jobs: it checks the file's owner, saves it into their Documents (redirected or network Documents folders work) and opens it in QuantiSheet. A person's jobs queue one at a time. Nothing runs as SYSTEM.
- **Why it changed (0.12.26):** 0.12.24-0.12.25 ran the helper as SYSTEM from a scheduled task and started QuantiSheet in the user's session from there. Microsoft Defender's machine-learning rules flagged that as malware (`Trojan:Win32/Bearfoos.A!ml`) on an unsigned build. On a Remote Desktop server, two people printing at the very same moment can make the second job fail (the port is one file); print again.
- **Security:** users may only create files in the spool folder, never read or change another person's job. The helper has only the rights of the person it runs for.
- **Needs:** the Windows feature *Microsoft Print to PDF* (on by default in Windows 10/11; on Server, Desktop Experience). Windows protected print mode allows it - the driver is Windows' own.
- **Log:** `%LOCALAPPDATA%\QuantiSheet\print-helper.log` for each person. A job printed while that person's helper isn't running waits in the spool folder and is collected the next time it starts.

## Group Policy

To add the template:
1. Copy `QuantiSheet.admx` to `C:\Windows\PolicyDefinitions`, or to the domain's Central Store (`\\<domain>\SYSVOL\<domain>\Policies\PolicyDefinitions`).
2. Copy `en-US\QuantiSheet.adml` to its `en-US` sub-folder.

Both files are in the install folder's `policy\` after a server install. The server setup's `gpo` task copies them to the local PolicyDefinitions for you.

The settings appear under **Computer Configuration** (and User Configuration) **> Administrative Templates > QuantiSheet**.

Where QuantiSheet reads settings from (first match wins):
1. `HKLM\Software\Policies\QuantiSheet` (Group Policy, computer)
2. `HKCU\Software\Policies\QuantiSheet` (Group Policy, user)
3. `%ProgramData%\QuantiSheet\policy.json`, for PCs without a domain. An administrator writes this file. For example: `{"PriceDatabasePath": "\\\\nas\\prices\\prices.db", "OfflineMode": true}`
The policy.json is read only when it is owned by Administrators, SYSTEM or TrustedInstaller (as a file an administrator saves there is), because any user can create a folder in ProgramData; otherwise it is ignored and the log says why.

Users can't change these inside the program. `LicenseKey`, `AcceptAgreement` and `SkipEmailSignIn` are taken **only from Group Policy** (the registry), never from policy.json. On a PC where IT hasn't created the folder, a user could create that file themselves. The server setup locks `C:\ProgramData\QuantiSheet` so only administrators can change it. QuantiSheet finds ProgramData through Windows itself, not through environment variables.

| Setting | Type | What it does |
|---|---|---|
| `LicenseKey` | text | Beta license key for every user of the PC. A valid key a user entered still wins. |
| `AcceptAgreement` | on/off | No longer used: 1.0.0 and later have no agreement page. Kept so an existing setting does no harm. |
| `SkipEmailSignIn` | on/off | No work-email sign-in for users of company-managed PCs. |
| `PriceDatabasePath` | text | The shared price database, e.g. `\\server\share\QuantiSheet\prices.db`. Users can't move or disconnect it. Everyone needs read/write on the folder. |
| `RelayURL` | text | The company's collaboration relay, e.g. `ws://quantisheet-relay:8765`, or `wss://…` with a certificate. |
| `RelayToken` | text | The relay's access token (on the relay server: `C:\ProgramData\QuantiSheet\relay\relay-token.txt`). |
| `AIHost` | text | The Ollama server for the AI features (default `http://localhost:11434`). |
| `LogDirectory` | text | Logs go here, in a sub-folder per Windows user, instead of each profile. |
| `OfflineMode` | on/off | No internet use at all (everything in the next table). |
| `DisableAerial` | on/off | No aerial photos, address lookup or site layers. |
| `DisableWeather` | on/off | No weather for daily logs. |
| `DisableRateLookup` | on/off | No labor-rate downloads. |
| `DisableDocuSign` | on/off | No DocuSign requests (QuantiSheet's own signing still works). |
| `DisableDropbox` | on/off | No Dropbox open and save (File > Open from Dropbox, Save to Dropbox). |
| `DropboxAppKey` | text | The App key of the company's Dropbox app, so users only sign in (see "Dropbox" below). Not a secret; the App secret is never needed. |
| `DisableAI` | on/off | Local AI features off. |
| `DisableUpdateCheck` | on/off | No daily update check: the team copy's check for a newer version, and the Microsoft Store copy's reminder when the Store has an update waiting (the Store does the install). |
| `DisablePackageStatus` | on/off | No live package status (Package Tracker > Check Status). |

### Which settings work in which copy

Every setting is read from the same registry keys, so Group Policy works the same for the setup copy and the Microsoft Store copy (packaged apps read `HKLM\SOFTWARE\Policies` and `HKCU\SOFTWARE\Policies` directly). The differences are in what each copy has:

| Setting | Setup copy (team / tester) | Microsoft Store copy |
|---|---|---|
| `LicenseKey`, `SkipEmailSignIn`, `PriceDatabasePath`, `RelayURL`, `RelayToken`, `DisableAI`, `AIHost`, `OfflineMode`, `DisableAerial`, `DisableWeather`, `DisableRateLookup`, `DisableDocuSign`, `DisableDropbox`, `DropboxAppKey`, `DisablePackageStatus`, `LogDirectory` | Yes | Yes |
| `DisableUpdateCheck` | Turns off the signed daily check | Turns off the Store-update reminder |
| Right-click actions in File Explorer | Setup option "Add QuantiSheet actions to the right-click menu" | PDFs only: Open in QuantiSheet, Reduce size. Convert to PDF and Combine PDFs (folders) need the setup copy |
| "QuantiSheet" printer | Setup option | Switch on "QuantiSheet Printer" in Settings > Apps > Startup |

To check what a PC is using:
- run `"C:\Program Files\QuantiSheet\QuantiSheet.exe" policy`, or
- use **Help > Support Bundle for IT**.

## Network: what QuantiSheet connects to

Opening, marking up, measuring, estimating and printing drawings never use the internet. These features do, only when someone uses them. All connections are HTTPS on port 443 unless noted.

| Feature | Hosts | Turn off with |
|---|---|---|
| Aerial photos, address lookup, site layers | `imagery.nationalmap.gov`, `basemap.nationalmap.gov`, `carto.nationalmap.gov`, `geocoding.geo.census.gov`, `hazards.fema.gov`, `fwspublicservices.wim.usgs.gov` | `DisableAerial` |
| Weather in daily logs | `api.open-meteo.com`, `archive-api.open-meteo.com`, `geocoding-api.open-meteo.com`; with an Open-Meteo commercial API key, `customer-api.open-meteo.com`, `customer-archive-api.open-meteo.com`, `customer-geocoding-api.open-meteo.com` instead | `DisableWeather` |
| Labor-rate downloads | `api.bls.gov`, `data.bls.gov` | `DisableRateLookup` |
| DocuSign signature requests | `*.docusign.net` (your account's base URL) | `DisableDocuSign` |
| Dropbox open and save | `www.dropbox.com`, `api.dropboxapi.com`, `content.dropboxapi.com` | `DisableDropbox` |
| Local AI | `localhost:11434` (or `AIHost`) – stays on your network | `DisableAI` |
| Live package status (Package Tracker > Check Status, only with that carrier's keys; only the tracking number is sent) | `onlinetools.ups.com`, `apis.fedex.com`, `apis.usps.com`, `api-eu.dhl.com` | `DisablePackageStatus` |
| Update check (team copy only; once a day and Help > Check for Updates Now) | `pub-1121abaa7290424187564108985e68a0.r2.dev` (the team update host, Cloudflare R2; set in `app/updatecheck.py` `UPDATE_BASE`) | `DisableUpdateCheck` |
| Collaboration | your own relay (`RelayURL`), TCP 8765 and 8766 | don't set a relay |

`OfflineMode` turns off every internet feature above.

### Dropbox

File > Open from Dropbox / Save to Dropbox work with the Dropbox website only (no Dropbox desktop app). The company registers one free Dropbox app and gives its App key to QuantiSheet:

1. On https://www.dropbox.com/developers/apps choose **Create app** > **Scoped access** > **Full Dropbox**, and give it a name.
2. **Permissions** tab: tick `files.metadata.read`, `files.content.read` and `files.content.write` (`account_info.read` is always on), then **Submit**.
3. **Settings** tab: under OAuth 2 **Redirect URIs** add exactly `http://127.0.0.1:53917/`, and leave **Allow public clients (Implicit Grant & PKCE)** on Allow.
4. Copy the **App key** into File > Dropbox Settings… on each PC, or set it for everyone with the `DropboxAppKey` policy. The App secret is not needed.

Each user signs in with their own Dropbox account in their browser. The sign-in is kept encrypted for that Windows user (DPAPI) in `%USERPROFILE%\.quantisheet\dropbox-token.dpapi`; working copies of downloaded files are in `%USERPROFILE%\.quantisheet\Dropbox\`. If port 53917 can't be opened on 127.0.0.1, QuantiSheet shows Dropbox's "copy this code" page instead.

The standalone setup's optional extras download from `github.com` (Tesseract), `ollama.com` (Ollama) and `python.org`. The server setup downloads nothing.

QuantiSheet sends no telemetry and has no automatic update check.

## Remote Desktop / Windows Server

- **Install:** use the server setup. Every user gets the Start-menu shortcut.
- **Each user's own data:** settings, recent files and logs are in `%USERPROFILE%\.quantisheet`, so users don't share a file. With roaming profiles or FSLogix, include that folder. Use `LogDirectory` to gather logs in one place.
- **Sign-in and license prompts:** these are per user. Set `LicenseKey`, `AcceptAgreement` and `SkipEmailSignIn` so nobody is asked.
- **Background drawing process:** each user's QuantiSheet starts its own. They talk over pipes, not network ports, so sessions don't clash.
- **The local AI:** run one Ollama on the server (or on a GPU box) and set `AIHost`. Don't install it per user.
- **Memory:** large drawing sets (hundreds of sheets) use the most. Size the server from a pilot group and watch Task Manager's per-user memory. We haven't measured a per-user figure on a server yet.
- **Updates:** the server setup asks running copies to close (Restart Manager). On a busy Remote Desktop server, run updates out of hours.
- **Collaboration:** use the server relay (below). Don't use the in-app "start a relay" button on a shared server: each user's copy would try to use the same ports.

## The collaboration relay (server setup, task `relay`)

What the relay task sets up:
- **A scheduled task "QuantiSheet Relay"**: starts with Windows and runs as `LOCAL SERVICE` (low rights).
- **Ports:** listens on TCP 8765 (desktop) and 8766 (phones/web).
- **Firewall:** an inbound rule for those ports.

| Item | Location |
|---|---|
| Token | `C:\ProgramData\QuantiSheet\relay\relay-token.txt`. Made at install; users may read only this file. Give it to users with the `RelayToken` policy. |
| Shared projects | `C:\ProgramData\QuantiSheet\relay\hub` (back this folder up). Users have no access to the `relay` folder; only the relay (LOCAL SERVICE) and administrators do. |
| Log | `C:\ProgramData\QuantiSheet\relay\relay.log` |

Back up `C:\ProgramData\QuantiSheet\relay` (token, shared projects, log).

**Encryption.** Without a certificate the relay runs as `ws://` and `http://`, which is fine only on a trusted internal network. For `wss://` and `https://`:
1. Give the relay a PEM certificate and key. Edit the task's action and add:

   ```
   --cert "C:\ProgramData\QuantiSheet\relay.crt" --key "C:\ProgramData\QuantiSheet\relay.key"
   ```

   To convert a `.pfx` from your certificate store: `openssl pkcs12 -in relay.pfx -out relay.crt -clcerts -nokeys`, then `openssl pkcs12 -in relay.pfx -out relay.key -nocerts -nodes`.
2. Restrict `relay.key` so only `LOCAL SERVICE` and Administrators can read it.
3. Set `RelayURL` to `wss://<server>:8765`.

Without a certificate, the `ws://` address IT sets in `RelayURL` is trusted as it is: users don't have to switch on "allow unencrypted" themselves. Any other plain `ws://` address is still refused.

**Behind a reverse proxy (`TRUSTED_PROXIES`).** 5 wrong passwords or tokens from one address within a minute lock that address out for a minute. When the relay sits behind a proxy or load balancer on another machine (nginx, a cloud host's proxy), every connection seems to come from the proxy; set the environment variable `TRUSTED_PROXIES` to the proxy's address or network (comma-separated, e.g. `10.0.0.0/8` or `192.0.2.10,fd00::/8`) so the relay reads the client's address from the proxy's `X-Forwarded-For` header. The header is ignored from any other address, and loopback is always trusted, so leave it unset when the relay is reached directly or through a proxy on the same machine. The hosted configs set it (Fly.io `fdaa::/16`, Render `10.0.0.0/8`; see server/README.md) - verify those ranges against the host's current documentation. Get it wrong and either every user looks like the proxy (one person's wrong password locks everyone out for a minute) or, if it is too wide, a client can fake its address and dodge the lockout.

Run it by hand to test:

```
QuantiSheet.exe relay --host 0.0.0.0 --token-file "C:\ProgramData\QuantiSheet\relay\relay-token.txt"
```

## Command line (scripts, help desk)

`QuantiSheet.exe <command>`. Add `--json` before the command for machine-readable output.

| Command | What it does |
|---|---|
| `policy` | The IT settings in effect on this PC |
| `diagnostics --out bundle.zip` | Support bundle. See below. |
| `sanitize in.pdf --out clean.pdf --manifest proof.json` | Removes hidden information and checks the saved file. Exit 0 when clean, 2 when not. |
| `genset --brief "1600 sf 3 bed house, lot 80 x 120" out.pdf --no-ai` | Generate Set |
| `relay …` | The collaboration relay (above) |
| `version` | Version and edition (tester or public) of this copy |
| `--help` | Every command |

## Support bundle

Users can run **Help > Support Bundle for IT…**; the command-line version is `QuantiSheet.exe diagnostics`. Either one makes a zip containing:
- the QuantiSheet and library versions;
- the Windows edition (desktop, Server or Server Core) and whether it's a Remote Desktop session;
- the policy in effect;
- whether the license, sign-in, price database, relay, AI and OCR work;
- the user's log files.

It never includes license keys, tokens, passwords, settings values or email addresses. Email addresses are removed from the logs as well.

## Code signing

The installers aren't code-signed yet, so Windows SmartScreen warns about an unknown publisher. Check the SHA-256 published with each release before running one:

```
Get-FileHash .\QuantiSheet-Beta-Server-Setup-0.12.28.exe
```

To sign, the company needs a code-signing certificate in its own name (an OV or EV certificate from a public certificate authority, typically $200–400 a year; EV clears SmartScreen at once). The build signs `QuantiSheet.exe` and both setups with `signtool` once the certificate is installed. This step is on `docs/RELEASE_CHECKLIST.md`.
