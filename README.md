# QuantiSheet

Cross-platform PDF review, markup, quantity takeoff, live collaboration, and
signing. Desktop (PySide6) + mobile web app + command line.

The program file is `QuantiSheet.exe`, the settings folder
`~/.quantisheet` and the install folder `...\QuantiSheet`. Files saved
under the program's earlier name are converted when they are opened
(`app/oldnames.py`).

## Install (Windows)

Double-click **install.bat**. It installs whatever of these is missing
(through winget, or the official installer), then sets up QuantiSheet, runs
its tests and puts a shortcut on the Desktop:

| Program | Used for | |
| --- | --- | --- |
| Python 3.12 | running QuantiSheet | required |
| Tesseract OCR | making scanned sheets searchable | recommended |
| Ollama + llama3.2 model (~2 GB) | AI review, Find RFIs, translate | optional |
| LibreOffice (~350 MB) | Word/Excel/PowerPoint to PDF when Microsoft Office isn't installed | optional |

`install.bat /minimal` skips the AI model and LibreOffice; `install.bat
/noai` skips only the AI model. The result is listed in
install-deps-log.txt.

## Install (any platform, by hand)

    python -m venv .venv
    source .venv/bin/activate          # Windows: .venv\Scripts\activate
    pip install -r requirements.txt pytest

Optional:
- **AI review**: install [Ollama](https://ollama.com), then `ollama pull llama3.2`
- **OCR** (scanned pages): install Tesseract

## Run

    python make_sample.py              # creates sample.pdf to try things on
    python quantisheet.py                # desktop app
    python quantisheet.py sample.pdf     # desktop app, opening a file
    python quantisheet.py --help         # command-line tools

## Test

    pytest

On a machine without a display (CI, SSH), set `QT_QPA_PLATFORM=offscreen`.

On Linux, Qt needs a few system libraries even offscreen:

    sudo apt install libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3

`run-tests.bat` (Windows) writes the results to `test-results.txt`.

## Build a standalone app

    ./build.sh                         # macOS / Linux
    build.bat                          # Windows

The program lands in `dist/QuantiSheet/` (`QuantiSheet.exe`). With no arguments it opens the desktop app;
with a command (`quantisheet rules in.pdf out.pdf`) it runs the CLI.
Pushing a `v*` tag to GitHub builds Windows, macOS and Linux versions and
attaches them to a release.

## Installer for testers (Windows)

    python tools/build_installer.py run    # -> release\QuantiSheet-Beta-Setup-<version>.exe

Builds the program, checks the built copy starts, opens drawings and finds
rooms, then packages it with Inno Setup (installed for you if missing).
Each tester needs a license key: `make-tester-key.bat`.

## Live collaboration

1. On the host computer: **Tools > Start Relay**. It shows two addresses.
2. Host: **Tools > Live Collaboration**, choose *Host*, pick a room
   password, Connect.
3. Other desktops: **Tools > Live Collaboration**, enter the host's relay
   address, the relay token it shows and the room password, choose *Join*.
4. Phones/tablets on the same network: open the `http://…:8766/?t=…` link
   (it carries the relay token) in a browser.

The first person into a room sets its password. Traffic is not encrypted,
so use it on networks you trust. Undo is turned off while collaborating.
The relay can also run headless: `python quantisheet.py relay --token
SECRET` (without a token it only listens on 127.0.0.1).

## Before you bid

**Estimate > Pre-bid Checklist** has to be green before **Lock Bid**: every
sheet reviewed, every markup priced (or linked to an estimate line),
excluded with a reason or sent as an RFI, and every revision cloud
accounted for. Right-click a markup > *Pre-bid Scope* to decide;
*Show Unpriced Markups* outlines what's left. `quantisheet prebid FILE.pdf`
checks from the command line (exit 0 = ready, 3 = not).

**Estimate > Job Cost Feedback** compares a locked bid with what the job
cost (Project Center direct costs or a job-cost CSV) and suggests cost book
prices from closed jobs; nothing changes until you apply a suggestion.

## Civil estimating

The **Civil** tab prices heavy civil work by crew and production rate:
equipment (owned or rented, with fuel), burdened labor, crews,
activities tied to takeoff groups, indirects, markup and bond. Import
the owner's bid schedule (CSV or Excel), assign activities to pay items
and the indirects spread across them (weights front-load items);
quantities more than 10% off the owner's are flagged. Also: a haul
calculator, prevailing wage import, saved and compared bid versions, and
phone time cards that feed production history and Job Cost Feedback,
an activity library and master estimates to start bids from, and a
cost-to-complete forecast by cost code while the job runs.
Starting rates in `app/data/heavy_starter.json` are samples.

## Signing

**File > Sign** signs with your personal certificate, created once in
`~/.quantisheet`. It is self-signed: it proves the file hasn't changed since
signing, but others' PDF readers will show the signer as unverified unless
they trust your certificate. Use `quantisheet sign --key --cert` with a
certificate from a certificate authority for that.

## Layout

    quantisheet.py  launcher (desktop app or CLI)
    app/            application code
    app/annotate.py every edit is applied here (desktop, rules, AI, collab)
    app/ai/         Ollama-backed review helpers
    app/sign/       signing, verification, hash-chained audit trail
    app/collab/     relay, client, op log, merge, web/ (phone app)
    tests/          pytest suite
