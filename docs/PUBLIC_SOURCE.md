# Publishing the QuantiSheet source

The public source lives in a separate repository named **quantisheet-source**.
This private repository stays private. The exporter does not create that
repository, change any visibility, push, or merge. Each release added there
is one clean snapshot commit: the tree of that release, and none of this
repository's history.

## Why the history stays private

The root commit of this private repository holds a retired relay key (it
lived under `server/data/`, which is gitignored now). Publishing this
history would publish that key. `git archive` exports one tree, so a
snapshot has no history.

## Each release

1. **Export and scan.** From this repository, with an empty folder that is
   not inside it:

       python tools/public_source.py <ref> <empty-folder>

   `<ref>` is the release tag or commit. The command archives only tracked
   files (`git archive`), drops the never-publish paths and anything
   `.gitignore` covers, writes `PUBLIC_SOURCE_README.md`, and scans the
   folder. A problem exits non-zero and prints a list. Do not publish a
   folder that failed the scan.

2. **Read the scan result.** It must say the snapshot is clean.

3. **Commit** in that new folder. The exporter prints the commands and
   does not run them. The author is `QuantiSheet <noreply@quantisheet.invalid>`
   (a placeholder; do not use a personal address):

       git init -b main
       git add --all
       git -c user.name=QuantiSheet -c user.email=noreply@quantisheet.invalid commit --author="QuantiSheet <noreply@quantisheet.invalid>" -m "QuantiSheet <ref> corresponding source"

4. **Push** to the public repository quantisheet-source:

       git remote add origin <url of quantisheet-source>
       git push -u origin main

5. **Tag** that commit with the release and push the tag:

       git tag -a <ref> -m "QuantiSheet <ref> corresponding source"
       git push origin <ref>

A later release is the same export, then one new commit on a checkout of
quantisheet-source (keep that clone's `.git`, replace the other files
with the new snapshot). The public history is only these snapshot commits.

## What the export leaves out

- `server/data/`
- `app/onboard.py`
- `tools/unlock_code.py`
- `.env*`, `*.pem`, `*.key`, `*.pfx`, `*.p12`, `company_*.json`
- anything else `.gitignore` covers
- `tools/public_source_scrub.json` (it lists the strings the scan looks
  for, so it stays in this private repository)

If any of those are still in the folder after the export, the scan fails.

## Scrub list

`tools/public_source_scrub.json` is the list. An entry with `enabled` true
must not appear in the snapshot. An entry with `enabled` false is recorded
and the scan does not fail on it.

- Plan-set folders and bid-set file names are read from the environment
  (`QS_AIKEN_SRC`, `QS_AIKEN_DRAWINGS`, `QS_AIKEN_SPEC`, `QS_AIKEN_XLSX`,
  and the same `QS_COLLETON_*` names) or from settings (`aiken_src`,
  `aiken_drawings`, `aiken_spec`, `aiken_xlsx`, and the `colleton_*`
  keys). The harness skips with a message when a value it needs is unset.
  `tools/aiken_map.json` and `tools/colleton_map.json` stay; they are
  quantity crosswalks.
- The street address that was in `tests/test_formlib.py` is replaced with
  a fictional one. That scrub entry is switched on.
- The support email in `app/issue_report.py` is **decided: keep**.
- The Partner Center identity in `installer/msix_identity.json` is
  **pending** and switched off.

The scan also rejects a 32-byte binary secret, the private Windows
username, a Windows profile path (a drive letter, then a Users directory),
and any path on the never-publish list.
