# Release checklist

## In-house tester build (what we ship today)
1. Back up: `python tools/backup_folder.py <label>`.
2. Full test suite on the PC (`tool tests_timed 1500 tests -q`): 0 failed.
3. Bump `app/__init__.py` and `installer/version_info.txt`.
4. `python tools/build_installer.py start`, then `status` until done. The
   built program's own check must show every line `ok`, including
   "drawing process" and "generate set: 9 sheets, Modulor ...".
   The build makes four setups: `release\QuantiSheet-Beta-Setup-<v>.exe`
   and `QuantiSheet-Beta-Server-Setup-<v>.exe` (in-house), and the public
   copies in `release\github\` (no contact list, key always required).
5. `python tools/install_release.py`, then `python tools/zip_release.py`
   (prints the installer SHA-256 to send with the zip).
6. What's New PDF in `release\` (made before the zip), named
   `QuantiSheet <v> - Whats New.pdf` - zip_release.py looks for that name.
   The zip is `QuantiSheet <v> for the team.zip`.
7. Review packets for Grok / Venice: no passwords, contacts, keys, emails
   or company details; never the real email domain; no sign-in code.

## Publishing on GitHub
Only the files in `release\github\` (`QuantiSheet-Public-Beta-...`) and
`SHA256SUMS.txt`. Never the in-house setups in `release\` (they carry the
sealed contact list and don't ask for a key). Jon decides when and to
which repository; check the repository is private unless a public release
was decided. Attach `docs/IT_DEPLOYMENT.md` and the release notes.
The public build covers the first two items below automatically
(tools/build_installer.py `public_copy`, checked by the build); the rest
still apply.

## Before ANY build goes outside the company
- [ ] License key back on: `KEY_REQUIRED = True` in `app/betalicense.py`
      (issue keys with `tools/beta_keys.py`).
- [ ] Company contacts out: delete `app/data/contacts.sealed` (see
      `app/sealed_contacts.py`, `FILE`) so it isn't in the installer, and
      check the built program's folder for it.
- [ ] Sign-in: decide whether the work-email gate stays (it is a speed
      bump only - see `docs/SIGNIN_NOTES.md`); an outside build needs a
      server check or the license key alone.
- [ ] Code signing: sign `QuantiSheet.exe` and the setup with the company
      certificate (signtool) so Windows SmartScreen doesn't warn.
- [ ] Practice drawings and samples contain no client drawings.
- [ ] Remove `tools/unlock_code.py` from anything you send; it is for Jon.
- [ ] Run Remove Hidden Information / External Issue on any sample PDFs.
- [ ] Third-party licenses (Help > Third-Party Licenses) list Modulor (MIT)
      and manifold3d.

## Tester builds are signed (0.12.24)
The in-house build is stamped with the license signing key
(tools/beta_keys.py; `~/QuantiSheet Keys/beta_signing_key.pem`). Without that
key on the build PC the build stops - an unsigned installed copy runs as a
public build and asks for a license key.
