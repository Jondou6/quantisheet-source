# Windows long paths, `\\?\` prefixes, and deep UNC paths

Audit of commit `86577a5` (QuantiSheet 1.1.1). No code is changed by this
note. Line numbers are the first line of each call.

This was read on Linux against Python 3.12's `ntpath.py` (the same
pure-Python source Windows uses when the native helper is absent) and
against `quantisheet.spec` / `quantisheet_claims.spec`. Anything that
depends on the real Windows API is marked **UNVERIFIED**.

## What fails

Windows still stops a path at **260 characters** (the `MAX_PATH` limit,
including the terminating NUL, so 259 characters of path) unless both of
these are true:

1. The process is long-path aware (`longPathAware` in the executable manifest).
2. The machine has long paths turned on (`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled` = 1).

`quantisheet.spec` and `quantisheet_claims.spec` do not set a manifest.
**UNVERIFIED:** whether the PyInstaller 6.3–6.x bootloader manifest already
sets `longPathAware` on its own. python.org's `python.exe` is long-path
aware; a PyInstaller `QuantiSheet.exe` is not known to be. A path of 260
characters or more then fails in `open`, `os`, `shutil` and `pathlib` with
`OSError` / `FileNotFoundError` (Windows error 206 or 3).

A **deep UNC path** (`\\server\share\...`) hits the same 260-character
ceiling. The form that gets past it is `\\?\UNC\server\share\...`.

A path that **already starts with `\\?\`** (or `\\?\UNC\`) bypasses the
260 limit, up to about 32,767 characters, but Windows then does **no**
normalisation:

- `/` is a literal character, not a separator, so the open fails.
- `.` and `..` are literal directory names, not "here" and "up", so the open fails.
- `os.path.join(r'\\?\C:\job', r'C:\other')` drops the prefix, because the
  second part has a different drive (`C:` versus `\\?\C:`). The result is
  a normal path and is subject to the 260 limit again.
- `os.path.relpath` and `os.path.commonpath` raise `ValueError` when one
  side is `\\?\C:` and the other is `C:`, or when one side is
  `\\server\share` and the other is `\\?\UNC\server\share`. Python 3.12's
  `splitroot` treats those as different drives (confirmed in the
  pure-Python `ntpath.splitroot`).

`os.path.realpath` on Windows calls `GetFinalPathName`. It fails past 260
when the input is not already prefixed. When it succeeds it **strips** a
`\\?\` prefix it added itself, so the string it returns can be too long
for the next `open`. **UNVERIFIED** against a live Windows call; this is
what Python 3.12's `ntpath.realpath` source does.

`os.path.normpath` in the pure-Python fallback collapses `.` and `..` and
keeps a `\\?\` / `\\?\UNC\` prefix (`splitroot` understands both). The
native Windows `_path_normpath` is **UNVERIFIED**. `normpath` does not
itself call the filesystem, so those calls are not listed below.

## Suggested fix, one pattern at a time

Do this in a new helper (for example `app/winpath.py`). Call it at the
sites below. Do not call `GetFullPathName` / `os.path.abspath` /
`os.path.realpath` on a path that is already longer than 259 characters:
those are the calls that fail. Do the prefix with string operations.

```text
extended(path) -> str
    On non-Windows, return the path unchanged.
    Turn "/" into "\".
    If it does not already start with \\?\, make it absolute with a
    string join onto the cwd (the cwd itself may need extended() first).
    Collapse "." and ".." in the string, before any \\?\ prefix is added.
    \\server\share\...  becomes  \\?\UNC\server\share\...
    C:\...              becomes  \\?\C:\...
    A path that already starts with \\?\ is only re-collapsed, not prefixed twice.

comparable(path) -> str
    The form to use before relpath, commonpath, or startswith("\\").
    Strip a leading \\?\ .
    Rewrite \\?\UNC\server\share as \\server\share.
    Leave \\?\C:\ as C:\ after the strip.
    Then both sides of a jail check share a drive.
```

On top of that, add `longPathAware` to the PyInstaller manifest and
document `LongPathsEnabled`. That is a second layer. It does not fix a
path that arrives as `\\?\` with a `/` or a `..` in it, and it does
nothing on a machine where the registry value is off.

### Pattern A — filesystem calls

`open`, `os.open`, `os.remove` / `unlink` / `rename` / `replace` / `mkdir` /
`makedirs` / `listdir` / `scandir` / `walk` / `stat` and the rest of the
Win32 set, `os.path.exists` / `isfile` / `isdir` / `getsize` / `getmtime` /
`realpath` / `abspath`, `shutil.copy` / `copy2` / `copytree` / `move` /
`rmtree`, `pathlib` read/write/mkdir/iterdir, `fitz.open(path)` /
`pymupdf.open(path)`, `Image.open`, `gzip`/`bz2`/`lzma`/`tarfile` open,
`zipfile.ZipFile`, `sqlite3.connect`, and `os.DirEntry.stat`.

**Fix:** pass `extended(path)` into the call. For `shutil.copytree` /
`rmtree` / `move`, prefix the root you pass in; children joined with
`os.path.join(prefixed, relative_name)` keep the prefix. For `fitz.open`,
only calls that take a filesystem path are listed. `fitz.open()`,
`fitz.open("pdf", data)` and `fitz.open(stream=...)` were counted and
skipped.

### Pattern B — `os.path.join`

**Fix:** join the parts first, then call `extended` once on the result.
Do not pass a `\\?\` path as the first argument and a drive-absolute path
(`C:\...` or another `\\...`) as a later argument: join replaces the drive
and the prefix is gone. Do not leave `..` in a string that already starts
with `\\?\`.

### Pattern C — `os.path.relpath`, `os.path.commonpath`, and `startswith("\\")`

These are the checks that change meaning, not only the ones that raise
past 260.

**Fix:** run both paths through `comparable` before `relpath` /
`commonpath` / a `startswith("\\")` test. Catch `ValueError` only after
that. A share is `\\server\...` or `\\?\UNC\...`. A local `\\?\C:\...` is
not a share.

Sites that already decide "inside or not" or "on a share or not"
(verified by reading them):

| Call | What a `\\?\` or deep UNC path does here |
|---|---|
| `app/collab/hub.py:141` `os.path.commonpath` | Jail for hub files. Mixed `\\?\C:` and `C:` raises `ValueError`, which the `except` treats as "not inside" (`HubError: Bad path`). A long path fails earlier in `realpath`. Fail-closed, so a real file under the data folder is rejected. `server/hub.py` is a copy; `tools/sync_server.py` must be run after the app copy changes. |
| `app/collab/relaycore.py:344` `safe_join` → `commonpath` at line 347 | Same jail for the phone web files. Same `ValueError` → `None` (refused). `server/relaycore.py:347` is the copy. |
| `app/estimating/_io.py:42` `_real` + `_inside` at line 49 | `realpath` then `commonpath`. `ValueError` returns False (not inside), so a save aimed at a prefixed path under the data folder is refused. |
| `tools/make_update_manifest.py:40` `commonpath` | "Is this key inside the repo?" Mixed prefix raises, or reports a different drive. |
| `app/jobsafe.py:180` `abspath`, then `startswith("\\\\")` at line 182 | `\\?\C:\job.pdf` starts with `\\`, so a local extended path is treated as a network share and gets a lock file. `\\?\UNC\server\share\...` is a share, and this check does say so, but only because every `\\` matches. |
| `quantisheet_backoffice/store.py:585` `abspath`, then `startswith("\\\\")` at line 586 | Same test, used to keep payroll off a share. A local `\\?\C:\` path is classified as a share. |
| `app/main_window.py:193` and `:196` `file_link_target` | Already refuses a link whose text contains `\\?\` or a UNC (`\\server` / `//server`). That is a string check on PDF link actions. It does not make `open()` of a long drawing path safe. |

### Pattern D — `pathlib` `as_posix` / `as_uri`, and Path methods that need a Path in hand

**Fix:** do not open `Path.as_posix()` when the path may carry `\\?\`.
Forward slashes are literal under that prefix and the open fails.
`os.fspath(path)` keeps the backslashes. `as_uri()` of a `\\?\` path is
not a usable file URI.

### Pattern E — `tempfile`

**Fix:** `mkdtemp` / `mkstemp` / `NamedTemporaryFile` return a path with
no `\\?\` prefix. Call `extended` on that path before it is opened,
copied, or removed. If `%TEMP%` itself is deep, creating the directory
fails first; point `dir=` at a short folder and extend afterwards.
**UNVERIFIED:** whether `tempfile` accepts a `dir` that already starts
with `\\?\`.

## How this list was made

An AST walk of every `*.py` file under `app/`, `tools/` (not
`tools/scratch/`), `server/`, `quantisheet_backoffice/` (including
`r111/`), `quantisheet_claims/`, `installer/`, `tests/`, and the
top-level scripts. `vendor/` is a third-party zip and was not unpacked.
A file is grouped under tests when a path component is exactly `tests`.
`quantisheet_backoffice/host_tests/` is grouped with production for that
reason.

Not listed, on purpose:

- `os.path.dirname`, `basename`, `split`, `splitext`, `splitdrive`,
  `normcase`, `isabs`, `commonprefix`, `expanduser`, `expandvars`,
  `normpath`. They do not call the filesystem. In Python 3.12 they keep
  a `\\?\` prefix. Counted below so it is clear they were seen.
- `os.environ`, `os.getpid`, `os.urandom`, `os.fdopen`, `os.close`,
  `shutil.which`, `shutil.copyfileobj`, `shutil.ignore_patterns`.
- UI methods named `open` (`self.open`, `ctl.open`) and `menu.resolve`.
  Those are not filesystem calls.
- `fitz.TextWriter.write_text` in `app/genset/draw.py`.
- `fitz.open()` with no path, a filetype string such as `"pdf"`, or
  `stream=`. Counted below.

Not seen by the walk: `getattr(os, name)(...)`, `exec`, and paths built
inside strings that are later passed to `cmd`. A text search for
`getattr(os`, `getattr(shutil` and `getattr(pathlib` is reported at the
end.

`tools/scratch/` is throwaway probes. It is excluded. It has the same
patterns and is not part of the program.

## Counts

| Pattern | Production | Tests | Total |
|---|---:|---:|---:|
| `open`, `os` file calls, `os.path` checks that hit the filesystem, `shutil` | 2043 | 791 | 2834 |
| `fitz.open` / `pymupdf.open` of a filesystem path | 183 | 254 | 437 |
| `Image.open` | 5 | 10 | 15 |
| `gzip` / `bz2` / `lzma` / `tarfile` / `zipfile.ZipFile` / `sqlite3.connect` | 42 | 36 | 78 |
| `pathlib` methods that read, write, create, or stat | 45 | 188 | 233 |
| `os.path.join` | 1196 | 316 | 1512 |
| `os.path.relpath` and `os.path.commonpath` | 39 | 6 | 45 |
| `pathlib` `as_posix` / `as_uri` (and Path methods only when the receiver is a Path) | 0 | 0 | 0 |
| `tempfile` | 118 | 13 | 131 |

Reviewed and not listed as failures:

- 4 `fitz.TextWriter.write_text` calls (drawing text, not a path)
- 647 `fitz.open()` calls that take bytes or no path (`fitz.open()`, `fitz.open("pdf", data)`, `fitz.open(stream=...)`)
- 1486 string-only `os.path` calls (`dirname`, `basename`, `split`, `normpath`, and the rest named above)
- 21 other `shutil` calls (`which`, `copyfileobj`, `ignore_patterns`)
- `tools/scratch/` is not walked (throwaway probes; the folder name `scratch` is skipped)
- 1348 Python files walked
- Method calls that are not `open` / `os` / `shutil` / `pathlib` / the libraries above are not path calls and are not listed. One `getattr` line is at the end of this note: `app/safeio.py:25` uses `getattr(os, "O_BINARY", 0)`, which is a flag, not a path.
- `app/textio.py` `read_text` and `app/roof_report.py` `read_text` / `read_file` are wrappers. Their `open` calls are in pattern A. The wrapper calls are not a second filesystem API.

## Inventory

### Pattern A — `open`, `os` file calls, `os.path` checks that hit the filesystem, `shutil`

Production sites: 2043. Test sites: 791.

#### Production

#### `app/acrobat.py`

- `app/acrobat.py:33` `os.path.isdir` — `if os.path.isdir(cand):`
- `app/acrobat.py:190` `os.remove` — `os.remove(png)`
- `app/acrobat.py:194` `os.rmdir` — `os.rmdir(tmpdir)`
- `app/acrobat.py:299` `open` — `with open(path, "w", encoding="utf-8") as f:`
- `app/acrobat.py:308` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `app/acrobat.py:786` `os.path.isfile` — `if path and not edited and os.path.isfile(path):`
- `app/acrobat.py:787` `os.path.getsize` — `return os.path.getsize(path)`
- `app/acrobat.py:801` `os.path.isfile` — `if name and os.path.isfile(name) and not doc.is_dirty:`
- `app/acrobat.py:802` `os.path.getsize` — `original = os.path.getsize(name)`
- `app/acrobat.py:820` `os.path.getsize` — `return os.path.getsize(path)`
- `app/acrobat.py:824` `os.path.getsize` — `after = os.path.getsize(tmp)`
- `app/acrobat.py:828` `os.replace` — `os.replace(tmp, path)`
- `app/acrobat.py:835` `os.path.exists` — `if os.path.exists(tmp):`
- `app/acrobat.py:837` `os.remove` — `os.remove(tmp)`

#### `app/acrobat2.py`

- `app/acrobat2.py:75` `os.path.exists` — `if os.path.exists(cand):`
- `app/acrobat2.py:91` `os.path.abspath` — `_powershell(_PS[kind], {"PS_IN": os.path.abspath(path),`
- `app/acrobat2.py:92` `os.path.abspath` — `"PS_OUT": os.path.abspath(out)})`
- `app/acrobat2.py:93` `os.path.exists` — `if os.path.exists(out):`
- `app/acrobat2.py:110` `os.path.exists` — `if os.path.exists(made):`
- `app/acrobat2.py:111` `os.replace` — `os.replace(made, out)`
- `app/acrobat2.py:141` `open` — `with open(path, encoding="utf-8", errors="replace") as f:`
- `app/acrobat2.py:144` `open` — `with open(path, encoding="utf-8", errors="replace") as f:`
- `app/acrobat2.py:145` `os.path.abspath` — `return _story_pdf(f.read(), os.path.dirname(os.path.abspath(path)))`
- `app/acrobat2.py:160` `os.makedirs` — `os.makedirs(out_dir, exist_ok=True)`
- `app/acrobat2.py:286` `open` — `with open(path, "w", encoding="utf-8") as f:`
- `app/acrobat2.py:353` `os.path.abspath` — `_powershell(_PPT_SCRIPT, {"PS_DIR": folder, "PS_OUT": os.path.abspath(path),`
- `app/acrobat2.py:470` `os.path.exists` — `while os.path.exists(out):`
- `app/acrobat2.py:922` `os.makedirs` — `os.makedirs(out_dir, exist_ok=True)`
- `app/acrobat2.py:928` `os.path.abspath` — `if os.path.abspath(out) == os.path.abspath(src):`
- `app/acrobat2.py:928` `os.path.abspath` — `if os.path.abspath(out) == os.path.abspath(src):`
- `app/acrobat2.py:954` `os.path.getsize` — `original=os.path.getsize(src))`

#### `app/acrobat2_dialogs.py`

- `app/acrobat2_dialogs.py:100` `os.listdir` — `os.path.join(d, f) for f in os.listdir(d)`

#### `app/ada_ref.py`

- `app/ada_ref.py:16` `os.path.abspath` — `FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `app/ada_ref.py:29` `open` — `with open(FILE, encoding="utf-8") as f:`

#### `app/ada_ui.py`

- `app/ada_ui.py:508` `open` — `with open(path, "w", encoding="utf-8") as fh:`

#### `app/aerial.py`

- `app/aerial.py:56` `open` — `with open(self.path, "rb") as f:`
- `app/aerial.py:481` `open` — `with open(p, "rb") as f:`
- `app/aerial.py:483` `os.utime` — `os.utime(p) # recently used`
- `app/aerial.py:495` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/aerial.py:498` `open` — `with open(tmp, "wb") as f:`
- `app/aerial.py:500` `os.replace` — `os.replace(tmp, p)`
- `app/aerial.py:501` `os.listdir` — `files = [os.path.join(d, n) for n in os.listdir(d)`
- `app/aerial.py:503` `os.path.getmtime` — `files.sort(key=lambda f: os.path.getmtime(f))`
- `app/aerial.py:504` `os.path.getsize` — `total = sum(os.path.getsize(f) for f in files)`
- `app/aerial.py:507` `os.path.getsize` — `total -= os.path.getsize(f)`
- `app/aerial.py:508` `os.remove` — `os.remove(f)`
- `app/aerial.py:653` `os.path.isfile` — `if os.path.isfile(name):`
- `app/aerial.py:655` `open` — `with open(name) as f:`

#### `app/aerial_ui.py`

- `app/aerial_ui.py:885` `os.path.isfile` — `if not os.path.isfile(path):`

#### `app/aitakeoff_ui.py`

- `app/aitakeoff_ui.py:244` `os.path.isfile` — `if name and os.path.isfile(name) and not doc.is_dirty:`

#### `app/assemblies.py`

- `app/assemblies.py:327` `open` — `with open(LIBRARY_PATH, encoding="utf-8") as f:`
- `app/assemblies.py:341` `open` — `with open(LIBRARY_PATH, encoding="utf-8") as f:`
- `app/assemblies.py:347` `os.makedirs` — `os.makedirs(os.path.dirname(LIBRARY_PATH), exist_ok=True)`
- `app/assemblies.py:349` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/assemblies.py:351` `os.replace` — `os.replace(tmp, LIBRARY_PATH)`
- `app/assemblies.py:357` `open` — `with open(LIBRARY_PATH, encoding="utf-8") as f:`
- `app/assemblies.py:363` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `app/assemblies.py:365` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/assemblies.py:367` `os.replace` — `os.replace(tmp, LIBRARY_PATH)`

#### `app/assembly_codes.py`

- `app/assembly_codes.py:39` `os.path.abspath` — `_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")`
- `app/assembly_codes.py:137` `open` — `with open(path, "w", newline="", encoding="utf-8") as f:`

#### `app/assembly_csv.py`

- `app/assembly_csv.py:36` `os.path.abspath` — `CATALOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `app/assembly_csv.py:204` `open` — `with open(path, "w", encoding="utf-8-sig", newline="") as f:`
- `app/assembly_csv.py:238` `open` — `with open(path, "w", encoding="utf-8-sig", newline="") as f:`
- `app/assembly_csv.py:261` `os.makedirs` — `os.makedirs(path, exist_ok=True)`
- `app/assembly_csv.py:266` `os.path.exists` — `files = [CATALOG] if os.path.exists(CATALOG) else []`
- `app/assembly_csv.py:269` `os.listdir` — `files += [os.path.join(d, n) for n in sorted(os.listdir(d))`
- `app/assembly_csv.py:300` `os.path.getmtime` — `key = (tuple((f, os.path.getmtime(f)) for f in files),`

#### `app/audit.py`

- `app/audit.py:152` `os.path.abspath` — `file = os.path.abspath(file or doc.name or "")`

#### `app/audit_ui.py`

- `app/audit_ui.py:232` `os.path.exists` — `if r.get("file") and os.path.exists(r["file"]):`

#### `app/autosave.py`

- `app/autosave.py:57` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/autosave.py:62` `os.path.abspath` — `ident = os.path.abspath(path) if path else f"untitled-{id(view)}"`
- `app/autosave.py:81` `os.replace` — `os.replace(tmp, pdf)`
- `app/autosave.py:82` `open` — `with open(meta, "w", encoding="utf-8") as f:`
- `app/autosave.py:83` `os.path.abspath` — `json.dump({"original": os.path.abspath(path) if path else "",`
- `app/autosave.py:95` `os.remove` — `os.remove(p)`
- `app/autosave.py:105` `os.listdir` — `for name in os.listdir(d):`
- `app/autosave.py:111` `open` — `with open(meta, encoding="utf-8") as f:`
- `app/autosave.py:115` `os.path.exists` — `if not os.path.exists(pdf):`
- `app/autosave.py:120` `os.path.exists` — `if orig and os.path.exists(orig) and \`
- `app/autosave.py:121` `os.path.getmtime` — `os.path.getmtime(orig) >= os.path.getmtime(pdf):`
- `app/autosave.py:121` `os.path.getmtime` — `os.path.getmtime(orig) >= os.path.getmtime(pdf):`
- `app/autosave.py:124` `os.remove` — `os.remove(p)`
- `app/autosave.py:136` `os.remove` — `os.remove(p)`
- `app/autosave.py:210` `os.access` — `if not os.path.exists(path) or not os.access(path, os.W_OK):`
- `app/autosave.py:210` `os.path.exists` — `if not os.path.exists(path) or not os.access(path, os.W_OK):`
- `app/autosave.py:215` `os.path.abspath` — `same = bool(doc.name) and os.path.abspath(doc.name) == \`
- `app/autosave.py:216` `os.path.abspath` — `os.path.abspath(path)`

#### `app/backoffice_hook.py`

- `app/backoffice_hook.py:54` `os.path.isfile` — `if isinstance(exe, str) and exe and os.path.isfile(exe) and \`
- `app/backoffice_hook.py:58` `os.path.abspath` — `install = os.path.dirname(os.path.abspath(sys.executable))`
- `app/backoffice_hook.py:61` `os.path.isfile` — `return [sib] if os.path.isfile(sib) else None`
- `app/backoffice_hook.py:305` `os.listdir` — `names = os.listdir(base)`
- `app/backoffice_hook.py:313` `os.path.isdir` — `if os.path.isdir(p) and not os.path.islink(p) and \`
- `app/backoffice_hook.py:313` `os.path.islink` — `if os.path.isdir(p) and not os.path.islink(p) and \`
- `app/backoffice_hook.py:314` `os.path.getmtime` — `now - os.path.getmtime(p) > max_age:`
- `app/backoffice_hook.py:315` `shutil.rmtree` — `shutil.rmtree(p, ignore_errors=True)`
- `app/backoffice_hook.py:327` `open` — `with open(path, "w", encoding="utf-8") as fh:`
- `app/backoffice_hook.py:374` `os.path.abspath` — `d = os.path.dirname(os.path.abspath(path))`

#### `app/betalicense.py`

- `app/betalicense.py:44` `os.path.abspath` — `return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")`
- `app/betalicense.py:49` `open` — `with open(os.path.join(_data_dir(), _PUBKEY_FILE)) as f:`
- `app/betalicense.py:124` `os.makedirs` — `os.makedirs(os.path.dirname(_seen_file()), exist_ok=True)`
- `app/betalicense.py:125` `open` — `with open(_seen_file(), "w") as f:`
- `app/betalicense.py:141` `open` — `with open(p) as f:`
- `app/betalicense.py:229` `os.path.abspath` — `data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")`
- `app/betalicense.py:231` `open` — `with open(os.path.join(data, "build.json"), encoding="utf-8") as f:`
- `app/betalicense.py:241` `os.path.isfile` — `sealed = os.path.isfile(os.path.join(data, "contacts.sealed"))`

#### `app/bidform_auto_ui.py`

- `app/bidform_auto_ui.py:89` `os.path.isfile` — `if not src or not os.path.isfile(src):`

#### `app/bidform_xl_ui.py`

- `app/bidform_xl_ui.py:23` `os.startfile` — `self.open_file = open_file or (lambda p: os.startfile(p))`
- `app/bidform_xl_ui.py:91` `os.path.exists` — `if os.path.exists(path) and ask and QMessageBox.question(`
- `app/bidform_xl_ui.py:111` `os.path.isfile` — `if self.book_path and os.path.isfile(self.book_path):`
- `app/bidform_xl_ui.py:119` `os.path.isfile` — `if not (self.book_path and os.path.isfile(self.book_path)):`
- `app/bidform_xl_ui.py:165` `os.path.isfile` — `if self.book_path and os.path.isfile(self.book_path):`
- `app/bidform_xl_ui.py:260` `os.access` — `folder = self.folder if self.folder and os.access(`

#### `app/bidtab.py`

- `app/bidtab.py:339` `open` — `with open(path, "w", encoding="utf-8-sig", newline="") as f:`

#### `app/bidzip.py`

- `app/bidzip.py:113` `open` — `with open(zip_path, "rb") as f:`
- `app/bidzip.py:126` `os.makedirs` — `os.makedirs(dest_dir, exist_ok=True)`
- `app/bidzip.py:130` `os.path.exists` — `while os.path.exists(dest): # same name, other content`
- `app/bidzip.py:134` `open` — `with open(dest, "wb") as f:`

#### `app/branding.py`

- `app/branding.py:25` `os.path.isfile` — `if d and os.path.isfile(os.path.join(d, EXE)):`

#### `app/civil_export.py`

- `app/civil_export.py:146` `open` — `with open(path, "w", newline="", encoding="utf-8") as f:`
- `app/civil_export.py:198` `open` — `with open(path, "w", newline="", encoding="utf-8") as f:`
- `app/civil_export.py:286` `open` — `with open(path, "w", newline="", encoding="utf-8") as f:`
- `app/civil_export.py:363` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`

#### `app/claims_hook.py`

- `app/claims_hook.py:58` `os.path.isfile` — `if isinstance(exe, str) and exe and os.path.isfile(exe) and \`
- `app/claims_hook.py:62` `os.path.abspath` — `install = os.path.dirname(os.path.abspath(sys.executable))`
- `app/claims_hook.py:64` `os.path.isfile` — `return [sib] if os.path.isfile(sib) else None`
- `app/claims_hook.py:132` `open` — `with open(path, "w", encoding="utf-8") as fh:`

#### `app/cli.py`

- `app/cli.py:165` `open` — `with open(path, encoding="utf-8") as f:`
- `app/cli.py:171` `os.makedirs` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `app/cli.py:171` `os.path.abspath` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `app/cli.py:173` `open` — `with open(path, "w", encoding="utf-8") as f:`
- `app/cli.py:192` `open` — `with open(a.out, "rb") as f:`
- `app/cli.py:200` `open` — `with open(a.manifest, "w", encoding="utf-8") as f:`
- `app/cli.py:405` `os.path.abspath` — `out = a.out or os.path.abspath(`
- `app/cli.py:414` `open` — `with open(a.out, "w", encoding="utf-8") as f:`
- `app/cli.py:432` `os.makedirs` — `os.makedirs(os.path.dirname(os.path.abspath(a.log)),`
- `app/cli.py:432` `os.path.abspath` — `os.makedirs(os.path.dirname(os.path.abspath(a.log)),`

#### `app/codelib.py`

- `app/codelib.py:33` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/codelib.py:44` `os.listdir` — `for f in sorted(os.listdir(folder())):`
- `app/codelib.py:50` `open` — `with open(idx, encoding="utf-8") as fh:`
- `app/codelib.py:105` `os.path.abspath` — `if os.path.abspath(pdf_path) != os.path.abspath(dest):`
- `app/codelib.py:105` `os.path.abspath` — `if os.path.abspath(pdf_path) != os.path.abspath(dest):`
- `app/codelib.py:106` `shutil.copyfile` — `shutil.copyfile(pdf_path, dest)`
- `app/codelib.py:119` `open` — `with open(_index_path(dest), "w", encoding="utf-8") as f:`
- `app/codelib.py:131` `os.remove` — `os.remove(p)`
- `app/codelib.py:143` `open` — `with open(_index_path(pdf), encoding="utf-8") as f:`

#### `app/collab/hub.py`

- `app/collab/hub.py:123` `os.path.abspath` — `self.dir = os.path.abspath(data_dir)`
- `app/collab/hub.py:124` `os.makedirs` — `os.makedirs(self.dir, exist_ok=True)`
- `app/collab/hub.py:127` `os.path.exists` — `if not os.path.exists(sp):`
- `app/collab/hub.py:128` `open` — `with open(sp, "wb") as f:`
- `app/collab/hub.py:130` `open` — `with open(sp, "rb") as f:`
- `app/collab/hub.py:138` `os.path.realpath` — `base = os.path.realpath(self.dir)`
- `app/collab/hub.py:139` `os.path.realpath` — `full = os.path.realpath(os.path.join(base, *parts))`
- `app/collab/hub.py:150` `open` — `with open(path, encoding="utf-8") as f:`
- `app/collab/hub.py:158` `os.makedirs` — `os.makedirs(os.path.dirname(path), exist_ok=True)`
- `app/collab/hub.py:160` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/collab/hub.py:162` `os.replace` — `os.replace(tmp, path)`
- `app/collab/hub.py:249` `os.makedirs` — `os.makedirs(d)`
- `app/collab/hub.py:266` `open` — `with open(os.path.join(d, f"p{n}.png"), "wb") as f:`
- `app/collab/hub.py:375` `os.path.isdir` — `if meta is None and os.path.isdir(root):`
- `app/collab/hub.py:376` `os.listdir` — `for name in os.listdir(root):`
- `app/collab/hub.py:378` `os.path.isfile` — `m = self._load(p) if os.path.isfile(p) else None`
- `app/collab/hub.py:637` `open` — `with open(p, "a", encoding="utf-8") as f:`
- `app/collab/hub.py:668` `os.makedirs` — `os.makedirs(os.path.join(d, "files"), exist_ok=True)`
- `app/collab/hub.py:829` `os.path.exists` — `if os.path.exists(p):`
- `app/collab/hub.py:830` `open` — `with open(p, encoding="utf-8") as f:`
- `app/collab/hub.py:895` `os.makedirs` — `os.makedirs(os.path.dirname(tmp), exist_ok=True)`
- `app/collab/hub.py:896` `open` — `open(tmp, "wb").close()`
- `app/collab/hub.py:911` `os.path.getsize` — `if off != os.path.getsize(up["path"]):`
- `app/collab/hub.py:913` `open` — `with open(up["path"], "ab") as f:`
- `app/collab/hub.py:923` `open` — `with open(up["path"], "rb") as f:`
- `app/collab/hub.py:926` `os.path.getsize` — `size = os.path.getsize(up["path"])`
- `app/collab/hub.py:929` `os.remove` — `os.remove(up["path"])`
- `app/collab/hub.py:935` `os.makedirs` — `os.makedirs(os.path.dirname(dest), exist_ok=True)`
- `app/collab/hub.py:936` `os.replace` — `os.replace(up["path"], dest)`
- `app/collab/hub.py:955` `os.path.isfile` — `if not os.path.isfile(p):`
- `app/collab/hub.py:959` `open` — `with open(p, "rb") as f:`
- `app/collab/hub.py:963` `os.path.getsize` — `"total": os.path.getsize(p), "version": v}`
- `app/collab/hub.py:987` `open` — `with open(p) as f:`
- `app/collab/hub.py:992` `open` — `with open(p, "w") as f:`
- `app/collab/hub.py:1001` `os.path.isdir` — `if os.path.isdir(d):`
- `app/collab/hub.py:1002` `os.listdir` — `for name in sorted(os.listdir(d)):`
- `app/collab/hub.py:1011` `os.path.exists` — `if os.path.exists(p):`
- `app/collab/hub.py:1012` `open` — `with open(p) as f:`
- `app/collab/hub.py:1099` `os.path.exists` — `if not os.path.exists(p):`
- `app/collab/hub.py:1100` `os.makedirs` — `os.makedirs(os.path.dirname(p), exist_ok=True)`
- `app/collab/hub.py:1101` `open` — `with open(p, "wb") as f:`
- `app/collab/hub.py:1112` `os.path.isfile` — `if not os.path.isfile(p):`
- `app/collab/hub.py:1114` `open` — `with open(p, "rb") as f:`
- `app/collab/hub.py:1217` `os.makedirs` — `os.makedirs(os.path.dirname(p), exist_ok=True)`
- `app/collab/hub.py:1412` `os.path.exists` — `if not os.path.exists(p):`
- `app/collab/hub.py:1413` `os.makedirs` — `os.makedirs(os.path.dirname(p), exist_ok=True)`
- `app/collab/hub.py:1414` `open` — `with open(p, "wb") as f:`
- `app/collab/hub.py:1519` `os.path.isfile` — `if not os.path.isfile(p):`
- `app/collab/hub.py:1521` `open` — `with open(p, "rb") as f:`
- `app/collab/hub.py:1533` `os.path.isfile` — `if not os.path.isfile(p):`
- `app/collab/hub.py:1535` `open` — `with open(p, "rb") as f:`
- `app/collab/hub.py:1545` `os.path.isfile` — `if not os.path.isfile(p):`
- `app/collab/hub.py:1547` `open` — `with open(p, "rb") as f:`

#### `app/collab/hubclient.py`

- `app/collab/hubclient.py:105` `os.path.getsize` — `size = os.path.getsize(path)`
- `app/collab/hubclient.py:107` `open` — `with open(path, "rb") as f:`
- `app/collab/hubclient.py:117` `open` — `with open(path, "rb") as f:`
- `app/collab/hubclient.py:134` `open` — `with self.session() as s, open(tmp, "wb") as f:`
- `app/collab/hubclient.py:147` `os.replace` — `os.replace(tmp, dest)`

#### `app/collab/relay.py`

- `app/collab/relay.py:34` `os.path.abspath` — `WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")`
- `app/collab/relay.py:41` `os.path.abspath` — `d = os.path.abspath(data_dir or HUB_DIR)`
- `app/collab/relay.py:124` `os.path.isfile` — `if not (cert and key and os.path.isfile(cert) and os.path.isfile(key)):`
- `app/collab/relay.py:124` `os.path.isfile` — `if not (cert and key and os.path.isfile(cert) and os.path.isfile(key)):`
- `app/collab/relay.py:211` `os.path.abspath` — `os.path.abspath(data_dir or HUB_DIR))`

#### `app/collab/relaycore.py`

- `app/collab/relaycore.py:344` `os.path.realpath` — `base = os.path.realpath(base)`
- `app/collab/relaycore.py:345` `os.path.realpath` — `full = os.path.realpath(os.path.join(base, path.lstrip("/\\")))`

#### `app/columns.py`

- `app/columns.py:254` `open` — `with open(path, "w", encoding="utf-8") as f:`

#### `app/convert.py`

- `app/convert.py:26` `os.makedirs` — `os.makedirs(out_dir, exist_ok=True)`

#### `app/cost_rollup.py`

- `app/cost_rollup.py:96` `open` — `with open(path, "w", newline="", encoding="utf-8") as f:`

#### `app/costbook.py`

- `app/costbook.py:49` `os.makedirs` — `os.makedirs(path, exist_ok=True)`
- `app/costbook.py:286` `open` — `with open(path, encoding="utf-8") as f:`
- `app/costbook.py:295` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/costbook.py:297` `os.replace` — `os.replace(tmp, path)`
- `app/costbook.py:673` `os.path.abspath` — `SHIPPED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `app/costbook.py:701` `os.path.isdir` — `if not os.path.isdir(SHIPPED):`
- `app/costbook.py:707` `os.listdir` — `for n in sorted(os.listdir(SHIPPED)):`
- `app/costbook.py:711` `open` — `with open(os.path.join(SHIPPED, n), encoding="utf-8") as f:`

#### `app/costlayer_ui.py`

- `app/costlayer_ui.py:34` `os.path.exists` — `return p if p and os.path.exists(p) else ""`
- `app/costlayer_ui.py:130` `shutil.copyfile` — `shutil.copyfile(src, path)`
- `app/costlayer_ui.py:417` `open` — `with open(p, "w", encoding="utf-8") as f:`

#### `app/count_library.py`

- `app/count_library.py:54` `os.path.abspath` — `p = os.path.normcase(os.path.abspath(p or path()))`
- `app/count_library.py:55` `os.path.abspath` — `return not p.startswith(os.path.normcase(os.path.abspath(settings.DIR)))`
- `app/count_library.py:61` `open` — `with open(p, "r", encoding="utf-8") as f:`
- `app/count_library.py:75` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `app/count_library.py:82` `os.replace` — `os.replace(tmp, p)`
- `app/count_library.py:85` `os.remove` — `os.remove(tmp)`

#### `app/crashreport.py`

- `app/crashreport.py:83` `open` — `with open(p, "rb") as f:`
- `app/crashreport.py:112` `os.listdir` — `names = sorted(n for n in os.listdir(d) if n.startswith("crash-")`
- `app/crashreport.py:115` `os.remove` — `os.remove(os.path.join(d, n))`
- `app/crashreport.py:126` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/crashreport.py:133` `open` — `with open(path, "w", encoding="utf-8") as f:`
- `app/crashreport.py:163` `os.path.getsize` — `size = os.path.getsize(crash_log)`
- `app/crashreport.py:169` `open` — `with open(seen_p, encoding="utf-8") as f:`
- `app/crashreport.py:178` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/crashreport.py:179` `open` — `with open(seen_p, "w", encoding="utf-8") as f:`
- `app/crashreport.py:185` `open` — `with open(crash_log, "rb") as f:`
- `app/crashreport.py:234` `os.listdir` — `names = sorted((n for n in os.listdir(d) if n.startswith("crash-")`
- `app/crashreport.py:245` `open` — `with open(path, encoding="utf-8", errors="replace") as f:`

#### `app/dashboard.py`

- `app/dashboard.py:377` `os.path.abspath` — `folder = os.path.abspath(folder)`
- `app/dashboard.py:378` `os.path.isdir` — `if not os.path.isdir(folder):`
- `app/dashboard.py:391` `os.stat` — `st = os.stat(path)`
- `app/dashboard.py:401` `open` — `with open(path, encoding="utf-8") as f:`
- `app/dashboard.py:709` `os.path.abspath` — `return os.path.normcase(os.path.abspath(f))`
- `app/dashboard.py:730` `os.path.abspath` — `files = [(j, os.path.normcase(os.path.abspath(j["file"])))`
- `app/dashboard.py:771` `os.path.abspath` — `bids += _apply_project(job, os.path.abspath(f), data, warnings)`
- `app/dashboard.py:797` `os.path.abspath` — `k = os.path.normcase(os.path.abspath(r["job"]))`
- `app/dashboard.py:805` `os.path.abspath` — `f = os.path.normcase(os.path.abspath(j["file"])) if j.get("file") \`
- `app/dashboard.py:807` `os.path.abspath` — `d = os.path.normcase(os.path.abspath(j["folder"])).rstrip(os.sep) + \`
- `app/dashboard.py:1222` `os.path.abspath` — `have.append(os.path.abspath(f))`
- `app/dashboard.py:1543` `os.makedirs` — `os.makedirs(os.path.dirname(os.path.abspath(path)) or ".",`
- `app/dashboard.py:1543` `os.path.abspath` — `os.makedirs(os.path.dirname(os.path.abspath(path)) or ".",`
- `app/dashboard.py:1708` `os.makedirs` — `os.makedirs(os.path.dirname(os.path.abspath(path)) or ".",`
- `app/dashboard.py:1708` `os.path.abspath` — `os.makedirs(os.path.dirname(os.path.abspath(path)) or ".",`

#### `app/dashboard_ui.py`

- `app/dashboard_ui.py:739` `os.path.isdir` — `if not j or not j.get("folder") or not os.path.isdir(j["folder"]):`
- `app/dashboard_ui.py:802` `open` — `with open(path, "w", newline="", encoding="utf-8") as f:`
- `app/dashboard_ui.py:827` `os.listdir` — `subs = [os.path.join(f, n) for n in sorted(os.listdir(f))`
- `app/dashboard_ui.py:828` `os.path.isdir` — `if os.path.isdir(os.path.join(f, n)) and`
- `app/dashboard_ui.py:829` `os.path.isfile` — `os.path.isfile(db.project_file(os.path.join(f, n)))]`

#### `app/databackup.py`

- `app/databackup.py:60` `os.path.isdir` — `if os.path.isdir(bo):`
- `app/databackup.py:66` `os.path.abspath` — `low = os.path.abspath(path).lower()`
- `app/databackup.py:85` `open` — `with open(path, "rb") as f:`
- `app/databackup.py:105` `os.walk` — `for dirpath, dirs, files in os.walk(root):`
- `app/databackup.py:125` `os.replace` — `os.replace(part, out_path)`
- `app/databackup.py:127` `shutil.rmtree` — `shutil.rmtree(tmpdir, ignore_errors=True)`
- `app/databackup.py:128` `os.path.exists` — `if os.path.exists(part):`
- `app/databackup.py:130` `os.remove` — `os.remove(part)`
- `app/databackup.py:133` `os.path.getsize` — `return {"files": n, "bytes": os.path.getsize(out_path)}`
- `app/databackup.py:151` `os.path.abspath` — `os.path.abspath(zip_path)), f"QuantiSheet data before restore "`
- `app/databackup.py:153` `os.path.isdir` — `make(safety, [(k, v) for k, v in targets.items() if os.path.isdir(v)])`
- `app/databackup.py:166` `os.makedirs` — `os.makedirs(os.path.dirname(dest), exist_ok=True)`
- `app/databackup.py:167` `open` — `with z.open(info) as src, open(dest + ".restoring", "wb") as f:`
- `app/databackup.py:169` `os.replace` — `os.replace(dest + ".restoring", dest)`
- `app/databackup.py:191` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `app/databackup.py:197` `os.listdir` — `old = sorted(f for f in os.listdir(folder)`
- `app/databackup.py:202` `os.remove` — `os.remove(os.path.join(folder, f))`

#### `app/diagnostics.py`

- `app/diagnostics.py:87` `os.path.exists` — `"reachable": os.path.exists(p)}`
- `app/diagnostics.py:103` `os.path.isdir` — `u = shutil.disk_usage(settings.DIR if os.path.isdir(settings.DIR)`
- `app/diagnostics.py:103` `shutil.disk_usage` — `u = shutil.disk_usage(settings.DIR if os.path.isdir(settings.DIR)`
- `app/diagnostics.py:121` `os.path.isfile` — `if os.path.isfile(p):`
- `app/diagnostics.py:178` `open` — `with open(p, "rb") as f:`

#### `app/docks.py`

- `app/docks.py:408` `open` — `with open(path, "w", newline="", encoding="utf-8-sig") as f:`
- `app/docks.py:1626` `os.stat` — `st = st or os.stat(path)`
- `app/docks.py:1631` `os.path.abspath` — `key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)`
- `app/docks.py:1645` `os.stat` — `st = st or os.stat(path)`
- `app/docks.py:1650` `os.path.abspath` — `return _PAGE_COUNTS.get((os.path.abspath(path), st.st_mtime_ns,`
- `app/docks.py:1656` `entry.stat (DirEntry or Path stat)` — `return entry.stat()`
- `app/docks.py:1759` `os.stat` — `st = os.stat(path)`
- `app/docks.py:1767` `os.path.abspath` — `key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)`
- `app/docks.py:1868` `os.path.isdir` — `if not os.path.isdir(self.folder): # share offline, drive gone`
- `app/docks.py:1927` `os.scandir` — `with os.scandir(folder) as it:`

#### `app/dropbox_sync.py`

- `app/dropbox_sync.py:145` `os.path.abspath` — `p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `app/dropbox_sync.py:148` `open` — `with open(p, encoding="utf-8") as f:`
- `app/dropbox_sync.py:255` `open` — `with open(path, "rb") as f:`
- `app/dropbox_sync.py:314` `os.path.abspath` — `root = os.path.normcase(os.path.abspath(work_root())) + os.sep`
- `app/dropbox_sync.py:315` `os.path.abspath` — `return os.path.normcase(os.path.abspath(local)).startswith(root)`
- `app/dropbox_sync.py:320` `os.path.abspath` — `return os.path.normcase(os.path.abspath(local))`
- `app/dropbox_sync.py:334` `open` — `with open(sidecar_path(local), encoding="utf-8") as f:`
- `app/dropbox_sync.py:345` `os.path.abspath` — `rec = {"local": os.path.abspath(local), "local_key": _key(local),`
- `app/dropbox_sync.py:353` `os.makedirs` — `os.makedirs(os.path.dirname(p), exist_ok=True)`
- `app/dropbox_sync.py:355` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/dropbox_sync.py:357` `os.replace` — `os.replace(tmp, p)`
- `app/dropbox_sync.py:363` `os.remove` — `os.remove(sidecar_path(local))`
- `app/dropbox_sync.py:381` `open` — `with open(p, "rb") as f:`
- `app/dropbox_sync.py:403` `os.makedirs` — `os.makedirs(os.path.dirname(p), exist_ok=True)`
- `app/dropbox_sync.py:407` `open` — `with open(tmp, "wb") as f:`
- `app/dropbox_sync.py:412` `os.remove` — `os.remove(tmp)`
- `app/dropbox_sync.py:415` `os.open` — `fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)`
- `app/dropbox_sync.py:419` `os.chmod` — `os.chmod(tmp, 0o600)`
- `app/dropbox_sync.py:422` `os.replace` — `os.replace(tmp, p)`
- `app/dropbox_sync.py:428` `os.remove` — `os.remove(os.path.join(settings.DIR, name))`
- `app/dropbox_sync.py:804` `os.makedirs` — `os.makedirs(os.path.dirname(dest), exist_ok=True)`
- `app/dropbox_sync.py:809` `open` — `with open(part, "wb") as f:`
- `app/dropbox_sync.py:825` `os.replace` — `os.replace(part, dest)`
- `app/dropbox_sync.py:828` `os.remove` — `os.remove(part)`
- `app/dropbox_sync.py:853` `os.path.getsize` — `size = os.path.getsize(local)`
- `app/dropbox_sync.py:855` `open` — `with open(local, "rb") as f:`
- `app/dropbox_sync.py:917` `os.path.isfile` — `if not os.path.isfile(local):`
- `app/dropbox_sync.py:929` `os.path.isfile` — `if os.path.isfile(local) and not replace_local and \`

#### `app/dropbox_ui.py`

- `app/dropbox_ui.py:553` `os.path.abspath` — `if p and os.path.normcase(os.path.abspath(p)) == \`
- `app/dropbox_ui.py:554` `os.path.abspath` — `os.path.normcase(os.path.abspath(local)):`
- `app/dropbox_ui.py:830` `os.path.isfile` — `if not os.path.isfile(local):`

#### `app/energy.py`

- `app/energy.py:17` `os.path.abspath` — `FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `app/energy.py:52` `open` — `with open(FILE, encoding="utf-8") as f:`

#### `app/esign.py`

- `app/esign.py:127` `open` — `with open(path, "rb") as f:`
- `app/esign.py:165` `open` — `with open(_reg_path(), encoding="utf-8") as f:`
- `app/esign.py:172` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `app/esign.py:174` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/esign.py:176` `os.replace` — `os.replace(tmp, _reg_path())`
- `app/esign.py:190` `os.path.isfile` — `if not os.path.isfile(path):`
- `app/esign.py:210` `os.path.abspath` — `env = {"provider": provider, "path": os.path.abspath(path),`
- `app/esign.py:384` `os.remove` — `os.remove(tmp)`
- `app/esign.py:387` `os.replace` — `os.replace(tmp, out_path)`
- `app/esign.py:389` `os.replace` — `os.replace(tmp, out_path)`

#### `app/esign_docusign.py`

- `app/esign_docusign.py:95` `open` — `with open(path, "rb") as fh:`
- `app/esign_docusign.py:151` `open` — `with open(out_path, "wb") as f:`

#### `app/estimate.py`

- `app/estimate.py:257` `open` — `with open(path, "w", newline="", encoding="utf-8-sig") as f:`

#### `app/estimate_export.py`

- `app/estimate_export.py:204` `open` — `with open(path, "w", newline="", encoding="utf-8-sig") as f:`
- `app/estimate_export.py:503` `open` — `with open(path, "w", newline="", encoding="utf-8-sig") as f:`

#### `app/estimate_layouts.py`

- `app/estimate_layouts.py:392` `open` — `with open(path, "w", encoding="utf-8") as f:`
- `app/estimate_layouts.py:401` `open` — `with open(path, encoding="utf-8") as f:`

#### `app/estimating/_io.py`

- `app/estimating/_io.py:21` `os.path.abspath` — `APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `app/estimating/_io.py:43` `os.path.realpath` — `return os.path.normcase(os.path.realpath(p))`
- `app/estimating/_io.py:71` `os.path.abspath` — `p = os.path.abspath(os.path.join(base, *[str(x) for x in parts]))`
- `app/estimating/_io.py:84` `os.path.isfile` — `if not os.path.isfile(path):`
- `app/estimating/_io.py:90` `os.makedirs` — `os.makedirs(os.path.dirname(dest), exist_ok=True)`
- `app/estimating/_io.py:93` `shutil.copyfile` — `shutil.copyfile(path, tmp)`
- `app/estimating/_io.py:94` `os.replace` — `os.replace(tmp, dest)`
- `app/estimating/_io.py:97` `os.remove` — `os.remove(tmp)`
- `app/estimating/_io.py:116` `os.path.abspath` — `p = os.path.abspath(os.path.expanduser(str(path)))`
- `app/estimating/_io.py:141` `os.makedirs` — `os.makedirs(os.path.dirname(p) or ".", exist_ok=True)`
- `app/estimating/_io.py:147` `open` — `with open(path, encoding="utf-8") as f:`
- `app/estimating/_io.py:154` `os.makedirs` — `os.makedirs(os.path.dirname(p) or ".", exist_ok=True)`
- `app/estimating/_io.py:167` `os.replace` — `os.replace(tmp, p)`
- `app/estimating/_io.py:170` `os.remove` — `os.remove(tmp)`
- `app/estimating/_io.py:187` `open` — `with open(path, "rb") as f:`

#### `app/estimating/actuals.py`

- `app/estimating/actuals.py:341` `os.path.isfile` — `if not os.path.isfile(path):`

#### `app/estimating/assembly_rules.py`

- `app/estimating/assembly_rules.py:156` `open` — `with open(assemblies.LIBRARY_PATH, encoding="utf-8") as f:`

#### `app/estimating/bidgate_ui.py`

- `app/estimating/bidgate_ui.py:63` `open` — `with open(path, "w", newline="", encoding="utf-8") as f:`

#### `app/estimating/boq.py`

- `app/estimating/boq.py:98` `os.path.isfile` — `if not os.path.isfile(p):`
- `app/estimating/boq.py:104` `os.path.isfile` — `if pricedb.is_shared(p) and os.path.isfile(cache):`
- `app/estimating/boq.py:357` `os.path.isfile` — `if not os.path.isfile(p):`

#### `app/estimating/levelboard.py`

- `app/estimating/levelboard.py:133` `open` — `with open(path, "w", newline="", encoding="utf-8") as f:`

#### `app/estimating/quote_pdf.py`

- `app/estimating/quote_pdf.py:119` `os.path.isfile` — `if logo and os.path.isfile(logo):`

#### `app/estimating/quotes.py`

- `app/estimating/quotes.py:336` `os.replace` — `os.replace(tmp, p)`
- `app/estimating/quotes.py:339` `os.remove` — `os.remove(tmp)`
- `app/estimating/quotes.py:438` `os.path.isfile` — `if logo and os.path.isfile(logo):`
- `app/estimating/quotes.py:476` `os.path.isfile` — `if photo and os.path.isfile(photo):`
- `app/estimating/quotes.py:571` `os.replace` — `os.replace(tmp, p)`
- `app/estimating/quotes.py:574` `os.remove` — `os.remove(tmp)`

#### `app/estimating/safedb.py`

- `app/estimating/safedb.py:45` `os.path.isfile` — `return os.path.isfile(path())`
- `app/estimating/safedb.py:95` `os.path.abspath` — `p = os.path.abspath(p).replace("\\", "/")`
- `app/estimating/safedb.py:114` `open` — `with open(heavy.STARTER, encoding="utf-8") as f:`
- `app/estimating/safedb.py:155` `os.path.isfile` — `if os.path.isfile(p):`
- `app/estimating/safedb.py:160` `os.path.isfile` — `if pricedb.is_shared(p) and os.path.isfile(cache):`
- `app/estimating/safedb.py:193` `os.path.isfile` — `if not os.path.isfile(p):`
- `app/estimating/safedb.py:198` `os.makedirs` — `os.makedirs(os.path.dirname(dest), exist_ok=True)`
- `app/estimating/safedb.py:207` `os.replace` — `os.replace(tmp, dest)`
- `app/estimating/safedb.py:210` `os.remove` — `os.remove(tmp)`

#### `app/estimating/service.py`

- `app/estimating/service.py:223` `os.path.isfile` — `if not os.path.isfile(p):`

#### `app/estimating/starters.py`

- `app/estimating/starters.py:291` `os.path.exists` — `if os.path.exists(p):`

#### `app/estimating/supplier_prices.py`

- `app/estimating/supplier_prices.py:141` `os.path.exists` — `if os.path.exists(p):`

#### `app/estimating/templates.py`

- `app/estimating/templates.py:143` `os.path.isdir` — `if not os.path.isdir(where):`
- `app/estimating/templates.py:145` `os.listdir` — `for f in sorted(os.listdir(where)):`

#### `app/estimating/ui.py`

- `app/estimating/ui.py:787` `os.path.exists` — `overwrite=os.path.exists(p))`

#### `app/estimating/workbook_pricer.py`

- `app/estimating/workbook_pricer.py:120` `os.path.exists` — `while os.path.exists(p):`
- `app/estimating/workbook_pricer.py:135` `os.path.abspath` — `if os.path.exists(p) or os.path.abspath(p) == os.path.abspath(path):`
- `app/estimating/workbook_pricer.py:135` `os.path.abspath` — `if os.path.exists(p) or os.path.abspath(p) == os.path.abspath(path):`
- `app/estimating/workbook_pricer.py:135` `os.path.exists` — `if os.path.exists(p) or os.path.abspath(p) == os.path.abspath(path):`
- `app/estimating/workbook_pricer.py:173` `os.makedirs` — `os.makedirs(os.path.dirname(p) or ".", exist_ok=True)`
- `app/estimating/workbook_pricer.py:177` `os.path.exists` — `if os.path.exists(p):`
- `app/estimating/workbook_pricer.py:180` `os.replace` — `os.replace(tmp, p)`
- `app/estimating/workbook_pricer.py:183` `os.path.exists` — `if os.path.exists(tmp):`
- `app/estimating/workbook_pricer.py:184` `os.remove` — `os.remove(tmp)`

#### `app/filedialogs.py`

- `app/filedialogs.py:33` `os.path.isdir` — `d = first if os.path.isdir(first) else os.path.dirname(first)`
- `app/filedialogs.py:34` `os.path.isdir` — `if d and os.path.isdir(d) and not settings._is_temp(d):`
- `app/filedialogs.py:45` `os.path.abspath` — `p = os.path.abspath(first)`
- `app/filedialogs.py:53` `os.path.isfile` — `return [p for p in SAVED if os.path.isfile(p)]`

#### `app/formlib.py`

- `app/formlib.py:31` `os.makedirs` — `os.makedirs(path, exist_ok=True)`
- `app/formlib.py:41` `open` — `with open(_index_path(), encoding="utf-8") as f:`
- `app/formlib.py:50` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/formlib.py:52` `os.replace` — `os.replace(tmp, _index_path())`
- `app/formlib.py:82` `os.walk` — `for dp, _dn, fn in os.walk(root):`
- `app/formlib.py:103` `os.path.exists` — `if os.path.exists(os.path.join(root, e["file"]))]`
- `app/formlib.py:125` `os.makedirs` — `os.makedirs(dest_dir, exist_ok=True)`
- `app/formlib.py:128` `os.path.exists` — `while os.path.exists(dest):`
- `app/formlib.py:133` `shutil.copyfile` — `shutil.copyfile(path, dest)`
- `app/formlib.py:140` `os.makedirs` — `os.makedirs(keep, exist_ok=True)`
- `app/formlib.py:142` `shutil.copyfile` — `shutil.copyfile(path, source)`
- `app/formlib.py:166` `os.makedirs` — `os.makedirs(new_dir, exist_ok=True)`
- `app/formlib.py:168` `shutil.move` — `shutil.move(os.path.join(folder(), e["file"]), new)`
- `app/formlib.py:185` `os.remove` — `os.remove(os.path.join(folder(), e["file"]))`
- `app/formlib.py:196` `open` — `with open(path_of(entry), "rb") as f:`

#### `app/formlib_ui.py`

- `app/formlib_ui.py:188` `os.walk` — `for dp, _dn, fn in os.walk(path):`

#### `app/genset/build.py`

- `app/genset/build.py:269` `os.path.abspath` — `out_path = os.path.abspath(out_path)`
- `app/genset/build.py:275` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/genset/build.py:278` `os.replace` — `os.replace(tmp, side)`
- `app/genset/build.py:281` `os.path.exists` — `if os.path.exists(tmp):`
- `app/genset/build.py:283` `os.remove` — `os.remove(tmp)`

#### `app/genset/draw.py`

- `app/genset/draw.py:36` `os.path.isfile` — `if os.path.isfile(reg) and os.path.isfile(bold):`
- `app/genset/draw.py:36` `os.path.isfile` — `if os.path.isfile(reg) and os.path.isfile(bold):`

#### `app/genset/quantities.py`

- `app/genset/quantities.py:193` `open` — `with open(path, "w", newline="", encoding="utf-8") as f:`

#### `app/geoexport.py`

- `app/geoexport.py:73` `open` — `with open(path, "w", encoding="utf-8") as f:`
- `app/geoexport.py:103` `open` — `with open(path, "w", encoding="utf-8") as f:`

#### `app/heavy.py`

- `app/heavy.py:32` `os.path.abspath` — `STARTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `app/heavy.py:77` `open` — `with open(STARTER, encoding="utf-8") as f:`
- `app/heavy.py:801` `open` — `with open(tmp, "rb") as f:`
- `app/heavy.py:803` `os.remove` — `os.remove(tmp)`
- `app/heavy.py:1018` `open` — `with open(tmp, "rb") as f:`
- `app/heavy.py:1020` `os.remove` — `os.remove(tmp)`

#### `app/history.py`

- `app/history.py:141` `open` — `with open("/proc/meminfo") as f:`

#### `app/invite_boost.py`

- `app/invite_boost.py:103` `os.path.abspath` — `p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `app/invite_boost.py:106` `open` — `with open(p, encoding="utf-8") as fh:`
- `app/invite_boost.py:278` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `app/invite_boost.py:292` `os.listdir` — `n = len([f for f in os.listdir(self.folder) if f.endswith(".eml")])`
- `app/invite_boost.py:295` `open` — `with open(path, "wb") as f:`
- `app/invite_boost.py:297` `open` — `with open(os.path.join(self.folder, "log.jsonl"), "a",`

#### `app/issue_report.py`

- `app/issue_report.py:41` `os.path.isfile` — `if path and os.path.isfile(path):`
- `app/issue_report.py:42` `os.path.getsize` — `out["file_mb"] = round(os.path.getsize(path) / 1e6, 1)`
- `app/issue_report.py:82` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `app/issue_report.py:99` `os.remove` — `os.remove(bundle)`
- `app/issue_report.py:105` `open` — `with open(shot, "wb") as f:`
- `app/issue_report.py:108` `os.path.isfile` — `if attach_doc and doc_path and os.path.isfile(doc_path) and \`
- `app/issue_report.py:109` `os.path.getsize` — `os.path.getsize(doc_path) <= MAX_ATTACH_MB * 1e6:`

#### `app/issue_report_ui.py`

- `app/issue_report_ui.py:56` `os.path.isfile` — `if self.doc_path and os.path.isfile(self.doc_path):`
- `app/issue_report_ui.py:57` `os.path.getsize` — `mb = os.path.getsize(self.doc_path) / 1e6`

#### `app/jobinfo.py`

- `app/jobinfo.py:74` `os.path.getsize` — `size = os.path.getsize(path)`
- `app/jobinfo.py:82` `open` — `with open(path, "rb") as f:`
- `app/jobinfo.py:94` `open` — `with open(path, "rb") as f:`

#### `app/jobsafe.py`

- `app/jobsafe.py:96` `os.path.abspath` — `p = os.path.normcase(os.path.abspath(path))`
- `app/jobsafe.py:110` `os.path.abspath` — `rec = {"file": os.path.abspath(path), "name": os.path.basename(path),`
- `app/jobsafe.py:115` `os.makedirs` — `os.makedirs(_dir(), exist_ok=True)`
- `app/jobsafe.py:126` `open` — `with open(backup_path(path), encoding="utf-8") as f:`
- `app/jobsafe.py:135` `os.listdir` — `for fn in os.listdir(_dir()):`
- `app/jobsafe.py:139` `open` — `with open(os.path.join(_dir(), fn), encoding="utf-8") as f:`
- `app/jobsafe.py:180` `os.path.abspath` — `p = os.path.abspath(path)`
- `app/jobsafe.py:197` `os.path.abspath` — `d, n = os.path.split(os.path.abspath(path))`
- `app/jobsafe.py:216` `open` — `with open(lp, encoding="utf-8") as f:`
- `app/jobsafe.py:238` `open` — `with open(lp, "w", encoding="utf-8") as f:`
- `app/jobsafe.py:255` `open` — `with open(lp, encoding="utf-8") as f:`
- `app/jobsafe.py:260` `os.remove` — `os.remove(lp)`
- `app/jobsafe.py:270` `os.stat` — `st = os.stat(path)`

#### `app/locfactors.py`

- `app/locfactors.py:45` `os.listdir` — `names = sorted(n for n in os.listdir(SHIPPED)`
- `app/locfactors.py:54` `os.path.getmtime` — `mtime = os.path.getmtime(path)`
- `app/locfactors.py:61` `open` — `with open(path, encoding="utf-8") as f:`

#### `app/macros.py`

- `app/macros.py:58` `open` — `with open(path, "w", encoding="utf-8") as f:`
- `app/macros.py:85` `open` — `with open(path, encoding="utf-8") as f:`

#### `app/mail.py`

- `app/mail.py:93` `os.path.abspath` — `item.Attachments.Add(os.path.abspath(path))`
- `app/mail.py:141` `open` — `with open(p, "rb") as f:`
- `app/mail.py:149` `open` — `with open(path, "wb") as f:`
- `app/mail.py:174` `os.path.isfile` — `if not os.path.isfile(p):`
- `app/mail.py:198` `os.startfile` — `os.startfile(path) # type: ignore[attr-defined]`

#### `app/main.py`

- `app/main.py:43` `os.makedirs` — `os.makedirs(log_dir, exist_ok=True)`
- `app/main.py:45` `open` — `with open(probe, "w") as f:`
- `app/main.py:47` `os.remove` — `os.remove(probe)`
- `app/main.py:50` `os.makedirs` — `os.makedirs(log_dir, exist_ok=True)`
- `app/main.py:53` `os.path.exists` — `if os.path.exists(path) and os.path.getsize(path) > 2_000_000:`
- `app/main.py:53` `os.path.getsize` — `if os.path.exists(path) and os.path.getsize(path) > 2_000_000:`
- `app/main.py:54` `os.replace` — `os.replace(path, path + ".old")`
- `app/main.py:59` `os.path.exists` — `if os.path.exists(crash) and os.path.getsize(crash) > 2_000_000:`
- `app/main.py:59` `os.path.getsize` — `if os.path.exists(crash) and os.path.getsize(crash) > 2_000_000:`
- `app/main.py:60` `os.replace` — `os.replace(crash, crash + ".old") # same limit as the log`
- `app/main.py:61` `open` — `_setup_logging.crash_file = open(crash, "a", encoding="utf-8")`
- `app/main.py:141` `os.path.exists` — `and os.path.exists(a)]`
- `app/main.py:217` `open` — `with open(out, "w", encoding="utf-8") as f:`
- `app/main.py:313` `shutil.rmtree` — `shutil.rmtree(d, ignore_errors=True)`
- `app/main.py:327` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `app/main.py:423` `open` — `with open(out_path, "w", encoding="utf-8") as f:`
- `app/main.py:471` `os.path.isfile` — `if logo and not os.path.isfile(logo):`
- `app/main.py:521` `os.path.abspath` — `os.path.dirname(os.path.abspath(__file__)))`
- `app/main.py:523` `os.path.isfile` — `if not os.path.isfile(path):`
- `app/main.py:547` `os.path.abspath` — `os.path.dirname(os.path.abspath(__file__)))`
- `app/main.py:553` `os.path.exists` — `if os.path.exists(path):`

#### `app/main_window.py`

- `app/main_window.py:109` `os.replace` — `os.replace(tmp, path)`
- `app/main_window.py:115` `open` — `with open(tmp, "rb") as src, open(path, "r+b") as dst:`
- `app/main_window.py:115` `open` — `with open(tmp, "rb") as src, open(path, "r+b") as dst:`
- `app/main_window.py:120` `os.remove` — `os.remove(tmp)`
- `app/main_window.py:168` `os.remove` — `os.remove(p)`
- `app/main_window.py:2772` `os.listdir` — `if os.listdir(folder):`
- `app/main_window.py:2774` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `app/main_window.py:2818` `open` — `with open(path, "rb") as f:`
- `app/main_window.py:2904` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/main_window.py:3257` `os.path.abspath` — `os.path.dirname(os.path.abspath(__file__))), "quantisheet.py"),`
- `app/main_window.py:3729` `os.path.abspath` — `path = os.path.join(os.path.dirname(os.path.abspath(__file__)),`
- `app/main_window.py:3731` `os.path.isfile` — `if not os.path.isfile(path):`
- `app/main_window.py:4181` `os.path.isfile` — `if new and os.path.isfile(path) and QMessageBox.question(`
- `app/main_window.py:4189` `os.startfile` — `os.startfile(path) # noqa: S606 (Windows)`
- `app/main_window.py:4370` `os.path.abspath` — `path = os.path.abspath(path)`
- `app/main_window.py:4600` `os.path.abspath` — `same = bool(doc.name) and os.path.abspath(doc.name) == os.path.abspath(path)`
- `app/main_window.py:4600` `os.path.abspath` — `same = bool(doc.name) and os.path.abspath(doc.name) == os.path.abspath(path)`
- `app/main_window.py:4651` `os.replace` — `os.replace(tmp, path)`
- `app/main_window.py:4798` `shutil.copyfile` — `shutil.copyfile(item["pdf"], tmp)`
- `app/main_window.py:4853` `os.path.abspath` — `os.path.abspath(v.doc.name) == os.path.abspath(path)`
- `app/main_window.py:4853` `os.path.abspath` — `os.path.abspath(v.doc.name) == os.path.abspath(path)`
- `app/main_window.py:5078` `os.path.abspath` — `if self._path and os.path.abspath(path) == \`
- `app/main_window.py:5079` `os.path.abspath` — `os.path.abspath(self._path):`
- `app/main_window.py:5681` `os.path.exists` — `if os.path.exists(path):`
- `app/main_window.py:5901` `os.path.isfile` — `src = doc.name if (doc.name and os.path.isfile(doc.name) and`
- `app/main_window.py:6472` `os.path.abspath` — `d = os.path.dirname(os.path.abspath(self._path))`
- `app/main_window.py:6944` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(`
- `app/main_window.py:7214` `os.path.isfile` — `if not path or not os.path.isfile(path):`
- `app/main_window.py:7552` `os.path.exists` — `if os.path.exists(out):`
- `app/main_window.py:7808` `os.path.abspath` — `d = os.path.dirname(os.path.abspath(self._path))`
- `app/main_window.py:7829` `os.path.abspath` — `d = os.path.dirname(os.path.abspath(self._path))`
- `app/main_window.py:7859` `os.path.abspath` — `d = os.path.dirname(os.path.abspath(path))`

#### `app/master_hook.py`

- `app/master_hook.py:96` `os.path.abspath` — `d = os.path.dirname(os.path.abspath(path))`
- `app/master_hook.py:113` `os.path.abspath` — `here = os.path.dirname(os.path.abspath(path)) if path else ""`

#### `app/name_memory.py`

- `app/name_memory.py:60` `open` — `with open(path(), "r", encoding="utf-8") as f:`
- `app/name_memory.py:74` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `app/name_memory.py:80` `os.replace` — `os.replace(tmp, p)`
- `app/name_memory.py:83` `os.remove` — `os.remove(tmp)`

#### `app/ocr.py`

- `app/ocr.py:25` `os.path.exists` — `if os.path.exists(cand):`
- `app/ocr.py:29` `os.path.exists` — `if os.path.exists(cand):`
- `app/ocr.py:32` `os.path.abspath` — `here = os.path.normcase(os.path.abspath(os.getcwd()))`
- `app/ocr.py:33` `os.path.abspath` — `if exe and os.path.normcase(os.path.dirname(os.path.abspath(exe))) \`
- `app/ocr.py:58` `os.unlink` — `os.unlink(tmp)`

#### `app/oldnames.py`

- `app/oldnames.py:192` `os.path.isfile` — `return p if os.path.isfile(p) else None`
- `app/oldnames.py:200` `os.path.exists` — `if not os.path.exists(new) and os.path.isdir(old):`
- `app/oldnames.py:200` `os.path.isdir` — `if not os.path.exists(new) and os.path.isdir(old):`
- `app/oldnames.py:202` `os.rename` — `os.rename(old, new)`
- `app/oldnames.py:216` `os.path.isdir` — `if os.path.isdir(p):`

#### `app/overlay_ui.py`

- `app/overlay_ui.py:187` `os.path.exists` — `if not p or not os.path.exists(p):`

#### `app/owncopy.py`

- `app/owncopy.py:19` `os.path.abspath` — `return os.path.normcase(os.path.abspath(p or ""))`
- `app/owncopy.py:53` `os.path.isfile` — `if not candidate or not os.path.isfile(candidate):`
- `app/owncopy.py:79` `os.path.exists` — `if not a.startswith("-") and os.path.exists(a)]`

#### `app/packaged.py`

- `app/packaged.py:47` `os.path.isfile` — `if not os.path.isfile(exe):`
- `app/packaged.py:51` `os.path.isfile` — `if os.path.isfile(p):`
- `app/packaged.py:87` `os.startfile` — `os.startfile("ms-settings:startupapps") # noqa: S606`

#### `app/packages.py`

- `app/packages.py:168` `open` — `with open(path(), encoding="utf-8") as f:`
- `app/packages.py:177` `os.makedirs` — `os.makedirs(os.path.dirname(path()), exist_ok=True)`

#### `app/packages_live.py`

- `app/packages_live.py:54` `open` — `with open(keys_path(), encoding="utf-8") as f:`
- `app/packages_live.py:68` `os.makedirs` — `os.makedirs(os.path.dirname(keys_path()), exist_ok=True)`

#### `app/panels.py`

- `app/panels.py:341` `open` — `with open(path, "w", newline="", encoding="utf-8-sig") as f:`

#### `app/pdfa.py`

- `app/pdfa.py:44` `os.path.abspath` — `here = os.path.normcase(os.path.abspath(os.getcwd()))`
- `app/pdfa.py:47` `os.path.abspath` — `if p and os.path.normcase(os.path.dirname(os.path.abspath(p))) \`
- `app/pdfa.py:59` `os.path.exists` — `if os.path.exists(p):`
- `app/pdfa.py:60` `open` — `with open(p, "rb") as f:`
- `app/pdfa.py:202` `os.path.exists` — `if p.returncode == 0 and os.path.exists(path):`
- `app/pdfa.py:213` `os.replace` — `os.replace(path + ".tmp", path)`

#### `app/pm/actions.py`

- `app/pm/actions.py:531` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`

#### `app/pm/autoschedule.py`

- `app/pm/autoschedule.py:1348` `os.path.isfile` — `if base and os.path.isfile(base + ".genset.json"):`
- `app/pm/autoschedule.py:1350` `os.path.getsize` — `if os.path.getsize(base + ".genset.json") <= GENSET_MAX_BYTES:`
- `app/pm/autoschedule.py:1351` `open` — `with open(base + ".genset.json", encoding="utf-8") as fh:`
- `app/pm/autoschedule.py:1359` `os.path.isfile` — `if base and os.path.isfile(base + ".quantities.csv"):`
- `app/pm/autoschedule.py:1361` `open` — `with open(base + ".quantities.csv", encoding="utf-8",`

#### `app/pm/bidforms.py`

- `app/pm/bidforms.py:119` `open` — `with open(_lib_path(), encoding="utf-8") as f:`
- `app/pm/bidforms.py:131` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `app/pm/bidforms.py:133` `open` — `with open(_lib_path(), encoding="utf-8") as f:`
- `app/pm/bidforms.py:138` `open` — `with open(_lib_path(), "w", encoding="utf-8") as f:`
- `app/pm/bidforms.py:471` `os.path.abspath` — `key = os.path.normcase(os.path.abspath(f))`
- `app/pm/bidforms.py:472` `os.path.isdir` — `if key in seen or not os.path.isdir(f):`
- `app/pm/bidforms.py:515` `open` — `with open(path, "w", encoding="utf-8", newline="") as f:`

#### `app/pm/bidletters.py`

- `app/pm/bidletters.py:152` `os.remove` — `os.remove(path)`
- `app/pm/bidletters.py:162` `os.makedirs` — `os.makedirs(tmp, exist_ok=True)`

#### `app/pm/center.py`

- `app/pm/center.py:2122` `os.path.isdir` — `recent = [f for f in settings.get("pm_recent", []) if os.path.isdir(f)]`

#### `app/pm/cost.py`

- `app/pm/cost.py:518` `open` — `with open(path, "w", newline="", encoding="utf-8") as f:`

#### `app/pm/docsui.py`

- `app/pm/docsui.py:173` `os.walk` — `for dp, dns, fns in os.walk(root):`
- `app/pm/docsui.py:180` `os.stat` — `st = os.stat(p)`
- `app/pm/docsui.py:191` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/pm/docsui.py:202` `os.path.exists` — `if os.path.exists(dest):`
- `app/pm/docsui.py:258` `os.path.isfile` — `if u.isLocalFile() and os.path.isfile(u.toLocalFile())])`

#### `app/pm/master/apply.py`

- `app/pm/master/apply.py:37` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/pm/master/apply.py:54` `os.path.getsize` — `size = os.path.getsize(path)`
- `app/pm/master/apply.py:64` `open` — `with open(path, "rb") as f:`
- `app/pm/master/apply.py:73` `os.path.exists` — `if not os.path.exists(q):`
- `app/pm/master/apply.py:75` `open` — `with open(tmp, "wb") as f:`
- `app/pm/master/apply.py:77` `os.replace` — `os.replace(tmp, q)`
- `app/pm/master/apply.py:510` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `app/pm/master/apply.py:514` `os.path.exists` — `while os.path.exists(dst):`
- `app/pm/master/apply.py:517` `shutil.move` — `shutil.move(src, dst)`

#### `app/pm/master/drafts.py`

- `app/pm/master/drafts.py:97` `os.path.isfile` — `att = [p for p in draft.get("attachments") or [] if os.path.isfile(p)]`

#### `app/pm/master/dropbox_inbox.py`

- `app/pm/master/dropbox_inbox.py:59` `os.path.realpath` — `k = os.path.normcase(os.path.realpath(store.folder))`
- `app/pm/master/dropbox_inbox.py:69` `open` — `with open(_jpath(store), encoding="utf-8") as f:`
- `app/pm/master/dropbox_inbox.py:80` `os.makedirs` — `os.makedirs(mirror_dir(store), exist_ok=True)`
- `app/pm/master/dropbox_inbox.py:82` `open` — `with open(p + ".tmp", "w", encoding="utf-8") as f:`
- `app/pm/master/dropbox_inbox.py:84` `os.replace` — `os.replace(p + ".tmp", p)`
- `app/pm/master/dropbox_inbox.py:104` `os.path.exists` — `if not os.path.exists(path):`
- `app/pm/master/dropbox_inbox.py:108` `os.path.exists` — `while os.path.exists(f"{base} ({n}){ext}"):`
- `app/pm/master/dropbox_inbox.py:154` `os.path.isfile` — `if os.path.isfile(local):`
- `app/pm/master/dropbox_inbox.py:159` `os.path.isfile` — `if os.path.isfile(os.path.join(folder, sub, name)):`
- `app/pm/master/dropbox_inbox.py:175` `os.path.isfile` — `if os.path.isfile(reason):`
- `app/pm/master/dropbox_inbox.py:237` `os.path.isdir` — `if not os.path.isdir(base):`
- `app/pm/master/dropbox_inbox.py:239` `os.listdir` — `for comp in sorted(os.listdir(base)):`
- `app/pm/master/dropbox_inbox.py:241` `os.path.isdir` — `if not os.path.isdir(ob):`
- `app/pm/master/dropbox_inbox.py:243` `os.listdir` — `for name in sorted(os.listdir(ob)):`
- `app/pm/master/dropbox_inbox.py:245` `os.path.isfile` — `if not os.path.isfile(p) or _skip(name):`
- `app/pm/master/dropbox_inbox.py:247` `os.stat` — `st = os.stat(p)`

#### `app/pm/master/formats/common.py`

- `app/pm/master/formats/common.py:24` `os.path.getsize` — `size = os.path.getsize(path)`
- `app/pm/master/formats/common.py:29` `open` — `with open(path, "rb") as f:`

#### `app/pm/master/formats/excel.py`

- `app/pm/master/formats/excel.py:148` `os.replace` — `os.replace(tmp, path)`
- `app/pm/master/formats/excel.py:173` `os.path.getsize` — `size = os.path.getsize(path)`

#### `app/pm/master/intake.py`

- `app/pm/master/intake.py:31` `os.path.realpath` — `return _STATES.setdefault(os.path.normcase(os.path.realpath(`
- `app/pm/master/intake.py:49` `open` — `with open(path, "rb"):`
- `app/pm/master/intake.py:52` `os.rename` — `os.rename(path, path)`
- `app/pm/master/intake.py:87` `os.makedirs` — `os.makedirs(inbox, exist_ok=True)`
- `app/pm/master/intake.py:89` `os.scandir` — `tops = sorted(os.scandir(inbox), key=lambda e: e.name.lower())`
- `app/pm/master/intake.py:104` `os.scandir` — `files = sorted(os.scandir(top.path), key=lambda e: e.name)`
- `app/pm/master/intake.py:112` `f.stat (DirEntry or Path stat)` — `st = f.stat()`
- `app/pm/master/intake.py:156` `open` — `with open(dst + ".reason.txt", "w", encoding="utf-8") as f:`
- `app/pm/master/intake.py:175` `os.makedirs` — `os.makedirs(d, exist_ok=True)`

#### `app/pm/owner_report.py`

- `app/pm/owner_report.py:379` `open` — `with open(_template_path(), encoding="utf-8") as f:`
- `app/pm/owner_report.py:399` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `app/pm/owner_report.py:401` `os.path.isfile` — `if logo and os.path.isfile(logo):`
- `app/pm/owner_report.py:402` `open` — `with open(logo, "rb") as f:`
- `app/pm/owner_report.py:407` `os.path.abspath` — `if os.path.abspath(logo) != os.path.abspath(dest):`
- `app/pm/owner_report.py:407` `os.path.abspath` — `if os.path.abspath(logo) != os.path.abspath(dest):`
- `app/pm/owner_report.py:408` `os.path.exists` — `if not os.path.exists(dest):`
- `app/pm/owner_report.py:409` `open` — `with open(dest, "wb") as f:`
- `app/pm/owner_report.py:413` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/pm/owner_report.py:415` `os.replace` — `os.replace(tmp, _template_path())`
- `app/pm/owner_report.py:422` `os.path.isfile` — `if logo and os.path.isfile(logo):`
- `app/pm/owner_report.py:423` `open` — `with open(logo, "rb") as f:`
- `app/pm/owner_report.py:436` `os.path.isfile` — `if logo and os.path.isfile(logo):`
- `app/pm/owner_report.py:1215` `os.path.abspath` — `return "path:" + os.path.normcase(os.path.abspath(str(sheet or "")))`
- `app/pm/owner_report.py:3048` `os.makedirs` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `app/pm/owner_report.py:3048` `os.path.abspath` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `app/pm/owner_report.py:3050` `open` — `with open(tmp, "wb") as f:`
- `app/pm/owner_report.py:3052` `os.replace` — `os.replace(tmp, path)`
- `app/pm/owner_report.py:3084` `os.path.isfile` — `if logo and os.path.isfile(logo):`
- `app/pm/owner_report.py:3119` `os.path.getsize` — `bpp = os.path.getsize(path) / float(max(1, iw * ih))`
- `app/pm/owner_report.py:3131` `os.stat` — `st = os.stat(path)`
- `app/pm/owner_report.py:3133` `os.path.abspath` — `key = (os.path.abspath(path), st.st_mtime_ns, st.st_size, preset, rot,`
- `app/pm/owner_report.py:3162` `os.stat` — `st = os.stat(path)`
- `app/pm/owner_report.py:3163` `os.path.abspath` — `key = ("raster", os.path.abspath(path), st.st_mtime_ns, st.st_size,`
- `app/pm/owner_report.py:3288` `os.path.getsize` — `guess = float(os.path.getsize(path))`
- `app/pm/owner_report.py:3323` `os.path.getsize` — `total += os.path.getsize(logo)`

#### `app/pm/owner_report_logs.py`

- `app/pm/owner_report_logs.py:145` `os.path.isdir` — `if base and os.path.isdir(os.path.join(base, "app", "data", "fonts")):`
- `app/pm/owner_report_logs.py:148` `os.path.abspath` — `os.path.abspath(__file__))), "data", "fonts")`
- `app/pm/owner_report_logs.py:158` `open` — `with open(os.path.join(font_dir(), name), "rb") as f:`
- `app/pm/owner_report_logs.py:467` `os.path.abspath` — `key = os.path.abspath(str(path))`
- `app/pm/owner_report_logs.py:485` `os.path.isfile` — `if not path or not os.path.isfile(str(path)):`
- `app/pm/owner_report_logs.py:1611` `os.path.isfile` — `return path if isinstance(path, str) and os.path.isfile(path) else None`

#### `app/pm/photofit.py`

- `app/pm/photofit.py:98` `os.path.getmtime` — `return datetime.fromtimestamp(os.path.getmtime(path)), "file"`
- `app/pm/photofit.py:251` `open` — `with open(path, "rb") as f:`
- `app/pm/photofit.py:259` `os.path.exists` — `if os.path.exists(hit):`
- `app/pm/photofit.py:260` `open` — `with open(hit, "rb") as f:`
- `app/pm/photofit.py:263` `os.makedirs` — `os.makedirs(cache, exist_ok=True)`
- `app/pm/photofit.py:265` `open` — `with open(tmp, "wb") as f:`
- `app/pm/photofit.py:267` `os.replace` — `os.replace(tmp, hit)`

#### `app/pm/productivity.py`

- `app/pm/productivity.py:529` `open` — `with open(path(), encoding="utf-8") as fh:`
- `app/pm/productivity.py:559` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `app/pm/productivity.py:562` `open` — `with open(tmp, "w", encoding="utf-8") as fh:`
- `app/pm/productivity.py:564` `os.replace` — `os.replace(tmp, path())`
- `app/pm/productivity.py:571` `os.remove` — `os.remove(path())`

#### `app/pm/project_backup.py`

- `app/pm/project_backup.py:28` `open` — `with open(path, "rb") as f:`
- `app/pm/project_backup.py:35` `os.walk` — `for base, dirs, files in os.walk(folder):`
- `app/pm/project_backup.py:36` `os.path.islink` — `dirs[:] = sorted(d for d in dirs if not os.path.islink(`
- `app/pm/project_backup.py:40` `os.path.islink` — `if f.endswith(SKIP_SUFFIX) or os.path.islink(p):`
- `app/pm/project_backup.py:48` `os.path.isdir` — `if not os.path.isdir(folder):`
- `app/pm/project_backup.py:56` `os.path.getsize` — `entries[rel] = {"sha256": _sha(p), "size": os.path.getsize(p)}`
- `app/pm/project_backup.py:61` `os.path.abspath` — `"job": os.path.basename(os.path.abspath(folder)),`
- `app/pm/project_backup.py:64` `os.replace` — `os.replace(tmp, out_path)`
- `app/pm/project_backup.py:115` `os.listdir` — `if os.path.exists(target) and os.listdir(target) and not overwrite:`
- `app/pm/project_backup.py:115` `os.path.exists` — `if os.path.exists(target) and os.listdir(target) and not overwrite:`
- `app/pm/project_backup.py:117` `os.path.abspath` — `parent = os.path.dirname(os.path.abspath(target))`
- `app/pm/project_backup.py:118` `os.makedirs` — `os.makedirs(parent, exist_ok=True)`
- `app/pm/project_backup.py:124` `os.makedirs` — `os.makedirs(os.path.dirname(dest), exist_ok=True)`
- `app/pm/project_backup.py:125` `open` — `with z.open(rel) as src, open(dest, "wb") as out:`
- `app/pm/project_backup.py:131` `os.path.exists` — `if os.path.exists(target):`
- `app/pm/project_backup.py:134` `os.replace` — `os.replace(target, keep)`
- `app/pm/project_backup.py:135` `os.replace` — `os.replace(work, target)`
- `app/pm/project_backup.py:139` `os.path.isdir` — `if work and os.path.isdir(work):`
- `app/pm/project_backup.py:140` `shutil.rmtree` — `shutil.rmtree(work, ignore_errors=True)`

#### `app/pm/schedule.py`

- `app/pm/schedule.py:812` `open` — `with open(path, encoding="cp1252", errors="replace") as f:`

#### `app/pm/scheduler.py`

- `app/pm/scheduler.py:1106` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `app/pm/scheduler.py:1146` `os.path.isdir` — `recent = [f for f in settings.get("pm_recent", []) if os.path.isdir(f)`

#### `app/pm/scope_sheet.py`

- `app/pm/scope_sheet.py:912` `os.path.isfile` — `return {"name": name, "logo": logo if logo and os.path.isfile(logo)`
- `app/pm/scope_sheet.py:1367` `os.makedirs` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `app/pm/scope_sheet.py:1367` `os.path.abspath` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `app/pm/scope_sheet.py:1794` `os.makedirs` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `app/pm/scope_sheet.py:1794` `os.path.abspath` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`

#### `app/pm/scope_sheet_ui.py`

- `app/pm/scope_sheet_ui.py:1683` `os.path.isdir` — `if self.store is not None and os.path.isdir(self.store.folder):`
- `app/pm/scope_sheet_ui.py:1858` `os.path.isdir` — `if os.path.isdir(f) and ProjectStore.exists(f)]`
- `app/pm/scope_sheet_ui.py:1911` `os.path.abspath` — `d = os.path.dirname(os.path.abspath(path))`

#### `app/pm/store.py`

- `app/pm/store.py:108` `os.path.abspath` — `self.folder = os.path.abspath(folder)`
- `app/pm/store.py:129` `open` — `with open(self.path, encoding="utf-8") as f:`
- `app/pm/store.py:137` `os.replace` — `os.replace(self.path, bad)`
- `app/pm/store.py:151` `os.path.exists` — `if now or not os.path.exists(self.path):`
- `app/pm/store.py:177` `os.makedirs` — `os.makedirs(os.path.dirname(self.path), exist_ok=True)`
- `app/pm/store.py:179` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/pm/store.py:181` `os.replace` — `os.replace(tmp, self.path)`
- `app/pm/store.py:185` `os.path.abspath` — `path = os.path.join(os.path.abspath(folder), FILE)`
- `app/pm/store.py:190` `os.path.isfile` — `if os.path.isfile(path):`
- `app/pm/store.py:193` `os.path.abspath` — `old = oldnames.job_dir_if_any(os.path.abspath(folder))`
- `app/pm/store.py:194` `os.path.isfile` — `return bool(old) and os.path.isfile(`
- `app/pm/store.py:626` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/pm/store.py:636` `open` — `with open(path, "rb") as f:`
- `app/pm/store.py:641` `os.path.exists` — `if not os.path.exists(local):`
- `app/pm/store.py:642` `shutil.copyfile` — `shutil.copyfile(path, local)`
- `app/pm/store.py:671` `os.path.exists` — `if os.path.exists(local):`
- `app/pm/store.py:679` `open` — `with open(tmp, "wb") as f:`
- `app/pm/store.py:681` `os.replace` — `os.replace(tmp, local) # never a half-written attachment`
- `app/pm/store.py:695` `open` — `with open(local, "rb") as f:`
- `app/pm/store.py:745` `os.path.abspath` — `folder = os.path.abspath(folder)`

#### `app/pm/submittals.py`

- `app/pm/submittals.py:82` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/pm/submittals.py:246` `os.replace` — `os.replace(tmp, path)`

#### `app/pm/widgets.py`

- `app/pm/widgets.py:528` `os.path.isfile` — `if os.path.isfile(p):`
- `app/pm/widgets.py:555` `os.path.exists` — `if os.path.exists(local):`

#### `app/policy.py`

- `app/policy.py:75` `os.path.abspath` — `os.path.abspath(__file__)), "updatecheck.py"))`
- `app/policy.py:247` `os.path.isfile` — `if not os.path.isfile(path):`
- `app/policy.py:261` `open` — `with open(path, encoding="utf-8") as f:`

#### `app/practice.py`

- `app/practice.py:169` `os.makedirs` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `app/practice.py:169` `os.path.abspath` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`

#### `app/prebid.py`

- `app/prebid.py:606` `open` — `with open(tmp, "rb") as f:`
- `app/prebid.py:608` `os.remove` — `os.remove(tmp)`

#### `app/preflight.py`

- `app/preflight.py:251` `os.path.exists` — `if p.returncode == 0 and os.path.exists(path):`
- `app/preflight.py:258` `os.replace` — `os.replace(path + ".tmp", path)`

#### `app/pricedb.py`

- `app/pricedb.py:170` `os.path.abspath` — `p = os.path.normcase(os.path.abspath(p or path()))`
- `app/pricedb.py:171` `os.path.abspath` — `return not p.startswith(os.path.normcase(os.path.abspath(settings.DIR)))`
- `app/pricedb.py:176` `os.path.abspath` — `low = os.path.abspath(p).lower().replace("\\", "/")`
- `app/pricedb.py:217` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/pricedb.py:314` `os.path.abspath` — `folder = os.path.dirname(os.path.abspath(p))`
- `app/pricedb.py:316` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `app/pricedb.py:317` `os.path.isdir` — `elif not os.path.isdir(folder):`
- `app/pricedb.py:324` `os.path.exists` — `if not is_shared(p) or not os.path.exists(cache_path()):`
- `app/pricedb.py:658` `open` — `with open(_seen_path(), encoding="utf-8") as f:`
- `app/pricedb.py:687` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `app/pricedb.py:689` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/pricedb.py:691` `os.replace` — `os.replace(tmp, _seen_path())`
- `app/pricedb.py:705` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `app/pricedb.py:706` `open` — `with open(_seen_path(), "w", encoding="utf-8") as f:`
- `app/pricedb.py:796` `os.path.exists` — `if not is_shared() and not os.path.exists(path()):`
- `app/pricedb.py:935` `os.path.abspath` — `new_path = os.path.abspath(new_path)`
- `app/pricedb.py:936` `os.path.isdir` — `if os.path.isdir(new_path):`
- `app/pricedb.py:939` `os.path.exists` — `if not os.path.exists(new_path):`
- `app/pricedb.py:940` `os.makedirs` — `os.makedirs(os.path.dirname(new_path), exist_ok=True)`
- `app/pricedb.py:941` `os.path.exists` — `if copy_current and os.path.exists(path()):`
- `app/pricedb.py:985` `os.path.isdir` — `if not os.path.isdir(folder):`
- `app/pricedb.py:988` `os.listdir` — `for n in sorted(os.listdir(folder)):`
- `app/pricedb.py:992` `open` — `with open(os.path.join(folder, n), encoding="utf-8") as f:`
- `app/pricedb.py:1006` `os.listdir` — `files = sorted(f for f in os.listdir(folder) if f.endswith(".bak"))`
- `app/pricedb.py:1008` `os.remove` — `os.remove(os.path.join(folder, f))`
- `app/pricedb.py:1016` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`

#### `app/pricedb_ui.py`

- `app/pricedb_ui.py:451` `os.path.exists` — `exists = os.path.exists(target)`

#### `app/printer_setup.py`

- `app/printer_setup.py:101` `open` — `with open(ph.log_path(), encoding="utf-8", errors="replace") as f:`
- `app/printer_setup.py:127` `os.makedirs` — `os.makedirs(ph.SPOOL_DIR, exist_ok=True)`
- `app/printer_setup.py:183` `os.path.isdir` — `if os.path.isdir(ph.SPOOL_DIR): # unread jobs go too`

#### `app/printhelper.py`

- `app/printhelper.py:73` `os.path.exists` — `while os.path.exists(p):`
- `app/printhelper.py:104` `os.path.isfile` — `return w if b.lower() == "python.exe" and os.path.isfile(w) else exe`
- `app/printhelper.py:112` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `app/printhelper.py:122` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `app/printhelper.py:294` `os.path.getsize` — `a = os.path.getsize(path)`
- `app/printhelper.py:296` `os.path.getsize` — `b = os.path.getsize(path)`
- `app/printhelper.py:297` `open` — `with open(path, "rb"):`
- `app/printhelper.py:311` `os.path.exists` — `return PORT if os.path.exists(PORT) else None`
- `app/printhelper.py:323` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `app/printhelper.py:325` `open` — `with open(path, "wb") as f:`
- `app/printhelper.py:352` `open` — `with open(port, "rb") as f:`
- `app/printhelper.py:359` `os.remove` — `os.remove(port)`
- `app/printhelper.py:445` `os.makedirs` — `os.makedirs(os.path.dirname(path), exist_ok=True)`

#### `app/proposal.py`

- `app/proposal.py:386` `os.path.isfile` — `if logo and os.path.isfile(logo):`

#### `app/qlink.py`

- `app/qlink.py:19` `os.path.abspath` — `return os.path.normcase(os.path.abspath(doc_path)) if doc_path else ""`
- `app/qlink.py:83` `os.replace` — `os.replace(tmp, xlsx_path)`
- `app/qlink.py:86` `os.remove` — `os.remove(tmp)`

#### `app/quickaccess.py`

- `app/quickaccess.py:671` `os.path.abspath` — `folder = os.path.dirname(os.path.abspath(path))`
- `app/quickaccess.py:672` `os.path.abspath` — `me = os.path.normcase(os.path.abspath(path))`
- `app/quickaccess.py:677` `os.listdir` — `for f in os.listdir(folder):`
- `app/quickaccess.py:680` `os.path.abspath` — `os.path.normcase(os.path.abspath(p)) != me and \`
- `app/quickaccess.py:681` `os.path.isfile` — `os.path.isfile(p):`
- `app/quickaccess.py:690` `os.path.getmtime` — `return max(pool, key=lambda p: os.path.getmtime(p))`
- `app/quickaccess.py:740` `os.path.isfile` — `if not other or not os.path.isfile(other):`
- `app/quickaccess.py:1396` `os.path.isfile` — `or not os.path.isfile(path) or not path.lower().endswith(".pdf"):`

#### `app/render_proc.py`

- `app/render_proc.py:44` `os.stat` — `st = os.stat(path)`

#### `app/review.py`

- `app/review.py:130` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/review.py:131` `open` — `with open(path, "a", encoding="utf-8") as f:`

#### `app/rfilog.py`

- `app/rfilog.py:192` `open` — `with open(path, "w", newline="", encoding="utf-8-sig") as f:`

#### `app/roof.py`

- `app/roof.py:446` `open` — `with open(path, "w", newline="", encoding="utf-8-sig") as f:`

#### `app/roof_report.py`

- `app/roof_report.py:140` `os.path.getsize` — `size = os.path.getsize(path)`
- `app/roof_report.py:146` `open` — `with open(path, "rb") as f:`

#### `app/rsmeans.py`

- `app/rsmeans.py:359` `open` — `with open(path, encoding="utf-8-sig", errors="replace") as f:`

#### `app/safeio.py`

- `app/safeio.py:25` `os.open` — `fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))`
- `app/safeio.py:43` `os.path.abspath` — `return bool(name) and os.path.normcase(os.path.abspath(name)) == \`
- `app/safeio.py:44` `os.path.abspath` — `os.path.normcase(os.path.abspath(os.fspath(path)))`
- `app/safeio.py:60` `os.replace` — `os.replace(tmp, path)`
- `app/safeio.py:68` `os.remove` — `os.remove(tmp)`
- `app/safeio.py:80` `open` — `with open(tmp, mode, **({} if mode == "wb" else`
- `app/safeio.py:88` `os.replace` — `os.replace(tmp, path)`
- `app/safeio.py:91` `os.remove` — `os.remove(tmp)`
- `app/safeio.py:102` `os.path.abspath` — `key = os.path.normcase(os.path.abspath(path))`
- `app/safeio.py:103` `os.path.isfile` — `if key in _BACKED_UP or not os.path.isfile(path):`
- `app/safeio.py:108` `shutil.copy2` — `shutil.copy2(path, tmp)`
- `app/safeio.py:109` `os.replace` — `os.replace(tmp, bak)`
- `app/safeio.py:184` `os.remove` — `os.remove(path)`
- `app/safeio.py:201` `os.replace` — `os.replace(tmp, path)`
- `app/safeio.py:209` `os.remove` — `os.remove(tmp)`

#### `app/safexml.py`

- `app/safexml.py:51` `os.path.getsize` — `size = os.path.getsize(path)`
- `app/safexml.py:55` `open` — `with open(path, "rb") as f:`

#### `app/sage_export.py`

- `app/sage_export.py:224` `open` — `with open(path, "w", newline="", encoding="utf-8-sig") as f:`

#### `app/sealed_contacts.py`

- `app/sealed_contacts.py:13` `os.path.abspath` — `FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `app/sealed_contacts.py:56` `os.path.exists` — `return os.path.exists(FILE)`
- `app/sealed_contacts.py:63` `open` — `with open(path or FILE, "rb") as f:`

#### `app/service/files.py`

- `app/service/files.py:92` `os.path.abspath` — `return os.path.abspath(os.path.expanduser(str(path)))`
- `app/service/files.py:99` `os.path.isfile` — `if not path or not os.path.isfile(path):`

#### `app/service/handover.py`

- `app/service/handover.py:135` `os.path.isfile` — `if path and os.path.isfile(path):`
- `app/service/handover.py:201` `os.path.isfile` — `if not path or not os.path.isfile(path):`

#### `app/service/handover_ui.py`

- `app/service/handover_ui.py:85` `os.path.isfile` — `if os.path.isfile(path):`

#### `app/service/pdfdoc.py`

- `app/service/pdfdoc.py:91` `os.path.isfile` — `if comp.get("logo") and os.path.isfile(comp["logo"]) and not continued:`
- `app/service/pdfdoc.py:208` `os.makedirs` — `os.makedirs(os.path.dirname(p) or ".", exist_ok=True)`
- `app/service/pdfdoc.py:215` `os.replace` — `os.replace(tmp, p)`
- `app/service/pdfdoc.py:217` `os.path.exists` — `if os.path.exists(tmp):`
- `app/service/pdfdoc.py:219` `os.remove` — `os.remove(tmp)`

#### `app/service/workorder.py`

- `app/service/workorder.py:235` `os.path.isfile` — `if not path or not os.path.isfile(path):`
- `app/service/workorder.py:237` `os.path.abspath` — `row = {"path": os.path.abspath(path), "caption": files.txt(caption, 200)}`
- `app/service/workorder.py:496` `os.path.isfile` — `if not os.path.isfile(ph.get("path") or ""):`

#### `app/sets.py`

- `app/sets.py:44` `os.path.abspath` — `base = os.path.dirname(os.path.abspath(path))`
- `app/sets.py:46` `os.path.abspath` — `"files": [_rel(os.path.abspath(f), base) for f in files],`
- `app/sets.py:47` `os.path.abspath` — `"index": [], "path": os.path.abspath(path)}`
- `app/sets.py:59` `open` — `with open(path, encoding="utf-8") as f:`
- `app/sets.py:66` `os.path.abspath` — `s["path"] = os.path.abspath(path)`
- `app/sets.py:75` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/sets.py:77` `os.replace` — `os.replace(tmp, s["path"])`
- `app/sets.py:90` `os.path.abspath` — `if os.path.normcase(os.path.abspath(p)) not in have:`
- `app/sets.py:91` `os.path.abspath` — `s["files"].append(_rel(os.path.abspath(p), base))`
- `app/sets.py:139` `os.stat` — `st = os.stat(p)`
- `app/sets.py:292` `os.makedirs` — `os.makedirs(bdir, exist_ok=True)`
- `app/sets.py:293` `shutil.copy2` — `shutil.copy2(path, os.path.join(bdir, os.path.basename(path)))`
- `app/sets.py:314` `os.replace` — `os.replace(tmp, path)`
- `app/sets.py:389` `open` — `with open(path, "w", newline="", encoding="utf-8-sig") as f:`

#### `app/sets_ui.py`

- `app/sets_ui.py:61` `os.path.exists` — `if last and os.path.exists(last):`

#### `app/settings.py`

- `app/settings.py:28` `open` — `with open(PATH, encoding="utf-8") as f:`
- `app/settings.py:56` `os.makedirs` — `os.makedirs(DIR, exist_ok=True)`
- `app/settings.py:58` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/settings.py:60` `os.replace` — `os.replace(tmp, PATH)`
- `app/settings.py:94` `os.path.realpath` — `tmp = os.path.normcase(os.path.realpath(tempfile.gettempdir()))`
- `app/settings.py:96` `os.path.realpath` — `p = os.path.normcase(os.path.realpath(path)).rstrip("\\/")`
- `app/settings.py:120` `os.path.exists` — `if not _is_temp(p) and os.path.exists(p):`
- `app/settings.py:141` `os.path.isdir` — `if isinstance(d, str) and os.path.isdir(d) and not _is_temp(d):`
- `app/settings.py:146` `os.path.isdir` — `if os.path.isdir(os.path.join(home, c)):`

#### `app/shellverbs.py`

- `app/shellverbs.py:43` `os.path.exists` — `while os.path.exists(out):`
- `app/shellverbs.py:57` `os.path.getsize` — `return out, os.path.getsize(path), os.path.getsize(out)`
- `app/shellverbs.py:57` `os.path.getsize` — `return out, os.path.getsize(path), os.path.getsize(out)`
- `app/shellverbs.py:61` `os.listdir` — `return sorted((os.path.join(folder, n) for n in os.listdir(folder)`
- `app/shellverbs.py:63` `os.path.isfile` — `os.path.isfile(os.path.join(folder, n))),`

#### `app/sign/embed.py`

- `app/sign/embed.py:28` `os.path.abspath` — `same = os.path.abspath(src) == os.path.abspath(out)`
- `app/sign/embed.py:28` `os.path.abspath` — `same = os.path.abspath(src) == os.path.abspath(out)`
- `app/sign/embed.py:30` `shutil.copyfile` — `shutil.copyfile(src, out)`
- `app/sign/embed.py:41` `os.path.abspath` — `dir=os.path.dirname(os.path.abspath(out)))`
- `app/sign/embed.py:46` `os.replace` — `os.replace(tmp, out)`

#### `app/sign/signer.py`

- `app/sign/signer.py:33` `os.path.exists` — `if not os.path.exists(pf):`
- `app/sign/signer.py:36` `open` — `with open(pf, "rb") as f:`
- `app/sign/signer.py:55` `os.makedirs` — `os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True)`
- `app/sign/signer.py:57` `os.open` — `fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)`
- `app/sign/signer.py:61` `open` — `with open(_pass_file(key_path) + ".tmp", "wb") as f:`
- `app/sign/signer.py:63` `os.replace` — `os.replace(_pass_file(key_path) + ".tmp", _pass_file(key_path))`
- `app/sign/signer.py:64` `os.replace` — `os.replace(tmp, key_path)`
- `app/sign/signer.py:72` `os.path.exists` — `if not secretstore.available() or not os.path.exists(key_path):`
- `app/sign/signer.py:74` `open` — `with open(key_path, "rb") as f:`
- `app/sign/signer.py:88` `os.path.exists` — `if os.path.exists(key_path) and os.path.exists(cert_path):`
- `app/sign/signer.py:88` `os.path.exists` — `if os.path.exists(key_path) and os.path.exists(cert_path):`
- `app/sign/signer.py:124` `open` — `with open(cert_path, "wb") as f:`
- `app/sign/signer.py:161` `os.path.abspath` — `out_dir = os.path.dirname(os.path.abspath(out))`
- `app/sign/signer.py:164` `open` — `with open(src, "rb") as f, os.fdopen(fd, "wb") as o:`
- `app/sign/signer.py:172` `os.replace` — `os.replace(tmp, out)`
- `app/sign/signer.py:174` `os.path.exists` — `if os.path.exists(tmp):`
- `app/sign/signer.py:175` `os.unlink` — `os.unlink(tmp)`

#### `app/sign/verify.py`

- `app/sign/verify.py:23` `open` — `with open(src, "rb") as f:`

#### `app/singleinstance.py`

- `app/singleinstance.py:100` `os.path.abspath` — `s.write(json.dumps([os.path.abspath(p) for p in paths]).encode("utf-8")`
- `app/singleinstance.py:140` `os.path.isfile` — `os.path.isfile(p)]`

#### `app/slipreport.py`

- `app/slipreport.py:108` `open` — `with open(path, "w", newline="", encoding="utf-8") as f:`

#### `app/specrisk_ui.py`

- `app/specrisk_ui.py:110` `os.access` — `if not folder or not os.access(folder, os.W_OK):`

#### `app/specs.py`

- `app/specs.py:290` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`

#### `app/subdir.py`

- `app/subdir.py:54` `open` — `with open(path(), encoding="utf-8") as f:`
- `app/subdir.py:74` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `app/subdir.py:80` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/subdir.py:84` `os.path.exists` — `if os.name == "nt" and os.path.exists(path()):`
- `app/subdir.py:89` `os.replace` — `os.replace(tmp, path())`

#### `app/syspaths.py`

- `app/syspaths.py:24` `os.path.exists` — `return p if os.path.exists(p) else "powershell"`
- `app/syspaths.py:29` `os.path.exists` — `return p if os.path.exists(p) else "icacls"`

#### `app/tagcheck.py`

- `app/tagcheck.py:62` `open` — `with open(path, "w", newline="", encoding="utf-8") as f:`

#### `app/textedit.py`

- `app/textedit.py:545` `open` — `return 0`

#### `app/textio.py`

- `app/textio.py:8` `open` — `with open(path, "rb") as f:`

#### `app/theme.py`

- `app/theme.py:108` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/theme.py:124` `open` — `with open(p, "w", encoding="utf-8") as f:`

#### `app/timelog.py`

- `app/timelog.py:31` `open` — `with open(path(), encoding="utf-8") as f:`
- `app/timelog.py:40` `os.makedirs` — `os.makedirs(os.path.dirname(path()), exist_ok=True)`
- `app/timelog.py:87` `open` — `with open(target, "w", newline="", encoding="utf-8") as f:`

#### `app/toolchest.py`

- `app/toolchest.py:92` `open` — `with open(PATH, encoding="utf-8") as f:`
- `app/toolchest.py:106` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `app/toolchest.py:108` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/toolchest.py:110` `os.replace` — `os.replace(tmp, PATH)`
- `app/toolchest.py:201` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/toolchest.py:203` `os.replace` — `os.replace(tmp, path)`
- `app/toolchest.py:215` `os.path.getsize` — `if os.path.getsize(path) > 2_000_000:`
- `app/toolchest.py:217` `open` — `with open(path, encoding="utf-8") as f:`

#### `app/updatecheck.py`

- `app/updatecheck.py:241` `open` — `with open(os.path.join(betalicense._data_dir(), PUBKEY_FILE),`
- `app/updatecheck.py:409` `os.path.abspath` — `here = os.path.join(os.path.dirname(os.path.abspath(__file__)),`
- `app/updatecheck.py:411` `open` — `with open(here, "r", encoding="utf-8") as f:`
- `app/updatecheck.py:475` `open` — `with open(path, "rb") as f:`
- `app/updatecheck.py:484` `os.path.getsize` — `if os.path.getsize(path) != info["size"]:`
- `app/updatecheck.py:497` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `app/updatecheck.py:505` `open` — `info["url"]) as r, open(part, "wb") as out:`
- `app/updatecheck.py:522` `os.replace` — `os.replace(part, final)`
- `app/updatecheck.py:526` `os.remove` — `os.remove(p)`
- `app/updatecheck.py:532` `os.remove` — `os.remove(final)`
- `app/updatecheck.py:558` `os.remove` — `os.remove(path)`
- `app/updatecheck.py:577` `os.path.isfile` — `return p if os.path.isfile(p) and verify_file(p, info) else None`
- `app/updatecheck.py:610` `os.listdir` — `names = os.listdir(folder)`
- `app/updatecheck.py:628` `os.listdir` — `names = os.listdir(folder)`
- `app/updatecheck.py:638` `os.remove` — `os.remove(os.path.join(folder, n))`

#### `app/updatecheck_ui.py`

- `app/updatecheck_ui.py:237` `os.remove` — `os.remove(self._path)`
- `app/updatecheck_ui.py:267` `os.startfile` — `os.startfile(os.path.dirname(self._path)) # noqa: S606`

#### `app/versions.py`

- `app/versions.py:17` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `app/versions.py:29` `os.path.exists` — `if os.path.exists(p):`
- `app/versions.py:31` `open` — `with open(p, encoding="utf-8") as f:`
- `app/versions.py:43` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `app/versions.py:45` `os.replace` — `os.replace(tmp, final) # never leaves a half-written index`
- `app/versions.py:53` `open` — `with open(os.path.join(_vdir(path), fname), "wb") as f:`
- `app/versions.py:73` `os.remove` — `os.remove(_rev_file(path, r))`
- `app/versions.py:95` `open` — `with open(_rev_file(path, r), "rb") as f:`

#### `app/viewer.py`

- `app/viewer.py:2936` `os.path.isfile` — `if (d.name and os.path.isfile(d.name) and not d.is_dirty`
- `app/viewer.py:2939` `open` — `with open(d.name, "rb") as f:`
- `app/viewer.py:3310` `os.path.getsize` — `if os.path.getsize(path) > 15 * 1024 * 1024:`
- `app/viewer.py:3314` `open` — `with open(path, "rb") as f:`
- `app/viewer.py:4580` `open` — `with open(path, "wb") as f:`

#### `app/voice.py`

- `app/voice.py:354` `os.remove` — `os.remove(f)`

#### `app/xfdf.py`

- `app/xfdf.py:107` `open` — `with open(path, "w", encoding="utf-8") as f:`

#### `quantisheet.py`

- `quantisheet.py:22` `open` — `sys.stdout = open("CONOUT$", "w", buffering=1, encoding="utf-8")`
- `quantisheet.py:23` `open` — `sys.stderr = open("CONOUT$", "w", buffering=1, encoding="utf-8")`
- `quantisheet.py:42` `os.path.exists` — `and os.path.exists(args[0]))`

#### `quantisheet_backoffice/__main__.py`

- `quantisheet_backoffice/__main__.py:54` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `quantisheet_backoffice/__main__.py:56` `open` — `with open(path, "a", encoding="utf-8") as fh:`

#### `quantisheet_backoffice/backup.py`

- `quantisheet_backoffice/backup.py:70` `os.path.exists` — `while os.path.exists(dest):`
- `quantisheet_backoffice/backup.py:86` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `quantisheet_backoffice/backup.py:91` `open` — `with open(tmp, "rb") as fh:`
- `quantisheet_backoffice/backup.py:94` `os.remove` — `os.remove(tmp)`
- `quantisheet_backoffice/backup.py:108` `open` — `with open(part, "wb") as fh:`
- `quantisheet_backoffice/backup.py:111` `os.replace` — `os.replace(part, dest)`
- `quantisheet_backoffice/backup.py:122` `os.path.isdir` — `if not os.path.isdir(folder):`
- `quantisheet_backoffice/backup.py:124` `os.listdir` — `return sorted(os.path.join(folder, f) for f in os.listdir(folder)`
- `quantisheet_backoffice/backup.py:136` `os.remove` — `os.remove(f)`
- `quantisheet_backoffice/backup.py:150` `open` — `with open(path, "rb") as fh:`
- `quantisheet_backoffice/backup.py:208` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `quantisheet_backoffice/backup.py:214` `os.path.exists` — `if os.path.exists(live):`
- `quantisheet_backoffice/backup.py:217` `shutil.copy2` — `shutil.copy2(live, live + time.strftime(`
- `quantisheet_backoffice/backup.py:229` `os.remove` — `os.remove(tmp)`

#### `quantisheet_backoffice/banking.py`

- `quantisheet_backoffice/banking.py:159` `open` — `with open(path, encoding="utf-8-sig", errors="replace") as fh:`

#### `quantisheet_backoffice/certified.py`

- `quantisheet_backoffice/certified.py:176` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`

#### `quantisheet_backoffice/erpsync.py`

- `quantisheet_backoffice/erpsync.py:123` `os.path.getsize` — `if os.path.getsize(path) > MAX_BYTES:`
- `quantisheet_backoffice/erpsync.py:137` `open` — `with open(path, encoding="utf-8-sig", errors="replace") as fh:`

#### `quantisheet_backoffice/exports.py`

- `quantisheet_backoffice/exports.py:251` `open` — `with open(path, "w", encoding="utf-8", newline="\r\n") as fh:`
- `quantisheet_backoffice/exports.py:334` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `quantisheet_backoffice/exports.py:368` `open` — `with open(path, "w", encoding="utf-8", newline="") as fh:`
- `quantisheet_backoffice/exports.py:429` `open` — `with open(path, "w", encoding="utf-8", newline="") as fh:`

#### `quantisheet_backoffice/fileguard.py`

- `quantisheet_backoffice/fileguard.py:71` `os.path.realpath` — `base = os.path.realpath(folder)`
- `quantisheet_backoffice/fileguard.py:72` `os.path.realpath` — `target = os.path.realpath(os.path.join(base, subdir, safe_name(name)))`

#### `quantisheet_backoffice/handoff.py`

- `quantisheet_backoffice/handoff.py:16` `os.path.realpath` — `p = os.path.realpath(path)`
- `quantisheet_backoffice/handoff.py:18` `os.path.realpath` — `tmp = os.path.realpath(tempfile.gettempdir())`
- `quantisheet_backoffice/handoff.py:28` `os.path.realpath` — `shutil.rmtree(os.path.dirname(os.path.realpath(path)), ignore_errors=True)`
- `quantisheet_backoffice/handoff.py:28` `shutil.rmtree` — `shutil.rmtree(os.path.dirname(os.path.realpath(path)), ignore_errors=True)`
- `quantisheet_backoffice/handoff.py:29` `os.path.exists` — `return not os.path.exists(path)`

#### `quantisheet_backoffice/host_tests/conftest.py`

- `quantisheet_backoffice/host_tests/conftest.py:15` `os.path.abspath` — `os.path.abspath(__file__))))`

#### `quantisheet_backoffice/host_tests/test_backoffice_hook.py`

- `quantisheet_backoffice/host_tests/test_backoffice_hook.py:145` `open` — `h0 = hashlib.sha256(open(path, "rb").read()).hexdigest()`
- `quantisheet_backoffice/host_tests/test_backoffice_hook.py:159` `open` — `json.load(open(p, encoding="utf-8"))`
- `quantisheet_backoffice/host_tests/test_backoffice_hook.py:161` `open` — `assert hashlib.sha256(open(path, "rb").read()).hexdigest() == h0`
- `quantisheet_backoffice/host_tests/test_backoffice_hook.py:181` `open` — `h0 = hashlib.sha256(open(pdf, "rb").read()).hexdigest()`
- `quantisheet_backoffice/host_tests/test_backoffice_hook.py:194` `os.path.isfile` — `assert os.path.isfile(tmp_path / "bo" / "crash.log")`
- `quantisheet_backoffice/host_tests/test_backoffice_hook.py:202` `open` — `assert hashlib.sha256(open(pdf, "rb").read()).hexdigest() == h0`
- `quantisheet_backoffice/host_tests/test_backoffice_hook.py:217` `open` — `snap = json.load(open(seen["args"][4], encoding="utf-8"))`

#### `quantisheet_backoffice/hr.py`

- `quantisheet_backoffice/hr.py:193` `open` — `with open(path, "rb") as fh:`
- `quantisheet_backoffice/hr.py:196` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `quantisheet_backoffice/hr.py:199` `open` — `with open(dest, "wb") as fh:`
- `quantisheet_backoffice/hr.py:227` `open` — `with open(d["file_path"], "rb") as fh:`

#### `quantisheet_backoffice/interface.py`

- `quantisheet_backoffice/interface.py:322` `open` — `with open(src, "rb") as fh:`

#### `quantisheet_backoffice/ledger.py`

- `quantisheet_backoffice/ledger.py:265` `open` — `with open(path_or_text, encoding="utf-8-sig", newline="") as fh:`

#### `quantisheet_backoffice/migrate.py`

- `quantisheet_backoffice/migrate.py:59` `open` — `with open(path, "rb") as fh:`

#### `quantisheet_backoffice/ocr.py`

- `quantisheet_backoffice/ocr.py:47` `os.access` — `if os.path.isfile(p) and os.access(p, os.X_OK):`
- `quantisheet_backoffice/ocr.py:47` `os.path.isfile` — `if os.path.isfile(p) and os.access(p, os.X_OK):`
- `quantisheet_backoffice/ocr.py:165` `shutil.rmtree` — `shutil.rmtree(tmp, ignore_errors=True)`

#### `quantisheet_backoffice/office.py`

- `quantisheet_backoffice/office.py:22` `os.makedirs` — `os.makedirs(self.folder, exist_ok=True)`

#### `quantisheet_backoffice/output.py`

- `quantisheet_backoffice/output.py:60` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `quantisheet_backoffice/output.py:67` `os.path.isfile` — `if c.get("logo") and os.path.isfile(c["logo"]):`
- `quantisheet_backoffice/output.py:302` `os.path.isfile` — `if f and os.path.isfile(f):`
- `quantisheet_backoffice/output.py:362` `os.startfile` — `os.startfile(path) # noqa: S606`
- `quantisheet_backoffice/output.py:385` `os.path.isfile` — `pdf = inv["pdf_path"] if inv["pdf_path"] and os.path.isfile(`
- `quantisheet_backoffice/output.py:400` `os.path.abspath` — `m.Attachments.Add(os.path.abspath(pdf))`
- `quantisheet_backoffice/output.py:412` `open` — `with open(pdf, "rb") as fh:`
- `quantisheet_backoffice/output.py:416` `open` — `with open(path, "wb") as fh:`

#### `quantisheet_backoffice/provider.py`

- `quantisheet_backoffice/provider.py:156` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `quantisheet_backoffice/provider.py:165` `open` — `with open(path, "w", encoding="utf-8", newline="") as fh:`
- `quantisheet_backoffice/provider.py:185` `open` — `with open(path, encoding="utf-8-sig") as fh:`

#### `quantisheet_backoffice/r111/apdrop.py`

- `quantisheet_backoffice/r111/apdrop.py:25` `os.path.isdir` — `if not path or not os.path.isdir(path):`
- `quantisheet_backoffice/r111/apdrop.py:33` `os.path.abspath` — `fid = office.db.insert("ap_drop_folders", path=os.path.abspath(path),`
- `quantisheet_backoffice/r111/apdrop.py:119` `os.path.isdir` — `if not os.path.isdir(fold["path"]):`
- `quantisheet_backoffice/r111/apdrop.py:122` `os.listdir` — `names = sorted(os.listdir(fold["path"]))`
- `quantisheet_backoffice/r111/apdrop.py:127` `os.path.isfile` — `if not os.path.isfile(path):`
- `quantisheet_backoffice/r111/apdrop.py:133` `os.path.getsize` — `if os.path.getsize(path) <= 0:`

#### `quantisheet_backoffice/r111/apstamp.py`

- `quantisheet_backoffice/r111/apstamp.py:51` `os.path.isfile` — `if src and os.path.isfile(src):`
- `quantisheet_backoffice/r111/apstamp.py:55` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `quantisheet_backoffice/r111/apstamp.py:71` `os.path.isfile` — `if src and os.path.isfile(src) and original_hash:`
- `quantisheet_backoffice/r111/apstamp.py:99` `os.path.exists` — `if os.path.exists(stale):`
- `quantisheet_backoffice/r111/apstamp.py:100` `os.remove` — `os.remove(stale)`
- `quantisheet_backoffice/r111/apstamp.py:101` `os.path.isfile` — `if src and os.path.isfile(src):`
- `quantisheet_backoffice/r111/apstamp.py:118` `os.path.exists` — `if os.path.exists(tmp):`
- `quantisheet_backoffice/r111/apstamp.py:119` `os.remove` — `os.remove(tmp)`
- `quantisheet_backoffice/r111/apstamp.py:123` `os.replace` — `os.replace(tmp, dest)`

#### `quantisheet_backoffice/r111/incident.py`

- `quantisheet_backoffice/r111/incident.py:85` `os.path.isfile` — `if not os.path.isfile(path):`
- `quantisheet_backoffice/r111/incident.py:179` `open` — `with open(path, "w", newline="", encoding="utf-8") as fh:`
- `quantisheet_backoffice/r111/incident.py:257` `os.path.isfile` — `if photo["file_path"] and os.path.isfile(photo["file_path"]) \`

#### `quantisheet_backoffice/r111/paykeys.py`

- `quantisheet_backoffice/r111/paykeys.py:49` `os.path.realpath` — `digest = hashlib.sha256(os.path.realpath(company_folder).encode()`
- `quantisheet_backoffice/r111/paykeys.py:51` `os.path.realpath` — `home = os.path.realpath(settings.home())`
- `quantisheet_backoffice/r111/paykeys.py:52` `os.path.realpath` — `company = os.path.realpath(company_folder)`
- `quantisheet_backoffice/r111/paykeys.py:69` `os.makedirs` — `os.makedirs(os.path.dirname(path), exist_ok=True)`
- `quantisheet_backoffice/r111/paykeys.py:70` `os.open` — `fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)`
- `quantisheet_backoffice/r111/paykeys.py:74` `os.chmod` — `os.chmod(path, 0o600)`
- `quantisheet_backoffice/r111/paykeys.py:81` `os.path.isfile` — `if not os.path.isfile(path):`
- `quantisheet_backoffice/r111/paykeys.py:86` `open` — `raw = open(path, "rb").read()`
- `quantisheet_backoffice/r111/paykeys.py:103` `os.path.isfile` — `if not os.path.isfile(path):`
- `quantisheet_backoffice/r111/paykeys.py:105` `open` — `blob = open(path, "rb").read()`
- `quantisheet_backoffice/r111/paykeys.py:118` `os.path.realpath` — `return hashlib.sha256(os.path.realpath(company_folder).encode()`
- `quantisheet_backoffice/r111/paykeys.py:135` `os.path.isfile` — `if not os.path.isfile(path):`
- `quantisheet_backoffice/r111/paykeys.py:137` `open` — `blob = open(path, "rb").read()`
- `quantisheet_backoffice/r111/paykeys.py:157` `os.path.isfile` — `if not os.path.isfile(path):`
- `quantisheet_backoffice/r111/paykeys.py:159` `open` — `blob = open(path, "rb").read()`
- `quantisheet_backoffice/r111/paykeys.py:167` `os.path.isdir` — `if not os.path.isdir(company_folder):`
- `quantisheet_backoffice/r111/paykeys.py:170` `os.listdir` — `for name in sorted(os.listdir(company_folder)):`
- `quantisheet_backoffice/r111/paykeys.py:174` `os.path.isfile` — `if not os.path.isfile(path):`
- `quantisheet_backoffice/r111/paykeys.py:176` `open` — `raw = open(path, "rb").read()`
- `quantisheet_backoffice/r111/paykeys.py:185` `os.path.exists` — `while os.path.exists(os.path.join(slot, f"key.retired-{n}")):`
- `quantisheet_backoffice/r111/paykeys.py:189` `os.remove` — `os.remove(path) # moved: sealed + original bytes in the profile`
- `quantisheet_backoffice/r111/paykeys.py:200` `os.path.isfile` — `if os.path.isfile(_key_path(slot)):`
- `quantisheet_backoffice/r111/paykeys.py:203` `os.path.isfile` — `if named and os.path.isfile(_key_path(named)):`
- `quantisheet_backoffice/r111/paykeys.py:227` `os.path.isfile` — `if os.path.isfile(legacy):`
- `quantisheet_backoffice/r111/paykeys.py:228` `open` — `raw = open(legacy, "rb").read()`
- `quantisheet_backoffice/r111/paykeys.py:234` `os.makedirs` — `os.makedirs(slot, exist_ok=True)`
- `quantisheet_backoffice/r111/paykeys.py:240` `os.makedirs` — `os.makedirs(slot, exist_ok=True)`
- `quantisheet_backoffice/r111/paykeys.py:256` `os.path.isdir` — `if not os.path.isdir(slot):`
- `quantisheet_backoffice/r111/paykeys.py:258` `os.listdir` — `names = [n for n in os.listdir(slot) if n.startswith("key.retired-")]`
- `quantisheet_backoffice/r111/paykeys.py:282` `open` — `data = open(path, "rb").read()`
- `quantisheet_backoffice/r111/paykeys.py:307` `os.makedirs` — `os.makedirs(slot, exist_ok=True)`
- `quantisheet_backoffice/r111/paykeys.py:309` `os.path.isfile` — `if os.path.isfile(live):`
- `quantisheet_backoffice/r111/paykeys.py:315` `os.path.exists` — `while os.path.exists(os.path.join(slot, f"key.retired-{n}")):`
- `quantisheet_backoffice/r111/paykeys.py:317` `os.replace` — `os.replace(live, os.path.join(slot, f"key.retired-{n}"))`
- `quantisheet_backoffice/r111/paykeys.py:384` `os.path.isfile` — `if path and os.path.isfile(path):`
- `quantisheet_backoffice/r111/paykeys.py:385` `open` — `found.append((path, old.decrypt_bytes(open(path, "rb").read())))`
- `quantisheet_backoffice/r111/paykeys.py:427` `open` — `with open(tmp, "wb") as fh:`
- `quantisheet_backoffice/r111/paykeys.py:442` `os.remove` — `os.remove(tmp)`
- `quantisheet_backoffice/r111/paykeys.py:450` `os.replace` — `os.replace(tmp, path)`
- `quantisheet_backoffice/r111/paykeys.py:488` `open` — `data = open(path, "rb").read()`
- `quantisheet_backoffice/r111/paykeys.py:517` `os.makedirs` — `os.makedirs(slot, exist_ok=True)`
- `quantisheet_backoffice/r111/paykeys.py:520` `os.path.isfile` — `if os.path.isfile(live):`
- `quantisheet_backoffice/r111/paykeys.py:524` `os.path.isfile` — `if os.path.isfile(legacy):`
- `quantisheet_backoffice/r111/paykeys.py:525` `open` — `blob = open(legacy, "rb").read()`
- `quantisheet_backoffice/r111/paykeys.py:536` `open` — `blob = open(path, "rb").read()`

#### `quantisheet_backoffice/r111/pdfutil.py`

- `quantisheet_backoffice/r111/pdfutil.py:29` `os.path.isfile` — `if not path or not os.path.isfile(path):`
- `quantisheet_backoffice/r111/pdfutil.py:37` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `quantisheet_backoffice/r111/pdfutil.py:51` `os.path.isfile` — `if logo and os.path.isfile(logo):`

#### `quantisheet_backoffice/r111/sagejc.py`

- `quantisheet_backoffice/r111/sagejc.py:357` `os.path.isfile` — `if not os.path.isfile(path):`

#### `quantisheet_backoffice/r111/vendmem.py`

- `quantisheet_backoffice/r111/vendmem.py:34` `os.path.isfile` — `if not path or not os.path.isfile(path):`
- `quantisheet_backoffice/r111/vendmem.py:119` `os.path.isfile` — `if path and os.path.isfile(path):`

#### `quantisheet_backoffice/r111/warranty.py`

- `quantisheet_backoffice/r111/warranty.py:72` `os.path.isfile` — `if not os.path.isfile(path):`
- `quantisheet_backoffice/r111/warranty.py:140` `os.path.isfile` — `if photo["file_path"] and os.path.isfile(photo["file_path"]) \`

#### `quantisheet_backoffice/remote.py`

- `quantisheet_backoffice/remote.py:266` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `quantisheet_backoffice/remote.py:269` `open` — `with open(photo, "wb") as fh:`

#### `quantisheet_backoffice/server/app.py`

- `quantisheet_backoffice/server/app.py:32` `os.path.abspath` — `STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")`
- `quantisheet_backoffice/server/app.py:69` `os.makedirs` — `os.makedirs(data_dir, exist_ok=True)`
- `quantisheet_backoffice/server/app.py:167` `open` — `with open(os.path.join(STATIC, name), encoding="utf-8") as fh:`

#### `quantisheet_backoffice/settings.py`

- `quantisheet_backoffice/settings.py:29` `os.path.realpath` — `return (os.path.realpath(os.path.join(home, ".quantisheet")),)`
- `quantisheet_backoffice/settings.py:33` `os.path.realpath` — `rp = os.path.realpath(path)`
- `quantisheet_backoffice/settings.py:69` `os.path.exists` — `if os.path.exists(p):`
- `quantisheet_backoffice/settings.py:71` `open` — `with open(p, encoding="utf-8") as fh:`
- `quantisheet_backoffice/settings.py:107` `os.path.realpath` — `low = os.path.realpath(path).lower()`
- `quantisheet_backoffice/settings.py:117` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `quantisheet_backoffice/settings.py:122` `os.replace` — `os.replace(tmp, path)`
- `quantisheet_backoffice/settings.py:125` `os.unlink` — `os.unlink(tmp)`

#### `quantisheet_backoffice/store.py`

- `quantisheet_backoffice/store.py:392` `os.makedirs` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `quantisheet_backoffice/store.py:392` `os.path.abspath` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `quantisheet_backoffice/store.py:563` `os.chmod` — `os.chmod(path, 0o600)`
- `quantisheet_backoffice/store.py:585` `os.path.abspath` — `p = os.path.abspath(path)`
- `quantisheet_backoffice/store.py:599` `open` — `with open(path, "rb") as fh:`
- `quantisheet_backoffice/store.py:608` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `quantisheet_backoffice/store.py:612` `os.path.exists` — `while os.path.exists(dest):`
- `quantisheet_backoffice/store.py:615` `shutil.copy2` — `shutil.copy2(path, dest)`

#### `quantisheet_backoffice/ten99.py`

- `quantisheet_backoffice/ten99.py:71` `open` — `with open(path, "w", encoding="utf-8", newline="") as fh:`

#### `quantisheet_backoffice/timeoff.py`

- `quantisheet_backoffice/timeoff.py:365` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`

#### `quantisheet_backoffice/wip.py`

- `quantisheet_backoffice/wip.py:121` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`

#### `quantisheet_claims/export.py`

- `quantisheet_claims/export.py:205` `os.makedirs` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `quantisheet_claims/export.py:205` `os.path.abspath` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `quantisheet_claims/export.py:206` `open` — `with open(path, "w", newline="", encoding="utf-8-sig") as fh:`
- `quantisheet_claims/export.py:264` `os.makedirs` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `quantisheet_claims/export.py:264` `os.path.abspath` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `quantisheet_claims/export.py:428` `os.makedirs` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`
- `quantisheet_claims/export.py:428` `os.path.abspath` — `os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)`

#### `quantisheet_claims/interface.py`

- `quantisheet_claims/interface.py:115` `os.path.getsize` — `if os.path.getsize(path) > MAX_BYTES:`
- `quantisheet_claims/interface.py:118` `open` — `with open(path, encoding="utf-8") as fh:`

#### `quantisheet_claims/library.py`

- `quantisheet_claims/library.py:110` `open` — `with open(path, newline="", encoding="utf-8-sig") as f:`
- `quantisheet_claims/library.py:147` `open` — `with open(path, "w", newline="", encoding="utf-8-sig") as f:`

#### `quantisheet_claims/photos.py`

- `quantisheet_claims/photos.py:35` `open` — `with open(path, "rb") as f:`
- `quantisheet_claims/photos.py:55` `os.path.getmtime` — `return _dt.date.fromtimestamp(os.path.getmtime(path)).isoformat()`
- `quantisheet_claims/photos.py:75` `os.makedirs` — `os.makedirs(os.path.dirname(dest), exist_ok=True)`
- `quantisheet_claims/photos.py:76` `os.path.exists` — `if not os.path.exists(dest):`
- `quantisheet_claims/photos.py:77` `shutil.copy2` — `shutil.copy2(src, dest)`
- `quantisheet_claims/photos.py:93` `os.path.exists` — `if not os.path.exists(f):`
- `quantisheet_claims/photos.py:118` `os.path.exists` — `if os.path.exists(f) and _sha(f) == p.sha256:`

#### `quantisheet_claims/settings.py`

- `quantisheet_claims/settings.py:45` `os.path.realpath` — `return (os.path.realpath(os.path.join(home, ".quantisheet")),)`
- `quantisheet_claims/settings.py:54` `os.path.realpath` — `rp = os.path.realpath(path)`
- `quantisheet_claims/settings.py:72` `os.makedirs` — `os.makedirs(h, exist_ok=True)`
- `quantisheet_claims/settings.py:109` `os.path.isdir` — `if os.path.isdir(os.path.join(plain, DOCS_DIR)):`
- `quantisheet_claims/settings.py:114` `os.path.abspath` — `if known and os.path.normcase(os.path.abspath(known)).startswith(`
- `quantisheet_claims/settings.py:115` `os.path.abspath` — `os.path.normcase(os.path.abspath(home_)) + os.sep):`
- `quantisheet_claims/settings.py:128` `os.makedirs` — `os.makedirs(f, exist_ok=True)`
- `quantisheet_claims/settings.py:148` `os.path.exists` — `if os.path.exists(p):`
- `quantisheet_claims/settings.py:150` `open` — `with open(p, encoding="utf-8") as fh:`
- `quantisheet_claims/settings.py:183` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `quantisheet_claims/settings.py:188` `os.replace` — `os.replace(tmp, path)`
- `quantisheet_claims/settings.py:191` `os.unlink` — `os.unlink(tmp)`

#### `quantisheet_claims/store.py`

- `quantisheet_claims/store.py:83` `os.path.exists` — `if os.path.exists(p):`
- `quantisheet_claims/store.py:85` `os.makedirs` — `os.makedirs(bdir, exist_ok=True)`
- `quantisheet_claims/store.py:87` `shutil.copy2` — `shutil.copy2(p, os.path.join(bdir, f"{os.path.basename(p)}.{stamp}"))`
- `quantisheet_claims/store.py:88` `os.listdir` — `olds = sorted(x for x in os.listdir(bdir)`
- `quantisheet_claims/store.py:91` `os.unlink` — `os.unlink(os.path.join(bdir, x))`
- `quantisheet_claims/store.py:114` `open` — `with open(path, encoding="utf-8") as fh:`
- `quantisheet_claims/store.py:127` `open` — `with open(path, encoding="utf-8") as fh:`

#### `quantisheet_claims/ui/extras.py`

- `quantisheet_claims/ui/extras.py:93` `os.path.exists` — `if not isinstance(p, str) or not os.path.exists(p):`

#### `quantisheet_claims/ui/workspace.py`

- `quantisheet_claims/ui/workspace.py:519` `os.path.exists` — `if os.path.exists(store.path_for(c)):`
- `quantisheet_claims/ui/workspace.py:627` `os.path.abspath` — `norm = os.path.normcase(os.path.abspath(path))`
- `quantisheet_claims/ui/workspace.py:630` `os.path.abspath` — `os.path.abspath(oc["path"])) == norm:`
- `quantisheet_claims/ui/workspace.py:660` `os.path.abspath` — `if old and os.path.normcase(os.path.abspath(old)) != \`
- `quantisheet_claims/ui/workspace.py:661` `os.path.abspath` — `os.path.normcase(os.path.abspath(p)) and \`
- `quantisheet_claims/ui/workspace.py:668` `os.makedirs` — `os.makedirs(bdir, exist_ok=True)`
- `quantisheet_claims/ui/workspace.py:669` `os.replace` — `os.replace(old, os.path.join(bdir, os.path.basename(old) + "." +`
- `quantisheet_claims/ui/workspace.py:2033` `os.path.getmtime` — `key.append((p.sha256, f, os.path.getmtime(f)))`

#### `server/hub.py`

- `server/hub.py:123` `os.path.abspath` — `self.dir = os.path.abspath(data_dir)`
- `server/hub.py:124` `os.makedirs` — `os.makedirs(self.dir, exist_ok=True)`
- `server/hub.py:127` `os.path.exists` — `if not os.path.exists(sp):`
- `server/hub.py:128` `open` — `with open(sp, "wb") as f:`
- `server/hub.py:130` `open` — `with open(sp, "rb") as f:`
- `server/hub.py:138` `os.path.realpath` — `base = os.path.realpath(self.dir)`
- `server/hub.py:139` `os.path.realpath` — `full = os.path.realpath(os.path.join(base, *parts))`
- `server/hub.py:150` `open` — `with open(path, encoding="utf-8") as f:`
- `server/hub.py:158` `os.makedirs` — `os.makedirs(os.path.dirname(path), exist_ok=True)`
- `server/hub.py:160` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `server/hub.py:162` `os.replace` — `os.replace(tmp, path)`
- `server/hub.py:249` `os.makedirs` — `os.makedirs(d)`
- `server/hub.py:266` `open` — `with open(os.path.join(d, f"p{n}.png"), "wb") as f:`
- `server/hub.py:375` `os.path.isdir` — `if meta is None and os.path.isdir(root):`
- `server/hub.py:376` `os.listdir` — `for name in os.listdir(root):`
- `server/hub.py:378` `os.path.isfile` — `m = self._load(p) if os.path.isfile(p) else None`
- `server/hub.py:637` `open` — `with open(p, "a", encoding="utf-8") as f:`
- `server/hub.py:668` `os.makedirs` — `os.makedirs(os.path.join(d, "files"), exist_ok=True)`
- `server/hub.py:829` `os.path.exists` — `if os.path.exists(p):`
- `server/hub.py:830` `open` — `with open(p, encoding="utf-8") as f:`
- `server/hub.py:895` `os.makedirs` — `os.makedirs(os.path.dirname(tmp), exist_ok=True)`
- `server/hub.py:896` `open` — `open(tmp, "wb").close()`
- `server/hub.py:911` `os.path.getsize` — `if off != os.path.getsize(up["path"]):`
- `server/hub.py:913` `open` — `with open(up["path"], "ab") as f:`
- `server/hub.py:923` `open` — `with open(up["path"], "rb") as f:`
- `server/hub.py:926` `os.path.getsize` — `size = os.path.getsize(up["path"])`
- `server/hub.py:929` `os.remove` — `os.remove(up["path"])`
- `server/hub.py:935` `os.makedirs` — `os.makedirs(os.path.dirname(dest), exist_ok=True)`
- `server/hub.py:936` `os.replace` — `os.replace(up["path"], dest)`
- `server/hub.py:955` `os.path.isfile` — `if not os.path.isfile(p):`
- `server/hub.py:959` `open` — `with open(p, "rb") as f:`
- `server/hub.py:963` `os.path.getsize` — `"total": os.path.getsize(p), "version": v}`
- `server/hub.py:987` `open` — `with open(p) as f:`
- `server/hub.py:992` `open` — `with open(p, "w") as f:`
- `server/hub.py:1001` `os.path.isdir` — `if os.path.isdir(d):`
- `server/hub.py:1002` `os.listdir` — `for name in sorted(os.listdir(d)):`
- `server/hub.py:1011` `os.path.exists` — `if os.path.exists(p):`
- `server/hub.py:1012` `open` — `with open(p) as f:`
- `server/hub.py:1099` `os.path.exists` — `if not os.path.exists(p):`
- `server/hub.py:1100` `os.makedirs` — `os.makedirs(os.path.dirname(p), exist_ok=True)`
- `server/hub.py:1101` `open` — `with open(p, "wb") as f:`
- `server/hub.py:1112` `os.path.isfile` — `if not os.path.isfile(p):`
- `server/hub.py:1114` `open` — `with open(p, "rb") as f:`
- `server/hub.py:1217` `os.makedirs` — `os.makedirs(os.path.dirname(p), exist_ok=True)`
- `server/hub.py:1412` `os.path.exists` — `if not os.path.exists(p):`
- `server/hub.py:1413` `os.makedirs` — `os.makedirs(os.path.dirname(p), exist_ok=True)`
- `server/hub.py:1414` `open` — `with open(p, "wb") as f:`
- `server/hub.py:1519` `os.path.isfile` — `if not os.path.isfile(p):`
- `server/hub.py:1521` `open` — `with open(p, "rb") as f:`
- `server/hub.py:1533` `os.path.isfile` — `if not os.path.isfile(p):`
- `server/hub.py:1535` `open` — `with open(p, "rb") as f:`
- `server/hub.py:1545` `os.path.isfile` — `if not os.path.isfile(p):`
- `server/hub.py:1547` `open` — `with open(p, "rb") as f:`

#### `server/relay_server.py`

- `server/relay_server.py:50` `os.path.abspath` — `os.path.abspath(__file__)), "..", "app", "collab"))`
- `server/relay_server.py:67` `os.path.abspath` — `os.path.dirname(os.path.abspath(__file__)), "web")`
- `server/relay_server.py:79` `os.path.abspath` — `os.path.abspath(__file__)), "data"))`
- `server/relay_server.py:108` `os.path.isfile` — `if full is None or not os.path.isfile(full):`
- `server/relay_server.py:122` `open` — `with open(full, "rb") as f:`

#### `server/relaycore.py`

- `server/relaycore.py:344` `os.path.realpath` — `base = os.path.realpath(base)`
- `server/relaycore.py:345` `os.path.realpath` — `full = os.path.realpath(os.path.join(base, path.lstrip("/\\")))`

#### `tools/accuracy.py`

- `tools/accuracy.py:24` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/accuracy_real.py`

- `tools/accuracy_real.py:17` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/ada_index.py`

- `tools/ada_index.py:14` `os.path.abspath` — `HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/ada_index.py:169` `open` — `with open(src, encoding="utf-8") as f:`
- `tools/ada_index.py:183` `open` — `with open(out, "w", encoding="utf-8") as f:`

#### `tools/aerial_live.py`

- `tools/aerial_live.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/ai_check.py`

- `tools/ai_check.py:11` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/ai_takeoff_compare.py`

- `tools/ai_takeoff_compare.py:20` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/ai_takeoff_compare.py:73` `os.path.isfile` — `if not os.path.isfile(src):`
- `tools/ai_takeoff_compare.py:75` `os.path.isfile` — `if not os.path.isfile(os.path.join(old, "app", "aitakeoff.py")):`
- `tools/ai_takeoff_compare.py:79` `shutil.copy2` — `shutil.copy2(src, pdf)`
- `tools/ai_takeoff_compare.py:80` `os.chmod` — `os.chmod(pdf, 0o444)`
- `tools/ai_takeoff_compare.py:87` `open` — `with open(OUT + ".json", "w", encoding="utf-8") as f:`
- `tools/ai_takeoff_compare.py:99` `open` — `with open(OUT + ".txt", "w", encoding="utf-8") as f:`
- `tools/ai_takeoff_compare.py:102` `os.chmod` — `os.chmod(pdf, 0o666)`
- `tools/ai_takeoff_compare.py:103` `shutil.rmtree` — `shutil.rmtree(tmp, ignore_errors=True)`
- `tools/ai_takeoff_compare.py:109` `os.makedirs` — `os.makedirs(os.path.dirname(OUT), exist_ok=True)`
- `tools/ai_takeoff_compare.py:110` `open` — `with open(OUT + ".status", "w") as f:`
- `tools/ai_takeoff_compare.py:114` `open` — `log = open(OUT + ".log", "w", encoding="utf-8")`
- `tools/ai_takeoff_compare.py:115` `os.path.abspath` — `subprocess.Popen([sys.executable, os.path.abspath(__file__), "bg"] + argv,`
- `tools/ai_takeoff_compare.py:128` `open` — `with open(OUT + ".status", "w") as f:`
- `tools/ai_takeoff_compare.py:135` `open` — `with open(OUT + ext, encoding="utf-8", errors="replace") as f:`
- `tools/ai_takeoff_compare.py:139` `os.path.exists` — `if os.path.exists(OUT + ".txt"):`
- `tools/ai_takeoff_compare.py:140` `open` — `with open(OUT + ".txt", encoding="utf-8") as f:`

#### `tools/ai_takeoff_gui.py`

- `tools/ai_takeoff_gui.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/ai_takeoff_gui.py:16` `open` — `with open(LOG, "a", encoding="utf-8") as f:`
- `tools/ai_takeoff_gui.py:21` `open` — `open(LOG, "w").close()`
- `tools/ai_takeoff_gui.py:22` `open` — `faulthandler.enable(open(LOG + ".fault", "w"))`
- `tools/ai_takeoff_gui.py:53` `os.path.abspath` — `subprocess.Popen([sys.executable, os.path.abspath(__file__)] + args,`
- `tools/ai_takeoff_gui.py:57` `open` — `stderr=open(LOG + ".err", "w"))`

#### `tools/ai_takeoff_run.py`

- `tools/ai_takeoff_run.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/ai_takeoff_run.py:42` `open` — `with open(LOG, "a", encoding="utf-8") as f:`
- `tools/ai_takeoff_run.py:49` `open` — `open(LOG, "w").close()`
- `tools/ai_takeoff_run.py:50` `open` — `fh = open(LOG + ".fault", "w")`
- `tools/ai_takeoff_run.py:85` `os.path.abspath` — `subprocess.Popen([sys.executable, os.path.abspath(__file__)] + args,`
- `tools/ai_takeoff_run.py:88` `open` — `stdout=subprocess.DEVNULL, stderr=open(`

#### `tools/aiken_eval.py`

- `tools/aiken_eval.py:65` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/aiken_eval.py:141` `os.path.abspath` — `if FORBIDDEN.search(os.path.abspath(path)):`
- `tools/aiken_eval.py:151` `os.makedirs` — `os.makedirs(dst_dir, exist_ok=True)`
- `tools/aiken_eval.py:153` `os.stat` — `s = os.stat(src)`
- `tools/aiken_eval.py:154` `os.path.exists` — `if os.path.exists(dst):`
- `tools/aiken_eval.py:155` `os.stat` — `d = os.stat(dst)`
- `tools/aiken_eval.py:158` `os.chmod` — `os.chmod(dst, stat.S_IWRITE | stat.S_IREAD)`
- `tools/aiken_eval.py:160` `shutil.copy2` — `shutil.copy2(src, tmp)`
- `tools/aiken_eval.py:161` `os.path.getsize` — `if os.path.getsize(tmp) != s.st_size:`
- `tools/aiken_eval.py:162` `os.remove` — `os.remove(tmp)`
- `tools/aiken_eval.py:164` `os.replace` — `os.replace(tmp, dst)`
- `tools/aiken_eval.py:165` `os.chmod` — `os.chmod(dst, stat.S_IREAD)`
- `tools/aiken_eval.py:190` `open` — `self.f = open(path, "w", encoding="utf-8")`
- `tools/aiken_eval.py:327` `open` — `with open(path, "w", newline="", encoding="utf-8") as f:`
- `tools/aiken_eval.py:344` `open` — `with open(path, newline="", encoding="utf-8") as f:`
- `tools/aiken_eval.py:390` `open` — `with open(path, encoding="utf-8") as f:`
- `tools/aiken_eval.py:501` `open` — `with open(args.map, "rb") as fh:`
- `tools/aiken_eval.py:674` `os.makedirs` — `os.makedirs(out_dir, exist_ok=True)`
- `tools/aiken_eval.py:677` `os.path.exists` — `if os.path.exists(card):`
- `tools/aiken_eval.py:678` `open` — `print(open(card, encoding="utf-8").read())`
- `tools/aiken_eval.py:685` `open` — `with open(os.path.join(out_dir, "console.txt"), "w") as con:`
- `tools/aiken_eval.py:686` `os.path.abspath` — `subprocess.Popen([sys.executable, os.path.abspath(__file__)] +`
- `tools/aiken_eval.py:703` `os.path.exists` — `if os.path.exists(os.path.join(out_dir, "meta.json")):`
- `tools/aiken_eval.py:704` `open` — `meta = json.load(open(os.path.join(out_dir, "meta.json")))`
- `tools/aiken_eval.py:728` `open` — `with open(os.path.join(out_dir, "summary.txt"), "w",`
- `tools/aiken_eval.py:731` `open` — `with open(os.path.join(out_dir, "problems.txt"), "w",`
- `tools/aiken_eval.py:734` `open` — `with open(os.path.join(out_dir, "checks.txt"), "w",`
- `tools/aiken_eval.py:775` `open` — `with open(os.path.join(out_dir, "meta.json"), "w") as f:`
- `tools/aiken_eval.py:787` `open` — `with open(card, "w", encoding="utf-8") as f:`

#### `tools/aiken_fetch.py`

- `tools/aiken_fetch.py:9` `os.path.abspath` — `dst = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),`
- `tools/aiken_fetch.py:11` `os.makedirs` — `os.makedirs(dst, exist_ok=True)`
- `tools/aiken_fetch.py:13` `os.listdir` — `for f in os.listdir(src):`
- `tools/aiken_fetch.py:15` `shutil.copy2` — `shutil.copy2(os.path.join(src, f), os.path.join(dst, f))`

#### `tools/autoscale_compare.py`

- `tools/autoscale_compare.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/autoscale_compare.py:11` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`

#### `tools/autoscale_profile.py`

- `tools/autoscale_profile.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/autotakeoff_check.py`

- `tools/autotakeoff_check.py:10` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(`

#### `tools/autotakeoff_demo.py`

- `tools/autotakeoff_demo.py:5` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(`

#### `tools/autotakeoff_dump.py`

- `tools/autotakeoff_dump.py:7` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(`
- `tools/autotakeoff_dump.py:21` `os.makedirs` — `os.makedirs("trial_output", exist_ok=True)`
- `tools/autotakeoff_dump.py:28` `open` — `open(f"trial_output/at_p{pno + 1}.json", "w"))`

#### `tools/backup_folder.py`

- `tools/backup_folder.py:13` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/backup_folder.py:28` `shutil.copytree` — `shutil.copytree(ROOT, dest, ignore=ignore, dirs_exist_ok=True)`
- `tools/backup_folder.py:29` `os.walk` — `for _d, _s, files in os.walk(dest):`
- `tools/backup_folder.py:33` `os.path.exists` — `if os.path.exists(pricedb.path()):`

#### `tools/beta_keys.py`

- `tools/beta_keys.py:21` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/beta_keys.py:33` `open` — `with open(PRIV, "rb") as f:`
- `tools/beta_keys.py:49` `os.makedirs` — `os.makedirs(KEYS, exist_ok=True)`
- `tools/beta_keys.py:50` `os.path.exists` — `if os.path.exists(PRIV):`
- `tools/beta_keys.py:55` `open` — `with open(PRIV, "wb") as f:`
- `tools/beta_keys.py:60` `open` — `with open(os.path.join(KEYS, "README.txt"), "w") as f:`
- `tools/beta_keys.py:68` `open` — `with open(PUB, "w") as f:`
- `tools/beta_keys.py:83` `os.path.exists` — `new = not os.path.exists(LOG)`
- `tools/beta_keys.py:84` `open` — `with open(LOG, "a", newline="", encoding="utf-8") as f:`
- `tools/beta_keys.py:93` `open` — `with open(path, "w", encoding="utf-8") as f:`
- `tools/beta_keys.py:110` `os.path.exists` — `if not os.path.exists(LOG):`
- `tools/beta_keys.py:113` `open` — `with open(LOG, encoding="utf-8") as f:`

#### `tools/bigset.py`

- `tools/bigset.py:19` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/bigset.py:22` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/bigset.py:108` `os.path.getsize` — `print(f"File: {os.path.getsize(path) / 1e6:.0f} MB")`
- `tools/bigset.py:185` `open` — `with open(argv[argv.index("--json") + 1].strip('"'), "w",`
- `tools/bigset.py:192` `os.remove` — `os.remove(path)`

#### `tools/bls.py`

- `tools/bls.py:9` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`

#### `tools/build_installer.py`

- `tools/build_installer.py:28` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/build_installer.py:47` `open` — `with open(LOG, "a", encoding="utf-8") as f:`
- `tools/build_installer.py:52` `open` — `with open(STATUS, "w") as f:`
- `tools/build_installer.py:61` `open` — `with open(LOG, "a", encoding="utf-8") as f:`
- `tools/build_installer.py:75` `os.path.isfile` — `if os.path.isfile(c):`
- `tools/build_installer.py:89` `os.path.exists` — `if not os.path.exists(beta_keys.PRIV):`
- `tools/build_installer.py:96` `open` — `with open(os.path.join(data, "build.json"), "w", encoding="utf-8") as f:`
- `tools/build_installer.py:106` `os.path.isdir` — `if os.path.isdir(pub):`
- `tools/build_installer.py:107` `shutil.rmtree` — `shutil.rmtree(pub)`
- `tools/build_installer.py:108` `shutil.copytree` — `shutil.copytree(app_dir, pub)`
- `tools/build_installer.py:113` `os.remove` — `os.remove(f)`
- `tools/build_installer.py:116` `os.remove` — `os.remove(f) # the company's own mailbox / app`
- `tools/build_installer.py:121` `shutil.rmtree` — `shutil.rmtree(pub, ignore_errors=True)`
- `tools/build_installer.py:125` `open` — `with open(os.path.join(data, "build.json"), "w", encoding="utf-8") as f:`
- `tools/build_installer.py:128` `os.path.isfile` — `if os.path.isfile(f) and (`
- `tools/build_installer.py:145` `os.path.exists` — `if os.path.exists(ans):`
- `tools/build_installer.py:146` `os.remove` — `os.remove(ans)`
- `tools/build_installer.py:150` `open` — `with open(ans, encoding="utf-8") as f:`
- `tools/build_installer.py:198` `os.path.isfile` — `if not os.path.isfile(f):`
- `tools/build_installer.py:205` `os.path.getsize` — `if os.path.getsize(f) > 60e6:`
- `tools/build_installer.py:217` `open` — `with open(f, "rb") as fh:`
- `tools/build_installer.py:230` `os.walk` — `for base, dirs, files in os.walk(os.path.join(ROOT, d)):`
- `tools/build_installer.py:235` `os.path.exists` — `"splash.png") if os.path.exists(os.path.join(ROOT, f))]`
- `tools/build_installer.py:248` `os.path.isfile` — `missing = [p for p in needed if not os.path.isfile(p)]`
- `tools/build_installer.py:255` `os.path.getsize` — `f"({os.path.getsize(p)} bytes)")`
- `tools/build_installer.py:278` `os.path.exists` — `if os.path.exists(out):`
- `tools/build_installer.py:279` `os.remove` — `os.remove(out)`
- `tools/build_installer.py:285` `os.path.exists` — `if os.path.exists(out):`
- `tools/build_installer.py:287` `os.path.exists` — `if not os.path.exists(out):`
- `tools/build_installer.py:291` `open` — `with open(out) as fh:`
- `tools/build_installer.py:303` `open` — `with open(os.path.join(ROOT, "quantisheet_claims", "__init__.py"),`
- `tools/build_installer.py:314` `os.path.exists` — `if not (os.path.exists(spec) and os.path.exists(iss)):`
- `tools/build_installer.py:314` `os.path.exists` — `if not (os.path.exists(spec) and os.path.exists(iss)):`
- `tools/build_installer.py:320` `os.path.exists` — `if not skip_program or not os.path.exists(src):`
- `tools/build_installer.py:325` `os.path.exists` — `if not os.path.exists(exe):`
- `tools/build_installer.py:343` `os.path.exists` — `if not os.path.exists(out):`
- `tools/build_installer.py:356` `open` — `with open(p, encoding="utf-8") as fh:`
- `tools/build_installer.py:370` `os.makedirs` — `os.makedirs(os.path.dirname(LOG), exist_ok=True)`
- `tools/build_installer.py:371` `open` — `open(LOG, "w").close()`
- `tools/build_installer.py:378` `os.makedirs` — `os.makedirs(BUILD, exist_ok=True)`
- `tools/build_installer.py:381` `os.path.isfile` — `if os.path.isfile(f) and (`
- `tools/build_installer.py:395` `open` — `with open(f, encoding="utf-8") as fh:`
- `tools/build_installer.py:414` `os.path.exists` — `if not os.path.exists(os.path.join(ROOT, "app", "data",`
- `tools/build_installer.py:432` `os.path.isfile` — `if not os.path.isfile(exe):`
- `tools/build_installer.py:435` `os.path.getsize` — `size = sum(os.path.getsize(p) for p in glob.glob(`
- `tools/build_installer.py:437` `os.path.isfile` — `if os.path.isfile(p))`
- `tools/build_installer.py:460` `os.makedirs` — `os.makedirs(RELEASE, exist_ok=True)`
- `tools/build_installer.py:466` `os.makedirs` — `os.makedirs(out_dir, exist_ok=True)`
- `tools/build_installer.py:500` `os.path.getsize` — `f"({os.path.getsize(m) / 1e6:.0f} MB)")`
- `tools/build_installer.py:520` `os.makedirs` — `os.makedirs(os.path.dirname(LOG), exist_ok=True)`
- `tools/build_installer.py:523` `os.path.abspath` — `subprocess.Popen([sys.executable, os.path.abspath(__file__), mode],`
- `tools/build_installer.py:531` `os.path.exists` — `if os.path.exists(STATUS):`
- `tools/build_installer.py:532` `open` — `with open(STATUS) as fh:`
- `tools/build_installer.py:536` `os.path.exists` — `if os.path.exists(LOG):`
- `tools/build_installer.py:537` `open` — `with open(LOG, encoding="utf-8", errors="replace") as fh:`
- `tools/build_installer.py:544` `os.makedirs` — `os.makedirs(os.path.dirname(LOG), exist_ok=True)`
- `tools/build_installer.py:545` `open` — `open(LOG, "w").close()`

#### `tools/build_msix.py`

- `tools/build_msix.py:21` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/build_msix.py:58` `os.path.isfile` — `if not os.path.isfile(STORE_SPLASH):`
- `tools/build_msix.py:66` `shutil.copyfile` — `shutil.copyfile(STORE_SPLASH, f)`
- `tools/build_msix.py:78` `open` — `with open(found[0], encoding="utf-8") as f:`
- `tools/build_msix.py:82` `open` — `with open(found[0], "w", encoding="utf-8") as f:`
- `tools/build_msix.py:169` `os.makedirs` — `os.makedirs(dest, exist_ok=True)`
- `tools/build_msix.py:180` `os.path.isdir` — `if not os.path.isdir(SRC):`
- `tools/build_msix.py:183` `os.path.isfile` — `if not os.path.isfile(IDENTITY):`
- `tools/build_msix.py:184` `open` — `with open(IDENTITY, "w", encoding="utf-8") as f:`
- `tools/build_msix.py:186` `open` — `with open(IDENTITY, encoding="utf-8") as f:`
- `tools/build_msix.py:189` `os.path.isdir` — `if os.path.isdir(LAYOUT):`
- `tools/build_msix.py:190` `shutil.rmtree` — `shutil.rmtree(LAYOUT)`
- `tools/build_msix.py:192` `shutil.copytree` — `shutil.copytree(SRC, LAYOUT)`
- `tools/build_msix.py:196` `open` — `with open(os.path.join(LAYOUT, "AppxManifest.xml"), "w",`
- `tools/build_msix.py:203` `os.makedirs` — `os.makedirs(OUT_DIR, exist_ok=True)`
- `tools/build_msix.py:211` `os.path.getsize` — `print("package:", out, f"({os.path.getsize(out) / 1e6:.0f} MB)")`

#### `tools/check_detect.py`

- `tools/check_detect.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/check_detect.py:31` `os.path.exists` — `if exe != "powershell" and not os.path.exists(exe):`

#### `tools/check_installer.py`

- `tools/check_installer.py:14` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/check_installer.py:23` `os.path.getsize` — `print("setup:", setup, f"({os.path.getsize(setup) / 1e6:.0f} MB)")`
- `tools/check_installer.py:32` `os.path.exists` — `print("installed exe:", os.path.exists(exe))`
- `tools/check_installer.py:33` `os.path.exists` — `print("no agreement (1.0.0):", not os.path.exists(os.path.join(`
- `tools/check_installer.py:35` `os.path.exists` — `print("extras script:", os.path.exists(os.path.join(`
- `tools/check_installer.py:38` `os.path.exists` — `if os.path.exists(out):`
- `tools/check_installer.py:39` `os.remove` — `os.remove(out)`
- `tools/check_installer.py:43` `os.path.exists` — `if os.path.exists(out):`
- `tools/check_installer.py:44` `open` — `with open(out) as fh:`
- `tools/check_installer.py:55` `os.path.exists` — `os.path.exists(exe))`

#### `tools/check_msi.py`

- `tools/check_msi.py:19` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/check_msi.py:49` `os.path.abspath` — `msi = os.path.abspath(argv[0])`
- `tools/check_msi.py:76` `os.path.exists` — `if p.returncode != 0 and os.path.exists(log):`
- `tools/check_msi.py:77` `open` — `with open(log, encoding="utf-16", errors="replace") as f:`
- `tools/check_msi.py:81` `os.walk` — `for dirpath, _dirs, files in os.walk(target):`
- `tools/check_msi.py:88` `os.walk` — `for dirpath, _dirs, files in os.walk(app_dir):`
- `tools/check_msi.py:93` `os.path.exists` — `if not os.path.exists(b):`
- `tools/check_msi.py:103` `os.path.exists` — `print(" extra", extra, os.path.exists(os.path.join(inst,`
- `tools/check_msi.py:110` `shutil.rmtree` — `shutil.rmtree(tmp, ignore_errors=True)`

#### `tools/check_paykey_move.py`

- `tools/check_paykey_move.py:18` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/check_paykey_move.py:26` `os.path.isfile` — `return folder if os.path.isfile(db) else None`
- `tools/check_paykey_move.py:36` `os.path.isfile` — `if os.path.isfile(key):`
- `tools/check_paykey_move.py:37` `open` — `head = open(key, "rb").read(7)`
- `tools/check_paykey_move.py:45` `os.makedirs` — `os.makedirs(copy)`
- `tools/check_paykey_move.py:52` `os.path.isfile` — `if os.path.isfile(key):`
- `tools/check_paykey_move.py:53` `shutil.copy2` — `shutil.copy2(key, os.path.join(copy, "datakey.bin"))`
- `tools/check_paykey_move.py:64` `open` — `moved = open(os.path.join(copy, "datakey.bin"), "rb").read(7)`

#### `tools/check_settings_test_marks.py`

- `tools/check_settings_test_marks.py:26` `os.stat` — `st = os.stat(P)`
- `tools/check_settings_test_marks.py:30` `open` — `with open(P, encoding="utf-8") as f:`

#### `tools/check_signing_key.py`

- `tools/check_signing_key.py:6` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`
- `tools/check_signing_key.py:9` `os.path.exists` — `print("signing key present:", os.path.exists(beta_keys.PRIV))`

#### `tools/civil_bid.py`

- `tools/civil_bid.py:19` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/civil_debug.py`

- `tools/civil_debug.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/civil_probe.py`

- `tools/civil_probe.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/civil_real.py`

- `tools/civil_real.py:19` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/claim_sample.py`

- `tools/claim_sample.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/clean_settings_test_recent.py`

- `tools/clean_settings_test_recent.py:19` `open` — `with open(P, encoding="utf-8") as f:`
- `tools/clean_settings_test_recent.py:26` `shutil.copy2` — `shutil.copy2(P, bak)`
- `tools/clean_settings_test_recent.py:30` `open` — `with open(tmp, "w", encoding="utf-8") as f:`
- `tools/clean_settings_test_recent.py:32` `os.replace` — `os.replace(tmp, P)`

#### `tools/click_everything.py`

- `tools/click_everything.py:18` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/click_everything.py:22` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/click_everything.py:66` `os.makedirs` — `os.makedirs(os.path.dirname(prog_path), exist_ok=True)`
- `tools/click_everything.py:67` `open` — `prog = open(prog_path, "w", encoding="utf-8", buffering=1)`

#### `tools/climate_index.py`

- `tools/climate_index.py:12` `os.path.abspath` — `HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/climate_index.py:92` `open` — `with open(src, encoding="utf-8") as f:`
- `tools/climate_index.py:106` `open` — `with open(out, "w", encoding="utf-8") as f:`

#### `tools/codesign.py`

- `tools/codesign.py:34` `open` — `with open(CONFIG, encoding="utf-8") as f:`
- `tools/codesign.py:68` `os.path.isfile` — `files = [f for f in files if f and os.path.isfile(f)]`

#### `tools/company_check.py`

- `tools/company_check.py:6` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`

#### `tools/crash_seen.py`

- `tools/crash_seen.py:11` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
- `tools/crash_seen.py:17` `os.path.exists` — `print("crash.log:", crash, os.path.getsize(crash) if os.path.exists(crash)`
- `tools/crash_seen.py:17` `os.path.getsize` — `print("crash.log:", crash, os.path.getsize(crash) if os.path.exists(crash)`
- `tools/crash_seen.py:21` `open` — `seen = json.load(open(seen_p, encoding="utf-8"))`
- `tools/crash_seen.py:28` `open` — `text = open(crash, "rb").read()[start:].decode("utf-8", "replace")`

#### `tools/crash_wrap.py`

- `tools/crash_wrap.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/crop.py`

- `tools/crop.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/dark_sweep.py`

- `tools/dark_sweep.py:15` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/dark_sweep.py:17` `os.chdir` — `os.chdir(ROOT)`

#### `tools/deps_check.py`

- `tools/deps_check.py:6` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/desktop_icon.py`

- `tools/desktop_icon.py:12` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(`
- `tools/desktop_icon.py:38` `os.path.isfile` — `print("installed program:", APP, os.path.isfile(APP))`
- `tools/desktop_icon.py:40` `os.path.isfile` — `if not os.path.isfile(APP):`

#### `tools/diag.py`

- `tools/diag.py:2` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag.py:4` `open` — `out = open(sys.argv[2], "w", encoding="utf-8")`
- `tools/diag.py:13` `os.remove` — `os.remove(f)`

#### `tools/diag_aiken_actgrid.py`

- `tools/diag_aiken_actgrid.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag_aiken_actgrid.py:66` `os.makedirs` — `os.makedirs(os.path.dirname(out), exist_ok=True)`

#### `tools/diag_aiken_compete.py`

- `tools/diag_aiken_compete.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_crop.py`

- `tools/diag_aiken_crop.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag_aiken_crop.py:28` `os.makedirs` — `os.makedirs(os.path.dirname(out), exist_ok=True)`

#### `tools/diag_aiken_devlegend.py`

- `tools/diag_aiken_devlegend.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_ductcrop.py`

- `tools/diag_aiken_ductcrop.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag_aiken_ductcrop.py:77` `os.makedirs` — `os.makedirs(os.path.dirname(out), exist_ok=True)`

#### `tools/diag_aiken_ducts.py`

- `tools/diag_aiken_ducts.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag_aiken_ducts.py:66` `os.makedirs` — `os.makedirs(os.path.dirname(out), exist_ok=True)`

#### `tools/diag_aiken_fills.py`

- `tools/diag_aiken_fills.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_groups.py`

- `tools/diag_aiken_groups.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag_aiken_groups.py:15` `os.path.getmtime` — `print(f, os.path.getmtime(f))`
- `tools/diag_aiken_groups.py:16` `open` — `with open(f, newline="", encoding="utf-8") as fh:`

#### `tools/diag_aiken_legend.py`

- `tools/diag_aiken_legend.py:6` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_linetypes.py`

- `tools/diag_aiken_linetypes.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_lod.py`

- `tools/diag_aiken_lod.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_piperuns.py`

- `tools/diag_aiken_piperuns.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_pipes.py`

- `tools/diag_aiken_pipes.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag_aiken_pipes.py:73` `os.makedirs` — `os.makedirs(os.path.dirname(out), exist_ok=True)`

#### `tools/diag_aiken_probe.py`

- `tools/diag_aiken_probe.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_rotlegend.py`

- `tools/diag_aiken_rotlegend.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_rows.py`

- `tools/diag_aiken_rows.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_scale.py`

- `tools/diag_aiken_scale.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_sched.py`

- `tools/diag_aiken_sched.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag_aiken_sched.py:43` `os.makedirs` — `os.makedirs(os.path.dirname(out), exist_ok=True)`

#### `tools/diag_aiken_sf.py`

- `tools/diag_aiken_sf.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag_aiken_sf.py:67` `os.makedirs` — `os.makedirs(os.path.dirname(out), exist_ok=True)`

#### `tools/diag_aiken_stage3.py`

- `tools/diag_aiken_stage3.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_tags.py`

- `tools/diag_aiken_tags.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_text.py`

- `tools/diag_aiken_text.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_wallasm.py`

- `tools/diag_aiken_wallasm.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_aiken_walls.py`

- `tools/diag_aiken_walls.py:16` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag_aiken_walls.py:39` `os.makedirs` — `os.makedirs(out_dir, exist_ok=True)`

#### `tools/diag_aiken_walltypes.py`

- `tools/diag_aiken_walltypes.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag_aiken_walltypes.py:56` `os.makedirs` — `os.makedirs(os.path.dirname(outp), exist_ok=True)`

#### `tools/diag_aiken_words.py`

- `tools/diag_aiken_words.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_autoscale.py`

- `tools/diag_autoscale.py:11` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_crop_points.py`

- `tools/diag_crop_points.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag_crop_points.py:25` `os.makedirs` — `os.makedirs(out, exist_ok=True)`

#### `tools/diag_doors.py`

- `tools/diag_doors.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_eval_lines.py`

- `tools/diag_eval_lines.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag_eval_lines.py:17` `os.path.exists` — `if os.path.exists(con):`
- `tools/diag_eval_lines.py:18` `open` — `t = open(con, encoding="utf-8", errors="replace").read()`
- `tools/diag_eval_lines.py:23` `os.path.exists` — `if os.path.exists(fp):`
- `tools/diag_eval_lines.py:25` `open` — `print(open(fp, encoding="utf-8", errors="replace").read()[:6000])`
- `tools/diag_eval_lines.py:28` `os.path.exists` — `if not os.path.exists(f):`
- `tools/diag_eval_lines.py:31` `os.path.getmtime` — `print(f, os.path.getmtime(f))`
- `tools/diag_eval_lines.py:32` `open` — `with open(f, newline="", encoding="utf-8") as fh:`
- `tools/diag_eval_lines.py:39` `os.path.exists` — `if rx and os.path.exists(rv):`
- `tools/diag_eval_lines.py:41` `open` — `with open(rv, newline="", encoding="utf-8") as fh:`

#### `tools/diag_legend.py`

- `tools/diag_legend.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_maximize_real.py`

- `tools/diag_maximize_real.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_pdfsched.py`

- `tools/diag_pdfsched.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_redact.py`

- `tools/diag_redact.py:38` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`

#### `tools/diag_ribbon_width.py`

- `tools/diag_ribbon_width.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_sched_table.py`

- `tools/diag_sched_table.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_sched_tags.py`

- `tools/diag_sched_tags.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_segs.py`

- `tools/diag_segs.py:14` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/diag_segs.py:84` `os.makedirs` — `os.makedirs(os.path.dirname(out), exist_ok=True)`

#### `tools/diag_tag_leaders.py`

- `tools/diag_tag_leaders.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_tag_shapes.py`

- `tools/diag_tag_shapes.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_textedit_dark.py`

- `tools/diag_textedit_dark.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/diag_walls.py`

- `tools/diag_walls.py:4` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`

#### `tools/docs_probe.py`

- `tools/docs_probe.py:11` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/docs_probe.py:15` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`

#### `tools/dump_paths.py`

- `tools/dump_paths.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/dxf_app_trial2.py`

- `tools/dxf_app_trial2.py:5` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/fetch_ada.py`

- `tools/fetch_ada.py:12` `os.path.abspath` — `HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/fetch_ada.py:19` `os.makedirs` — `os.makedirs(OUT, exist_ok=True)`
- `tools/fetch_ada.py:31` `open` — `with open(tmp, "wb") as f:`
- `tools/fetch_ada.py:33` `os.replace` — `os.replace(tmp, PDF)`
- `tools/fetch_ada.py:42` `open` — `with open(os.path.join(OUT, "pages.json"), "w", encoding="utf-8") as f:`

#### `tools/fetch_climate.py`

- `tools/fetch_climate.py:13` `os.path.abspath` — `HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/fetch_climate.py:20` `os.makedirs` — `os.makedirs(OUT, exist_ok=True)`
- `tools/fetch_climate.py:32` `open` — `with open(PDF + ".part", "wb") as f:`
- `tools/fetch_climate.py:34` `os.replace` — `os.replace(PDF + ".part", PDF)`
- `tools/fetch_climate.py:40` `open` — `with open(os.path.join(OUT, "pages.json"), "w", encoding="utf-8") as f:`

#### `tools/fetch_logs.py`

- `tools/fetch_logs.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/fetch_logs.py:12` `os.makedirs` — `os.makedirs(out, exist_ok=True)`
- `tools/fetch_logs.py:15` `os.path.exists` — `if os.path.exists(p):`
- `tools/fetch_logs.py:16` `open` — `with open(p, "rb") as f:`
- `tools/fetch_logs.py:17` `os.path.getsize` — `f.seek(max(0, os.path.getsize(p) - keep))`
- `tools/fetch_logs.py:19` `open` — `with open(os.path.join(out, name), "wb") as f:`
- `tools/fetch_logs.py:21` `os.path.getsize` — `print(name, os.path.getsize(p), "bytes")`

#### `tools/fetch_ppi.py`

- `tools/fetch_ppi.py:4` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`

#### `tools/find_home_writers.py`

- `tools/find_home_writers.py:13` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/find_home_writers.py:21` `os.path.isdir` — `if not os.path.isdir(h):`
- `tools/find_home_writers.py:23` `os.listdir` — `for name in os.listdir(h):`
- `tools/find_home_writers.py:25` `os.path.isfile` — `if not os.path.isfile(p):`
- `tools/find_home_writers.py:27` `os.stat` — `st = os.stat(p)`
- `tools/find_home_writers.py:32` `open` — `with open(p, "rb") as f:`

#### `tools/find_in_backups.py`

- `tools/find_in_backups.py:17` `open` — `with open(f, encoding="utf-8", errors="replace") as fh:`

#### `tools/find_thumb_tools.py`

- `tools/find_thumb_tools.py:13` `os.path.isfile` — `print(os.path.basename(p), "->", os.path.isfile(p))`

#### `tools/font_probe.py`

- `tools/font_probe.py:5` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/font_probe.py:40` `os.path.isfile` — `if os.path.isfile(p):`

#### `tools/forms_add_aitem.py`

- `tools/forms_add_aitem.py:2` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/forms_add_aitem.py:10` `os.makedirs` — `os.makedirs(keep, exist_ok=True)`
- `tools/forms_add_aitem.py:11` `shutil.copyfile` — `shutil.copyfile(os.path.join(ROOT, ".run", "forms_in", "Action Item List.xlsx"),`

#### `tools/forms_check.py`

- `tools/forms_check.py:2` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/forms_check.py:6` `os.makedirs` — `out = os.path.join(ROOT, ".run", "forms_check"); os.makedirs(out, exist_ok=True)`

#### `tools/forms_install.py`

- `tools/forms_install.py:3` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/forms_probe.py`

- `tools/forms_probe.py:6` `os.walk` — `for dp, dn, fn in os.walk(root):`

#### `tools/genset_new_types.py`

- `tools/genset_new_types.py:6` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/genset_new_types.py:20` `os.makedirs` — `os.makedirs(out, exist_ok=True)`

#### `tools/genset_preview.py`

- `tools/genset_preview.py:6` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(`
- `tools/genset_preview.py:35` `os.makedirs` — `os.makedirs(out, exist_ok=True)`

#### `tools/genset_samples.py`

- `tools/genset_samples.py:11` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/genset_samples.py:27` `os.makedirs` — `os.makedirs(out, exist_ok=True)`
- `tools/genset_samples.py:48` `open` — `"sidecar kernel modulor": json.load(open(res["sidecar"]))[`

#### `tools/genset_text.py`

- `tools/genset_text.py:5` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/handles_probe.py`

- `tools/handles_probe.py:15` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/handles_probe.py:18` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/handles_probe.py:27` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tools/handles_probe.py:60` `shutil.copy` — `shutil.copy(src, path)`
- `tools/handles_probe.py:96` `shutil.rmtree` — `shutil.rmtree(TMP, ignore_errors=True)`

#### `tools/help_screens.py`

- `tools/help_screens.py:2` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/help_screens.py:5` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/help_screens.py:13` `os.makedirs` — `out = os.path.join(ROOT, ".run", "helpshots"); os.makedirs(out, exist_ok=True)`

#### `tools/import_contacts.py`

- `tools/import_contacts.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/install_info.py`

- `tools/install_info.py:10` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
- `tools/install_info.py:15` `os.path.getmtime` — `return datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime(`
- `tools/install_info.py:24` `os.path.exists` — `if os.path.exists(p):`
- `tools/install_info.py:25` `os.path.getsize` — `print(f" {n:16} {t(p)} {os.path.getsize(p):,} bytes")`
- `tools/install_info.py:37` `os.path.isdir` — `if f and os.path.isdir(f):`
- `tools/install_info.py:40` `os.path.getsize` — `print(f" {t(p)} {os.path.basename(p)} {os.path.getsize(p):,}")`
- `tools/install_info.py:44` `open` — `with open(p, encoding="utf-8-sig", errors="replace") as fh:`

#### `tools/install_modulor.py`

- `tools/install_modulor.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/install_modulor.py:16` `os.path.isfile` — `if not os.path.isfile(ZIP) and os.path.isfile(SPIKE):`
- `tools/install_modulor.py:16` `os.path.isfile` — `if not os.path.isfile(ZIP) and os.path.isfile(SPIKE):`
- `tools/install_modulor.py:18` `os.makedirs` — `os.makedirs(os.path.dirname(ZIP), exist_ok=True)`
- `tools/install_modulor.py:19` `shutil.copy2` — `shutil.copy2(SPIKE, ZIP)`
- `tools/install_modulor.py:21` `open` — `h = hashlib.sha256(open(ZIP, "rb").read()).hexdigest()`

#### `tools/install_release.py`

- `tools/install_release.py:11` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/install_release.py:30` `open` — `with open(STATUS) as fh:`
- `tools/install_release.py:32` `os.path.getmtime` — `age = time.time() - os.path.getmtime(STATUS)`
- `tools/install_release.py:49` `os.path.isfile` — `if not ONLY_CLAIMS and not os.path.isfile(setup): # claims-only needs none`
- `tools/install_release.py:63` `os.path.isfile` — `print("installed:", exe, os.path.isfile(exe))`
- `tools/install_release.py:79` `os.path.isfile` — `claims = [want] if want and os.path.isfile(want) else sorted(`
- `tools/install_release.py:91` `os.path.isfile` — `os.path.isfile(cexe))`

#### `tools/iscc_check.py`

- `tools/iscc_check.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/js_probe.py`

- `tools/js_probe.py:5` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/leader_debug.py`

- `tools/leader_debug.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/legend_timing.py`

- `tools/legend_timing.py:15` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/legend_timing.py:29` `shutil.copy2` — `shutil.copy2(argv[0], pdf)`
- `tools/legend_timing.py:66` `os.makedirs` — `os.makedirs(os.path.dirname(OUT), exist_ok=True)`
- `tools/legend_timing.py:67` `open` — `with open(OUT, "w", encoding="utf-8") as f:`

#### `tools/load_rates.py`

- `tools/load_rates.py:11` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/log_tail.py`

- `tools/log_tail.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/log_tail.py:14` `os.path.isfile` — `print("log:", p, os.path.isfile(p))`
- `tools/log_tail.py:15` `os.path.isfile` — `if os.path.isfile(p):`
- `tools/log_tail.py:16` `open` — `with open(p, encoding="utf-8", errors="replace") as f:`

#### `tools/lookahead_sample.py`

- `tools/lookahead_sample.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/make_admx.py`

- `tools/make_admx.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/make_admx.py:161` `os.makedirs` — `os.makedirs(os.path.join(d, "en-US"), exist_ok=True)`
- `tools/make_admx.py:164` `open` — `with open(path, "w", encoding="utf-8", newline="\r\n") as f:`

#### `tools/make_costsummary_golden.py`

- `tools/make_costsummary_golden.py:18` `os.path.realpath` — `real = os.path.realpath(os.path.join(os.path.expanduser("~"), _name))`
- `tools/make_costsummary_golden.py:19` `os.path.isdir` — `assert not os.path.isdir(real), "run with a temp HOME"`
- `tools/make_costsummary_golden.py:91` `os.makedirs` — `os.makedirs(out, exist_ok=True)`
- `tools/make_costsummary_golden.py:92` `open` — `with open(os.path.join(out, "golden_costsummary.json"), "w") as fh:`
- `tools/make_costsummary_golden.py:94` `open` — `with open(os.path.join(out, "golden_snapshot.json"), "w") as fh:`

#### `tools/make_fix_diffs.py`

- `tools/make_fix_diffs.py:13` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/make_fix_diffs.py:18` `open` — `with open(p, encoding="utf-8", newline="") as f:`
- `tools/make_fix_diffs.py:40` `open` — `with open(out, "w", encoding="utf-8", newline="\n") as f:`

#### `tools/make_msi.py`

- `tools/make_msi.py:39` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/make_msi.py:121` `os.path.isfile` — `if not os.path.isfile(exe):`
- `tools/make_msi.py:125` `os.path.abspath` — `out_path = os.path.abspath(out_path)`
- `tools/make_msi.py:126` `os.makedirs` — `os.makedirs(os.path.dirname(out_path), exist_ok=True)`
- `tools/make_msi.py:179` `os.listdir` — `names = sorted(os.listdir(path))`
- `tools/make_msi.py:182` `os.path.isfile` — `if os.path.isfile(p):`
- `tools/make_msi.py:187` `os.path.isdir` — `if os.path.isdir(p):`
- `tools/make_msi.py:206` `os.path.isdir` — `if os.path.isdir(os.path.join(app_dir, *rel.split("/"))):`
- `tools/make_msi.py:217` `os.path.isfile` — `if not os.path.isfile(f):`
- `tools/make_msi.py:371` `os.path.getsize` — `print(f"MSI {path}: {n} files, {os.path.getsize(path) / 1e6:.0f} MB, "`

#### `tools/make_shortcut.py`

- `tools/make_shortcut.py:6` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/make_update_key.py`

- `tools/make_update_key.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/make_update_manifest.py`

- `tools/make_update_manifest.py:25` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/make_update_manifest.py:38` `os.path.exists` — `if os.path.exists(key_path):`
- `tools/make_update_manifest.py:40` `os.path.abspath` — `if os.path.commonpath([os.path.abspath(key_path), ROOT]) == ROOT:`
- `tools/make_update_manifest.py:43` `os.makedirs` — `os.makedirs(os.path.dirname(os.path.abspath(key_path)), exist_ok=True)`
- `tools/make_update_manifest.py:43` `os.path.abspath` — `os.makedirs(os.path.dirname(os.path.abspath(key_path)), exist_ok=True)`
- `tools/make_update_manifest.py:44` `open` — `with open(key_path, "wb") as f:`
- `tools/make_update_manifest.py:50` `open` — `with open(_pub_path(), "w", encoding="utf-8") as f:`
- `tools/make_update_manifest.py:62` `open` — `with open(installer_bytes_path, "rb") as f:`
- `tools/make_update_manifest.py:89` `open` — `with open(args.key, "rb") as f:`
- `tools/make_update_manifest.py:93` `open` — `with open(args.notes_file, encoding="utf-8") as f:`
- `tools/make_update_manifest.py:98` `open` — `with open(args.out, "wb") as f:`

#### `tools/make_winget.py`

- `tools/make_winget.py:20` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/make_winget.py:35` `open` — `with open(path, encoding="utf-8") as f:`
- `tools/make_winget.py:108` `os.makedirs` — `os.makedirs(out, exist_ok=True)`
- `tools/make_winget.py:110` `open` — `with open(os.path.join(out, name), "w", encoding="utf-8",`

#### `tools/md5list.py`

- `tools/md5list.py:5` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/md5list.py:7` `os.walk` — `for dp, dn, fn in os.walk(os.path.join(ROOT, base)):`
- `tools/md5list.py:13` `open` — `with open(p, "rb") as fh:`

#### `tools/modern_screens.py`

- `tools/modern_screens.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/modern_screens.py:14` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/modern_screens.py:33` `os.makedirs` — `os.makedirs(out, exist_ok=True)`
- `tools/modern_screens.py:37` `os.path.isfile` — `pdf = argv[1] if len(argv) > 1 and os.path.isfile(argv[1]) else None`

#### `tools/modulor_spike.py`

- `tools/modulor_spike.py:20` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/modulor_spike.py:109` `open` — `h = hashlib.sha256(open(ZIP, "rb").read()).hexdigest()`
- `tools/modulor_spike.py:113` `os.makedirs` — `os.makedirs(BASE, exist_ok=True)`
- `tools/modulor_spike.py:114` `os.path.exists` — `if not os.path.exists(PY):`
- `tools/modulor_spike.py:132` `os.makedirs` — `os.makedirs(OUT, exist_ok=True)`
- `tools/modulor_spike.py:134` `open` — `open(script, "w", encoding="utf-8").write(CHECK)`
- `tools/modulor_spike.py:164` `open` — `open(script, "w", encoding="utf-8").write(FROZEN)`

#### `tools/move_meeting_shots.py`

- `tools/move_meeting_shots.py:12` `os.makedirs` — `os.makedirs(DST, exist_ok=True)`
- `tools/move_meeting_shots.py:15` `os.path.isfile` — `if not os.path.isfile(s):`
- `tools/move_meeting_shots.py:17` `os.path.exists` — `elif os.path.exists(d):`
- `tools/move_meeting_shots.py:20` `shutil.move` — `shutil.move(s, d)`

#### `tools/msi_trial.py`

- `tools/msi_trial.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/msi_trial.py:26` `os.path.getsize` — `print(f"built {path} ({os.path.getsize(path) / 1e6:.0f} MB, {n} files) "`

#### `tools/nav_screens.py`

- `tools/nav_screens.py:2` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/nav_screens.py:5` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/nav_screens.py:14` `os.makedirs` — `out = os.path.join(ROOT, ".run", "navshots"); os.makedirs(out, exist_ok=True)`

#### `tools/new_screens.py`

- `tools/new_screens.py:11` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/new_screens.py:16` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/new_screens.py:65` `os.makedirs` — `os.makedirs(out, exist_ok=True)`

#### `tools/or_font_diag.py`

- `tools/or_font_diag.py:19` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/owner_logs_sample.py`

- `tools/owner_logs_sample.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/owner_report_sample.py`

- `tools/owner_report_sample.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/page_turn_probe.py`

- `tools/page_turn_probe.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/page_turn_probe.py:18` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/page_turn_probe.py:42` `shutil.copy` — `shutil.copy(SRC, copy)`

#### `tools/pdf_revisions.py`

- `tools/pdf_revisions.py:46` `open` — `data = open(path, "rb").read()`
- `tools/pdf_revisions.py:47` `os.stat` — `st = os.stat(path)`
- `tools/pdf_revisions.py:81` `shutil.copy2` — `shutil.copy2(path, backup)`
- `tools/pdf_revisions.py:83` `open` — `with open(path, "r+b") as f:`
- `tools/pdf_revisions.py:86` `open` — `chk = annots_by_page(open(path, "rb").read())`

#### `tools/perf.py`

- `tools/perf.py:15` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/perf.py:19` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/perf.py:83` `os.path.getsize` — `print(f"{os.path.basename(path)}: {os.path.getsize(path) / 1e6:.0f} MB\n")`
- `tools/perf.py:198` `open` — `with open(argv[argv.index("--json") + 1].strip('"'), "w",`

#### `tools/perf_gate.py`

- `tools/perf_gate.py:29` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/perf_gate.py:50` `open` — `with open(js, encoding="utf-8") as f:`
- `tools/perf_gate.py:54` `os.remove` — `os.remove(js)`
- `tools/perf_gate.py:75` `os.makedirs` — `os.makedirs(os.path.dirname(log), exist_ok=True)`
- `tools/perf_gate.py:78` `open` — `with open(log, "w", encoding="utf-8") as f:`
- `tools/perf_gate.py:79` `os.path.abspath` — `subprocess.Popen([sys.executable, os.path.abspath(__file__), *argv],`
- `tools/perf_gate.py:90` `os.makedirs` — `os.makedirs(os.path.dirname(LAST), exist_ok=True)`
- `tools/perf_gate.py:91` `open` — `with open(LAST, "w", encoding="utf-8") as f:`
- `tools/perf_gate.py:94` `open` — `with open(BUDGETS, "w", encoding="utf-8") as f:`
- `tools/perf_gate.py:98` `open` — `with open(BUDGETS, encoding="utf-8") as f:`

#### `tools/pip_install.py`

- `tools/pip_install.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/pm2_diag.py`

- `tools/pm2_diag.py:27` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/pm2_diag.py:102` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tools/pm2_diag.py:278` `open` — `d = fitz.open("pdf", open(src, "rb").read())`
- `tools/pm2_diag.py:282` `open` — `d = fitz.open("pdf", open(src, "rb").read())`
- `tools/pm2_diag.py:403` `os.replace` — `os.replace(tmp, path)`
- `tools/pm2_diag.py:438` `os.replace` — `os.replace(tmp, path)`
- `tools/pm2_diag.py:467` `os.listdir` — `path = sample(os.path.join(TMP, f"qt_{len(os.listdir(TMP))}.pdf"))`
- `tools/pm2_diag.py:518` `shutil.rmtree` — `shutil.rmtree(TMP, ignore_errors=True)`

#### `tools/pm_screens.py`

- `tools/pm_screens.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/pm_screens.py:13` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/pm_screens.py:189` `os.makedirs` — `os.makedirs(out, exist_ok=True)`

#### `tools/practice_dropbox_inbox.py`

- `tools/practice_dropbox_inbox.py:21` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/practice_dropbox_inbox.py:94` `shutil.rmtree` — `shutil.rmtree(tmp, ignore_errors=True)`

#### `tools/preview_simple_menu.py`

- `tools/preview_simple_menu.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/preview_simple_menu.py:13` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/preview_simple_menu.py:30` `os.makedirs` — `os.makedirs(out, exist_ok=True)`

#### `tools/printer_trial.py`

- `tools/printer_trial.py:18` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/printer_trial.py:21` `os.path.exists` — `if not os.path.exists(PY):`
- `tools/printer_trial.py:34` `os.path.exists` — `if os.path.exists(OUT):`
- `tools/printer_trial.py:35` `os.remove` — `os.remove(OUT)`
- `tools/printer_trial.py:37` `open` — `with open(script, "w", encoding="utf-8-sig") as f:`
- `tools/printer_trial.py:51` `open` — `with open(OUT, encoding="utf-16", errors="replace") as f:`
- `tools/printer_trial.py:57` `open` — `with open(OUT, encoding="utf-8", errors="replace") as f:`
- `tools/printer_trial.py:66` `os.path.exists` — `if os.path.exists(OUT):`
- `tools/printer_trial.py:67` `os.remove` — `os.remove(OUT)`
- `tools/printer_trial.py:69` `open` — `with open(script, "w", encoding="utf-8-sig") as f:`
- `tools/printer_trial.py:79` `open` — `with open(OUT, encoding=enc) as f:`
- `tools/printer_trial.py:119` `open` — `with open(f, "rb") as fh:`
- `tools/printer_trial.py:122` `os.path.getsize` — `f"({os.path.getsize(f)} bytes, starts {head!r})")`
- `tools/printer_trial.py:187` `os.path.exists` — `before = os.path.getmtime(port) if os.path.exists(port) else 0`
- `tools/printer_trial.py:187` `os.path.getmtime` — `before = os.path.getmtime(port) if os.path.exists(port) else 0`
- `tools/printer_trial.py:194` `os.path.exists` — `if os.path.exists(port) and os.path.getmtime(port) > before:`
- `tools/printer_trial.py:194` `os.path.getmtime` — `if os.path.exists(port) and os.path.getmtime(port) > before:`
- `tools/printer_trial.py:198` `os.path.exists` — `if os.path.exists(port):`
- `tools/printer_trial.py:199` `open` — `with open(port, "rb") as f:`
- `tools/printer_trial.py:204` `os.path.getsize` — `print(f"file port wrote {os.path.getsize(port)} bytes, starts "`
- `tools/printer_trial.py:213` `open` — `with open(r"\\.\pipe\QuantiSheetPrint", "wb") as f:`
- `tools/printer_trial.py:234` `open` — `print("### helper log\n", open(log, encoding="utf-8",`

#### `tools/probe_msi.py`

- `tools/probe_msi.py:32` `os.path.exists` — `print("dotnet global tool wix:", os.path.exists(tools), tools)`

#### `tools/probe_open.py`

- `tools/probe_open.py:15` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/probe_open.py:208` `shutil.copy2` — `shutil.copy2(src, pdf)`
- `tools/probe_open.py:209` `os.path.getsize` — `print("copy", os.path.getsize(pdf), "bytes", flush=True)`
- `tools/probe_open.py:214` `shutil.rmtree` — `shutil.rmtree(tmp, ignore_errors=True)`

#### `tools/profile_open.py`

- `tools/profile_open.py:11` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/profile_open.py:14` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`

#### `tools/profile_start.py`

- `tools/profile_start.py:17` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/profile_start.py:25` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`

#### `tools/profile_ui.py`

- `tools/profile_ui.py:14` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/profile_ui.py:18` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`

#### `tools/profile_walls.py`

- `tools/profile_walls.py:2` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/pymupdf2_trial.py`

- `tools/pymupdf2_trial.py:17` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/pymupdf2_trial.py:39` `os.path.exists` — `if not os.path.exists(base):`
- `tools/pymupdf2_trial.py:41` `os.path.exists` — `if not os.path.exists(_py(VENV)):`
- `tools/pymupdf2_trial.py:60` `open` — `with open(os.path.join(new_site, "zz_main_venv.pth"), "w",`
- `tools/pymupdf2_trial.py:69` `os.path.exists` — `if not os.path.exists(_py(VENV)):`
- `tools/pymupdf2_trial.py:85` `os.path.exists` — `if not os.path.exists(_py(VENV)):`

#### `tools/rail_click_probe.py`

- `tools/rail_click_probe.py:13` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/rail_click_probe.py:18` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/rail_click_probe.py:31` `open` — `with open(REAL, encoding="utf-8") as f:`
- `tools/rail_click_probe.py:122` `os.path.isfile` — `if os.path.isfile(big):`
- `tools/rail_click_probe.py:125` `shutil.copy` — `shutil.copy(big, copy)`

#### `tools/release_files.py`

- `tools/release_files.py:26` `open` — `with open(path, "rb") as f:`
- `tools/release_files.py:62` `os.path.isdir` — `if os.path.isdir(gh):`
- `tools/release_files.py:68` `open` — `with open(sums, "w", newline="\n") as f:`
- `tools/release_files.py:70` `os.path.exists` — `elif os.path.exists(sums):`
- `tools/release_files.py:71` `os.remove` — `os.remove(sums) # nothing to vouch for`
- `tools/release_files.py:75` `os.path.isfile` — `if os.path.isfile(src):`
- `tools/release_files.py:76` `shutil.copyfile` — `shutil.copyfile(src, dst)`
- `tools/release_files.py:78` `os.path.exists` — `elif os.path.exists(dst):`
- `tools/release_files.py:79` `os.remove` — `os.remove(dst) # an old version's notes`
- `tools/release_files.py:81` `os.path.isfile` — `if os.path.isfile(setup):`
- `tools/release_files.py:87` `open` — `with open(rd, "w", newline="") as f:`
- `tools/release_files.py:94` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/release_hashes.py`

- `tools/release_hashes.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/release_hashes.py:17` `open` — `with open(p, "rb") as f:`

#### `tools/rename_old_names.py`

- `tools/rename_old_names.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/rename_old_names.py:16` `os.path.isdir` — `if os.path.isdir(new):`
- `tools/rename_old_names.py:18` `os.path.isdir` — `elif not os.path.isdir(old):`
- `tools/rename_old_names.py:21` `os.rename` — `os.rename(old, new)`
- `tools/rename_old_names.py:23` `os.listdir` — `print(" files:", sorted(os.listdir(new)))`
- `tools/rename_old_names.py:36` `os.path.isfile` — `if not os.path.isfile(src):`
- `tools/rename_old_names.py:39` `os.path.exists` — `if os.path.exists(dst):`
- `tools/rename_old_names.py:42` `os.makedirs` — `os.makedirs(os.path.dirname(dst), exist_ok=True)`
- `tools/rename_old_names.py:43` `shutil.move` — `shutil.move(src, dst)`
- `tools/rename_old_names.py:45` `os.path.isdir` — `print("left in", OUT if os.path.isdir(OUT) else "(nothing moved)")`

#### `tools/render_probe.py`

- `tools/render_probe.py:14` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/review_copy.py`

- `tools/review_copy.py:22` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/review_copy.py:36` `os.path.abspath` — `top = os.path.abspath(d) == ROOT`
- `tools/review_copy.py:39` `os.path.isdir` — `if n in SKIP_DIRS or (n.startswith(".") and os.path.isdir(p)):`
- `tools/review_copy.py:41` `os.path.isfile` — `elif top and os.path.isfile(p) and not n.lower().endswith(`
- `tools/review_copy.py:52` `open` — `text = open(diff_path, encoding="utf-8").read()`
- `tools/review_copy.py:59` `open` — `src = open(path, encoding="utf-8").read()`
- `tools/review_copy.py:72` `open` — `with open(path, "w", encoding="utf-8", newline="\n") as f:`
- `tools/review_copy.py:78` `os.path.abspath` — `zip_path = os.path.abspath(zip_path)`
- `tools/review_copy.py:80` `os.path.isdir` — `if os.path.isdir(d):`
- `tools/review_copy.py:81` `shutil.rmtree` — `shutil.rmtree(d)`
- `tools/review_copy.py:82` `shutil.copytree` — `shutil.copytree(ROOT, COPY, ignore=_ignore)`
- `tools/review_copy.py:90` `os.path.exists` — `if os.path.exists(diff):`
- `tools/review_copy.py:109` `os.makedirs` — `os.makedirs(env[k], exist_ok=True)`
- `tools/review_copy.py:118` `shutil.rmtree` — `shutil.rmtree(home, ignore_errors=True)`
- `tools/review_copy.py:125` `os.path.isdir` — `if not os.path.isdir(BARE):`
- `tools/review_copy.py:126` `shutil.copytree` — `shutil.copytree(COPY, BARE)`
- `tools/review_copy.py:127` `shutil.rmtree` — `shutil.rmtree(os.path.join(BARE, module), ignore_errors=True)`

#### `tools/room_debug.py`

- `tools/room_debug.py:17` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/room_debug.py:34` `shutil.copy2` — `shutil.copy2(src, pdf)`
- `tools/room_debug.py:70` `open` — `with open(OUT + ".txt", "w", encoding="utf-8") as f:`
- `tools/room_debug.py:98` `shutil.rmtree` — `shutil.rmtree(tmp, ignore_errors=True)`

#### `tools/rooms_debug.py`

- `tools/rooms_debug.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/rooms_debug.py:27` `os.makedirs` — `os.makedirs(OUT, exist_ok=True)`

#### `tools/rooms_real.py`

- `tools/rooms_real.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/rooms_real.py:21` `os.makedirs` — `os.makedirs(OUT, exist_ok=True)`

#### `tools/run_tests.py`

- `tools/run_tests.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/run_tests.py:10` `open` — `with open(out, "w", encoding="utf-8") as f:`
- `tools/run_tests.py:14` `open` — `with open(out, encoding="utf-8", errors="replace") as f:`

#### `tools/runner.py`

- `tools/runner.py:15` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/runner.py:18` `os.path.exists` — `if not os.path.exists(PY):`
- `tools/runner.py:23` `open` — `with open(req, encoding="utf-8") as f:`
- `tools/runner.py:32` `os.path.isfile` — `if not os.path.isfile(script):`
- `tools/runner.py:92` `open` — `with open(f"/proc/{int(pid)}/cmdline", "rb") as f:`
- `tools/runner.py:112` `open` — `with open(alive) as f:`
- `tools/runner.py:128` `os.makedirs` — `os.makedirs(RUN, exist_ok=True)`
- `tools/runner.py:131` `os.path.exists` — `if os.path.exists(stop):`
- `tools/runner.py:132` `os.remove` — `os.remove(stop)`
- `tools/runner.py:134` `open` — `with open(os.path.join(RUN, "runner.alive"), "w") as f:`
- `tools/runner.py:136` `os.path.exists` — `while time.time() < end and not os.path.exists(stop):`
- `tools/runner.py:137` `os.listdir` — `for name in sorted(os.listdir(RUN)):`
- `tools/runner.py:144` `os.replace` — `os.replace(req, work) # claim it`
- `tools/runner.py:151` `open` — `with open(out + ".tmp", "w", encoding="utf-8") as f:`
- `tools/runner.py:153` `os.replace` — `os.replace(out + ".tmp", out)`
- `tools/runner.py:154` `os.remove` — `os.remove(work)`
- `tools/runner.py:157` `os.remove` — `os.remove(os.path.join(RUN, "runner.alive"))`

#### `tools/sbom.py`

- `tools/sbom.py:85` `os.path.abspath` — `return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/sbom.py:154` `os.path.isfile` — `if os.path.isfile(path):`
- `tools/sbom.py:155` `open` — `with open(path, encoding="utf-8") as fh:`
- `tools/sbom.py:159` `os.path.isfile` — `if os.path.isfile(path):`
- `tools/sbom.py:160` `open` — `with open(path, encoding="utf-8") as fh:`
- `tools/sbom.py:266` `open` — `with open(path, encoding="utf-8") as fh:`
- `tools/sbom.py:373` `os.makedirs` — `os.makedirs(out_dir, exist_ok=True)`
- `tools/sbom.py:376` `open` — `with open(cdx, "w", encoding="utf-8") as fh:`
- `tools/sbom.py:379` `open` — `with open(txt, "w", encoding="utf-8") as fh:`
- `tools/sbom.py:392` `os.path.abspath` — `root = os.path.abspath(args.root or repo_root())`
- `tools/sbom.py:393` `os.path.abspath` — `out = os.path.abspath(args.out or default_out(root))`

#### `tools/scanset.py`

- `tools/scanset.py:17` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/scanset.py:21` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/scanset.py:68` `os.path.getsize` — `print(f"File: {os.path.getsize(path) / 1e6:.0f} MB")`
- `tools/scanset.py:119` `open` — `with open(argv[argv.index("--json") + 1].strip('"'), "w",`
- `tools/scanset.py:123` `os.remove` — `os.remove(path)`

#### `tools/sched_check.py`

- `tools/sched_check.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/schedule_real.py`

- `tools/schedule_real.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/scratch_leader.py`

- `tools/scratch_leader.py:2` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/screenshot.py`

- `tools/screenshot.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/screenshot.py:15` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/screenshot.py:66` `os.makedirs` — `os.makedirs(out, exist_ok=True)`

#### `tools/seal_contacts.py`

- `tools/seal_contacts.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/seal_contacts.py:18` `open` — `back = sealed_contacts.unseal(open(sealed_contacts.FILE, "rb").read(), pw)`

#### `tools/serve_upload.py`

- `tools/serve_upload.py:20` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/serve_upload.py:28` `os.listdir` — `for d in os.listdir(UP):`
- `tools/serve_upload.py:30` `os.path.isdir` — `if os.path.isdir(p):`
- `tools/serve_upload.py:55` `os.listdir` — `body = json.dumps(sorted(os.listdir(self.folder))).encode()`
- `tools/serve_upload.py:57` `os.path.isfile` — `elif name and os.path.isfile(p):`
- `tools/serve_upload.py:58` `open` — `with open(p, "rb") as f:`
- `tools/serve_upload.py:81` `open` — `with open(STATE, "w") as f:`
- `tools/serve_upload.py:84` `os.listdir` — `"files": sorted(os.listdir(folder))}, f)`
- `tools/serve_upload.py:98` `open` — `print(open(STATE).read() if os.path.exists(STATE) else "starting")`
- `tools/serve_upload.py:98` `os.path.exists` — `print(open(STATE).read() if os.path.exists(STATE) else "starting")`
- `tools/serve_upload.py:102` `open` — `print(open(STATE).read() if os.path.exists(STATE) else "not running")`
- `tools/serve_upload.py:102` `os.path.exists` — `print(open(STATE).read() if os.path.exists(STATE) else "not running")`

#### `tools/set_company.py`

- `tools/set_company.py:9` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
- `tools/set_company.py:16` `os.path.isfile` — `if not c.get("logo") and os.path.isfile(logo):`

#### `tools/setup_costbooks.py`

- `tools/setup_costbooks.py:6` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(`
- `tools/setup_costbooks.py:20` `os.path.abspath` — `os.path.abspath(__file__))), path)`
- `tools/setup_costbooks.py:31` `os.path.exists` — `if os.path.exists(old):`
- `tools/setup_costbooks.py:32` `os.replace` — `os.replace(old, old + ".old")`

#### `tools/sheet_probe.py`

- `tools/sheet_probe.py:11` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/sheet_probe.py:22` `os.path.isfile` — `if os.path.isfile(target):`
- `tools/sheet_probe.py:25` `os.walk` — `for d, dirs, fs in os.walk(target):`

#### `tools/ship_check.py`

- `tools/ship_check.py:136` `os.walk` — `for base, _dirs, files in os.walk(root):`
- `tools/ship_check.py:213` `os.path.isfile` — `if os.path.isfile(root):`
- `tools/ship_check.py:217` `os.walk` — `for base, _dirs, names in os.walk(root):`
- `tools/ship_check.py:225` `os.path.getsize` — `if os.path.getsize(p) > MAX_SCAN:`
- `tools/ship_check.py:227` `open` — `with open(p, "rb") as f:`

#### `tools/shot_measure.py`

- `tools/shot_measure.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/shot_measure.py:11` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/shot_measure.py:30` `shutil.copy` — `shutil.copy(src, cp)`

#### `tools/shot_project_calendar.py`

- `tools/shot_project_calendar.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/shot_project_calendar.py:12` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/shot_project_calendar.py:59` `os.makedirs` — `os.makedirs(os.path.dirname(out), exist_ok=True)`

#### `tools/shot_scheduler.py`

- `tools/shot_scheduler.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/shot_scheduler.py:11` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`

#### `tools/shot_takeoff.py`

- `tools/shot_takeoff.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/shot_takeoff.py:11` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/shot_takeoff.py:29` `shutil.copy` — `shutil.copy(src, cp)`

#### `tools/shot_timeoff.py`

- `tools/shot_timeoff.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/shot_timeoff.py:12` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"): # real text offscreen`
- `tools/shot_timeoff.py:63` `os.makedirs` — `os.makedirs(os.path.dirname(out), exist_ok=True)`

#### `tools/show_logs.py`

- `tools/show_logs.py:10` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
- `tools/show_logs.py:17` `os.path.exists` — `if not os.path.exists(p):`
- `tools/show_logs.py:20` `os.stat` — `st = os.stat(p)`
- `tools/show_logs.py:23` `open` — `with open(p, encoding="utf-8", errors="replace") as f:`

#### `tools/show_scales.py`

- `tools/show_scales.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/sig_check.py`

- `tools/sig_check.py:35` `os.path.isfile` — `if not os.path.isfile(p):`
- `tools/sig_check.py:39` `open` — `with open(p, "rb") as f:`
- `tools/sig_check.py:42` `os.path.getsize` — `print(" size", os.path.getsize(p), "sha256", h.hexdigest())`

#### `tools/sign_team_update.py`

- `tools/sign_team_update.py:18` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/sign_team_update.py:31` `os.path.isfile` — `if not os.path.isfile(KEY):`
- `tools/sign_team_update.py:34` `os.path.isfile` — `if not os.path.isfile(src):`
- `tools/sign_team_update.py:38` `os.makedirs` — `os.makedirs(out, exist_ok=True)`
- `tools/sign_team_update.py:45` `os.path.isfile` — `if os.path.isfile(notes):`
- `tools/sign_team_update.py:50` `shutil.copy2` — `shutil.copy2(src, os.path.join(out, SETUP))`
- `tools/sign_team_update.py:54` `os.listdir` — `for n in sorted(os.listdir(out)):`
- `tools/sign_team_update.py:55` `os.path.getsize` — `print(" ", n, os.path.getsize(os.path.join(out, n)), "bytes")`

#### `tools/site_layers_probe.py`

- `tools/site_layers_probe.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/site_layers_probe.py:16` `os.makedirs` — `os.makedirs(out, exist_ok=True)`
- `tools/site_layers_probe.py:30` `open` — `open(os.path.join(out, key + ".png"), "wb").write(data)`

#### `tools/smoke_src.py`

- `tools/smoke_src.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/smoke_src.py:21` `os.path.exists` — `if os.path.exists(out):`
- `tools/smoke_src.py:22` `open` — `with open(out) as fh:`

#### `tools/snap_probe.py`

- `tools/snap_probe.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/stage3_shots.py`

- `tools/stage3_shots.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/stage3_shots.py:14` `os.path.isdir` — `if os.path.isdir(r"C:\\Windows\\Fonts"):`
- `tools/stage3_shots.py:31` `os.makedirs` — `os.makedirs(out, exist_ok=True)`
- `tools/stage3_shots.py:37` `os.makedirs` — `os.makedirs(jobs, exist_ok=True)`

#### `tools/stdio_probe.py`

- `tools/stdio_probe.py:13` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/stdio_probe.py:42` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tools/stdio_probe.py:48` `shutil.copy` — `shutil.copy(src, path)`
- `tools/stdio_probe.py:105` `shutil.rmtree` — `shutil.rmtree(TMP, ignore_errors=True)`

#### `tools/stress_new.py`

- `tools/stress_new.py:20` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/stress_new.py:23` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/stress_new.py:34` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tools/stress_new.py:69` `shutil.copy` — `shutil.copy(plans_src, plans)`
- `tools/stress_new.py:70` `shutil.copy` — `shutil.copy(specs_src, specs)`
- `tools/stress_new.py:265` `os.path.getsize` — `return f"{os.path.getsize(out) / 1e6:.1f} MB, no job data"`
- `tools/stress_new.py:393` `open` — `with open(os.path.join(ROOT, ".run", "stress_new.json"), "w",`
- `tools/stress_new.py:396` `shutil.rmtree` — `shutil.rmtree(TMP, ignore_errors=True)`

#### `tools/sync_server.py`

- `tools/sync_server.py:15` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/sync_server.py:26` `os.path.exists` — `if not os.path.exists(b):`
- `tools/sync_server.py:28` `open` — `with open(a, "rb") as fa, open(b, "rb") as fb:`
- `tools/sync_server.py:28` `open` — `with open(a, "rb") as fa, open(b, "rb") as fb:`
- `tools/sync_server.py:41` `shutil.copyfile` — `shutil.copyfile(src, dst)`

#### `tools/testfiles.py`

- `tools/testfiles.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/tests_timed.py`

- `tools/tests_timed.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/theme_probe.py`

- `tools/theme_probe.py:11` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tools/thumbs.py`

- `tools/thumbs.py:19` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/thumbs.py:38` `os.path.isfile` — `if os.path.isfile(p):`
- `tools/thumbs.py:47` `os.path.isfile` — `hit = next((h for h in hits if os.path.isfile(h)), None)`
- `tools/thumbs.py:55` `os.makedirs` — `os.makedirs(OUT, exist_ok=True)`
- `tools/thumbs.py:91` `os.path.isfile` — `if not os.path.isfile(DLL):`
- `tools/thumbs.py:139` `os.path.isfile` — `print("dll:", DLL, os.path.isfile(DLL))`

#### `tools/tidy.py`

- `tools/tidy.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/tidy.py:25` `os.listdir` — `for name in sorted(os.listdir(TOOLS)):`
- `tools/tidy.py:27` `os.path.isfile` — `if os.path.isfile(full) and any(fnmatch.fnmatch(name, p)`
- `tools/tidy.py:32` `os.path.isfile` — `if os.path.isfile(full):`
- `tools/tidy.py:36` `os.path.isfile` — `if os.path.isfile(full):`
- `tools/tidy.py:45` `os.makedirs` — `os.makedirs(SCRATCH, exist_ok=True)`
- `tools/tidy.py:46` `open` — `with open(os.path.join(SCRATCH, "README.txt"), "w") as f:`
- `tools/tidy.py:53` `shutil.move` — `shutil.move(a, b)`
- `tools/tidy.py:57` `os.remove` — `os.remove(d)`

#### `tools/time_installed.py`

- `tools/time_installed.py:84` `os.path.abspath` — `os.path.abspath(__file__))))`
- `tools/time_installed.py:87` `os.path.exists` — `print("exe:", exe, "exists" if os.path.exists(exe) else "MISSING",`
- `tools/time_installed.py:101` `os.path.exists` — `if os.path.exists(marks):`
- `tools/time_installed.py:102` `os.remove` — `os.remove(marks)`
- `tools/time_installed.py:132` `os.path.exists` — `while not os.path.exists(marks) and time.time() - t1 < 30:`
- `tools/time_installed.py:136` `open` — `with open(marks, encoding="utf-8") as f:`

#### `tools/time_launch.py`

- `tools/time_launch.py:15` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/time_launch.py:27` `os.path.isfile` — `if not os.path.isfile(exe):`
- `tools/time_launch.py:37` `os.path.isfile` — `if os.path.isfile(out):`
- `tools/time_launch.py:38` `open` — `with open(out, encoding="utf-8") as f:`

#### `tools/trade_screens.py`

- `tools/trade_screens.py:3` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/trade_screens.py:6` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/trade_screens.py:19` `os.makedirs` — `os.makedirs(out, exist_ok=True)`

#### `tools/trial_copy.py`

- `tools/trial_copy.py:17` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/trial_copy.py:26` `os.path.isdir` — `if os.path.isdir(d):`
- `tools/trial_copy.py:27` `shutil.rmtree` — `shutil.rmtree(d) # only ever the trial copy`
- `tools/trial_copy.py:38` `os.walk` — `for base, _dirs, files in os.walk(ov):`
- `tools/trial_copy.py:43` `os.makedirs` — `os.makedirs(os.path.dirname(out), exist_ok=True)`
- `tools/trial_copy.py:44` `shutil.copyfile` — `shutil.copyfile(src, out)`
- `tools/trial_copy.py:83` `open` — `with open(os.path.join(d, f"trial-full-{start:%H%M%S}.txt"), "w",`

#### `tools/trial_excel_roundtrip.py`

- `tools/trial_excel_roundtrip.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/trial_excel_roundtrip.py:33` `os.path.getsize` — `print("template made:", os.path.getsize(path), "bytes")`
- `tools/trial_excel_roundtrip.py:89` `shutil.rmtree` — `shutil.rmtree(tmp, ignore_errors=True)`

#### `tools/trial_master_real.py`

- `tools/trial_master_real.py:17` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/trial_master_real.py:80` `shutil.copy2` — `shutil.copy2(f, q)`
- `tools/trial_master_real.py:119` `shutil.rmtree` — `shutil.rmtree(tmp, ignore_errors=True)`

#### `tools/trial_run.py`

- `tools/trial_run.py:12` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
- `tools/trial_run.py:20` `os.path.abspath` — `OUT = os.path.join(os.path.dirname(os.path.abspath(REPORT)), "trial_output")`
- `tools/trial_run.py:21` `os.makedirs` — `os.makedirs(OUT, exist_ok=True)`
- `tools/trial_run.py:28` `open` — `with open(REPORT, "w", encoding="utf-8") as f:`
- `tools/trial_run.py:44` `os.path.getsize` — `log(f"Trial on {os.path.basename(SRC)} ({os.path.getsize(SRC) / 1e6:.1f} MB)")`
- `tools/trial_run.py:102` `open` — `with open(SRC, "rb") as _fh:`
- `tools/trial_run.py:132` `os.path.getsize` — `step("export text", lambda: os.path.getsize(`
- `tools/trial_run.py:134` `os.path.getsize` — `step("export Word (.docx)", lambda: os.path.getsize(`

#### `tools/try_patch.py`

- `tools/try_patch.py:22` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/try_patch.py:65` `shutil.copytree` — `shutil.copytree(os.path.join(ROOT, d), os.path.join(tmp, d),`
- `tools/try_patch.py:67` `shutil.copytree` — `shutil.copytree(os.path.join(ROOT, "tools"),`
- `tools/try_patch.py:70` `os.listdir` — `for f in os.listdir(ROOT): # make_sample.py, pyproject...`
- `tools/try_patch.py:72` `os.path.isfile` — `os.path.isfile(os.path.join(ROOT, f)):`
- `tools/try_patch.py:73` `shutil.copy2` — `shutil.copy2(os.path.join(ROOT, f), tmp)`
- `tools/try_patch.py:76` `os.path.isdir` — `if os.path.isdir(src):`
- `tools/try_patch.py:77` `os.listdir` — `for n in os.listdir(src):`
- `tools/try_patch.py:78` `shutil.copy2` — `shutil.copy2(os.path.join(src, n),`
- `tools/try_patch.py:106` `os.path.exists` — `if os.path.exists(os.path.join(tmp, t))],`
- `tools/try_patch.py:112` `shutil.rmtree` — `shutil.rmtree(tmp, ignore_errors=True)`

#### `tools/uac_check.py`

- `tools/uac_check.py:13` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(`
- `tools/uac_check.py:30` `open` — `with open(path, "rb") as f:`
- `tools/uac_check.py:59` `os.path.isfile` — `print("exe:", EXE, os.path.isfile(EXE))`
- `tools/uac_check.py:60` `os.path.isfile` — `if os.path.isfile(EXE):`
- `tools/uac_check.py:64` `os.path.isfile` — `if not os.path.isfile(p):`
- `tools/uac_check.py:66` `open` — `with open(p, "rb") as f:`
- `tools/uac_check.py:73` `open` — `with open(p, "wb") as f:`

#### `tools/unpack_incoming.py`

- `tools/unpack_incoming.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/unpack_incoming.py:20` `os.makedirs` — `os.makedirs(OUT, exist_ok=True)`
- `tools/unpack_incoming.py:29` `os.path.exists` — `if os.path.exists(dst):`
- `tools/unpack_incoming.py:32` `open` — `with z.open(m) as f, open(dst, "wb") as g:`
- `tools/unpack_incoming.py:35` `open` — `with open(dst, "rb") as f:`

#### `tools/user_session.py`

- `tools/user_session.py:20` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/user_session.py:23` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`
- `tools/user_session.py:96` `os.makedirs` — `os.makedirs(out, exist_ok=True)`
- `tools/user_session.py:175` `os.path.isfile` — `if not os.path.isfile(pdf):`
- `tools/user_session.py:366` `os.path.getsize` — `f"after reopen; size {os.path.getsize(target) / 1e6:.1f} MB"`
- `tools/user_session.py:376` `os.path.isfile` — `assert os.path.isfile(target), "no file written"`
- `tools/user_session.py:377` `open` — `rows = open(target, encoding="utf-8-sig").read().count("\n")`
- `tools/user_session.py:404` `open` — `with open(os.path.join(out, "session.json"), "w", encoding="utf-8") as f:`

#### `tools/venice_check.py`

- `tools/venice_check.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/venice_check.py:13` `shutil.copytree` — `shutil.copytree(os.path.join(ROOT, "app"), os.path.join(tmp, "app"),`
- `tools/venice_check.py:15` `os.makedirs` — `os.makedirs(os.path.join(tmp, "tests"))`
- `tools/venice_check.py:16` `os.listdir` — `for f in os.listdir(os.path.join(SRC, "app")):`
- `tools/venice_check.py:17` `shutil.copy` — `shutil.copy(os.path.join(SRC, "app", f), os.path.join(tmp, "app", f))`
- `tools/venice_check.py:18` `os.listdir` — `for f in os.listdir(os.path.join(SRC, "tests")):`
- `tools/venice_check.py:19` `shutil.copy` — `shutil.copy(os.path.join(SRC, "tests", f),`
- `tools/venice_check.py:30` `os.listdir` — `"mods=" + repr([f[:-3] for f in os.listdir(os.path.join(SRC, 'app'))`
- `tools/venice_check.py:38` `shutil.rmtree` — `shutil.rmtree(tmp, ignore_errors=True)`

#### `tools/verify_update.py`

- `tools/verify_update.py:17` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/verify_update.py:23` `open` — `with open(p, "rb") as f:`
- `tools/verify_update.py:42` `os.listdir` — `local = next((os.path.join(up, d, "team") for d in os.listdir(up)`
- `tools/verify_update.py:43` `os.path.isdir` — `if os.path.isdir(os.path.join(up, d, "team"))), None)`
- `tools/verify_update.py:45` `open` — `with open(os.path.join(local, "version.json"), "rb") as f:`
- `tools/verify_update.py:51` `os.path.getsize` — `print("installer download: OK -", os.path.getsize(p), "bytes,",`
- `tools/verify_update.py:58` `os.path.isfile` — `if q and os.path.isfile(q):`
- `tools/verify_update.py:61` `shutil.rmtree` — `shutil.rmtree(tmp, ignore_errors=True)`

#### `tools/width_probe.py`

- `tools/width_probe.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/width_probe.py:14` `os.path.isdir` — `if os.path.isdir(r"C:\Windows\Fonts"):`

#### `tools/zip_release.py`

- `tools/zip_release.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/zip_release.py:18` `os.path.isfile` — `missing = [p for p in (setup, notes) if not os.path.isfile(p)]`
- `tools/zip_release.py:25` `open` — `with open(setup, "rb") as f:`
- `tools/zip_release.py:33` `open` — `with open(claims, "rb") as f:`
- `tools/zip_release.py:40` `open` — `with open(os.path.join(desk, f"{NAME} {V} SHA256.txt"), "w") as f:`
- `tools/zip_release.py:54` `os.path.getsize` — `print(out, f"{os.path.getsize(out) / 1e6:.1f} MB")`
- `tools/zip_release.py:65` `open` — `with open(p, "rb") as f:`
- `tools/zip_release.py:72` `os.path.isfile` — `if os.path.isfile(server):`
- `tools/zip_release.py:75` `os.path.isfile` — `if os.path.isfile(msi):`

#### `tools/zip_source.py`

- `tools/zip_source.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tools/zip_source.py:32` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`
- `tools/zip_source.py:49` `os.path.isfile` — `if os.path.isfile(p) and wanted(f):`
- `tools/zip_source.py:53` `os.walk` — `for base, dirs, files in os.walk(os.path.join(ROOT, d)):`
- `tools/zip_source.py:63` `os.path.getsize` — `print(out, n, "files", f"{os.path.getsize(out) / 1e6:.1f} MB")`

#### Tests

#### `quantisheet_backoffice/tests/conftest.py`

- `quantisheet_backoffice/tests/conftest.py:11` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
- `quantisheet_backoffice/tests/conftest.py:26` `os.path.realpath` — `rp = os.path.realpath(p)`
- `quantisheet_backoffice/tests/conftest.py:29` `os.path.realpath` — `bad = os.path.realpath(os.path.join(os.path.expanduser("~"), name))`

#### `quantisheet_backoffice/tests/test_m3_p2_01_02_payroll.py`

- `quantisheet_backoffice/tests/test_m3_p2_01_02_payroll.py:146` `open` — `rows = list(csv.DictReader(io.StringIO(open(out["path"]).read())))`

#### `quantisheet_backoffice/tests/test_m3_p2_03_certified.py`

- `quantisheet_backoffice/tests/test_m3_p2_03_certified.py:98` `os.path.isfile` — `assert os.path.isfile(r["file_path"]) # original kept`

#### `quantisheet_backoffice/tests/test_m3_p2_04_06_people.py`

- `quantisheet_backoffice/tests/test_m3_p2_04_06_people.py:76` `open` — `blob = open(doc["file_path"], "rb").read()`

#### `quantisheet_backoffice/tests/test_m4_store_rules.py`

- `quantisheet_backoffice/tests/test_m4_store_rules.py:9` `os.path.abspath` — `PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `quantisheet_backoffice/tests/test_m4_store_rules.py:38` `open` — `src = open(os.path.join(PKG, m + ".py"), encoding="utf-8").read()`
- `quantisheet_backoffice/tests/test_m4_store_rules.py:41` `open` — `src = open(os.path.join(PKG, "localai.py"), encoding="utf-8").read()`

#### `quantisheet_backoffice/tests/test_p1_01_isolation.py`

- `quantisheet_backoffice/tests/test_p1_01_isolation.py:19` `os.path.abspath` — `PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:24` `os.walk` — `for d, dirs, fs in os.walk(PKG):`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:35` `open` — `open(os.path.join(REAL, "settings.json"))`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:53` `os.path.realpath` — `assert os.path.realpath(p).startswith(os.path.realpath(str(bo_home)))`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:53` `os.path.realpath` — `assert os.path.realpath(p).startswith(os.path.realpath(str(bo_home)))`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:54` `os.path.realpath` — `assert not os.path.realpath(p).startswith(os.path.realpath(REAL))`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:54` `os.path.realpath` — `assert not os.path.realpath(p).startswith(os.path.realpath(REAL))`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:57` `os.walk` — `written = [os.path.join(d, f) for d, _, fs in os.walk(tmp_path) for f in fs]`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:76` `os.path.abspath` — `hits = [p for p in _files((".py",)) if p != os.path.abspath(__file__) and`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:77` `open` — `(pat.search(open(p, encoding="utf-8").read()) or`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:78` `open` — `dyn.search(open(p, encoding="utf-8").read()))]`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:104` `open` — `data = open(p, "rb").read()`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:115` `os.path.abspath` — `if p != os.path.abspath(__file__) and`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:116` `open` — `banned.search(open(p, encoding="utf-8").read())]`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:121` `open` — `text = open(os.path.join(PKG, "THIRD_PARTY_NOTICES.txt"),`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:134` `open` — `src = open(p, encoding="utf-8").read()`

#### `quantisheet_backoffice/tests/test_p1_04_storage.py`

- `quantisheet_backoffice/tests/test_p1_04_storage.py:41` `os.remove` — `os.remove(path)`
- `quantisheet_backoffice/tests/test_p1_04_storage.py:42` `os.path.exists` — `assert not os.path.exists(path)`
- `quantisheet_backoffice/tests/test_p1_04_storage.py:60` `open` — `raw = open(os.path.join(office.folder, "backoffice.sqlite"), "rb").read()`

#### `quantisheet_backoffice/tests/test_p1_07_jobcost.py`

- `quantisheet_backoffice/tests/test_p1_07_jobcost.py:72` `open` — `golden = json.load(open(os.path.join(DATA, "golden_costsummary.json")))`

#### `quantisheet_backoffice/tests/test_p1_14_16_waivers_payments_output.py`

- `quantisheet_backoffice/tests/test_p1_14_16_waivers_payments_output.py:175` `open` — `em = email.message_from_bytes(open(msg["path"], "rb").read())`

#### `quantisheet_backoffice/tests/test_p1_17_exports.py`

- `quantisheet_backoffice/tests/test_p1_17_exports.py:14` `os.path.abspath` — `PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `quantisheet_backoffice/tests/test_p1_17_exports.py:30` `open` — `with open(path, encoding="utf-8") as fh:`
- `quantisheet_backoffice/tests/test_p1_17_exports.py:106` `open` — `with open(r["path"], encoding="utf-8") as fh:`
- `quantisheet_backoffice/tests/test_p1_17_exports.py:114` `open` — `with open(sample, encoding="utf-8-sig") as fh:`
- `quantisheet_backoffice/tests/test_p1_17_exports.py:134` `open` — `assert "HL-91" not in open(r["path"], encoding="utf-8").read()`
- `quantisheet_backoffice/tests/test_p1_17_exports.py:154` `os.walk` — `for root, _dirs, files in os.walk(PKG):`
- `quantisheet_backoffice/tests/test_p1_17_exports.py:159` `open` — `text = open(os.path.join(root, f), encoding="utf-8").read()`

#### `quantisheet_backoffice/tests/test_p1_18_21_accounting.py`

- `quantisheet_backoffice/tests/test_p1_18_21_accounting.py:202` `os.listdir` — `files_before = sorted(os.listdir(office.folder))`
- `quantisheet_backoffice/tests/test_p1_18_21_accounting.py:213` `os.listdir` — `assert sorted(os.listdir(office.folder)) == files_before`

#### `quantisheet_backoffice/tests/test_p2_books.py`

- `quantisheet_backoffice/tests/test_p2_books.py:209` `open` — `rows = list(csv.reader(open(p, encoding="utf-8")))`

#### `quantisheet_backoffice/tests/test_r111_ap_extras.py`

- `quantisheet_backoffice/tests/test_r111_ap_extras.py:122` `os.path.isfile` — `assert os.path.isfile(stamped) and store.file_hash(stamped) != before`

#### `quantisheet_backoffice/tests/test_r111_field.py`

- `quantisheet_backoffice/tests/test_r111_field.py:75` `open` — `rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))`

#### `quantisheet_backoffice/tests/test_r111_menu.py`

- `quantisheet_backoffice/tests/test_r111_menu.py:30` `os.listdir` — `for name in os.listdir(ROOT):`
- `quantisheet_backoffice/tests/test_r111_menu.py:34` `open` — `tree = ast.parse(open(path, encoding="utf-8").read())`
- `quantisheet_backoffice/tests/test_r111_menu.py:45` `open` — `text = open(path, encoding="utf-8").read().lower()`

#### `quantisheet_backoffice/tests/test_r111_qs020_duplicates.py`

- `quantisheet_backoffice/tests/test_r111_qs020_duplicates.py:40` `shutil.copyfile` — `shutil.copyfile(src, copy)`
- `quantisheet_backoffice/tests/test_r111_qs020_duplicates.py:73` `shutil.copyfile` — `shutil.copyfile(src, folder / "again.pdf")`

#### `quantisheet_backoffice/tests/test_r111_qs025_migration.py`

- `quantisheet_backoffice/tests/test_r111_qs025_migration.py:29` `shutil.rmtree` — `shutil.rmtree(os.path.dirname(paykeys.location(str(folder))))`
- `quantisheet_backoffice/tests/test_r111_qs025_migration.py:31` `open` — `with open(folder / "datakey.bin", "wb") as fh:`
- `quantisheet_backoffice/tests/test_r111_qs025_migration.py:38` `open` — `raw = open(folder / "datakey.bin", "rb").read()`
- `quantisheet_backoffice/tests/test_r111_qs025_migration.py:42` `open` — `stub = open(folder / "datakey.bin", "rb").read()`
- `quantisheet_backoffice/tests/test_r111_qs025_migration.py:45` `open` — `assert open(os.path.join(slot, "legacy-datakey.bin"), "rb").read() == raw`
- `quantisheet_backoffice/tests/test_r111_qs025_migration.py:51` `shutil.rmtree` — `shutil.rmtree(os.path.dirname(paykeys.location(str(folder))))`
- `quantisheet_backoffice/tests/test_r111_qs025_migration.py:55` `os.path.isfile` — `assert not os.path.isfile(paykeys.location(str(folder)))`
- `quantisheet_backoffice/tests/test_r111_qs025_migration.py:62` `os.replace` — `os.replace(folder, moved)`
- `quantisheet_backoffice/tests/test_r111_qs025_migration.py:79` `shutil.rmtree` — `shutil.rmtree(os.path.dirname(paykeys.location(str(folder))))`

#### `quantisheet_backoffice/tests/test_r111_qs025_paykeys.py`

- `quantisheet_backoffice/tests/test_r111_qs025_paykeys.py:16` `open` — `stub = open(os.path.join(company, "datakey.bin"), "rb").read()`
- `quantisheet_backoffice/tests/test_r111_qs025_paykeys.py:21` `os.path.realpath` — `assert not os.path.realpath(slot).startswith(os.path.realpath(company) + os.sep)`
- `quantisheet_backoffice/tests/test_r111_qs025_paykeys.py:21` `os.path.realpath` — `assert not os.path.realpath(slot).startswith(os.path.realpath(company) + os.sep)`
- `quantisheet_backoffice/tests/test_r111_qs025_paykeys.py:22` `open` — `sealed = open(slot, "rb").read()`
- `quantisheet_backoffice/tests/test_r111_qs025_paykeys.py:25` `open` — `assert key not in open(office.db.path, "rb").read()`
- `quantisheet_backoffice/tests/test_r111_qs025_paykeys.py:38` `open` — `blob = b"".join(open(p, "rb").read()`
- `quantisheet_backoffice/tests/test_r111_qs025_paykeys.py:49` `open` — `backed = open(path, "rb").read()`
- `quantisheet_backoffice/tests/test_r111_qs025_paykeys.py:52` `os.remove` — `os.remove(paykeys.location(office.folder))`

#### `quantisheet_backoffice/tests/test_r111_qs025_sample.py`

- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:16` `os.path.abspath` — `os.path.abspath(__file__)))), "tests", "sample_data", "payroll_company")`
- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:17` `os.path.isdir` — `pytestmark = pytest.mark.skipif(not os.path.isdir(SAMPLE),`
- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:23` `shutil.copytree` — `shutil.copytree(SAMPLE, dst)`
- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:39` `open` — `before = open(os.path.join(SAMPLE, "datakey.bin"), "rb").read()`
- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:48` `open` — `stub = open(os.path.join(folder, "datakey.bin"), "rb").read()`
- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:54` `open` — `assert open(os.path.join(SAMPLE, "datakey.bin"), "rb").read() == before`
- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:63` `open` — `assert open(os.path.join(folder, "datakey.bin"), "rb").read() == \`
- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:64` `open` — `open(os.path.join(SAMPLE, "datakey.bin"), "rb").read()`

#### `quantisheet_backoffice/tests/test_r111_sagejc.py`

- `quantisheet_backoffice/tests/test_r111_sagejc.py:121` `open` — `open(prn, "w", encoding="utf-8").write("not a pdf\n")`

#### `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py`

- `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py:118` `os.path.abspath` — `os.path.abspath(__file__)))), "tests", "sample_data")`
- `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py:121` `os.path.isfile` — `@pytest.mark.skipif(not os.path.isfile(os.path.join(`
- `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py:156` `os.path.isfile` — `@pytest.mark.skipif(not os.path.isfile(os.path.join(`

#### `quantisheet_backoffice/tests/test_r111_security_ui.py`

- `quantisheet_backoffice/tests/test_r111_security_ui.py:28` `shutil.copyfile` — `shutil.copyfile(src, folder / "again.pdf")`
- `quantisheet_backoffice/tests/test_r111_security_ui.py:79` `shutil.rmtree` — `shutil.rmtree(os.path.dirname(paykeys.location(folder)))`

#### `quantisheet_backoffice/tests/test_r38_jobcost_split.py`

- `quantisheet_backoffice/tests/test_r38_jobcost_split.py:70` `open` — `rows = list(csv.reader(open(path, newline="")))`

#### `quantisheet_backoffice/tests/test_r38_perdiem_export.py`

- `quantisheet_backoffice/tests/test_r38_perdiem_export.py:23` `open` — `with open(path, newline="", encoding="utf-8") as fh:`
- `quantisheet_backoffice/tests/test_r38_perdiem_export.py:116` `os.path.exists` — `assert r["count"] == 1 and os.path.exists(r["path"])`

#### `quantisheet_backoffice/tests/test_r38_provider_perdiem.py`

- `quantisheet_backoffice/tests/test_r38_provider_perdiem.py:42` `open` — `return list(csv.DictReader(io.StringIO(open(path).read())))`

#### `quantisheet_backoffice/tests/test_review_fixes.py`

- `quantisheet_backoffice/tests/test_review_fixes.py:45` `os.path.isfile` — `assert os.path.isfile(image_path)`
- `quantisheet_backoffice/tests/test_review_fixes.py:67` `os.path.exists` — `assert not os.path.exists(img) and not os.path.exists(os.path.dirname(img))`
- `quantisheet_backoffice/tests/test_review_fixes.py:67` `os.path.exists` — `assert not os.path.exists(img) and not os.path.exists(os.path.dirname(img))`
- `quantisheet_backoffice/tests/test_review_fixes.py:68` `os.listdir` — `assert sorted(os.listdir(folder)) == ["bill-page1.png", "bill.pdf"]`
- `quantisheet_backoffice/tests/test_review_fixes.py:77` `open` — `open(p, "w").write("{}")`
- `quantisheet_backoffice/tests/test_review_fixes.py:79` `os.path.exists` — `assert not os.path.exists(p) and not os.path.exists(d)`
- `quantisheet_backoffice/tests/test_review_fixes.py:79` `os.path.exists` — `assert not os.path.exists(p) and not os.path.exists(d)`
- `quantisheet_backoffice/tests/test_review_fixes.py:93` `open` — `open(p, "w").write("{}")`
- `quantisheet_backoffice/tests/test_review_fixes.py:101` `os.path.exists` — `assert not os.path.exists(p)`
- `quantisheet_backoffice/tests/test_review_fixes.py:119` `os.path.realpath` — `out = os.path.realpath(office.output_folder())`
- `quantisheet_backoffice/tests/test_review_fixes.py:121` `os.path.realpath` — `assert os.path.dirname(os.path.realpath(p)) == out`
- `quantisheet_backoffice/tests/test_review_fixes.py:124` `os.path.realpath` — `assert os.path.dirname(os.path.realpath(s)) == out`
- `quantisheet_backoffice/tests/test_review_fixes.py:150` `open` — `cells = [c for row in csv.reader(open(r["path"], encoding="utf-8"))`
- `quantisheet_backoffice/tests/test_review_fixes.py:173` `open` — `rows = list(csv.reader(open(p, encoding="utf-8")))`
- `quantisheet_backoffice/tests/test_review_fixes.py:210` `open` — `raw = open(bk, "rb").read()`
- `quantisheet_backoffice/tests/test_review_fixes.py:245` `open` — `msg = message_from_bytes(open(m["path"], "rb").read())`
- `quantisheet_backoffice/tests/test_review_fixes.py:255` `open` — `src = open(sec_mod.__file__, encoding="utf-8").read()`
- `quantisheet_backoffice/tests/test_review_fixes.py:272` `open` — `assert "600_000" in open(crypto.__file__, encoding="utf-8").read()`
- `quantisheet_backoffice/tests/test_review_fixes.py:348` `fake.stat (DirEntry or Path stat)` — `fake.chmod(fake.stat().st_mode | stat.S_IEXEC)`
- `quantisheet_backoffice/tests/test_review_fixes.py:372` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `quantisheet_backoffice/tests/test_review_fixes.py:374` `os.walk` — `for d, _, fs in os.walk(root):`
- `quantisheet_backoffice/tests/test_review_fixes.py:381` `open` — `t = open(os.path.join(d, f), encoding="utf-8").read()`

#### `quantisheet_backoffice/tests/test_t004_encryption_at_rest.py`

- `quantisheet_backoffice/tests/test_t004_encryption_at_rest.py:35` `open` — `raw = open(office.db.path, "rb").read()`
- `quantisheet_backoffice/tests/test_t004_encryption_at_rest.py:48` `open` — `assert b"999111" not in open(office.db.path, "rb").read()`
- `quantisheet_backoffice/tests/test_t004_encryption_at_rest.py:103` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `quantisheet_backoffice/tests/test_t004_encryption_at_rest.py:109` `os.walk` — `for base, _d, files in os.walk(root):`
- `quantisheet_backoffice/tests/test_t004_encryption_at_rest.py:114` `open` — `for i, ln in enumerate(open(os.path.join(base, f),`

#### `quantisheet_claims/tests/conftest.py`

- `quantisheet_claims/tests/conftest.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`

#### `quantisheet_claims/tests/test_contents.py`

- `quantisheet_claims/tests/test_contents.py:98` `open` — `assert json.load(open(p))["schema_version"] == 3`
- `quantisheet_claims/tests/test_contents.py:104` `open` — `assert json.load(open(p2))["schema_version"] == 3`
- `quantisheet_claims/tests/test_contents.py:115` `open` — `rows = list(csv.reader(open(to_csv(md, str(tmp_path / "c.csv")),`

#### `quantisheet_claims/tests/test_cost_split.py`

- `quantisheet_claims/tests/test_cost_split.py:39` `open` — `rows = list(csv.reader(open(to_csv(md, str(tmp_path / "s.csv")),`

#### `quantisheet_claims/tests/test_export.py`

- `quantisheet_claims/tests/test_export.py:25` `open` — `raw = open(p, "rb").read()`
- `quantisheet_claims/tests/test_export.py:33` `open` — `t2 = open(to_csv(_model(credit), str(tmp_path / "cr.csv")),`

#### `quantisheet_claims/tests/test_isolation.py`

- `quantisheet_claims/tests/test_isolation.py:13` `os.path.abspath` — `PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `quantisheet_claims/tests/test_isolation.py:23` `os.path.realpath` — `rp = os.path.realpath(os.fsdecode(p))`
- `quantisheet_claims/tests/test_isolation.py:49` `os.walk` — `written = [os.path.join(d, f) for d, _, fs in os.walk(tmp_path) for f in fs]`
- `quantisheet_claims/tests/test_isolation.py:58` `os.path.realpath` — `assert not os.path.realpath(p).startswith(os.path.realpath(real))`
- `quantisheet_claims/tests/test_isolation.py:58` `os.path.realpath` — `assert not os.path.realpath(p).startswith(os.path.realpath(real))`
- `quantisheet_claims/tests/test_isolation.py:83` `os.walk` — `for d, _, fs in os.walk(PKG):`
- `quantisheet_claims/tests/test_isolation.py:91` `open` — `hits = [p for p in _sources() if pat.search(open(p, encoding="utf-8").read())]`
- `quantisheet_claims/tests/test_isolation.py:107` `open` — `src = open(os.path.join(PKG, name), encoding="utf-8").read()`

#### `quantisheet_claims/tests/test_nw15_tax_op.py`

- `quantisheet_claims/tests/test_nw15_tax_op.py:53` `open` — `raw = json.load(open(p, encoding="utf-8"))`
- `quantisheet_claims/tests/test_nw15_tax_op.py:55` `open` — `json.dump(raw, open(p, "w", encoding="utf-8"))`

#### `quantisheet_claims/tests/test_nw16_photos.py`

- `quantisheet_claims/tests/test_nw16_photos.py:20` `os.makedirs` — `os.makedirs(folder)`
- `quantisheet_claims/tests/test_nw16_photos.py:45` `os.makedirs` — `os.makedirs(folder)`
- `quantisheet_claims/tests/test_nw16_photos.py:49` `open` — `with open(f, "ab") as fh:`
- `quantisheet_claims/tests/test_nw16_photos.py:52` `os.remove` — `os.remove(f)`
- `quantisheet_claims/tests/test_nw16_photos.py:72` `open` — `raw = json.load(open(p, encoding="utf-8"))`
- `quantisheet_claims/tests/test_nw16_photos.py:74` `open` — `json.dump(raw, open(p, "w", encoding="utf-8"))`

#### `quantisheet_claims/tests/test_p1_line_library.py`

- `quantisheet_claims/tests/test_p1_line_library.py:42` `open` — `with open(p, "w", newline="", encoding="utf-8") as f:`
- `quantisheet_claims/tests/test_p1_line_library.py:61` `open` — `rows = list(csv.reader(open(out, encoding="utf-8-sig")))`

#### `quantisheet_claims/tests/test_store_recipes.py`

- `quantisheet_claims/tests/test_store_recipes.py:29` `os.listdir` — `assert len(os.listdir(bdir)) == 10`
- `quantisheet_claims/tests/test_store_recipes.py:34` `open` — `txt = open(p, encoding="utf-8").read().replace('"qty_q4": 10000',`
- `quantisheet_claims/tests/test_store_recipes.py:36` `open` — `open(p, "w", encoding="utf-8").write(txt)`

#### `quantisheet_claims/tests/test_v022.py`

- `quantisheet_claims/tests/test_v022.py:81` `open` — `assert json.load(open(p))["schema_version"] == 2`
- `quantisheet_claims/tests/test_v022.py:84` `open` — `assert json.load(open(p))["schema_version"] == 3`
- `quantisheet_claims/tests/test_v022.py:95` `open` — `assert json.load(open(p))["schema_version"] == 3`
- `quantisheet_claims/tests/test_v022.py:107` `open` — `rows = list(csv.reader(open(p, encoding="utf-8-sig")))`
- `quantisheet_claims/tests/test_v022.py:196` `os.path.abspath` — `os.path.abspath(__file__))))`
- `quantisheet_claims/tests/test_v022.py:197` `open` — `src = open(os.path.join(root, "tools", "install_release.py"),`
- `quantisheet_claims/tests/test_v022.py:212` `os.utime` — `os.utime(tmp_path / "s", (old, old))`
- `quantisheet_claims/tests/test_v022.py:214` `os.utime` — `os.utime(tmp_path / "s", None)`

#### `quantisheet_claims/tests/test_v02_engine.py`

- `quantisheet_claims/tests/test_v02_engine.py:130` `open` — `data = json.load(open(p, encoding="utf-8"))`
- `quantisheet_claims/tests/test_v02_engine.py:134` `open` — `json.dump(data, open(p, "w", encoding="utf-8"))`
- `quantisheet_claims/tests/test_v02_engine.py:213` `open` — `data = json.load(open(p, encoding="utf-8"))`
- `quantisheet_claims/tests/test_v02_engine.py:216` `open` — `json.dump(data, open(p, "w", encoding="utf-8"))`
- `quantisheet_claims/tests/test_v02_engine.py:219` `open` — `json.dump([1, 2], open(p, "w", encoding="utf-8"))`

#### `quantisheet_claims/tests/test_v02_window.py`

- `quantisheet_claims/tests/test_v02_window.py:43` `os.path.exists` — `assert os.path.exists(win.open_claims[0]["path"]) # saved straight away`
- `quantisheet_claims/tests/test_v02_window.py:385` `os.path.exists` — `assert new != old and os.path.exists(new) and not os.path.exists(old)`
- `quantisheet_claims/tests/test_v02_window.py:385` `os.path.exists` — `assert new != old and os.path.exists(new) and not os.path.exists(old)`
- `quantisheet_claims/tests/test_v02_window.py:387` `os.listdir` — `assert any(x.startswith("EX-501.claim.json.") for x in os.listdir(bak))`

#### `quantisheet_claims/tests/test_window.py`

- `quantisheet_claims/tests/test_window.py:108` `os.path.abspath` — `os.path.abspath(__file__))))`
- `quantisheet_claims/tests/test_window.py:109` `open` — `spec = open(os.path.join(root, "quantisheet_claims.spec"),`
- `quantisheet_claims/tests/test_window.py:112` `open` — `src = open(os.path.join(root, "claimit_launch.py"),`

#### `tests/conftest.py`

- `tests/conftest.py:5` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
- `tests/conftest.py:6` `os.path.abspath` — `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`
- `tests/conftest.py:27` `os.makedirs` — `os.makedirs(os.environ[_k], exist_ok=True)`
- `tests/conftest.py:62` `os.makedirs` — `os.makedirs(_pd, exist_ok=True)`

#### `tests/diag_pm2_write.py`

- `tests/diag_pm2_write.py:65` `os.remove` — `os.remove(tmp)`

#### `tests/r111_support.py`

- `tests/r111_support.py:28` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`

#### `tests/r39_master_fixtures.py`

- `tests/r39_master_fixtures.py:58` `open` — `with open(s.path, "rb") as f:`
- `tests/r39_master_fixtures.py:150` `open` — `with open(path, "w", encoding="utf-8") as f:`
- `tests/r39_master_fixtures.py:194` `open` — `with open(path, "w", encoding="cp1252", newline="\r\n") as f:`

#### `tests/sample_data/make_samples.py`

- `tests/sample_data/make_samples.py:16` `os.path.abspath` — `HERE = os.path.dirname(os.path.abspath(__file__))`
- `tests/sample_data/make_samples.py:151` `open` — `with open(prn_path, "w", encoding="utf-8", newline="") as fh:`
- `tests/sample_data/make_samples.py:433` `os.makedirs` — `os.makedirs(folder, exist_ok=True)`
- `tests/sample_data/make_samples.py:437` `os.path.exists` — `if os.path.exists(path):`
- `tests/sample_data/make_samples.py:438` `os.remove` — `os.remove(path)`
- `tests/sample_data/make_samples.py:476` `os.replace` — `os.replace(os.path.join(tmp, "backoffice.sqlite"), db_path)`
- `tests/sample_data/make_samples.py:477` `os.replace` — `os.replace(os.path.join(tmp, "datakey.bin"), key_path)`
- `tests/sample_data/make_samples.py:480` `os.rmdir` — `os.rmdir(tmp)`
- `tests/sample_data/make_samples.py:484` `os.chmod` — `os.chmod(db_path, 0o600)`
- `tests/sample_data/make_samples.py:485` `os.chmod` — `os.chmod(key_path, 0o600)`
- `tests/sample_data/make_samples.py:488` `open` — `blob = open(key_path, "rb").read()`
- `tests/sample_data/make_samples.py:496` `open` — `with open(path, "w", encoding="utf-8") as fh:`

#### `tests/test_acrobat.py`

- `tests/test_acrobat.py:40` `open` — `assert "Hello world 2" in open(t, encoding="utf-8").read()`
- `tests/test_acrobat.py:42` `os.path.getsize` — `assert len(imgs) == 2 and all(os.path.getsize(i) > 0 for i in imgs)`

#### `tests/test_acrobat2.py`

- `tests/test_acrobat2.py:110` `open` — `assert "Hello web" in open(out, encoding="utf-8").read()`

#### `tests/test_aerial_ui.py`

- `tests/test_aerial_ui.py:362` `os.path.isdir` — `assert os.path.isdir(aerial._cache_dir())`

#### `tests/test_ai_features.py`

- `tests/test_ai_features.py:15` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tests/test_aitakeoff_wiring_phase2.py`

- `tests/test_aitakeoff_wiring_phase2.py:34` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_aitakeoff_wiring_phase2.py:475` `os.path.exists` — `if os.path.exists(p):`
- `tests/test_aitakeoff_wiring_phase2.py:481` `open` — `with open(os.path.join(ROOT, "tools", "aiken_map.json"),`

#### `tests/test_assembly_codes.py`

- `tests/test_assembly_codes.py:88` `open` — `t = list(csv.reader(open(ac.TEMPLATE, encoding="utf-8")))`
- `tests/test_assembly_codes.py:90` `open` — `ex = list(csv.reader(open(ac.EXAMPLE, encoding="utf-8")))`

#### `tests/test_assembly_csv.py`

- `tests/test_assembly_csv.py:94` `open` — `text = open(tpl, encoding="utf-8-sig").read().replace(`
- `tests/test_assembly_csv.py:97` `open` — `open(tpl, "w", encoding="utf-8-sig").write(text)`
- `tests/test_assembly_csv.py:124` `os.path.exists` — `assert n == 25 and os.path.exists(assemblies.LIBRARY_PATH)`
- `tests/test_assembly_csv.py:137` `open` — `assert "A-03-STRIPFOOT.1" in open(tpl, encoding="utf-8-sig").read()`
- `tests/test_assembly_csv.py:139` `os.path.getsize` — `assert os.path.getsize(out) > 0`

#### `tests/test_audit.py`

- `tests/test_audit.py:75` `os.path.getsize` — `assert os.path.getsize(out) > 1000`

#### `tests/test_autosave.py`

- `tests/test_autosave.py:51` `os.path.exists` — `assert os.path.exists(pdf)`
- `tests/test_autosave.py:53` `open` — `m = json.load(open(meta))`
- `tests/test_autosave.py:56` `open` — `json.dump(m, open(meta, "w"))`
- `tests/test_autosave.py:57` `os.path.getmtime` — `os.utime(pdf, (os.path.getmtime(path) + 60,) * 2)`
- `tests/test_autosave.py:57` `os.utime` — `os.utime(pdf, (os.path.getmtime(path) + 60,) * 2)`
- `tests/test_autosave.py:59` `os.path.abspath` — `assert len(items) == 1 and items[0]["original"] == os.path.abspath(path)`
- `tests/test_autosave.py:61` `os.path.abspath` — `assert tab.path is None and tab.suggest == os.path.abspath(path)`
- `tests/test_autosave.py:64` `os.path.exists` — `assert not os.path.exists(pdf)`
- `tests/test_autosave.py:76` `os.chmod` — `os.chmod(path, stat.S_IREAD)`
- `tests/test_autosave.py:82` `os.path.exists` — `assert os.path.exists(pdf)`
- `tests/test_autosave.py:84` `os.chmod` — `os.chmod(path, stat.S_IREAD | stat.S_IWRITE)`
- `tests/test_autosave.py:94` `os.path.exists` — `assert not os.path.exists(pdf)`

#### `tests/test_autoscale.py`

- `tests/test_autoscale.py:93` `os.path.exists` — `if not os.path.exists(path):`

#### `tests/test_betalicense.py`

- `tests/test_betalicense.py:125` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_betalicense.py:135` `open` — `pub = open(tmp_path / "pub.txt").read().strip()`
- `tests/test_betalicense.py:139` `open` — `assert "Bob Jones" in open(tmp_path / "log.csv").read()`

#### `tests/test_bid_wiring.py`

- `tests/test_bid_wiring.py:127` `os.path.isfile` — `assert os.path.isfile(out[k]) and out[k].endswith(".xlsx")`

#### `tests/test_bidbuild.py`

- `tests/test_bidbuild.py:15` `os.path.abspath` — `TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(`

#### `tests/test_bidding.py`

- `tests/test_bidding.py:67` `open` — `with open(p, "w", newline="") as f:`
- `tests/test_bidding.py:78` `open` — `with open(b, "w", newline="") as f:`
- `tests/test_bidding.py:186` `open` — `with open(p, "w", newline="") as f:`
- `tests/test_bidding.py:227` `open` — `text = open(ics, encoding="utf-8").read()`
- `tests/test_bidding.py:248` `os.path.exists` — `assert os.path.exists(p)`
- `tests/test_bidding.py:285` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tests/test_bidform_xl.py`

- `tests/test_bidform_xl.py:214` `os.path.isfile` — `assert os.path.isfile(book)`
- `tests/test_bidform_xl.py:254` `os.path.isfile` — `assert os.path.isfile(pdf) and pdf.startswith(str(tmp_path))`

#### `tests/test_bidgate.py`

- `tests/test_bidgate.py:174` `open` — `assert "Hardware" in open(p, encoding="utf-8").read()`

#### `tests/test_big_set_background.py`

- `tests/test_big_set_background.py:48` `os.path.getsize` — `assert calls and os.path.getsize(out) > 0`

#### `tests/test_billing.py`

- `tests/test_billing.py:121` `os.path.getsize` — `assert os.path.getsize(xl) > 0`
- `tests/test_billing.py:125` `os.path.getsize` — `assert os.path.getsize(money.change_log_xlsx(`
- `tests/test_billing.py:213` `os.path.exists` — `assert os.path.exists(out)`
- `tests/test_billing.py:242` `os.path.exists` — `assert os.path.exists(out)`

#### `tests/test_brand_rename.py`

- `tests/test_brand_rename.py:37` `open` — `with open(p, "rb") as f:`
- `tests/test_brand_rename.py:139` `os.listdir` — `names = os.listdir(costbook.SHIPPED)`
- `tests/test_brand_rename.py:141` `open` — `with open(os.path.join(costbook.SHIPPED, names[0]),`

#### `tests/test_brand_rename_2.py`

- `tests/test_brand_rename_2.py:9` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_brand_rename_2.py:80` `os.path.isdir` — `assert os.path.isdir(cs.home())`
- `tests/test_brand_rename_2.py:82` `os.path.realpath` — `assert cs.quantisheet_dirs() == (os.path.realpath(`

#### `tests/test_branding_v34.py`

- `tests/test_branding_v34.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_branding_v34.py:12` `os.path.isfile` — `assert os.path.isfile(path), f"missing {rel}"`
- `tests/test_branding_v34.py:49` `open` — `text = open(_read(os.path.join("installer", "quantisheet.iss")),`
- `tests/test_branding_v34.py:58` `open` — `text = open(_read(os.path.join("tools", "build_installer.py")),`
- `tests/test_branding_v34.py:66` `open` — `text = open(_read("quantisheet.spec"), encoding="utf-8").read()`
- `tests/test_branding_v34.py:71` `open` — `text = open(_read(os.path.join("app", "main.py")), encoding="utf-8").read()`
- `tests/test_branding_v34.py:81` `open` — `text = open(_read(os.path.join("app", "main.py")), encoding="utf-8").read()`

#### `tests/test_build_msix.py`

- `tests/test_build_msix.py:6` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_build_msix.py:32` `open` — `with open(os.path.join(ROOT, "installer", "msix_identity.json"),`
- `tests/test_build_msix.py:48` `open` — `assert json.load(open(p)) == {"edition": "store",`
- `tests/test_build_msix.py:102` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_build_msix.py:105` `os.path.isfile` — `assert os.path.isfile(store)`
- `tests/test_build_msix.py:109` `os.path.isfile` — `assert os.path.isfile(company)`
- `tests/test_build_msix.py:116` `open` — `assert (inner / "splash.png").read_bytes() == open(store, "rb").read()`

#### `tests/test_button_slots.py`

- `tests/test_button_slots.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_button_slots.py:15` `os.walk` — `for root, _, files in os.walk(os.path.join(ROOT, "app")):`
- `tests/test_button_slots.py:20` `open` — `tree = ast.parse(open(p, encoding="utf-8").read())`

#### `tests/test_cashflow.py`

- `tests/test_cashflow.py:57` `os.path.getsize` — `assert os.path.getsize(cashflow.xlsx(s, str(tmp_path / "cf.xlsx"),`

#### `tests/test_civil_export.py`

- `tests/test_civil_export.py:80` `open` — `rows = list(csv.DictReader(open(out, encoding="utf-8")))`
- `tests/test_civil_export.py:140` `open` — `assert open(p, "rb").read() == JON_CSV.encode("utf-8")`
- `tests/test_civil_export.py:173` `open` — `txt = open(c, encoding="utf-8").read()`
- `tests/test_civil_export.py:221` `open` — `txt = open(out["resources"], encoding="utf-8").read()`

#### `tests/test_civiltakeoff.py`

- `tests/test_civiltakeoff.py:14` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tests/test_claims_hook.py`

- `tests/test_claims_hook.py:61` `os.path.realpath` — `p = os.path.realpath(pricedb.path())`
- `tests/test_claims_hook.py:62` `os.path.realpath` — `assert p.startswith(os.path.realpath(str(cfg)))`
- `tests/test_claims_hook.py:63` `os.path.realpath` — `assert not p.startswith(os.path.realpath(REAL_DIR) + os.sep)`
- `tests/test_claims_hook.py:111` `open` — `before = open(path, "rb").read()`
- `tests/test_claims_hook.py:118` `open` — `assert open(path, "rb").read() == before`
- `tests/test_claims_hook.py:148` `open` — `data = json.load(open(snap_path, encoding="utf-8"))`

#### `tests/test_cli_sanitize_genset.py`

- `tests/test_cli_sanitize_genset.py:44` `open` — `rep = json.load(open(man))`
- `tests/test_cli_sanitize_genset.py:82` `os.path.exists` — `assert not os.path.exists(tmp_path / "g.pdf")`

#### `tests/test_codecheck.py`

- `tests/test_codecheck.py:166` `os.path.exists` — `assert os.path.exists(out)`

#### `tests/test_cost_rollup.py`

- `tests/test_cost_rollup.py:54` `open` — `txt = open(p, encoding="utf-8").read()`

#### `tests/test_costbook_columns.py`

- `tests/test_costbook_columns.py:123` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tests/test_costbook_columns.py:153` `open` — `with open(path, encoding="utf-8") as f:`
- `tests/test_costbook_columns.py:178` `open` — `with open(c, "w", newline="", encoding="utf-8") as f:`

#### `tests/test_costbook_picker.py`

- `tests/test_costbook_picker.py:27` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`

#### `tests/test_costlayer_wiring.py`

- `tests/test_costlayer_wiring.py:58` `os.path.exists` — `assert os.path.exists(out)`

#### `tests/test_count_library.py`

- `tests/test_count_library.py:80` `open` — `with open(count_library.path(), encoding="utf-8") as f:`
- `tests/test_count_library.py:84` `open` — `with open(count_library.path(), "w", encoding="utf-8") as f:`
- `tests/test_count_library.py:97` `os.path.exists` — `assert os.path.exists(share / count_library.FILENAME)`

#### `tests/test_crashreport.py`

- `tests/test_crashreport.py:25` `open` — `text = open(path, encoding="utf-8").read()`
- `tests/test_crashreport.py:43` `open` — `with open(crash, "a", encoding="utf-8") as f:`
- `tests/test_crashreport.py:46` `open` — `with open(crash, "a", encoding="utf-8") as f:`
- `tests/test_crashreport.py:50` `open` — `assert p and "hard crash in the previous session" in open(`
- `tests/test_crashreport.py:98` `open` — `with open(crash, "a", encoding="utf-8") as f:`
- `tests/test_crashreport.py:101` `open` — `stale = open(seen, encoding="utf-8").read()`
- `tests/test_crashreport.py:110` `open` — `assert open(seen, encoding="utf-8").read() == stale # not saved`

#### `tests/test_dashboard.py`

- `tests/test_dashboard.py:30` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tests/test_dashboard.py:60` `os.makedirs` — `os.makedirs(os.path.join(folder, ".quantisheet"), exist_ok=True)`
- `tests/test_dashboard.py:71` `open` — `with open(os.path.join(folder, db.PROJECT_FILE), "w",`
- `tests/test_dashboard.py:239` `os.path.abspath` — `assert job["folder"] == os.path.abspath(folder) # linked by number`
- `tests/test_dashboard.py:246` `open` — `with open(os.path.join(folder, db.PROJECT_FILE), encoding="utf-8") as f:`
- `tests/test_dashboard.py:254` `os.makedirs` — `os.makedirs(os.path.dirname(p), exist_ok=True)`
- `tests/test_dashboard.py:365` `os.makedirs` — `os.makedirs(os.path.join(bad, ".quantisheet"))`
- `tests/test_dashboard.py:366` `open` — `with open(os.path.join(bad, db.PROJECT_FILE), "w") as f:`
- `tests/test_dashboard.py:369` `open` — `with open(os.path.join(worse, db.PROJECT_FILE), "w") as f:`
- `tests/test_dashboard.py:372` `os.makedirs` — `os.makedirs(nothing)`
- `tests/test_dashboard.py:381` `os.path.isfile` — `assert os.path.isfile(os.path.join(bad, db.PROJECT_FILE))`
- `tests/test_dashboard.py:382` `os.path.exists` — `assert not os.path.exists(os.path.join(bad, db.PROJECT_FILE +`
- `tests/test_dashboard.py:390` `open` — `with open(path, encoding="utf-8") as fh:`
- `tests/test_dashboard.py:393` `open` — `with open(path, "w", encoding="utf-8") as fh:`
- `tests/test_dashboard.py:503` `os.path.isfile` — `assert os.path.isfile(db.export_xlsx(r, str(tmp_path / "e.xlsx")))`
- `tests/test_dashboard.py:520` `os.path.isfile` — `assert os.path.isfile(empty)`
- `tests/test_dashboard.py:560` `os.path.isfile` — `assert out and os.path.isfile(out)`
- `tests/test_dashboard.py:586` `os.makedirs` — `os.makedirs(os.path.join(bad, ".quantisheet"))`
- `tests/test_dashboard.py:587` `open` — `with open(os.path.join(bad, db.PROJECT_FILE), "w") as f:`

#### `tests/test_databackup.py`

- `tests/test_databackup.py:56` `os.path.isfile` — `assert os.path.isfile(safety)`
- `tests/test_databackup.py:85` `os.listdir` — `assert len([f for f in os.listdir(folder) if f.endswith(".zip")]) == 4`

#### `tests/test_datecalc.py`

- `tests/test_datecalc.py:150` `open` — `src = open(os.path.join(os.path.dirname(__file__), "..", "app",`

#### `tests/test_dropbox.py`

- `tests/test_dropbox.py:334` `open` — `assert open(local, "rb").read() == data`
- `tests/test_dropbox.py:335` `os.path.exists` — `assert not os.path.exists(local + ".part")`
- `tests/test_dropbox.py:343` `open` — `with open(local, "ab") as f:`
- `tests/test_dropbox.py:349` `open` — `assert open(local, "rb").read() == data`
- `tests/test_dropbox.py:363` `os.path.exists` — `assert not os.path.exists(dbx.local_path_for("/a.pdf"))`
- `tests/test_dropbox.py:373` `open` — `with open(local, "wb") as f:`
- `tests/test_dropbox.py:379` `open` — `with open(local, "wb") as f:`
- `tests/test_dropbox.py:389` `open` — `with open(local, "wb") as f:`
- `tests/test_dropbox.py:405` `open` — `with open(local, "wb") as f:`
- `tests/test_dropbox.py:536` `os.path.exists` — `assert not os.path.exists(os.path.join(str(home), dbx.TOKEN_FILE_PLAIN))`
- `tests/test_dropbox.py:541` `os.stat` — `st = os.stat(os.path.join(str(home), dbx.TOKEN_FILE_PLAIN))`
- `tests/test_dropbox.py:559` `open` — `assert REFRESH.encode() not in open(p, "rb").read()`
- `tests/test_dropbox.py:561` `os.path.exists` — `assert not os.path.exists(os.path.join(str(home), dbx.TOKEN_FILE_PLAIN))`
- `tests/test_dropbox.py:563` `os.path.exists` — `assert not os.path.exists(p)`
- `tests/test_dropbox.py:580` `open` — `with open(local, "wb") as f:`
- `tests/test_dropbox.py:689` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_dropbox.py:690` `open` — `doc = open(os.path.join(root, "docs", "IT_DEPLOYMENT.md"),`
- `tests/test_dropbox.py:698` `open` — `src = open(os.path.join(os.path.dirname(dbx.__file__), "dropbox_ui.py"),`

#### `tests/test_dxf.py`

- `tests/test_dxf.py:149` `os.path.exists` — `while not os.path.exists(str(tmp_path / "back.dxf")) and \`
- `tests/test_dxf.py:153` `os.path.exists` — `assert os.path.exists(str(tmp_path / "back.dxf"))`

#### `tests/test_energy.py`

- `tests/test_energy.py:72` `os.path.exists` — `assert b["sections"] >= 5 and os.path.exists(b["pdf"])`

#### `tests/test_esign.py`

- `tests/test_esign.py:235` `open` — `assert open(out, "rb").read().startswith(b"%PDF")`

#### `tests/test_estimate_export.py`

- `tests/test_estimate_export.py:111` `open` — `rows = list(csv.reader(open(path, encoding="utf-8-sig")))`
- `tests/test_estimate_export.py:152` `os.path.getsize` — `assert fn(p) == p and os.path.getsize(p) > 0`
- `tests/test_estimate_export.py:182` `open` — `assert "Test flooring" in open(c, encoding="utf-8-sig").read()`

#### `tests/test_estimate_layouts.py`

- `tests/test_estimate_layouts.py:235` `open` — `data = json.loads(open(path, encoding="utf-8").read())`
- `tests/test_estimate_layouts.py:284` `open` — `rows = list(csv.reader(open(p, encoding="utf-8-sig")))`
- `tests/test_estimate_layouts.py:319` `os.path.getsize` — `assert fn(p) == p and os.path.getsize(p) > 0`
- `tests/test_estimate_layouts.py:320` `open` — `rows = list(csv.reader(open(str(tmp_path / "layout.csv"),`
- `tests/test_estimate_layouts.py:352` `open` — `assert p and L.from_json(open(p, encoding="utf-8").read())[0][`

#### `tests/test_estimate_lines.py`

- `tests/test_estimate_lines.py:189` `open` — `text = open(path, encoding="utf-8-sig").read()`

#### `tests/test_export_background.py`

- `tests/test_export_background.py:28` `open` — `open(path, "wb").write(b"x")`
- `tests/test_export_background.py:35` `os.path.exists` — `assert _wait(lambda: os.path.exists(out))`
- `tests/test_export_background.py:44` `open` — `open(path, "w").write("0\nEOF\n")`
- `tests/test_export_background.py:50` `os.path.exists` — `assert _wait(lambda: os.path.exists(out))`

#### `tests/test_fewer_clicks.py`

- `tests/test_fewer_clicks.py:94` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_fewer_clicks.py:368` `os.utime` — `os.utime(tmp_path / name, (t, t))`
- `tests/test_fewer_clicks.py:427` `os.path.isfile` — `assert out and os.path.isfile(out) and out.endswith("set - page 2.pdf")`

#### `tests/test_fixes.py`

- `tests/test_fixes.py:149` `os.listdir` — `files = os.listdir(str(src) + ".versions")`

#### `tests/test_formlib.py`

- `tests/test_formlib.py:52` `os.path.exists` — `assert os.path.exists(formlib.path_of(e))`
- `tests/test_formlib.py:87` `os.path.exists` — `e2["category"] == "Field Forms" and os.path.exists(`
- `tests/test_formlib.py:90` `os.makedirs` — `os.makedirs(os.path.join(formlib.folder(), "Bidding"))`

#### `tests/test_formula_guard_exporters.py`

- `tests/test_formula_guard_exporters.py:23` `open` — `with open(path, encoding="utf-8-sig", newline="") as f:`
- `tests/test_formula_guard_exporters.py:250` `open` — `with open(path, encoding="utf-8-sig", newline="") as f:`

#### `tests/test_freeze_offer.py`

- `tests/test_freeze_offer.py:32` `open` — `with open(crash, "a", encoding="utf-8") as f:`
- `tests/test_freeze_offer.py:36` `open` — `assert "froze in the previous session" in open(p, encoding="utf-8").read()`
- `tests/test_freeze_offer.py:46` `open` — `with open(crash, "a", encoding="utf-8") as f:`
- `tests/test_freeze_offer.py:51` `open` — `with open(crash, "a", encoding="utf-8") as f:`

#### `tests/test_freeze_watch.py`

- `tests/test_freeze_watch.py:15` `open` — `f = open(path, "w", encoding="utf-8")`

#### `tests/test_genset.py`

- `tests/test_genset.py:79` `open` — `side = json.load(open(res["sidecar"]))`
- `tests/test_genset.py:174` `os.path.isfile` — `assert os.path.isfile(out[:-4] + ".genset.json")`
- `tests/test_genset.py:175` `os.path.exists` — `assert not os.path.exists(out[:-4] + ".genset.json.tmp")`
- `tests/test_genset.py:333` `open` — `side = json.load(open(res["sidecar"]))`
- `tests/test_genset.py:345` `os.path.isfile` — `assert res["dxf"] and os.path.isfile(res["dxf"])`
- `tests/test_genset.py:349` `open` — `side = json.load(open(res["sidecar"]))`
- `tests/test_genset.py:834` `open` — `rows = list(csv.reader(open(res["quantities"], encoding="utf-8")))`
- `tests/test_genset.py:861` `open` — `text = open(path, encoding="utf-8-sig").read()`

#### `tests/test_genset_restaurant.py`

- `tests/test_genset_restaurant.py:272` `open` — `side = json.load(open(res["sidecar"]))`
- `tests/test_genset_restaurant.py:1186` `os.path.abspath` — `d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `tests/test_genset_restaurant.py:1188` `open` — `with open(os.path.join(d, name + ".json"), encoding="utf-8") as f:`

#### `tests/test_genset_strip.py`

- `tests/test_genset_strip.py:288` `open` — `side = json.load(open(res["sidecar"]))`

#### `tests/test_genset_types.py`

- `tests/test_genset_types.py:13` `os.path.abspath` — `GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `tests/test_genset_types.py:18` `open` — `with open(os.path.join(GOLDEN, "cases.json"), encoding="utf-8") as f:`
- `tests/test_genset_types.py:47` `open` — `with open(os.path.join(GOLDEN, name + ".json"), encoding="utf-8") as f:`
- `tests/test_genset_types.py:56` `open` — `with open(os.path.join(GOLDEN, "derived.json"), encoding="utf-8") as f:`
- `tests/test_genset_types.py:66` `open` — `with open(os.path.join(GOLDEN, "house_1story.json"),`

#### `tests/test_genset_warehouse.py`

- `tests/test_genset_warehouse.py:268` `open` — `side = json.load(open(res["sidecar"]))`

#### `tests/test_gui.py`

- `tests/test_gui.py:210` `os.path.exists` — `assert os.path.exists(tmp_path / "copy.pdf")`
- `tests/test_gui.py:242` `open` — `assert "Outlets" in open(out, encoding="utf-8-sig").read()`
- `tests/test_gui.py:407` `open` — `assert "Accepted" in open(out, encoding="utf-8-sig").read()`
- `tests/test_gui.py:478` `open` — `assert "My Cloud" in open(toolchest.PATH).read() # saved to disk`
- `tests/test_gui.py:500` `open` — `assert "Grand Total" in open(out, encoding="utf-8-sig").read()`
- `tests/test_gui.py:555` `os.path.exists` — `assert os.path.exists(tmp_path / "combined.pdf")`
- `tests/test_gui.py:730` `open` — `assert out and open(out, "rb").read(4) == b"\x89PNG"`

#### `tests/test_heavy.py`

- `tests/test_heavy.py:24` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tests/test_heavy.py:120` `open` — `with open(p, "w", newline="") as f:`
- `tests/test_heavy.py:157` `open` — `rows = list(csv.reader(open(out)))`
- `tests/test_heavy.py:291` `open` — `html = open(os.path.join(os.path.dirname(hubmod.__file__), "web",`
- `tests/test_heavy.py:446` `open` — `assert list(csv.reader(open(out)))[0][0] == "Month"`
- `tests/test_heavy.py:452` `open` — `st = json.load(open(heavy.STARTER, encoding="utf-8"))`
- `tests/test_heavy.py:575` `open` — `assert list(csv.reader(open(out)))[0][0] == "Cost code"`

#### `tests/test_heavybid_background.py`

- `tests/test_heavybid_background.py:36` `os.listdir` — `names = os.listdir(folder)`

#### `tests/test_help_111.py`

- `tests/test_help_111.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_help_111.py:71` `open` — `text = open(os.path.join(ROOT, rel), encoding="utf-8").read()`

#### `tests/test_help_nov3.py`

- `tests/test_help_nov3.py:38` `open` — `s = json.load(open(p, encoding="utf-8"))["1.0.6"]`
- `tests/test_help_nov3.py:47` `open` — `s = json.load(open(p, encoding="utf-8"))["1.1.1"]`

#### `tests/test_hosted_relay.py`

- `tests/test_hosted_relay.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tests/test_interop.py`

- `tests/test_interop.py:61` `open` — `f = json.load(open(path))["features"][0]`
- `tests/test_interop.py:73` `open` — `assert "<Polygon>" in open(kml).read()`

#### `tests/test_it_policy.py`

- `tests/test_it_policy.py:186` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_it_policy.py:187` `open` — `admx = open(os.path.join(root, "installer", "policy",`
- `tests/test_it_policy.py:189` `open` — `adml = open(os.path.join(root, "installer", "policy", "en-US",`
- `tests/test_it_policy.py:191` `open` — `doc = open(os.path.join(root, "docs", "IT_DEPLOYMENT.md"),`
- `tests/test_it_policy.py:212` `open` — `src = open(weather.__file__, encoding="utf-8").read()`
- `tests/test_it_policy.py:228` `os.path.isfile` — `assert len(a) >= 24 and os.path.isfile(p)`
- `tests/test_it_policy.py:245` `open` — `assert seen["args"][3] == open(tok).read().strip()`
- `tests/test_it_policy.py:270` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_it_policy.py:271` `open` — `iss = open(os.path.join(root, "installer", "quantisheet_server.iss"),`
- `tests/test_it_policy.py:273` `open` — `doc = open(os.path.join(root, "docs", "IT_DEPLOYMENT.md"),`

#### `tests/test_job_info.py`

- `tests/test_job_info.py:37` `open` — `with open(path, "wb") as f:`
- `tests/test_job_info.py:90` `open` — `with open(img, "rb") as f:`
- `tests/test_job_info.py:132` `open` — `with open(big, "wb") as f:`

#### `tests/test_levelboard.py`

- `tests/test_levelboard.py:53` `open` — `assert "Fire-rated shaft walls" in open(p, encoding="utf-8").read()`

#### `tests/test_leveling.py`

- `tests/test_leveling.py:13` `os.path.abspath` — `TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(`
- `tests/test_leveling.py:93` `os.path.getsize` — `assert os.path.getsize(out) > 1000`

#### `tests/test_master_decisions.py`

- `tests/test_master_decisions.py:178` `os.makedirs` — `os.makedirs(os.path.dirname(dest), exist_ok=True)`
- `tests/test_master_decisions.py:179` `open` — `with open(dest, "wb") as f:`
- `tests/test_master_decisions.py:190` `open` — `with open(local, "rb") as f:`
- `tests/test_master_decisions.py:203` `open` — `with open(p, "rb") as f:`

#### `tests/test_model_estimate.py`

- `tests/test_model_estimate.py:29` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`

#### `tests/test_msi.py`

- `tests/test_msi.py:8` `os.path.abspath` — `os.path.abspath(__file__))), "tools"))`
- `tests/test_msi.py:22` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_msi.py:23` `open` — `iss = open(os.path.join(root, "installer", "quantisheet_server.iss"),`

#### `tests/test_name_memory.py`

- `tests/test_name_memory.py:94` `open` — `with open(nm.path(), "w", encoding="utf-8") as f:`

#### `tests/test_no_rival_names.py`

- `tests/test_no_rival_names.py:12` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_no_rival_names.py:19` `open` — `tree = ast.parse(open(path, encoding="utf-8").read())`
- `tests/test_no_rival_names.py:52` `open` — `with open(p, encoding="utf-8", errors="replace") as f:`

#### `tests/test_nov4_items.py`

- `tests/test_nov4_items.py:96` `os.makedirs` — `os.makedirs(folder)`
- `tests/test_nov4_items.py:118` `os.path.abspath` — `here = os.path.dirname(os.path.abspath(__file__))`
- `tests/test_nov4_items.py:166` `os.path.abspath` — `here = os.path.dirname(os.path.abspath(__file__))`
- `tests/test_nov4_items.py:167` `open` — `src = open(os.path.join(here, "..", "tools", "build_installer.py"),`

#### `tests/test_onboard.py`

- `tests/test_onboard.py:44` `open` — `src = open(onboard.__file__, encoding="utf-8").read().lower()`

#### `tests/test_openwith.py`

- `tests/test_openwith.py:8` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_openwith.py:19` `open` — `text = open(os.path.join(ROOT, "installer", name),`
- `tests/test_openwith.py:170` `open` — `src = open(build_msix.__file__, encoding="utf-8").read()`

#### `tests/test_owner_report.py`

- `tests/test_owner_report.py:54` `os.utime` — `os.utime(p, (t, t))`
- `tests/test_owner_report.py:121` `os.path.getsize` — `assert res["bytes"] == os.path.getsize(tmp_path / "r.pdf")`
- `tests/test_owner_report.py:279` `os.path.isfile` — `assert os.path.isfile(ex["path"])`
- `tests/test_owner_report.py:933` `os.path.getsize` — `full = os.path.getsize(os.path.join(orl.font_dir(),`

#### `tests/test_owner_report_logs.py`

- `tests/test_owner_report_logs.py:547` `os.path.getsize` — `full = os.path.getsize(os.path.join(L.font_dir(),`
- `tests/test_owner_report_logs.py:560` `os.path.isfile` — `assert os.path.isfile(os.path.join(L.font_dir(), name)), name`
- `tests/test_owner_report_logs.py:561` `open` — `with open(os.path.join(L.font_dir(), "OFL.txt"), encoding="utf-8") as f:`

#### `tests/test_owner_report_ui.py`

- `tests/test_owner_report_ui.py:113` `os.path.isfile` — `assert os.path.isfile(w.last_pdf)`
- `tests/test_owner_report_ui.py:284` `os.path.isfile` — `assert os.path.isfile(store.attachment_path(kp["sheet"]))`

#### `tests/test_p0_safety.py`

- `tests/test_p0_safety.py:165` `os.path.exists` — `assert not os.path.exists(tmp / "copy.pdf")`
- `tests/test_p0_safety.py:193` `os.path.getsize` — `before = os.path.getsize(newer)`
- `tests/test_p0_safety.py:195` `os.path.getsize` — `assert os.path.getsize(newer) == before`
- `tests/test_p0_safety.py:221` `os.path.isfile` — `assert os.path.isfile(jobsafe.backup_path(path))`
- `tests/test_p0_safety.py:227` `os.makedirs` — `os.makedirs(os.path.dirname(stripped))`
- `tests/test_p0_safety.py:247` `os.path.isfile` — `assert os.path.isfile(jobsafe.lock_path(path))`
- `tests/test_p0_safety.py:251` `open` — `with open(other, "w") as f:`
- `tests/test_p0_safety.py:257` `os.utime` — `os.utime(path, (1, 1))`
- `tests/test_p0_safety.py:263` `os.path.exists` — `assert not os.path.exists(jobsafe.lock_path(path)) # removed on close`

#### `tests/test_p0_updater.py`

- `tests/test_p0_updater.py:42` `os.listdir` — `left = sorted(os.listdir(tmp_path))`

#### `tests/test_p1_own_wording_payapp.py`

- `tests/test_p1_own_wording_payapp.py:33` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_p1_own_wording_payapp.py:35` `open` — `src = open(os.path.join(root, "app", f), encoding="utf-8").read()`

#### `tests/test_p1_photo_library.py`

- `tests/test_p1_photo_library.py:55` `open` — `src = open(pl.__file__, encoding="utf-8").read()`

#### `tests/test_p1_project_backup.py`

- `tests/test_p1_project_backup.py:49` `os.listdir` — `assert not [d for d in os.listdir(tmp_path) if d.startswith(".qs-")]`
- `tests/test_p1_project_backup.py:69` `os.listdir` — `kept = [d for d in os.listdir(tmp_path) if ".before-restore-" in d]`

#### `tests/test_p1_roles.py`

- `tests/test_p1_roles.py:67` `os.walk` — `for base, _d, files in os.walk(str(tmp / "hub")):`
- `tests/test_p1_roles.py:70` `open` — `rows += [json.loads(x) for x in open(os.path.join(base, f),`

#### `tests/test_packages.py`

- `tests/test_packages.py:56` `os.path.isfile` — `assert os.path.isfile(os.path.join(str(tmp_path), "packages.json"))`

#### `tests/test_packages_live.py`

- `tests/test_packages_live.py:40` `os.path.isfile` — `assert os.path.isfile(os.path.join(str(cfg), "carrier_keys.json"))`

#### `tests/test_patent_design_rules.py`

- `tests/test_patent_design_rules.py:16` `open` — `with open(os.path.join(APP, name), encoding="utf-8") as f:`

#### `tests/test_pdf_tools_0_13_5.py`

- `tests/test_pdf_tools_0_13_5.py:169` `open` — `assert b"Examplefield" not in open(out, "rb").read()`
- `tests/test_pdf_tools_0_13_5.py:249` `open` — `on_disk = open(path, "rb").read()`
- `tests/test_pdf_tools_0_13_5.py:275` `open` — `assert open(path, "rb").read() == on_disk # nothing was saved`
- `tests/test_pdf_tools_0_13_5.py:355` `os.path.getsize` — `original=os.path.getsize(src))`
- `tests/test_pdf_tools_0_13_5.py:360` `os.listdir` — `assert sorted(os.listdir(tmp_path)) == ["small.pdf"] # no temp left`
- `tests/test_pdf_tools_0_13_5.py:373` `os.path.getsize` — `original=os.path.getsize(src))`
- `tests/test_pdf_tools_0_13_5.py:383` `os.path.getsize` — `original=os.path.getsize(src))`
- `tests/test_pdf_tools_0_13_5.py:384` `os.path.getsize` — `assert out.exists() and size == os.path.getsize(out)`
- `tests/test_pdf_tools_0_13_5.py:385` `os.path.getsize` — `assert size < os.path.getsize(src)`
- `tests/test_pdf_tools_0_13_5.py:399` `os.path.isfile` — `assert os.path.isfile(res[scan])`
- `tests/test_pdf_tools_0_13_5.py:400` `os.listdir` — `assert os.listdir(out_dir) == ["scan.pdf"]`
- `tests/test_pdf_tools_0_13_5.py:408` `os.path.isfile` — `assert os.path.isfile(out), res`
- `tests/test_pdf_tools_0_13_5.py:430` `open` — `data = bytearray(open(path, "rb").read())`
- `tests/test_pdf_tools_0_13_5.py:440` `open` — `open(path, "wb").write(bytes(data))`
- `tests/test_pdf_tools_0_13_5.py:446` `open` — `original = open(src, "rb").read()`
- `tests/test_pdf_tools_0_13_5.py:459` `open` — `assert open(src, "rb").read() == original # never overwritten`
- `tests/test_pdf_tools_0_13_5.py:468` `open` — `data = open(src, "rb").read()`
- `tests/test_pdf_tools_0_13_5.py:469` `open` — `open(src, "wb").write(data[:int(len(data) * 0.7)])`
- `tests/test_pdf_tools_0_13_5.py:475` `os.path.isfile` — `assert rep.out and os.path.isfile(rep.out)`
- `tests/test_pdf_tools_0_13_5.py:487` `os.listdir` — `assert os.listdir(tmp_path) == ["Example clean.pdf"]`
- `tests/test_pdf_tools_0_13_5.py:625` `os.path.isfile` — `assert os.path.isfile(tmp_path / "Example damaged (repaired).pdf")`

#### `tests/test_photofit.py`

- `tests/test_photofit.py:154` `os.utime` — `os.utime(p, (t, t))`
- `tests/test_photofit.py:157` `os.utime` — `os.utime(p, (t, t))`
- `tests/test_photofit.py:161` `os.utime` — `os.utime(q, (t, t))`
- `tests/test_photofit.py:221` `os.path.getsize` — `assert os.path.getsize(p) > sizes["print"]`
- `tests/test_photofit.py:288` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `tests/test_photofit.py:314` `os.listdir` — `cached = os.listdir(os.path.join(store.att_dir(), "cache"))`
- `tests/test_photofit.py:317` `open` — `with open(src, "rb") as f:`

#### `tests/test_pipe_pricing.py`

- `tests/test_pipe_pricing.py:54` `open` — `with open(p, "w", newline="") as f:`
- `tests/test_pipe_pricing.py:73` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`

#### `tests/test_pm.py`

- `tests/test_pm.py:22` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_pm.py:548` `open` — `body = open(csv).read()`

#### `tests/test_price_import.py`

- `tests/test_price_import.py:23` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_price_import.py:186` `open` — `with open(pricedb.path(), "rb") as f:`
- `tests/test_price_import.py:258` `open` — `with open(p, "w", newline="", encoding="utf-8") as f:`
- `tests/test_price_import.py:283` `open` — `with open(build / "mine.json", encoding="utf-8") as f:`
- `tests/test_price_import.py:311` `open` — `with open(os.path.join(ROOT, rel), encoding="utf-8") as f:`

#### `tests/test_pricedb.py`

- `tests/test_pricedb.py:38` `os.path.exists` — `assert path == "db:Shop 2026" and os.path.exists(pricedb.path())`
- `tests/test_pricedb.py:94` `shutil.move` — `shutil.move(str(tmp_path / "server"), str(tmp_path / "gone"))`
- `tests/test_pricedb.py:99` `shutil.move` — `shutil.move(str(tmp_path / "gone"), str(tmp_path / "server"))`
- `tests/test_pricedb.py:106` `os.path.exists` — `assert os.path.exists(pricedb.snapshot())`
- `tests/test_pricedb.py:111` `open` — `with open(os.path.join(folder, "Old.json"), "w", encoding="utf-8") as f:`
- `tests/test_pricedb.py:149` `os.path.getsize` — `assert os.path.getsize(out) > 50`

#### `tests/test_pricehistory.py`

- `tests/test_pricehistory.py:22` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tests/test_pricehistory.py:73` `open` — `with open(rep, "w", newline="") as f:`

#### `tests/test_printer.py`

- `tests/test_printer.py:93` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_printer.py:94` `open` — `server = open(os.path.join(root, "installer", "quantisheet_server.iss"),`
- `tests/test_printer.py:116` `open` — `assert open(got, "rb").read() == b"%PDF-1.7 fake"`
- `tests/test_printer.py:160` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_printer.py:161` `open` — `msi = open(os.path.join(root, "tools", "make_msi.py"),`
- `tests/test_printer.py:164` `open` — `iss = open(os.path.join(root, "installer", "quantisheet_server.iss"),`

#### `tests/test_productivity.py`

- `tests/test_productivity.py:93` `os.path.exists` — `assert not os.path.exists(prod.path())`
- `tests/test_productivity.py:95` `open` — `with open(prod.path(), "w", encoding="utf-8") as fh:`
- `tests/test_productivity.py:120` `open` — `with open(prod.path(), "w", encoding="utf-8") as fh:`
- `tests/test_productivity.py:125` `os.path.exists` — `assert not os.path.exists(prod.path())`
- `tests/test_productivity.py:293` `os.path.exists` — `assert not os.path.exists(prod.path())`
- `tests/test_productivity.py:421` `os.remove` — `os.remove(os.path.splitext(pdf)[0] + ".genset.json")`

#### `tests/test_project.py`

- `tests/test_project.py:97` `os.path.getsize` — `assert os.path.getsize(doccontrol.register_xlsx(`
- `tests/test_project.py:132` `os.path.getsize` — `assert os.path.getsize(qa.punch_xlsx(d, str(tmp_path / "p.xlsx"))) > 0`
- `tests/test_project.py:221` `os.path.exists` — `assert q._pl_pdf() == out and os.path.exists(out)`

#### `tests/test_public_scan.py`

- `tests/test_public_scan.py:8` `os.path.abspath` — `os.path.abspath(__file__))), "tools"))`

#### `tests/test_quick_sf.py`

- `tests/test_quick_sf.py:20` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`

#### `tests/test_r111_agreements.py`

- `tests/test_r111_agreements.py:119` `os.path.isfile` — `return os.path.isfile(path)`

#### `tests/test_r111_backflow.py`

- `tests/test_r111_backflow.py:17` `open` — `src = open(backflow.__file__, encoding="utf-8").read().lower()`
- `tests/test_r111_backflow.py:89` `open` — `assert COMPANY["name"] not in open(backflow.__file__, encoding="utf-8").read()`
- `tests/test_r111_backflow.py:113` `os.path.isfile` — `assert path and os.path.isfile(path)`

#### `tests/test_r111_dispatch.py`

- `tests/test_r111_dispatch.py:83` `os.path.isfile` — `assert path and os.path.isfile(path)`

#### `tests/test_r111_handover.py`

- `tests/test_r111_handover.py:120` `os.path.isdir` — `assert os.path.isdir(os.path.dirname(service.default_path()))`

#### `tests/test_r111_pricebook.py`

- `tests/test_r111_pricebook.py:82` `os.path.isfile` — `assert path and os.path.isfile(path)`

#### `tests/test_r111_recommend.py`

- `tests/test_r111_recommend.py:71` `os.path.isfile` — `assert path and os.path.isfile(path)`

#### `tests/test_r111_refrigerant.py`

- `tests/test_r111_refrigerant.py:19` `open` — `src = open(refrigerant.__file__, encoding="utf-8").read()`

#### `tests/test_r111_service_menu.py`

- `tests/test_r111_service_menu.py:15` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_r111_service_menu.py:53` `os.walk` — `for dirpath, _dirs, names in os.walk(base):`
- `tests/test_r111_service_menu.py:58` `open` — `tree = ast.parse(open(path, encoding="utf-8").read())`

#### `tests/test_r111_tmtag.py`

- `tests/test_r111_tmtag.py:54` `os.path.isfile` — `assert os.path.isfile(dest)`
- `tests/test_r111_tmtag.py:55` `os.path.getsize` — `assert os.path.getsize(dest) > os.path.getsize(src)`
- `tests/test_r111_tmtag.py:55` `os.path.getsize` — `assert os.path.getsize(dest) > os.path.getsize(src)`

#### `tests/test_r111_truckstock.py`

- `tests/test_r111_truckstock.py:64` `open` — `text = open(path, encoding="utf-8").read()`
- `tests/test_r111_truckstock.py:90` `open` — `assert path and "Test fuse" in open(path, encoding="utf-8").read()`

#### `tests/test_r111_workorder.py`

- `tests/test_r111_workorder.py:171` `os.path.isfile` — `assert os.path.isfile(path)`
- `tests/test_r111_workorder.py:194` `os.path.isfile` — `assert os.path.isfile(os.path.join(`
- `tests/test_r111_workorder.py:197` `os.path.isfile` — `assert printed and os.path.isfile(printed)`

#### `tests/test_r34_startup_lock.py`

- `tests/test_r34_startup_lock.py:6` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_r34_startup_lock.py:14` `open` — `with open(os.path.join(ROOT, "quantisheet.py"), encoding="utf-8") as f:`

#### `tests/test_r36_actuals.py`

- `tests/test_r36_actuals.py:87` `open` — `assert "Estimate cost" in open(p, encoding="utf-8").read()`

#### `tests/test_r36_actuals_import.py`

- `tests/test_r36_actuals_import.py:46` `open` — `with open(path, "w", newline="", encoding=enc) as f:`
- `tests/test_r36_actuals_import.py:124` `open` — `rows = list(csv.reader(open(e, encoding="utf-8-sig")))`
- `tests/test_r36_actuals_import.py:143` `open` — `txt = open(e, encoding="utf-8-sig").read()`
- `tests/test_r36_actuals_import.py:151` `os.path.exists` — `had = os.path.exists(pricedb.path())`
- `tests/test_r36_actuals_import.py:153` `os.path.exists` — `assert os.path.exists(pricedb.path()) == had`

#### `tests/test_r36_actuals_waste.py`

- `tests/test_r36_actuals_waste.py:116` `open` — `rows = list(csv.reader(open(p, encoding="utf-8-sig")))`

#### `tests/test_r36_assembly_rules.py`

- `tests/test_r36_assembly_rules.py:31` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tests/test_r36_assembly_rules.py:188` `os.listdir` — `assert os.listdir(os.path.join(settings.DIR, "backups"))`
- `tests/test_r36_assembly_rules.py:197` `os.path.exists` — `assert not os.path.exists(pricedb.path()) # never made`

#### `tests/test_r36_bid_items.py`

- `tests/test_r36_bid_items.py:43` `open` — `rows = list(csv.reader(open(p, encoding="utf-8")))`
- `tests/test_r36_bid_items.py:67` `os.path.getsize` — `assert os.path.getsize(p) > 0`

#### `tests/test_r36_bidday.py`

- `tests/test_r36_bidday.py:75` `open` — `rows = list(csv.reader(open(out, encoding="utf-8")))`

#### `tests/test_r36_bidday_takeoff.py`

- `tests/test_r36_bidday_takeoff.py:43` `open` — `rows = list(csv.reader(open(form, encoding="utf-8-sig")))`
- `tests/test_r36_bidday_takeoff.py:50` `open` — `with open(back, "w", newline="", encoding="utf-8") as f:`

#### `tests/test_r36_check_rules.py`

- `tests/test_r36_check_rules.py:94` `open` — `src = open(ui.__file__, encoding="utf-8").read()`

#### `tests/test_r36_checks.py`

- `tests/test_r36_checks.py:134` `open` — `text = open(p, encoding="utf-8").read()`

#### `tests/test_r36_crewhours.py`

- `tests/test_r36_crewhours.py:72` `open` — `text = open(p, encoding="utf-8").read()`

#### `tests/test_r36_db_safety.py`

- `tests/test_r36_db_safety.py:47` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tests/test_r36_db_safety.py:59` `open` — `return {os.path.basename(f): open(f, "rb").read()`
- `tests/test_r36_db_safety.py:72` `os.path.isfile` — `assert os.path.isfile(_db())`
- `tests/test_r36_db_safety.py:113` `os.path.exists` — `assert not os.path.exists(_db())`
- `tests/test_r36_db_safety.py:143` `os.path.exists` — `if os.path.exists(_db()):`
- `tests/test_r36_db_safety.py:144` `os.remove` — `os.remove(_db())`
- `tests/test_r36_db_safety.py:186` `os.path.exists` — `if os.path.exists(_db()):`
- `tests/test_r36_db_safety.py:187` `os.remove` — `os.remove(_db())`
- `tests/test_r36_db_safety.py:202` `os.path.exists` — `assert n == 0 and not os.path.exists(_db())`
- `tests/test_r36_db_safety.py:241` `os.path.exists` — `assert not os.path.exists(_db()), "price database created"`
- `tests/test_r36_db_safety.py:353` `os.path.isdir` — `assert not os.path.isdir(templates.folder()) or \`
- `tests/test_r36_db_safety.py:354` `os.listdir` — `not os.listdir(templates.folder())`

#### `tests/test_r36_friendly_names.py`

- `tests/test_r36_friendly_names.py:65` `open` — `body = open(p, encoding="utf-8-sig").read()`

#### `tests/test_r36_materials.py`

- `tests/test_r36_materials.py:71` `open` — `rows = list(csv.reader(open(p, encoding="utf-8")))`
- `tests/test_r36_materials.py:76` `os.path.getsize` — `assert os.path.getsize(p2) > 0`

#### `tests/test_r36_parametric.py`

- `tests/test_r36_parametric.py:90` `open` — `assert "Capital total" in open(out, encoding="utf-8").read()`

#### `tests/test_r36_price_workbook.py`

- `tests/test_r36_price_workbook.py:39` `open` — `return hashlib.sha256(open(p, "rb").read()).hexdigest()`

#### `tests/test_r36_quote_pdf_own.py`

- `tests/test_r36_quote_pdf_own.py:20` `os.path.abspath` — `HERE = os.path.dirname(os.path.abspath(__file__))`
- `tests/test_r36_quote_pdf_own.py:127` `open` — `with open(GOLDEN, encoding="utf-8") as f:`
- `tests/test_r36_quote_pdf_own.py:161` `open` — `src = open(mod.__file__, encoding="utf-8").read()`
- `tests/test_r36_quote_pdf_own.py:175` `open` — `with open(sys.argv[1], "w", encoding="utf-8") as f:`

#### `tests/test_r36_quotes.py`

- `tests/test_r36_quotes.py:118` `open` — `rows = list(csv.reader(open(p, encoding="utf-8")))`

#### `tests/test_r36_rate_matcher.py`

- `tests/test_r36_rate_matcher.py:33` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tests/test_r36_rate_matcher.py:53` `open` — `return {os.path.basename(f): open(f, "rb").read()`
- `tests/test_r36_rate_matcher.py:108` `os.path.exists` — `assert not os.path.exists(pricedb.path())`
- `tests/test_r36_rate_matcher.py:112` `os.path.exists` — `assert not os.path.exists(pricedb.path()) # no file made by a read`

#### `tests/test_r36_safe_writes.py`

- `tests/test_r36_safe_writes.py:37` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tests/test_r36_safe_writes.py:41` `os.listdir` — `return [f for f in os.listdir(folder)`
- `tests/test_r36_safe_writes.py:88` `open` — `assert len(baks) == 1 and open(baks[0], "rb").read() == old`
- `tests/test_r36_safe_writes.py:159` `os.path.abspath` — `_io.data_file(os.path.abspath(os.sep), "outside.json")`
- `tests/test_r36_safe_writes.py:161` `os.path.realpath` — `assert p.startswith(os.path.realpath(settings.DIR) + os.sep)`
- `tests/test_r36_safe_writes.py:164` `os.path.realpath` — `assert os.path.realpath(saved).startswith(`
- `tests/test_r36_safe_writes.py:165` `os.path.realpath` — `os.path.realpath(settings.DIR) + os.sep)`
- `tests/test_r36_safe_writes.py:167` `os.path.realpath` — `assert os.path.realpath(f).startswith(`
- `tests/test_r36_safe_writes.py:168` `os.path.realpath` — `os.path.realpath(templates.folder()) + os.sep)`
- `tests/test_r36_safe_writes.py:169` `os.path.realpath` — `assert os.path.realpath(service.default_path()).startswith(`
- `tests/test_r36_safe_writes.py:170` `os.path.realpath` — `os.path.realpath(settings.DIR) + os.sep)`
- `tests/test_r36_safe_writes.py:177` `os.symlink` — `os.symlink(str(away), os.path.join(settings.DIR, "estimate_templates"),`
- `tests/test_r36_safe_writes.py:184` `os.listdir` — `assert os.listdir(str(away)) == []`
- `tests/test_r36_safe_writes.py:197` `os.path.exists` — `assert not os.path.exists(bad) or bad.endswith("settings.json")`
- `tests/test_r36_safe_writes.py:202` `os.path.isfile` — `assert os.path.isfile(ok)`
- `tests/test_r36_safe_writes.py:220` `open` — `src = open(ui.__file__, encoding="utf-8").read()`

#### `tests/test_r36_service.py`

- `tests/test_r36_service.py:86` `open` — `text = open(out, encoding="utf-8").read()`

#### `tests/test_r36_starters.py`

- `tests/test_r36_starters.py:28` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tests/test_r36_starters.py:75` `open` — `with open(mine, encoding="utf-8") as f:`
- `tests/test_r36_starters.py:78` `open` — `with open(mine, "w", encoding="utf-8") as f:`

#### `tests/test_r36_supplier_prices.py`

- `tests/test_r36_supplier_prices.py:75` `open` — `data = json.load(open(res["saved"], encoding="utf-8"))`
- `tests/test_r36_supplier_prices.py:89` `os.walk` — `for dp, _dn, fn in os.walk(_io.APP_DIR):`

#### `tests/test_r36_ui.py`

- `tests/test_r36_ui.py:80` `os.path.isfile` — `assert os.path.isfile(tmp_path / "quote.pdf")`
- `tests/test_r36_ui.py:131` `os.path.isfile` — `assert os.path.isfile(tmp_path / "yard.json")`

#### `tests/test_r36_ui_step7.py`

- `tests/test_r36_ui_step7.py:101` `os.path.exists` — `assert os.path.exists(tmp_path / "m.json")`
- `tests/test_r36_ui_step7.py:115` `os.path.exists` — `assert os.path.exists(tmp_path / "Job - priced.xlsx")`
- `tests/test_r36_ui_step7.py:134` `os.path.exists` — `assert os.path.exists(tmp_path / "rules.json")`

#### `tests/test_r39_characterize.py`

- `tests/test_r39_characterize.py:99` `os.makedirs` — `os.makedirs(DATA, exist_ok=True)`
- `tests/test_r39_characterize.py:100` `open` — `with open(path, "w", encoding="utf-8") as f:`
- `tests/test_r39_characterize.py:102` `open` — `with open(path, encoding="utf-8") as f:`

#### `tests/test_r39_master_cycle.py`

- `tests/test_r39_master_cycle.py:44` `os.path.exists` — `assert os.path.exists(inbox / ACME / "Processed" / "acme.xml")`
- `tests/test_r39_master_cycle.py:56` `open` — `open(pdf, "wb").close()`
- `tests/test_r39_master_cycle.py:73` `open` — `raw = open(s.path, "rb").read()`
- `tests/test_r39_master_cycle.py:78` `open` — `assert open(s.path, "rb").read() == raw`

#### `tests/test_r39_master_drafts.py`

- `tests/test_r39_master_drafts.py:14` `os.path.abspath` — `PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(`
- `tests/test_r39_master_drafts.py:66` `os.walk` — `for dp, _dn, fn in os.walk(PKG):`
- `tests/test_r39_master_drafts.py:70` `open` — `src = open(os.path.join(dp, f), encoding="utf-8").read()`

#### `tests/test_r39_master_flow.py`

- `tests/test_r39_master_flow.py:20` `os.listdir` — `name = name or f"{company[:4]}_{len(os.listdir(tmp_path))}.xlsx"`
- `tests/test_r39_master_flow.py:188` `os.listdir` — `assert os.listdir(q) == [first["sha256"] + ".xlsx"]`
- `tests/test_r39_master_flow.py:346` `open` — `raw = open(s.path, "rb").read()`
- `tests/test_r39_master_flow.py:350` `open` — `assert open(s.path, "rb").read() == raw`

#### `tests/test_r39_master_import.py`

- `tests/test_r39_master_import.py:213` `open` — `raw = open(s.path, "rb").read()`
- `tests/test_r39_master_import.py:217` `open` — `assert open(s.path, "rb").read() == raw`
- `tests/test_r39_master_import.py:281` `open` — `with open(p, "a", encoding="cp1252") as f:`

#### `tests/test_r39_master_intake.py`

- `tests/test_r39_master_intake.py:31` `os.replace` — `os.replace(p, dst)`
- `tests/test_r39_master_intake.py:67` `open` — `with open(f, "ab") as fh:`
- `tests/test_r39_master_intake.py:81` `os.listdir` — `assert sorted(os.listdir(inbox / ACME)) == sorted(`
- `tests/test_r39_master_intake.py:146` `os.path.exists` — `assert all(p.endswith(".xlsx") and os.path.exists(p) for p in out)`

#### `tests/test_r39_master_ui.py`

- `tests/test_r39_master_ui.py:55` `os.makedirs` — `os.makedirs(os.path.dirname(pdf))`
- `tests/test_r39_master_ui.py:56` `open` — `open(pdf, "wb").close()`
- `tests/test_r39_master_ui.py:59` `os.path.samefile` — `assert got is not None and os.path.samefile(got.folder, s.folder)`
- `tests/test_r39_master_ui.py:203` `open` — `raw = open(s.path, "rb").read()`
- `tests/test_r39_master_ui.py:210` `open` — `assert open(s.path, "rb").read() == raw`

#### `tests/test_rebrand.py`

- `tests/test_rebrand.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_rebrand.py:37` `os.path.isfile` — `if os.path.isfile(p):`
- `tests/test_rebrand.py:40` `os.walk` — `for base, dirs, names in os.walk(p):`
- `tests/test_rebrand.py:54` `open` — `with open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8",`
- `tests/test_rebrand.py:71` `os.walk` — `for base, dirs, names in os.walk(os.path.join(ROOT, item)):`
- `tests/test_rebrand.py:80` `open` — `iss = open(os.path.join(ROOT, "installer", "quantisheet.iss"),`
- `tests/test_rebrand.py:85` `open` — `te = open(os.path.join(ROOT, "quantisheet_backoffice", "timeentry.py"),`
- `tests/test_rebrand.py:104` `open` — `with open(os.path.join(ROOT, *p), encoding="utf-8-sig") as f:`

#### `tests/test_relay_hardening.py`

- `tests/test_relay_hardening.py:13` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tests/test_release_files.py`

- `tests/test_release_files.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_release_files.py:66` `open` — `t = open(os.path.join(ROOT, "installer", iss), encoding="utf-8",`
- `tests/test_release_files.py:76` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_release_files.py:77` `open` — `with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as f:`

#### `tests/test_review_0_12_32.py`

- `tests/test_review_0_12_32.py:43` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_review_0_12_32.py:45` `open` — `with open(os.path.join(root, name), encoding="utf-8") as f:`

#### `tests/test_review_0_13_5.py`

- `tests/test_review_0_13_5.py:106` `open` — `with open(p, "wb") as f: # sparse: 60 MB, nothing written`
- `tests/test_review_0_13_5.py:241` `open` — `with open(p, "wb") as f:`

#### `tests/test_review_0_13_6.py`

- `tests/test_review_0_13_6.py:42` `open` — `src = open(os.path.join(os.path.dirname(os.path.dirname(`
- `tests/test_review_0_13_6.py:43` `os.path.abspath` — `os.path.abspath(__file__))), "app", "tradetakeoff_ui.py"),`

#### `tests/test_review_f11_f14.py`

- `tests/test_review_f11_f14.py:10` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_review_f11_f14.py:14` `open` — `with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:`
- `tests/test_review_f11_f14.py:28` `os.path.isfile` — `assert os.path.isfile(os.path.join(costbook.SHIPPED,`
- `tests/test_review_f11_f14.py:52` `open` — `head = open(path, encoding="utf-8", errors="replace").read()`

#### `tests/test_review_followups.py`

- `tests/test_review_followups.py:26` `open` — `assert bak and open(bak, "rb").read() == b"%PDF-1.7 first"`
- `tests/test_review_followups.py:29` `open` — `assert open(bak, "rb").read() == b"%PDF-1.7 first"`

#### `tests/test_review_oct16.py`

- `tests/test_review_oct16.py:22` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tests/test_review_oct16.py:42` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_review_oct16.py:45` `open` — `assert open(os.path.join(root, a), "rb").read() == \`
- `tests/test_review_oct16.py:46` `open` — `open(os.path.join(root, b), "rb").read()`
- `tests/test_review_oct16.py:103` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_review_oct16.py:104` `os.walk` — `for dirpath, _d, files in os.walk(os.path.join(root, "app")):`
- `tests/test_review_oct16.py:107` `open` — `assert "mktemp(" not in open(os.path.join(dirpath, f),`
- `tests/test_review_oct16.py:125` `open` — `self.kept.append(open(p, "rb").read()[:4])`
- `tests/test_review_oct16.py:133` `os.listdir` — `assert os.listdir(os.path.join(str(tmp_path), ".pm_letters")) == []`

#### `tests/test_review_oct17.py`

- `tests/test_review_oct17.py:18` `os.path.abspath` — `HERE = os.path.dirname(os.path.abspath(__file__))`
- `tests/test_review_oct17.py:28` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tests/test_review_oct17.py:256` `os.path.exists` — `assert not os.path.exists(esign._signed_name(env["path"]))`

#### `tests/test_review_venice.py`

- `tests/test_review_venice.py:14` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_review_venice.py:58` `open` — `raw = open(out, "rb").read()`

#### `tests/test_revisions.py`

- `tests/test_revisions.py:66` `os.path.getsize` — `assert os.path.getsize(out) > 2000`

#### `tests/test_roof.py`

- `tests/test_roof.py:208` `open` — `text = open(path, encoding="utf-8").read()`
- `tests/test_roof.py:289` `open` — `raw = open(p, "rb").read()`
- `tests/test_roof.py:291` `open` — `got = list(csv.reader(open(p, encoding="utf-8-sig")))`

#### `tests/test_roof_flow.py`

- `tests/test_roof_flow.py:140` `open` — `src = open(os.path.join(os.path.dirname(os.path.dirname(`
- `tests/test_roof_flow.py:141` `os.path.abspath` — `os.path.abspath(__file__))), f), encoding="utf-8").read()`

#### `tests/test_room_bench_passage.py`

- `tests/test_room_bench_passage.py:114` `os.path.abspath` — `_HERE = os.path.dirname(os.path.abspath(__file__))`
- `tests/test_room_bench_passage.py:120` `os.path.exists` — `if os.path.exists(p)), "")`
- `tests/test_room_bench_passage.py:145` `os.path.exists` — `@pytest.mark.skipif(not os.path.exists(PLAN), reason="HMB plan set not here")`

#### `tests/test_rooms_real.py`

- `tests/test_rooms_real.py:7` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tests/test_safeio.py`

- `tests/test_safeio.py:22` `open` — `with open(path, "wb") as f:`
- `tests/test_safeio.py:42` `open` — `assert open(bak).read() == "two"`
- `tests/test_safeio.py:45` `open` — `assert open(bak).read() == "two"`

#### `tests/test_sage_export.py`

- `tests/test_sage_export.py:133` `open` — `raw = open(path, "rb").read()`

#### `tests/test_sample_data.py`

- `tests/test_sample_data.py:13` `os.path.abspath` — `HERE = os.path.dirname(os.path.abspath(__file__))`
- `tests/test_sample_data.py:26` `open` — `with open(os.path.join(SAMPLE, name), encoding="utf-8") as fh:`
- `tests/test_sample_data.py:134` `os.path.isfile` — `@pytest.mark.skipif(not os.path.isfile(os.path.join(`
- `tests/test_sample_data.py:152` `open` — `blob = open(os.path.join(folder, "datakey.bin"), "rb").read()`
- `tests/test_sample_data.py:156` `open` — `raw = open(os.path.join(folder, "backoffice.sqlite"), "rb").read()`
- `tests/test_sample_data.py:163` `os.listdir` — `for name in os.listdir(SAMPLE):`
- `tests/test_sample_data.py:165` `os.path.isdir` — `if os.path.isdir(path) or name == "datakey.bin":`
- `tests/test_sample_data.py:172` `open` — `chunks.append(open(path, encoding="utf-8", errors="ignore").read())`
- `tests/test_sample_data.py:174` `open` — `chunks.append(open(pay_db, encoding="utf-8", errors="ignore").read())`

#### `tests/test_sbom.py`

- `tests/test_sbom.py:6` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_sbom.py:133` `open` — `body = json.loads(open(cdx, encoding="utf-8").read())`
- `tests/test_sbom.py:135` `open` — `text = open(txt, encoding="utf-8").read()`
- `tests/test_sbom.py:189` `open` — `text = open(sbom.__file__, encoding="utf-8").read()`

#### `tests/test_scheduler.py`

- `tests/test_scheduler.py:68` `os.path.getsize` — `assert os.path.getsize(path) > 1000`
- `tests/test_scheduler.py:128` `os.path.getsize` — `assert os.path.getsize(p) > 1000`

#### `tests/test_scope_nov2.py`

- `tests/test_scope_nov2.py:157` `open` — `text = open(x, encoding="utf-8").read()`

#### `tests/test_scope_sheet_ui.py`

- `tests/test_scope_sheet_ui.py:179` `os.path.isfile` — `assert os.path.isfile(path)`

#### `tests/test_sealed_contacts.py`

- `tests/test_sealed_contacts.py:14` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`

#### `tests/test_security_0_13_5.py`

- `tests/test_security_0_13_5.py:110` `open` — `on_disk = open(H._p("projects", "Example Sewer", "records",`
- `tests/test_security_0_13_5.py:226` `open` — `data = json.load(open(p, encoding="utf-8"))`
- `tests/test_security_0_13_5.py:230` `open` — `with open(p, "w", encoding="utf-8") as f:`
- `tests/test_security_0_13_5.py:234` `open` — `assert not any(t in open(p, encoding="utf-8").read() for t in toks)`
- `tests/test_security_0_13_5.py:287` `os.path.abspath` — `root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",`
- `tests/test_security_0_13_5.py:293` `open` — `fly_text = open(os.path.join(root, "fly.toml"), encoding="utf-8").read()`
- `tests/test_security_0_13_5.py:300` `open` — `render = open(os.path.join(root, "render.yaml"), encoding="utf-8").read()`
- `tests/test_security_0_13_5.py:304` `open` — `readme = open(os.path.join(root, "README.md"), encoding="utf-8").read()`
- `tests/test_security_0_13_5.py:324` `open` — `with open(p, "w", newline="", encoding="utf-8") as f:`
- `tests/test_security_0_13_5.py:328` `open` — `rows = list(csv.reader(open(p, encoding="utf-8")))`
- `tests/test_security_0_13_5.py:354` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tests/test_security_0_13_5.py:404` `open` — `cells = [c for row in csv.reader(open(p, encoding="utf-8-sig"))`
- `tests/test_security_0_13_5.py:415` `os.makedirs` — `os.makedirs(settings.DIR, exist_ok=True)`
- `tests/test_security_0_13_5.py:424` `os.path.abspath` — `assert job["folder"] == os.path.abspath(folder)`
- `tests/test_security_0_13_5.py:425` `open` — `with open(os.path.join(folder, db.PROJECT_FILE), "w",`

#### `tests/test_sets.py`

- `tests/test_sets.py:89` `os.path.exists` — `assert os.path.exists(os.path.join(rep["backup"], "Arch.pdf"))`
- `tests/test_sets.py:168` `open` — `rows = list(csv.reader(open(out, encoding="utf-8-sig")))`

#### `tests/test_shellverbs.py`

- `tests/test_shellverbs.py:9` `os.path.abspath` — `HERE = os.path.dirname(os.path.abspath(__file__))`
- `tests/test_shellverbs.py:29` `open` — `before = open(src, "rb").read()`
- `tests/test_shellverbs.py:32` `open` — `assert open(src, "rb").read() == before and a > 0 and b > 0`
- `tests/test_shellverbs.py:68` `open` — `iss = open(os.path.join(HERE, "..", "installer", "quantisheet.iss"),`

#### `tests/test_ship_check.py`

- `tests/test_ship_check.py:10` `os.path.abspath` — `os.path.abspath(__file__))), "tools"))`
- `tests/test_ship_check.py:95` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_ship_check.py:98` `open` — `with open(os.path.join(root, "installer", iss),`
- `tests/test_ship_check.py:102` `open` — `with open(os.path.join(root, "quantisheet.spec"), encoding="utf-8") as f:`
- `tests/test_ship_check.py:176` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_ship_check.py:179` `os.path.isdir` — `if not os.path.isdir(top):`
- `tests/test_ship_check.py:181` `os.walk` — `for base, _dirs, files in os.walk(top):`

#### `tests/test_slipreport.py`

- `tests/test_slipreport.py:57` `open` — `got = list(csv.reader(open(c, encoding="utf-8")))`

#### `tests/test_specrisk.py`

- `tests/test_specrisk.py:126` `os.path.isfile` — `assert os.path.isfile(w.review_path)`

#### `tests/test_start_and_dialogs.py`

- `tests/test_start_and_dialogs.py:26` `os.makedirs` — `os.makedirs(d, exist_ok=True)`
- `tests/test_start_and_dialogs.py:36` `shutil.rmtree` — `shutil.rmtree(os.path.join(os.path.expanduser("~"),`
- `tests/test_start_and_dialogs.py:42` `open` — `open(real, "wb").close()`
- `tests/test_start_and_dialogs.py:45` `open` — `open(tmp, "wb").close()`
- `tests/test_start_and_dialogs.py:59` `open` — `open(mail, "wb").close()`
- `tests/test_start_and_dialogs.py:64` `open` — `open(old, "wb").close()`
- `tests/test_start_and_dialogs.py:80` `os.path.isdir` — `assert seen[-1] != tempfile.gettempdir() and os.path.isdir(seen[-1])`
- `tests/test_start_and_dialogs.py:111` `open` — `src = open(os.path.join(os.path.dirname(__file__), "..", "app",`
- `tests/test_start_and_dialogs.py:124` `open` — `open(p, "wb").close()`
- `tests/test_start_and_dialogs.py:156` `open` — `open(p, "wb").close()`
- `tests/test_start_and_dialogs.py:174` `open` — `open(p, "wb").close()`

#### `tests/test_starter_costbook.py`

- `tests/test_starter_costbook.py:47` `open` — `rows = list(csv.DictReader(open(assembly_csv.CATALOG,`
- `tests/test_starter_costbook.py:94` `open` — `other = costbook.Book(json.load(open(STARTER, encoding="utf-8")))`

#### `tests/test_store_privacy.py`

- `tests/test_store_privacy.py:6` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_store_privacy.py:19` `open` — `iss = open(os.path.join(ROOT, "installer", "quantisheet.iss"),`
- `tests/test_store_privacy.py:35` `open` — `text = open(os.path.join(ROOT, "installer", name),`

#### `tests/test_stress_findings.py`

- `tests/test_stress_findings.py:159` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`

#### `tests/test_takeoff_plus.py`

- `tests/test_takeoff_plus.py:311` `open` — `assert "D-3" in open(out).read()`

#### `tests/test_threat_model_small_fixes.py`

- `tests/test_threat_model_small_fixes.py:12` `open` — `src = open(mod.__file__, encoding="utf-8").read()`
- `tests/test_threat_model_small_fixes.py:57` `os.utime` — `os.utime(old, (past, past))`
- `tests/test_threat_model_small_fixes.py:58` `os.utime` — `os.utime(other, (past, past))`
- `tests/test_threat_model_small_fixes.py:72` `open` — `assert "EXAMPLE-KEY-123" not in open(settings.PATH,`

#### `tests/test_timelog.py`

- `tests/test_timelog.py:59` `open` — `text = open(p, encoding="utf-8").read()`

#### `tests/test_updatecheck.py`

- `tests/test_updatecheck.py:17` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_updatecheck.py:353` `open` — `with open(p, "rb") as f:`
- `tests/test_updatecheck.py:366` `os.listdir` — `assert os.listdir(d) == [] # no .part, no installer`
- `tests/test_updatecheck.py:375` `os.listdir` — `assert os.listdir(d) == []`
- `tests/test_updatecheck.py:382` `open` — `with open(p, "r+b") as f: # swapped after download`
- `tests/test_updatecheck.py:386` `os.path.exists` — `assert ran == [] and not os.path.exists(p)`
- `tests/test_updatecheck.py:399` `open` — `with open(os.path.join(ROOT, "app", "updatecheck.py"),`
- `tests/test_updatecheck.py:406` `open` — `iss = open(os.path.join(ROOT, "installer", "quantisheet.iss"),`

#### `tests/test_v33_security.py`

- `tests/test_v33_security.py:16` `os.path.abspath` — `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_v33_security.py:197` `open` — `text = open(os.path.join(ROOT, "server", name)).read()`
- `tests/test_v33_security.py:210` `open` — `html = open(os.path.join(ROOT, "app", "collab", "web", "index.html"),`
- `tests/test_v33_security.py:306` `open` — `pem = open(kp, "rb").read()`
- `tests/test_v33_security.py:332` `open` — `assert b"BEGIN PRIVATE KEY" in open(kp, "rb").read()`
- `tests/test_v33_security.py:346` `open` — `src = open(os.path.join(ROOT, "app", "main_window.py"),`
- `tests/test_v33_security.py:357` `os.path.getsize` — `assert os.path.getsize(os.path.join(ROOT, "tools", "bls.py")) < 2000`

#### `tests/test_v35_money_security.py`

- `tests/test_v35_money_security.py:57` `os.path.isfile` — `assert os.path.isfile(s.path)`
- `tests/test_v35_money_security.py:70` `open` — `with open(s.path, encoding="utf-8") as f:`
- `tests/test_v35_money_security.py:91` `open` — `assert open(p, "rb").read() == b"hello"`
- `tests/test_v35_money_security.py:92` `os.path.exists` — `assert not os.path.exists(p + ".tmp")`
- `tests/test_v35_money_security.py:384` `os.path.abspath` — `root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- `tests/test_v35_money_security.py:385` `open` — `sw = open(os.path.join(root, "app", "collab", "web", "sw.js"),`

#### `tests/test_v35_windows_save.py`

- `tests/test_v35_windows_save.py:38` `open` — `before = open(p, "rb").read()`
- `tests/test_v35_windows_save.py:42` `os.listdir` — `assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]`
- `tests/test_v35_windows_save.py:45` `open` — `assert open(p, "rb").read() == before # untouched`

#### `tests/test_v3_ai_badge.py`

- `tests/test_v3_ai_badge.py:163` `open` — `rows = list(csv.reader(open(p, encoding="utf-8-sig")))`
- `tests/test_v3_ai_badge.py:188` `open` — `assert "ps-badge" in open(p, encoding="utf-8").read()`

#### `tests/test_vocab.py`

- `tests/test_vocab.py:13` `os.path.abspath` — `TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(`

#### `tests/test_winget.py`

- `tests/test_winget.py:8` `os.path.abspath` — `os.path.abspath(__file__))), "tools"))`

#### `tests/test_zoom_rfi_xfdf.py`

- `tests/test_zoom_rfi_xfdf.py:100` `open` — `text = open(csv_path, encoding="utf-8-sig").read()`
- `tests/test_zoom_rfi_xfdf.py:102` `os.path.getsize` — `assert os.path.getsize(rfilog.export_xlsx(d, str(tmp_path / "l.xlsx")))`

### Pattern A — `fitz.open` / `pymupdf.open` of a filesystem path

Production sites: 183. Test sites: 254.

#### Production

#### `app/acrobat.py`

- `app/acrobat.py:557` `fitz.open` — `img = fitz.open(path)`
- `app/acrobat.py:563` `fitz.open` — `src = fitz.open(path)`

#### `app/acrobat2.py`

- `app/acrobat2.py:137` `fitz.open` — `return fitz.open(path)`
- `app/acrobat2.py:151` `fitz.open` — `return fitz.open(out)`
- `app/acrobat2.py:198` `fitz.open` — `src = fitz.open(src_path)`
- `app/acrobat2.py:228` `fitz.open` — `a, b = fitz.open(old_path), fitz.open(new_path)`
- `app/acrobat2.py:228` `fitz.open` — `a, b = fitz.open(old_path), fitz.open(new_path)`
- `app/acrobat2.py:527` `fitz.open` — `doc = fitz.open(path)`
- `app/acrobat2.py:631` `fitz.open` — `chk = fitz.open(out)`

#### `app/aitakeoff_ui.py`

- `app/aitakeoff_ui.py:245` `fitz.open` — `work = fitz.open(name)`
- `app/aitakeoff_ui.py:521` `fitz.open` — `with fitz.open(path) as sd:`

#### `app/bidform_auto.py`

- `app/bidform_auto.py:269` `fitz.open` — `form = fitz.open(form_path)`

#### `app/bidform_xl_ui.py`

- `app/bidform_xl_ui.py:58` `fitz.open` — `self.src, self.doc = path, fitz.open(path)`
- `app/bidform_xl_ui.py:151` `fitz.open` — `add = fitz.open(path)`

#### `app/bidtab.py`

- `app/bidtab.py:76` `fitz.open` — `with fitz.open(path) as d:`

#### `app/bidzip.py`

- `app/bidzip.py:153` `fitz.open` — `d = fitz.open(p)`

#### `app/cli.py`

- `app/cli.py:189` `fitz.open` — `saved = fitz.open(a.out)`
- `app/cli.py:281` `fitz.open` — `doc = fitz.open(path)`

#### `app/co_delta_ui.py`

- `app/co_delta_ui.py:56` `fitz.open` — `self.old = fitz.open(path)`

#### `app/codelib.py`

- `app/codelib.py:107` `fitz.open` — `with fitz.open(dest) as d:`

#### `app/convert.py`

- `app/convert.py:12` `fitz.open` — `img = fitz.open(p)`
- `app/convert.py:27` `fitz.open` — `doc = fitz.open(path)`

#### `app/costlayer_ui.py`

- `app/costlayer_ui.py:383` `fitz.open` — `old = fitz.open(old_path)`

#### `app/docks.py`

- `app/docks.py:1617` `fitz.open` — `with fitz.open(path) as d:`

#### `app/embfiles.py`

- `app/embfiles.py:528` `fitz.open` — `d = fitz.open(path)`

#### `app/esign.py`

- `app/esign.py:192` `fitz.open` — `doc = fitz.open(path)`
- `app/esign.py:330` `fitz.open` — `doc = fitz.open(env["path"])`

#### `app/estimating/levelboard_ui.py`

- `app/estimating/levelboard_ui.py:157` `fitz.open` — `spec = fitz.open(spec_path)`

#### `app/formlib.py`

- `app/formlib.py:63` `fitz.open` — `with fitz.open(path) as d:`

#### `app/formlib_ui.py`

- `app/formlib_ui.py:123` `fitz.open` — `with fitz.open(formlib.path_of(e)) as d:`

#### `app/genset/sketch.py`

- `app/genset/sketch.py:16` `fitz.open` — `doc = fitz.open(path)`

#### `app/genset_ui.py`

- `app/genset_ui.py:200` `fitz.open` — `doc = fitz.open(out_path)`

#### `app/main_window.py`

- `app/main_window.py:2863` `fitz.open` — `doc = fitz.open(path)`
- `app/main_window.py:2894` `fitz.open` — `fitz.open(p), "Change Order Proposal"))`
- `app/main_window.py:4051` `fitz.open` — `src = fitz.open(path)`
- `app/main_window.py:4385` `fitz.open` — `doc = fitz.open(path)`
- `app/main_window.py:4642` `fitz.open` — `view.doc = fitz.open(path)`
- `app/main_window.py:5915` `fitz.open` — `with (fitz.open(src) if src else fitz.open("pdf", data)) as d:`
- `app/main_window.py:5925` `fitz.open` — `with fitz.open(spec) as sd:`

#### `app/ocr.py`

- `app/ocr.py:85` `fitz.open` — `doc = fitz.open(path)`

#### `app/overlay_ui.py`

- `app/overlay_ui.py:194` `fitz.open` — `self.other_doc = fitz.open(p)`

#### `app/page_ops.py`

- `app/page_ops.py:66` `fitz.open` — `d = fitz.open(p)`

#### `app/pagetools.py`

- `app/pagetools.py:48` `fitz.open` — `src = fitz.open(path)`

#### `app/pdfa.py`

- `app/pdfa.py:203` `fitz.open` — `out = fitz.open(path)`
- `app/pdfa.py:223` `fitz.open` — `out = fitz.open(path)`

#### `app/pm/actions.py`

- `app/pm/actions.py:1003` `fitz.open` — `new = fitz.open(path)`

#### `app/pm/master/formats/pdfsched.py`

- `app/pm/master/formats/pdfsched.py:223` `fitz.open` — `doc = fitz.open(path)`

#### `app/pm/owner_report.py`

- `app/pm/owner_report.py:2517` `fitz.open` — `return fitz.open(_sheet_path(store, sheet))`
- `app/pm/owner_report.py:3167` `fitz.open` — `with fitz.open(path) as src:`

#### `app/pm/owner_report_logs.py`

- `app/pm/owner_report_logs.py:472` `fitz.open` — `with fitz.open(path) as src:`
- `app/pm/owner_report_logs.py:1628` `fitz.open` — `with fitz.open(path) as src:`

#### `app/pm/owner_report_ui.py`

- `app/pm/owner_report_ui.py:1037` `fitz.open` — `with fitz.open(path) as d:`

#### `app/pm/photo_library_ui.py`

- `app/pm/photo_library_ui.py:156` `fitz.open` — `with fitz.open(path) as d:`

#### `app/pm/recovery.py`

- `app/pm/recovery.py:689` `fitz.open` — `g = fitz.open(tmp)`

#### `app/pm/scheduler.py`

- `app/pm/scheduler.py:1321` `fitz.open` — `docs[key] = fitz.open(path)`

#### `app/pm/submittals.py`

- `app/pm/submittals.py:216` `fitz.open` — `d = fitz.open(src)`
- `app/pm/submittals.py:219` `fitz.open` — `img = fitz.open(src)`
- `app/pm/submittals.py:605` `fitz.open` — `with fitz.open(path) as d:`

#### `app/preflight.py`

- `app/preflight.py:252` `fitz.open` — `out = fitz.open(path)`
- `app/preflight.py:269` `fitz.open` — `out = fitz.open(path)`

#### `app/prequal.py`

- `app/prequal.py:124` `fitz.open` — `with fitz.open(path) as doc:`

#### `app/proposal_level.py`

- `app/proposal_level.py:72` `fitz.open` — `img = fitz.open(path)`
- `app/proposal_level.py:76` `fitz.open` — `return fitz.open(path)`

#### `app/quickaccess.py`

- `app/quickaccess.py:1357` `fitz.open` — `d = fitz.open(path)`

#### `app/redaction.py`

- `app/redaction.py:557` `fitz.open` — `d = fitz.open(path)`

#### `app/render_proc.py`

- `app/render_proc.py:54` `fitz.open` — `doc = fitz.open(path)`
- `app/render_proc.py:95` `fitz.open` — `with fitz.open(path) as d:`

#### `app/roof_report.py`

- `app/roof_report.py:129` `fitz.open` — `with fitz.open(path) as d:`

#### `app/safeio.py`

- `app/safeio.py:143` `fitz.open` — `d = fitz.open(os.fspath(path))`

#### `app/service/handover.py`

- `app/service/handover.py:119` `fitz.open` — `with fitz.open(path) as doc:`

#### `app/service/pdfdoc.py`

- `app/service/pdfdoc.py:57` `fitz.open` — `with fitz.open(path) as doc:`

#### `app/sets.py`

- `app/sets.py:110` `fitz.open` — `doc = fitz.open(path)`
- `app/sets.py:267` `fitz.open` — `doc = open_docs.get(path) or fitz.open(path)`
- `app/sets.py:274` `fitz.open` — `nd = new_docs[m["new_file"]] = fitz.open(m["new_file"])`
- `app/sets.py:334` `fitz.open` — `nd = new_docs.get(r["file"]) or fitz.open(r["file"])`
- `app/sets.py:365` `fitz.open` — `with fitz.open(f) as d:`

#### `app/shellverbs.py`

- `app/shellverbs.py:55` `fitz.open` — `with fitz.open(path) as d:`
- `app/shellverbs.py:76` `fitz.open` — `with fitz.open(p) as d:`

#### `app/sign/embed.py`

- `app/sign/embed.py:31` `fitz.open` — `doc = fitz.open(out)`
- `app/sign/embed.py:51` `fitz.open` — `doc = fitz.open(src)`

#### `app/slipreport.py`

- `app/slipreport.py:44` `fitz.open` — `d = d or fitz.open(f["file"])`

#### `app/specrisk_ui.py`

- `app/specrisk_ui.py:67` `fitz.open` — `return self.load(fitz.open(path))`
- `app/specrisk_ui.py:122` `fitz.open` — `doc = fitz.open(self.src_path) if self.src_path else None`

#### `app/versions.py`

- `app/versions.py:117` `fitz.open` — `a, b = fitz.open(a_path), fitz.open(b_path)`
- `app/versions.py:117` `fitz.open` — `a, b = fitz.open(a_path), fitz.open(b_path)`

#### `quantisheet_backoffice/certified.py`

- `quantisheet_backoffice/certified.py:368` `fitz.open` — `with fitz.open(path) as d:`

#### `quantisheet_backoffice/host_tests/test_backoffice_hook.py`

- `quantisheet_backoffice/host_tests/test_backoffice_hook.py:134` `fitz.open` — `doc = fitz.open(path)`
- `quantisheet_backoffice/host_tests/test_backoffice_hook.py:146` `fitz.open` — `doc = fitz.open(path)`

#### `quantisheet_backoffice/ocr.py`

- `quantisheet_backoffice/ocr.py:141` `fitz.open` — `with fitz.open(path) as doc:`
- `quantisheet_backoffice/ocr.py:161` `fitz.open` — `with fitz.open(path) as doc:`

#### `quantisheet_backoffice/output.py`

- `quantisheet_backoffice/output.py:305` `fitz.open` — `with fitz.open(f) as src:`

#### `quantisheet_backoffice/r111/apstamp.py`

- `quantisheet_backoffice/r111/apstamp.py:102` `fitz.open` — `doc = fitz.open(src)`

#### `quantisheet_backoffice/r111/pdfutil.py`

- `quantisheet_backoffice/r111/pdfutil.py:15` `fitz.open` — `with fitz.open(path) as doc:`
- `quantisheet_backoffice/r111/pdfutil.py:31` `fitz.open` — `with fitz.open(path) as doc:`

#### `tools/aerial_live.py`

- `tools/aerial_live.py:20` `fitz.open` — `site = aerial.find_site(fitz.open(where))`

#### `tools/ai_takeoff_run.py`

- `tools/ai_takeoff_run.py:54` `fitz.open` — `doc = fitz.open(path)`

#### `tools/aiken_eval.py`

- `tools/aiken_eval.py:211` `fitz.open` — `doc = fitz.open(pdf)`
- `tools/aiken_eval.py:721` `_fz.open` — `_fz.open(spec)))`

#### `tools/autoscale_compare.py`

- `tools/autoscale_compare.py:22` `fitz.open` — `doc = fitz.open(path)`

#### `tools/autoscale_profile.py`

- `tools/autoscale_profile.py:19` `fitz.open` — `doc = fitz.open(SRC)`

#### `tools/autotakeoff_check.py`

- `tools/autotakeoff_check.py:21` `fitz.open` — `doc = fitz.open(path)`

#### `tools/autotakeoff_demo.py`

- `tools/autotakeoff_demo.py:11` `fitz.open` — `doc = fitz.open(sys.argv[1])`

#### `tools/autotakeoff_dump.py`

- `tools/autotakeoff_dump.py:15` `fitz.open` — `doc = fitz.open(path)`

#### `tools/bigset.py`

- `tools/bigset.py:110` `fitz.open` — `doc = timed("open", lambda: fitz.open(path), rows)`

#### `tools/civil_bid.py`

- `tools/civil_bid.py:54` `fitz.open` — `doc = fitz.open(path)`
- `tools/civil_bid.py:145` `fitz.open` — `back = step("read it back", lambda: heavy.read(fitz.open(out)))`

#### `tools/civil_debug.py`

- `tools/civil_debug.py:18` `fitz.open` — `doc = fitz.open(argv[0].strip('"'))`

#### `tools/civil_probe.py`

- `tools/civil_probe.py:19` `fitz.open` — `doc = fitz.open(argv[0].strip('"'))`

#### `tools/crop.py`

- `tools/crop.py:15` `fitz.open` — `doc = fitz.open(argv[0].strip('"'))`

#### `tools/diag_aiken_actgrid.py`

- `tools/diag_aiken_actgrid.py:18` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_compete.py`

- `tools/diag_aiken_compete.py:16` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_crop.py`

- `tools/diag_aiken_crop.py:18` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_devlegend.py`

- `tools/diag_aiken_devlegend.py:17` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_ductcrop.py`

- `tools/diag_aiken_ductcrop.py:21` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_ducts.py`

- `tools/diag_aiken_ducts.py:19` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_fills.py`

- `tools/diag_aiken_fills.py:18` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_legend.py`

- `tools/diag_aiken_legend.py:14` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_linetypes.py`

- `tools/diag_aiken_linetypes.py:16` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_lod.py`

- `tools/diag_aiken_lod.py:19` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_piperuns.py`

- `tools/diag_aiken_piperuns.py:19` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_pipes.py`

- `tools/diag_aiken_pipes.py:16` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_probe.py`

- `tools/diag_aiken_probe.py:18` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_rotlegend.py`

- `tools/diag_aiken_rotlegend.py:17` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_rows.py`

- `tools/diag_aiken_rows.py:19` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_scale.py`

- `tools/diag_aiken_scale.py:17` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_sched.py`

- `tools/diag_aiken_sched.py:16` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_sf.py`

- `tools/diag_aiken_sf.py:19` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_stage3.py`

- `tools/diag_aiken_stage3.py:20` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_tags.py`

- `tools/diag_aiken_tags.py:16` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_text.py`

- `tools/diag_aiken_text.py:18` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_wallasm.py`

- `tools/diag_aiken_wallasm.py:15` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_walls.py`

- `tools/diag_aiken_walls.py:36` `fitz.open` — `doc = fitz.open(pdf)`

#### `tools/diag_aiken_walltypes.py`

- `tools/diag_aiken_walltypes.py:15` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_words.py`

- `tools/diag_aiken_words.py:20` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_autoscale.py`

- `tools/diag_autoscale.py:19` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_crop_points.py`

- `tools/diag_crop_points.py:19` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_doors.py`

- `tools/diag_doors.py:22` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_legend.py`

- `tools/diag_legend.py:18` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_sched_table.py`

- `tools/diag_sched_table.py:18` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_sched_tags.py`

- `tools/diag_sched_tags.py:19` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_segs.py`

- `tools/diag_segs.py:24` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_tag_leaders.py`

- `tools/diag_tag_leaders.py:18` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_tag_shapes.py`

- `tools/diag_tag_shapes.py:19` `fitz.open` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/dump_paths.py`

- `tools/dump_paths.py:18` `fitz.open` — `doc = fitz.open(argv[0].strip('"'))`

#### `tools/fetch_ada.py`

- `tools/fetch_ada.py:40` `fitz.open` — `doc = fitz.open(PDF)`

#### `tools/fetch_climate.py`

- `tools/fetch_climate.py:38` `fitz.open` — `with fitz.open(PDF) as d:`

#### `tools/fills_probe.py`

- `tools/fills_probe.py:5` `fitz.open` — `doc = fitz.open(sys.argv[1].strip('"'))`

#### `tools/forms_probe.py`

- `tools/forms_probe.py:12` `fitz.open` — `d = fitz.open(p)`

#### `tools/genset_preview.py`

- `tools/genset_preview.py:39` `fitz.open` — `doc = fitz.open(pdf)`

#### `tools/genset_samples.py`

- `tools/genset_samples.py:37` `fitz.open` — `doc = fitz.open(pdf)`

#### `tools/genset_text.py`

- `tools/genset_text.py:11` `fitz.open` — `doc = fitz.open(p)`

#### `tools/leader_debug.py`

- `tools/leader_debug.py:17` `fitz.open` — `doc = fitz.open(sys.argv[1].strip('"'))`

#### `tools/legend_timing.py`

- `tools/legend_timing.py:30` `fitz.open` — `doc = fitz.open(pdf)`

#### `tools/modulor_spike.py`

- `tools/modulor_spike.py:154` `fitz.open` — `svg = fitz.open(os.path.join(OUT, "plan.svg"))`

#### `tools/new_screens.py`

- `tools/new_screens.py:210` `fitz.open` — `pix = fitz.open(p)[0].get_pixmap(dpi=110)`

#### `tools/or_font_diag.py`

- `tools/or_font_diag.py:134` `fitz.open` — `src = fitz.open(sheet)`
- `tools/or_font_diag.py:210` `fitz.open` — `doc = fitz.open(out)`

#### `tools/pm2_diag.py`

- `tools/pm2_diag.py:275` `fitz.open` — `with fitz.open(src) as d:`
- `tools/pm2_diag.py:358` `fitz.open` — `with fitz.open(path) as d:`
- `tools/pm2_diag.py:368` `fitz.open` — `doc = fitz.open(path)`
- `tools/pm2_diag.py:421` `fitz.open` — `doc = fitz.open(path)`
- `tools/pm2_diag.py:483` `fitz.open` — `with fitz.open(w._path) as d:`

#### `tools/probe_open.py`

- `tools/probe_open.py:33` `fitz.open` — `doc = t("open", lambda: fitz.open(pdf))`
- `tools/probe_open.py:105` `fitz.open` — `d = fitz.open(pdf)`
- `tools/probe_open.py:174` `fitz.open` — `doc = fitz.open(pdf)`

#### `tools/render_probe.py`

- `tools/render_probe.py:28` `fitz.open` — `doc = fitz.open(path)`
- `tools/render_probe.py:70` `fitz.open` — `d2 = fitz.open(path)`

#### `tools/room_debug.py`

- `tools/room_debug.py:35` `fitz.open` — `doc = fitz.open(pdf)`

#### `tools/rooms_debug.py`

- `tools/rooms_debug.py:28` `fitz.open` — `doc = fitz.open(path)`

#### `tools/rooms_real.py`

- `tools/rooms_real.py:22` `fitz.open` — `doc = fitz.open(path)`

#### `tools/scanset.py`

- `tools/scanset.py:69` `fitz.open` — `doc = timed("open scanned set", lambda: fitz.open(path))`

#### `tools/sched_check.py`

- `tools/sched_check.py:13` `fitz.open` — `plans = fitz.open(sys.argv[1])`
- `tools/sched_check.py:14` `fitz.open` — `spec = fitz.open(sys.argv[2]) if len(sys.argv) > 2 else None`

#### `tools/schedule_real.py`

- `tools/schedule_real.py:24` `fitz.open` — `plans = fitz.open(argv[0].strip('"')) if argv[0] != "-" else None`
- `tools/schedule_real.py:25` `fitz.open` — `spec = fitz.open(argv[1].strip('"')) if len(argv) > 1 else None`

#### `tools/sheet_probe.py`

- `tools/sheet_probe.py:32` `fitz.open` — `doc = fitz.open(f)`

#### `tools/show_scales.py`

- `tools/show_scales.py:15` `fitz.open` — `doc = fitz.open(sys.argv[1].strip('"'))`

#### `tools/snap_probe.py`

- `tools/snap_probe.py:18` `fitz.open` — `doc = fitz.open(SRC)`

#### `tools/stress_new.py`

- `tools/stress_new.py:261` `fitz.open` — `d2 = fitz.open(out)`
- `tools/stress_new.py:330` `fitz.open` — `d = fitz.open(specs)`

#### `tools/trial_run.py`

- `tools/trial_run.py:45` `fitz.open` — `doc = step("open", lambda: fitz.open(SRC))`
- `tools/trial_run.py:129` `fitz.open` — `fresh = fitz.open(SRC)`
- `tools/trial_run.py:141` `fitz.open` — `step("reduce file size", lambda: f"{acrobat.reduce_size(fitz.open(SRC), os.path.join(OUT, 'spec_small.pdf')) / 1e6:.1f} MB")`

#### Tests

#### `quantisheet_backoffice/tests/test_m4_p3_02_04_sync_wip.py`

- `quantisheet_backoffice/tests/test_m4_p3_02_04_sync_wip.py:139` `fitz.open` — `txt = fitz.open(p)[0].get_text()`
- `quantisheet_backoffice/tests/test_m4_p3_02_04_sync_wip.py:183` `fitz.open` — `txt = fitz.open(p)[0].get_text()`

#### `quantisheet_backoffice/tests/test_p1_10_13_billing.py`

- `quantisheet_backoffice/tests/test_p1_10_13_billing.py:75` `fitz.open` — `txt = "".join(pg.get_text() for pg in fitz.open(p))`
- `quantisheet_backoffice/tests/test_p1_10_13_billing.py:94` `fitz.open` — `doc = fitz.open(p)`

#### `quantisheet_backoffice/tests/test_p1_14_16_waivers_payments_output.py`

- `quantisheet_backoffice/tests/test_p1_14_16_waivers_payments_output.py:162` `fitz.open` — `doc = fitz.open(p)`
- `quantisheet_backoffice/tests/test_p1_14_16_waivers_payments_output.py:200` `fitz.open` — `doc = fitz.open(p)`

#### `quantisheet_backoffice/tests/test_p2_banking.py`

- `quantisheet_backoffice/tests/test_p2_banking.py:278` `fitz.open` — `assert "$1,150.00" in fitz.open(p)[0].get_text().replace("-$", "$")`

#### `quantisheet_backoffice/tests/test_r111_ap_extras.py`

- `quantisheet_backoffice/tests/test_r111_ap_extras.py:124` `fitz.open` — `text = fitz.open(stamped)[0].get_text()`

#### `quantisheet_backoffice/tests/test_r111_field.py`

- `quantisheet_backoffice/tests/test_r111_field.py:33` `fitz.open` — `text = fitz.open(path)[0].get_text()`
- `quantisheet_backoffice/tests/test_r111_field.py:64` `fitz.open` — `text = "".join(p.get_text() for p in fitz.open(packet))`
- `quantisheet_backoffice/tests/test_r111_field.py:67` `fitz.open` — `assert fitz.open(packet)[0].get_images()`
- `quantisheet_backoffice/tests/test_r111_field.py:69` `fitz.open` — `log_text = fitz.open(log)[0].get_text()`
- `quantisheet_backoffice/tests/test_r111_field.py:90` `fitz.open` — `assert "J. Ruiz" in fitz.open(path)[0].get_text()`
- `quantisheet_backoffice/tests/test_r111_field.py:91` `fitz.open` — `assert "Sharp edges" in fitz.open(path)[0].get_text()`
- `quantisheet_backoffice/tests/test_r111_field.py:142` `fitz.open` — `text = fitz.open(path)[0].get_text()`
- `quantisheet_backoffice/tests/test_r111_field.py:160` `fitz.open` — `doc = fitz.open(path)`

#### `quantisheet_backoffice/tests/test_timeoff.py`

- `quantisheet_backoffice/tests/test_timeoff.py:181` `fitz.open` — `with fitz.open(out) as d:`

#### `quantisheet_claims/tests/test_contents.py`

- `quantisheet_claims/tests/test_contents.py:122` `fitz.open` — `txt = " ".join(pg.get_text() for pg in fitz.open(`

#### `quantisheet_claims/tests/test_export.py`

- `quantisheet_claims/tests/test_export.py:64` `fitz.open` — `doc = fitz.open(p)`
- `quantisheet_claims/tests/test_export.py:73` `fitz.open` — `d1 = fitz.open(p1)`

#### `quantisheet_claims/tests/test_nw16_photos.py`

- `quantisheet_claims/tests/test_nw16_photos.py:36` `fitz.open` — `d = fitz.open(out)`

#### `quantisheet_claims/tests/test_v022.py`

- `quantisheet_claims/tests/test_v022.py:172` `fitz.open` — `txt = " ".join(" ".join(pg.get_text().split()) for pg in fitz.open(p))`

#### `tests/diag_pm2_write.py`

- `tests/diag_pm2_write.py:27` `fitz.open` — `d = fitz.open(path)`
- `tests/diag_pm2_write.py:73` `fitz.open` — `d = fitz.open(path)`
- `tests/diag_pm2_write.py:78` `fitz.open` — `v.doc = fitz.open(path)`

#### `tests/diag_pm2_write2.py`

- `tests/diag_pm2_write2.py:18` `fitz.open` — `raw = fitz.open(path)`
- `tests/diag_pm2_write2.py:32` `fitz.open` — `d = fitz.open(path)`

#### `tests/test_acrobat.py`

- `tests/test_acrobat.py:90` `fitz.open` — `d = fitz.open(path)`
- `tests/test_acrobat.py:97` `fitz.open` — `assert not fitz.open(out).needs_pass`

#### `tests/test_acrobat2.py`

- `tests/test_acrobat2.py:73` `fitz.open` — `assert [fitz.open(p).page_count for p in out] == [2, 2, 1]`
- `tests/test_acrobat2.py:76` `fitz.open` — `assert [fitz.open(p).page_count for p in out] == [2, 3]`
- `tests/test_acrobat2.py:136` `fitz.open` — `out_b = fitz.open(res[1][1])`
- `tests/test_acrobat2.py:141` `fitz.open` — `assert fitz.open(res[0][1]).needs_pass`

#### `tests/test_activity_lookahead.py`

- `tests/test_activity_lookahead.py:77` `fitz.open` — `doc = fitz.open(p)`
- `tests/test_activity_lookahead.py:104` `fitz.open` — `doc = fitz.open(la.export_pdf(s, str(tmp_path / "big.pdf"), 2, WED))`
- `tests/test_activity_lookahead.py:116` `fitz.open` — `t = fitz.open(la.export_pdf(s, str(tmp_path / "e.pdf"), 2, WED))[0]`
- `tests/test_activity_lookahead.py:131` `fitz.open` — `assert out and fitz.open(out).page_count >= 1`

#### `tests/test_ada.py`

- `tests/test_ada.py:227` `fitz.open` — `assert ac.read(fitz.open(path))["use"] == "retail"`
- `tests/test_ada.py:295` `fitz.open` — `doc = fitz.open(out)`

#### `tests/test_addendum_summary.py`

- `tests/test_addendum_summary.py:11` `fitz.open` — `old, new = fitz.open(po), fitz.open(pn)`
- `tests/test_addendum_summary.py:11` `fitz.open` — `old, new = fitz.open(po), fitz.open(pn)`

#### `tests/test_autosave.py`

- `tests/test_autosave.py:21` `fitz.open` — `d = fitz.open(path)`

#### `tests/test_autoscale.py`

- `tests/test_autoscale.py:95` `fitz.open` — `rows = autoscale.detect(fitz.open(path))`

#### `tests/test_autotag.py`

- `tests/test_autotag.py:60` `fitz.open` — `t = fitz.open(str(out))`
- `tests/test_autotag.py:97` `fitz.open` — `o = fitz.open(str(out))`

#### `tests/test_award_to_estimate.py`

- `tests/test_award_to_estimate.py:142` `fitz.open` — `d = fitz.open(path)`

#### `tests/test_bidform_auto.py`

- `tests/test_bidform_auto.py:58` `fitz.open` — `f = fitz.open(out)`

#### `tests/test_bidform_xl.py`

- `tests/test_bidform_xl.py:132` `fitz.open` — `return fitz.open(path)`
- `tests/test_bidform_xl.py:144` `fitz.open` — `d = fitz.open(out)`
- `tests/test_bidform_xl.py:190` `fitz.open` — `text = fitz.open(pdf)[0].get_text()`
- `tests/test_bidform_xl.py:219` `fitz.open` — `assert fitz.open(opened[-1]).page_count == 2`

#### `tests/test_bidzip.py`

- `tests/test_bidzip.py:54` `fitz.open` — `assert n == 3 and len(fitz.open(out).get_toc()) == 2`

#### `tests/test_big_markup_sets.py`

- `tests/test_big_markup_sets.py:38` `fitz.open` — `d = fitz.open(p)`
- `tests/test_big_markup_sets.py:78` `fitz.open` — `d = fitz.open(p)`

#### `tests/test_billing.py`

- `tests/test_billing.py:38` `fitz.open` — `with fitz.open(path) as d:`
- `tests/test_billing.py:112` `fitz.open` — `d2 = fitz.open(path)`

#### `tests/test_brand_rename.py`

- `tests/test_brand_rename.py:29` `fitz.open` — `d = fitz.open(p) # the hook converts on open`
- `tests/test_brand_rename.py:40` `fitz.open` — `d = fitz.open(p)`

#### `tests/test_cashflow.py`

- `tests/test_cashflow.py:56` `fitz.open` — `assert "Cash Flow" in fitz.open(p)[0].get_text()`

#### `tests/test_claim_package.py`

- `tests/test_claim_package.py:65` `fitz.open` — `doc = fitz.open(p)`
- `tests/test_claim_package.py:85` `fitz.open` — `t = fitz.open(cp.export_pdf(s, str(tmp_path / "c.pdf"), TODAY))[0] \`
- `tests/test_claim_package.py:96` `fitz.open` — `t = "".join(pg.get_text() for pg in fitz.open(`
- `tests/test_claim_package.py:115` `fitz.open` — `assert "DCMA" in fitz.open(str(tmp_path / "q.pdf"))[0].get_text()`
- `tests/test_claim_package.py:142` `fitz.open` — `assert "Schedule Claim Package" in fitz.open(p)[0].get_text()`

#### `tests/test_claims_hook.py`

- `tests/test_claims_hook.py:41` `fitz.open` — `d = fitz.open(path)`
- `tests/test_claims_hook.py:112` `fitz.open` — `doc = fitz.open(path)`
- `tests/test_claims_hook.py:135` `fitz.open` — `doc = fitz.open(_plan(tmp_path))`

#### `tests/test_cli_sanitize_genset.py`

- `tests/test_cli_sanitize_genset.py:29` `fitz.open` — `d = fitz.open(_dirty(tmp_path))`
- `tests/test_cli_sanitize_genset.py:47` `fitz.open` — `d = fitz.open(out)`

#### `tests/test_co_delta.py`

- `tests/test_co_delta.py:48` `fitz.open` — `d = fitz.open(p)`

#### `tests/test_codecheck.py`

- `tests/test_codecheck.py:136` `fitz.open` — `with fitz.open(out) as rep:`

#### `tests/test_copy_text.py`

- `tests/test_copy_text.py:37` `fitz.open` — `d = fitz.open(_pdf(os.path.join(os.environ.get("TMP", "/tmp"),`

#### `tests/test_dashboard.py`

- `tests/test_dashboard.py:513` `fitz.open` — `doc = fitz.open(path)`

#### `tests/test_dxf.py`

- `tests/test_dxf.py:44` `fitz.open` — `d = fitz.open(out)`
- `tests/test_dxf.py:88` `fitz.open` — `p = fitz.open(out)`

#### `tests/test_esign.py`

- `tests/test_esign.py:57` `fitz.open` — `d = fitz.open(str(path))`
- `tests/test_esign.py:72` `fitz.open` — `doc = fitz.open(str(path))`
- `tests/test_esign.py:110` `fitz.open` — `signed = fitz.open(out)`
- `tests/test_esign.py:131` `fitz.open` — `d = fitz.open(str(path))`
- `tests/test_esign.py:157` `fitz.open` — `d = fitz.open(str(path))`
- `tests/test_esign.py:174` `fitz.open` — `d = fitz.open(str(_contract(tmp / "a.pdf")))`

#### `tests/test_estimate_export.py`

- `tests/test_estimate_export.py:81` `fitz.open` — `out = fitz.open(path)`
- `tests/test_estimate_export.py:184` `fitz.open` — `text = fitz.open(p)[0].get_text()`

#### `tests/test_estimate_layouts.py`

- `tests/test_estimate_layouts.py:217` `fitz.open` — `d2 = fitz.open(p)`
- `tests/test_estimate_layouts.py:293` `fitz.open` — `text = "".join(pg.get_text() for pg in fitz.open(pdf))`

#### `tests/test_estimate_lines.py`

- `tests/test_estimate_lines.py:50` `fitz.open` — `d = fitz.open(path)`
- `tests/test_estimate_lines.py:241` `fitz.open` — `d = fitz.open(str(tmp_path / "saved.pdf"))`

#### `tests/test_estimating.py`

- `tests/test_estimating.py:197` `fitz.open` — `d2 = fitz.open(path) # book travels in the PDF`

#### `tests/test_fewer_clicks.py`

- `tests/test_fewer_clicks.py:428` `fitz.open` — `assert fitz.open(out).page_count == 1`

#### `tests/test_fixes.py`

- `tests/test_fixes.py:160` `fitz.open` — `text = fitz.open(out)[0].get_text()`

#### `tests/test_genset.py`

- `tests/test_genset.py:71` `fitz.open` — `doc = fitz.open(out)`
- `tests/test_genset.py:168` `fitz.open` — `doc = fitz.open(out)`
- `tests/test_genset.py:331` `fitz.open` — `t = fitz.open(out)[0].get_text()`
- `tests/test_genset.py:425` `fitz.open` — `doc = fitz.open(out)`
- `tests/test_genset.py:574` `fitz.open` — `doc = fitz.open(out)`
- `tests/test_genset.py:660` `fitz.open` — `doc = fitz.open(out)`
- `tests/test_genset.py:681` `fitz.open` — `doc = fitz.open(out)`
- `tests/test_genset.py:728` `fitz.open` — `doc = fitz.open(out)`
- `tests/test_genset.py:828` `fitz.open` — `doc = fitz.open(out)`
- `tests/test_genset.py:848` `fitz.open` — `doc = fitz.open(out)`

#### `tests/test_genset_restaurant.py`

- `tests/test_genset_restaurant.py:274` `fitz.open` — `doc = fitz.open(out)`

#### `tests/test_genset_strip.py`

- `tests/test_genset_strip.py:290` `fitz.open` — `doc = fitz.open(out)`

#### `tests/test_genset_warehouse.py`

- `tests/test_genset_warehouse.py:270` `fitz.open` — `doc = fitz.open(out)`

#### `tests/test_gui.py`

- `tests/test_gui.py:183` `fitz.open` — `assert fitz.open(out).page_count == win._view.doc.page_count`
- `tests/test_gui.py:185` `fitz.open` — `got = fitz.open(out)`
- `tests/test_gui.py:205` `fitz.open` — `d = fitz.open(win._path)`
- `tests/test_gui.py:292` `fitz.open` — `assert fitz.open(tmp_path / "extract.pdf").page_count == 2`
- `tests/test_gui.py:669` `fitz.open` — `d = fitz.open(other)`
- `tests/test_gui.py:853` `fitz.open` — `assert fitz.open(out).page_count == len(dlg.pages())`

#### `tests/test_help.py`

- `tests/test_help.py:18` `fitz.open` — `d = fitz.open(p)`
- `tests/test_help.py:66` `fitz.open` — `assert "Limitation of liability" in fitz.open(p)[0].get_text() or \`
- `tests/test_help.py:68` `fitz.open` — `for pg in fitz.open(p))`

#### `tests/test_history.py`

- `tests/test_history.py:96` `fitz.open` — `again = fitz.open(out)`

#### `tests/test_issue_report.py`

- `tests/test_issue_report.py:48` `fitz.open` — `doc = fitz.open(pdf)`
- `tests/test_issue_report.py:62` `fitz.open` — `doc = fitz.open(pdf)`

#### `tests/test_item_defaults.py`

- `tests/test_item_defaults.py:32` `fitz.open` — `d2 = fitz.open(p)`

#### `tests/test_job_info.py`

- `tests/test_job_info.py:84` `fitz.open` — `again = fitz.open(path)`

#### `tests/test_lookahead.py`

- `tests/test_lookahead.py:115` `fitz.open` — `with fitz.open(path) as doc:`

#### `tests/test_nov4_items.py`

- `tests/test_nov4_items.py:79` `fitz.open` — `for p in fitz.open(str(tmp_path / "out.pdf")) for w in p.widgets()}`
- `tests/test_nov4_items.py:87` `fitz.open` — `for p in fitz.open(str(tmp_path / "o2.pdf")) for w in p.widgets()}`

#### `tests/test_organize.py`

- `tests/test_organize.py:26` `fitz.open` — `d = fitz.open(_doc(str(tmp_path / "a.pdf")))`

#### `tests/test_overlay.py`

- `tests/test_overlay.py:50` `fitz.open` — `old, new = fitz.open(po), fitz.open(pn)`
- `tests/test_overlay.py:50` `fitz.open` — `old, new = fitz.open(po), fitz.open(pn)`
- `tests/test_overlay.py:78` `fitz.open` — `old, new = fitz.open(po), fitz.open(pn)`
- `tests/test_overlay.py:78` `fitz.open` — `old, new = fitz.open(po), fitz.open(pn)`
- `tests/test_overlay.py:99` `fitz.open` — `assert fitz.open(out).page_count == 3`
- `tests/test_overlay.py:104` `fitz.open` — `doc, new = fitz.open(po), fitz.open(pn)`
- `tests/test_overlay.py:104` `fitz.open` — `doc, new = fitz.open(po), fitz.open(pn)`
- `tests/test_overlay.py:129` `fitz.open` — `assert min(_rgb(fitz.open(tmp)[0], 150, 300)) > 200`
- `tests/test_overlay.py:148` `fitz.open` — `d2 = fitz.open(path)`
- `tests/test_overlay.py:209` `fitz.open` — `old, new = fitz.open(po), fitz.open(pn)`
- `tests/test_overlay.py:209` `fitz.open` — `old, new = fitz.open(po), fitz.open(pn)`
- `tests/test_overlay.py:231` `fitz.open` — `od = fitz.open(po)`
- `tests/test_overlay.py:244` `fitz.open` — `old, new = fitz.open(po), fitz.open(pn)`
- `tests/test_overlay.py:244` `fitz.open` — `old, new = fitz.open(po), fitz.open(pn)`

#### `tests/test_owner_report.py`

- `tests/test_owner_report.py:73` `fitz.open` — `return res, fitz.open(path)`

#### `tests/test_owner_report_fonts.py`

- `tests/test_owner_report_fonts.py:85` `fitz.open` — `return res, fitz.open(path)`
- `tests/test_owner_report_fonts.py:146` `fitz.open` — `with fitz.open(_pdf(tmp_path, "a.pdf", "Hello", False)) as d:`
- `tests/test_owner_report_fonts.py:150` `fitz.open` — `with fitz.open(_pdf(tmp_path, "b.pdf", "Hello", True)) as d:`
- `tests/test_owner_report_fonts.py:164` `fitz.open` — `with fitz.open(b14) as src:`
- `tests/test_owner_report_fonts.py:175` `fitz.open` — `with fitz.open(emb) as src:`

#### `tests/test_owner_report_gaps.py`

- `tests/test_owner_report_gaps.py:183` `fitz.open` — `doc = fitz.open(str(tmp_path / name))`

#### `tests/test_owner_report_pack.py`

- `tests/test_owner_report_pack.py:41` `fitz.open` — `return res, fitz.open(path)`
- `tests/test_owner_report_pack.py:176` `fitz.open` — `doc = fitz.open(path)`

#### `tests/test_owner_report_ui.py`

- `tests/test_owner_report_ui.py:116` `fitz.open` — `doc = fitz.open(res["path"])`
- `tests/test_owner_report_ui.py:200` `fitz.open` — `doc = fitz.open(str(tmp_path / "f.pdf"))`
- `tests/test_owner_report_ui.py:232` `fitz.open` — `d = fitz.open(path)`
- `tests/test_owner_report_ui.py:335` `fitz.open` — `doc = fitz.open(str(tmp_path / "kp.pdf"))`
- `tests/test_owner_report_ui.py:400` `fitz.open` — `doc = fitz.open(str(tmp_path / "wa.pdf"))`

#### `tests/test_p0_safety.py`

- `tests/test_p0_safety.py:55` `fitz.open` — `d = fitz.open(path)`
- `tests/test_p0_safety.py:89` `fitz.open` — `assert "Keep this line" in fitz.open(path)[0].get_text()`
- `tests/test_p0_safety.py:107` `fitz.open` — `d = fitz.open(_doc(str(tmp_path / "w.pdf")))`
- `tests/test_p0_safety.py:127` `fitz.open` — `assert savecheck.is_signed(fitz.open(out))`
- `tests/test_p0_safety.py:128` `fitz.open` — `assert not savecheck.is_signed(fitz.open(_doc(str(tmp_path / "u.pdf"))))`
- `tests/test_p0_safety.py:183` `fitz.open` — `d = fitz.open(_job_pdf(str(tmp / "job.pdf")))`
- `tests/test_p0_safety.py:224` `fitz.open` — `d = fitz.open(path)`

#### `tests/test_p1_own_wording_payapp.py`

- `tests/test_p1_own_wording_payapp.py:25` `fitz.open` — `text = " ".join(p.get_text() for p in fitz.open(out)).upper()`

#### `tests/test_pdf_tools_0_13_5.py`

- `tests/test_pdf_tools_0_13_5.py:122` `fitz.open` — `r = fitz.open(str(out))`
- `tests/test_pdf_tools_0_13_5.py:163` `fitz.open` — `r = fitz.open(str(out))`
- `tests/test_pdf_tools_0_13_5.py:250` `fitz.open` — `v = PdfView(fitz.open(path), path)`
- `tests/test_pdf_tools_0_13_5.py:290` `fitz.open` — `v = PdfView(fitz.open(path), path)`
- `tests/test_pdf_tools_0_13_5.py:354` `fitz.open` — `acrobat.reduce_size(fitz.open(src), str(out),`
- `tests/test_pdf_tools_0_13_5.py:363` `fitz.open` — `acrobat.reduce_size(fitz.open(src), str(out))`
- `tests/test_pdf_tools_0_13_5.py:372` `fitz.open` — `acrobat.reduce_size(fitz.open(src), str(out),`
- `tests/test_pdf_tools_0_13_5.py:382` `fitz.open` — `size = acrobat.reduce_size(fitz.open(src), str(out),`
- `tests/test_pdf_tools_0_13_5.py:386` `fitz.open` — `r = fitz.open(str(out))`
- `tests/test_pdf_tools_0_13_5.py:409` `fitz.open` — `assert "Page 1 of 3" in fitz.open(out)[0].get_text()`
- `tests/test_pdf_tools_0_13_5.py:447` `fitz.open` — `d = fitz.open(src)`
- `tests/test_pdf_tools_0_13_5.py:453` `fitz.open` — `r = fitz.open(rep.out)`
- `tests/test_pdf_tools_0_13_5.py:476` `fitz.open` — `r = fitz.open(rep.out)`
- `tests/test_pdf_tools_0_13_5.py:569` `fitz.open` — `r = fitz.open(out)`
- `tests/test_pdf_tools_0_13_5.py:591` `fitz.open` — `r = fitz.open(out)`

#### `tests/test_planswift.py`

- `tests/test_planswift.py:97` `fitz.open` — `d2 = fitz.open(path)`

#### `tests/test_pm.py`

- `tests/test_pm.py:187` `fitz.open` — `assert "Which lockset" in fitz.open(m["attachments"][0])[0].get_text()`
- `tests/test_pm.py:278` `fitz.open` — `text = fitz.open(path)[0].get_text()`
- `tests/test_pm.py:283` `fitz.open` — `doc = fitz.open(path)`
- `tests/test_pm.py:532` `fitz.open` — `text = fitz.open(g702)[0].get_text()`
- `tests/test_pm.py:546` `fitz.open` — `assert "Projected margin" in fitz.open(p)[0].get_text()`

#### `tests/test_prebid.py`

- `tests/test_prebid.py:136` `fitz.open` — `pdf = fitz.open(out)`
- `tests/test_prebid.py:146` `fitz.open` — `txt = fitz.open(out)[0].get_text()`
- `tests/test_prebid.py:151` `fitz.open` — `d2 = fitz.open(str(p))`

#### `tests/test_prebid_phase1.py`

- `tests/test_prebid_phase1.py:139` `fitz.open` — `txt = fitz.open(p)[0].get_text()`

#### `tests/test_precon2.py`

- `tests/test_precon2.py:101` `fitz.open` — `d = fitz.open(src)`
- `tests/test_precon2.py:287` `fitz.open` — `award = fitz.open(s.attachment_path(next(`

#### `tests/test_project.py`

- `tests/test_project.py:37` `fitz.open` — `with fitz.open(path) as d:`
- `tests/test_project.py:87` `fitz.open` — `d2 = fitz.open(path)`

#### `tests/test_r111_backflow.py`

- `tests/test_r111_backflow.py:65` `fitz.open` — `with fitz.open(path) as doc:`

#### `tests/test_r111_dispatch.py`

- `tests/test_r111_dispatch.py:53` `fitz.open` — `with fitz.open(path) as doc:`

#### `tests/test_r111_pricebook.py`

- `tests/test_r111_pricebook.py:54` `fitz.open` — `with fitz.open(path) as doc:`
- `tests/test_r111_pricebook.py:83` `fitz.open` — `with fitz.open(path) as doc:`

#### `tests/test_r111_recommend.py`

- `tests/test_r111_recommend.py:42` `fitz.open` — `with fitz.open(path) as doc:`
- `tests/test_r111_recommend.py:72` `fitz.open` — `with fitz.open(path) as doc:`

#### `tests/test_r111_refrigerant.py`

- `tests/test_r111_refrigerant.py:128` `fitz.open` — `with fitz.open(path) as doc:`
- `tests/test_r111_refrigerant.py:138` `fitz.open` — `with fitz.open(path2) as doc:`

#### `tests/test_r111_tmtag.py`

- `tests/test_r111_tmtag.py:38` `fitz.open` — `with fitz.open(path) as doc:`

#### `tests/test_r111_workorder.py`

- `tests/test_r111_workorder.py:156` `fitz.open` — `with fitz.open(path) as doc:`
- `tests/test_r111_workorder.py:167` `fitz.open` — `with fitz.open(inv["pdf"]) as doc:`

#### `tests/test_r36_actuals.py`

- `tests/test_r36_actuals.py:52` `fitz.open` — `assert actuals.read(fitz.open(p))[ids[0]]["cost"] == "2100.00"`

#### `tests/test_r36_end_to_end.py`

- `tests/test_r36_end_to_end.py:118` `fitz.open` — `r3 = flow.run(fitz.open(p), lib=LIB)`

#### `tests/test_r36_quotes.py`

- `tests/test_r36_quotes.py:86` `fitz.open` — `d2 = fitz.open(p)`
- `tests/test_r36_quotes.py:105` `fitz.open` — `text = "".join(pg.get_text() for pg in fitz.open(out))`

#### `tests/test_recovery.py`

- `tests/test_recovery.py:108` `fitz.open` — `doc = fitz.open(p)`

#### `tests/test_review_fixes.py`

- `tests/test_review_fixes.py:84` `fitz.open` — `p2 = fitz.open(parts[1])`
- `tests/test_review_fixes.py:89` `fitz.open` — `assert _ppu(fitz.open(out)) == [10, 30]`
- `tests/test_review_fixes.py:96` `fitz.open` — `assert _ppu(fitz.open(merged)) == [36, 9, 18]`

#### `tests/test_review_oct15.py`

- `tests/test_review_oct15.py:230` `fitz.open` — `d = fitz.open(_damaged(tmp_path))`

#### `tests/test_review_oct17.py`

- `tests/test_review_oct17.py:240` `fitz.open` — `page = fitz.open(out)[0]`

#### `tests/test_review_venice.py`

- `tests/test_review_venice.py:55` `fitz.open` — `e = fitz.open(out)`
- `tests/test_review_venice.py:92` `fitz.open` — `assert res and jobdata.names(fitz.open(out)) == []`

#### `tests/test_rfi_rules.py`

- `tests/test_rfi_rules.py:19` `fitz.open` — `with fitz.open(p) as d:`
- `tests/test_rfi_rules.py:21` `fitz.open` — `with fitz.open(s) as d:`
- `tests/test_rfi_rules.py:77` `fitz.open` — `plans = fitz.open(str(tmp_path / "plans.pdf"))`

#### `tests/test_room_bench_passage.py`

- `tests/test_room_bench_passage.py:137` `fitz.open` — `doc = fitz.open(PLAN)`

#### `tests/test_safeio.py`

- `tests/test_safeio.py:32` `fitz.open` — `assert "new" in fitz.open(str(p))[0].get_text()`

#### `tests/test_sample_data.py`

- `tests/test_sample_data.py:99` `pymupdf.open` — `doc = pymupdf.open(path)`
- `tests/test_sample_data.py:168` `pymupdf.open` — `doc = pymupdf.open(path)`

#### `tests/test_schedule.py`

- `tests/test_schedule.py:106` `fitz.open` — `d = fitz.open(p)`
- `tests/test_schedule.py:114` `fitz.open` — `assert "Lookahead" in fitz.open(str(tmp_path / "la.pdf"))[0].get_text()`

#### `tests/test_schedule_check.py`

- `tests/test_schedule_check.py:263` `fitz.open` — `d = fitz.open(p)`
- `tests/test_schedule_check.py:274` `fitz.open` — `assert "DCMA" in fitz.open(p2)[0].get_text()`

#### `tests/test_scope_clarifications.py`

- `tests/test_scope_clarifications.py:186` `fitz.open` — `with fitz.open(path) as d:`

#### `tests/test_scope_sheet.py`

- `tests/test_scope_sheet.py:436` `fitz.open` — `doc = fitz.open(path)`

#### `tests/test_security_0_13_5.py`

- `tests/test_security_0_13_5.py:494` `fitz.open` — `doc = fitz.open(str(path))`
- `tests/test_security_0_13_5.py:508` `fitz.open` — `d = fitz.open(str(path))`
- `tests/test_security_0_13_5.py:522` `fitz.open` — `r = fitz.open(str(copy))`
- `tests/test_security_0_13_5.py:534` `fitz.open` — `r = fitz.open(str(copy))`
- `tests/test_security_0_13_5.py:555` `fitz.open` — `r = fitz.open(str(out))`
- `tests/test_security_0_13_5.py:624` `fitz.open` — `r = fitz.open(str(out))`
- `tests/test_security_0_13_5.py:636` `fitz.open` — `doc = fitz.open(str(src))`
- `tests/test_security_0_13_5.py:654` `fitz.open` — `doc = fitz.open(str(src))`
- `tests/test_security_0_13_5.py:665` `fitz.open` — `r = fitz.open(str(out))`
- `tests/test_security_0_13_5.py:676` `fitz.open` — `doc = fitz.open(str(src))`
- `tests/test_security_0_13_5.py:688` `fitz.open` — `doc = fitz.open(str(src))`
- `tests/test_security_0_13_5.py:724` `fitz.open` — `doc = fitz.open(str(p))`
- `tests/test_security_0_13_5.py:730` `fitz.open` — `r = fitz.open(str(out))`

#### `tests/test_sets.py`

- `tests/test_sets.py:92` `fitz.open` — `d = fitz.open(pa)`
- `tests/test_sets.py:129` `fitz.open` — `d = fitz.open(pr)`
- `tests/test_sets.py:154` `fitz.open` — `d = fitz.open(pa)`

#### `tests/test_slipreport.py`

- `tests/test_slipreport.py:14` `fitz.open` — `d = fitz.open(pr)`
- `tests/test_slipreport.py:60` `fitz.open` — `txt = fitz.open(p)[0].get_text()`

#### `tests/test_specrisk.py`

- `tests/test_specrisk.py:41` `fitz.open` — `t = fitz.open(p)[0].get_text()`
- `tests/test_specrisk.py:100` `fitz.open` — `r = fitz.open(p)`

#### `tests/test_specs.py`

- `tests/test_specs.py:49` `fitz.open` — `assert len(paths) == 4 and fitz.open(paths[0]).page_count == 3`

#### `tests/test_standards.py`

- `tests/test_standards.py:56` `fitz.open` — `o = fitz.open(out)`

#### `tests/test_submittals.py`

- `tests/test_submittals.py:110` `fitz.open` — `out = fitz.open(path)`

#### `tests/test_takeoff_items.py`

- `tests/test_takeoff_items.py:103` `fitz.open` — `d = fitz.open(win._path)`

#### `tests/test_v35_crash_nits.py`

- `tests/test_v35_crash_nits.py:91` `fitz.open` — `text = "".join(pg.get_text() for pg in fitz.open(str(out)))`
- `tests/test_v35_crash_nits.py:95` `fitz.open` — `d = fitz.open(str(letter))`

#### `tests/test_v35_windows_save.py`

- `tests/test_v35_windows_save.py:39` `fitz.open` — `doc = fitz.open(p) # held open, like a viewer tab`
- `tests/test_v35_windows_save.py:47` `fitz.open` — `text = fitz.open(p)[0].get_text()`
- `tests/test_v35_windows_save.py:54` `fitz.open` — `doc = fitz.open(p)`
- `tests/test_v35_windows_save.py:57` `fitz.open` — `assert "edit 2" in fitz.open(q)[0].get_text()`

#### `tests/test_v3_ai_badge.py`

- `tests/test_v3_ai_badge.py:129` `fitz.open` — `d2 = fitz.open(p)`

#### `tests/test_zoom_rfi_xfdf.py`

- `tests/test_zoom_rfi_xfdf.py:103` `fitz.open` — `pdf = fitz.open(rfilog.export_pdf(d, str(tmp_path / "log.pdf"),`

### Pattern A — `Image.open`

Production sites: 5. Test sites: 10.

#### Production

#### `app/aerial.py`

- `app/aerial.py:568` `Image.open` — `return xy, Image.open(io.BytesIO(data)).convert("RGB")`
- `app/aerial.py:592` `Image.open` — `im = Image.open(io.BytesIO(data)).convert("RGB")`

#### `app/pm/photofit.py`

- `app/pm/photofit.py:42` `Image.open` — `return Image.open(path)`

#### `quantisheet_claims/photos.py`

- `quantisheet_claims/photos.py:45` `Image.open` — `with Image.open(path) as im:`

#### `tools/build_msix.py`

- `tools/build_msix.py:168` `Image.open` — `src = Image.open(os.path.join(ROOT, "icon.png")).convert("RGBA")`

#### Tests

#### `tests/test_branding_v34.py`

- `tests/test_branding_v34.py:19` `Image.open` — `im = Image.open(path)`
- `tests/test_branding_v34.py:28` `Image.open` — `im = Image.open(path)`
- `tests/test_branding_v34.py:36` `Image.open` — `im = Image.open(path)`
- `tests/test_branding_v34.py:44` `Image.open` — `im = Image.open(path)`

#### `tests/test_photofit.py`

- `tests/test_photofit.py:140` `Image.open` — `out = Image.open(io.BytesIO(pf.encode(img, w, h, "email", box)))`
- `tests/test_photofit.py:191` `Image.open` — `out = Image.open(io.BytesIO(pf.encode(img, w, h, preset, box)))`
- `tests/test_photofit.py:196` `Image.open` — `out = Image.open(io.BytesIO(pf.encode(img, 500, 375, "small")))`
- `tests/test_photofit.py:203` `Image.open` — `with Image.open(p) as raw:`
- `tests/test_photofit.py:212` `Image.open` — `out = Image.open(io.BytesIO(data))`
- `tests/test_photofit.py:316` `Image.open` — `assert Image.open(io.BytesIO(a)).size == (417, 556) # upright`

### Pattern A — `gzip` / `bz2` / `lzma` / `tarfile` / `zipfile.ZipFile` / `sqlite3.connect`

Production sites: 42. Test sites: 36.

#### Production

#### `app/acrobat.py`

- `app/acrobat.py:365` `zipfile.ZipFile` — `with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:`
- `app/acrobat.py:484` `zipfile.ZipFile` — `with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:`

#### `app/bidtab.py`

- `app/bidtab.py:38` `zipfile.ZipFile` — `with zipfile.ZipFile(path) as z:`

#### `app/bidzip.py`

- `app/bidzip.py:44` `zipfile.ZipFile` — `z = zipfile.ZipFile(io.BytesIO(data) if isinstance(data, bytes)`

#### `app/databackup.py`

- `app/databackup.py:72` `sqlite3.connect` — `a = sqlite3.connect(f"file:{src}?mode=ro", uri=True)`
- `app/databackup.py:74` `sqlite3.connect` — `b = sqlite3.connect(dst)`
- `app/databackup.py:99` `zipfile.ZipFile` — `with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:`
- `app/databackup.py:137` `zipfile.ZipFile` — `with zipfile.ZipFile(zip_path) as z:`
- `app/databackup.py:154` `zipfile.ZipFile` — `with zipfile.ZipFile(zip_path) as z:`

#### `app/diagnostics.py`

- `app/diagnostics.py:175` `zipfile.ZipFile` — `with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:`

#### `app/estimating/safedb.py`

- `app/estimating/safedb.py:105` `sqlite3.connect` — `con = sqlite3.connect(_uri(p), uri=True, timeout=15)`
- `app/estimating/safedb.py:202` `sqlite3.connect` — `dst = sqlite3.connect(tmp)`

#### `app/issue_report.py`

- `app/issue_report.py:89` `zipfile.ZipFile` — `with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:`
- `app/issue_report.py:93` `zipfile.ZipFile` — `with zipfile.ZipFile(bundle) as b:`

#### `app/pm/project_backup.py`

- `app/pm/project_backup.py:52` `zipfile.ZipFile` — `with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:`
- `app/pm/project_backup.py:77` `zipfile.ZipFile` — `with zipfile.ZipFile(zip_path) as z:`
- `app/pm/project_backup.py:121` `zipfile.ZipFile` — `with zipfile.ZipFile(zip_path) as z:`

#### `app/pricedb.py`

- `app/pricedb.py:213` `sqlite3.connect` — `con = sqlite3.connect(uri, uri=True, timeout=15)`
- `app/pricedb.py:218` `sqlite3.connect` — `con = sqlite3.connect(p, timeout=15)`
- `app/pricedb.py:296` `sqlite3.connect` — `dst = sqlite3.connect(cache_path())`
- `app/pricedb.py:943` `sqlite3.connect` — `dst = sqlite3.connect(new_path)`
- `app/pricedb.py:971` `sqlite3.connect` — `out = sqlite3.connect(dest)`

#### `app/vocab_core.py`

- `app/vocab_core.py:391` `sqlite3.connect` — `conn = sqlite3.connect(args.db)`

#### `quantisheet_backoffice/backup.py`

- `quantisheet_backoffice/backup.py:219` `sqlite3.connect` — `src = sqlite3.connect(tmp)`
- `quantisheet_backoffice/backup.py:220` `sqlite3.connect` — `dst = sqlite3.connect(live)`

#### `quantisheet_backoffice/server/app.py`

- `quantisheet_backoffice/server/app.py:79` `sqlite3.connect` — `self.db = sqlite3.connect(os.path.join(data_dir, "selfservice.sqlite"),`

#### `quantisheet_backoffice/store.py`

- `quantisheet_backoffice/store.py:395` `sqlite3.connect` — `self.conn = sqlite3.connect(path, isolation_level=None)`
- `quantisheet_backoffice/store.py:550` `sqlite3.connect` — `out = sqlite3.connect(path)`

#### `tools/build_installer.py`

- `tools/build_installer.py:208` `zipfile.ZipFile` — `with zipfile.ZipFile(f) as z:`

#### `tools/check_paykey_move.py`

- `tools/check_paykey_move.py:47` `sqlite3.connect` — `s = sqlite3.connect(os.path.join(src, "backoffice.sqlite"))`
- `tools/check_paykey_move.py:48` `sqlite3.connect` — `d = sqlite3.connect(os.path.join(copy, "backoffice.sqlite"))`
- `tools/check_paykey_move.py:66` `sqlite3.connect` — `con = sqlite3.connect(os.path.join(copy, "backoffice.sqlite"))`

#### `tools/compare_price_db.py`

- `tools/compare_price_db.py:13` `sqlite3.connect` — `con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)`

#### `tools/costdb.py`

- `tools/costdb.py:232` `sqlite3.connect` — `conn = sqlite3.connect(path)`

#### `tools/review_copy.py`

- `tools/review_copy.py:83` `zipfile.ZipFile` — `with zipfile.ZipFile(zip_path) as z:`

#### `tools/ship_check.py`

- `tools/ship_check.py:203` `zipfile.ZipFile` — `with zipfile.ZipFile(io.BytesIO(data)) as z:`

#### `tools/sig_check.py`

- `tools/sig_check.py:46` `zipfile.ZipFile` — `with zipfile.ZipFile(p) as z:`

#### `tools/unpack_incoming.py`

- `tools/unpack_incoming.py:21` `zipfile.ZipFile` — `with zipfile.ZipFile(src) as z:`

#### `tools/vocab.py`

- `tools/vocab.py:388` `sqlite3.connect` — `conn = sqlite3.connect(args.db)`

#### `tools/zip_release.py`

- `tools/zip_release.py:48` `zipfile.ZipFile` — `with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:`

#### `tools/zip_source.py`

- `tools/zip_source.py:46` `zipfile.ZipFile` — `with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:`
- `tools/zip_source.py:61` `zipfile.ZipFile` — `with zipfile.ZipFile(out) as z: # checked, not trusted`

#### Tests

#### `quantisheet_backoffice/tests/test_m3_upgrade.py`

- `quantisheet_backoffice/tests/test_m3_upgrade.py:11` `sqlite3.connect` — `conn = sqlite3.connect(path)`

#### `quantisheet_backoffice/tests/test_p1_01_isolation.py`

- `quantisheet_backoffice/tests/test_p1_01_isolation.py:37` `sqlite3.connect` — `sqlite3.connect(str(tmp_path / "prices.db"))`

#### `quantisheet_backoffice/tests/test_p1_04_storage.py`

- `quantisheet_backoffice/tests/test_p1_04_storage.py:62` `sqlite3.connect` — `con = sqlite3.connect(os.path.join(office.folder, "backoffice.sqlite"))`

#### `quantisheet_backoffice/tests/test_r38_migration.py`

- `quantisheet_backoffice/tests/test_r38_migration.py:19` `sqlite3.connect` — `conn = sqlite3.connect(path)`

#### `quantisheet_backoffice/tests/test_t004_encryption_at_rest.py`

- `quantisheet_backoffice/tests/test_t004_encryption_at_rest.py:16` `sqlite3.connect` — `con = sqlite3.connect(office.db.path)`

#### `tests/test_acrobat.py`

- `tests/test_acrobat.py:49` `zipfile.ZipFile` — `with zipfile.ZipFile(path) as z:`
- `tests/test_acrobat.py:60` `zipfile.ZipFile` — `with zipfile.ZipFile(tmp_path / "t.xlsx") as z:`
- `tests/test_acrobat.py:68` `zipfile.ZipFile` — `with zipfile.ZipFile(tmp_path / "t.xlsx") as z:`

#### `tests/test_acrobat2.py`

- `tests/test_acrobat2.py:64` `zipfile.ZipFile` — `with zipfile.ZipFile(out) as z:`

#### `tests/test_bidzip.py`

- `tests/test_bidzip.py:23` `zipfile.ZipFile` — `with zipfile.ZipFile(inner, "w") as z:`
- `tests/test_bidzip.py:27` `zipfile.ZipFile` — `with zipfile.ZipFile(path, "w") as z:`

#### `tests/test_brand_rename.py`

- `tests/test_brand_rename.py:113` `sqlite3.connect` — `con = sqlite3.connect(str(tmp_path / "p.db"))`

#### `tests/test_costbook_columns.py`

- `tests/test_costbook_columns.py:98` `sqlite3.connect` — `con = sqlite3.connect(path)`

#### `tests/test_crashreport.py`

- `tests/test_crashreport.py:60` `zipfile.ZipFile` — `with zipfile.ZipFile(out) as z:`

#### `tests/test_dashboard.py`

- `tests/test_dashboard.py:255` `sqlite3.connect` — `con = sqlite3.connect(p)`

#### `tests/test_databackup.py`

- `tests/test_databackup.py:22` `sqlite3.connect` — `db = sqlite3.connect(str(bo / "backoffice.db"))`
- `tests/test_databackup.py:34` `zipfile.ZipFile` — `names = zipfile.ZipFile(out).namelist()`
- `tests/test_databackup.py:40` `zipfile.ZipFile` — `z = zipfile.ZipFile(out)`
- `tests/test_databackup.py:43` `sqlite3.connect` — `assert sqlite3.connect(str(p)).execute(`
- `tests/test_databackup.py:65` `zipfile.ZipFile` — `with zipfile.ZipFile(evil, "w") as z:`

#### `tests/test_gaps.py`

- `tests/test_gaps.py:276` `zipfile.ZipFile` — `with zipfile.ZipFile(xlsx) as z:`

#### `tests/test_gui.py`

- `tests/test_gui.py:609` `zipfile.ZipFile` — `with zipfile.ZipFile(p) as z:`

#### `tests/test_issue_report.py`

- `tests/test_issue_report.py:67` `zipfile.ZipFile` — `names = zipfile.ZipFile(z).namelist()`
- `tests/test_issue_report.py:73` `zipfile.ZipFile` — `log = "".join(zipfile.ZipFile(z).read(n).decode("utf-8", "replace")`

#### `tests/test_it_policy.py`

- `tests/test_it_policy.py:157` `zipfile.ZipFile` — `with zipfile.ZipFile(out) as z:`
- `tests/test_it_policy.py:367` `zipfile.ZipFile` — `with zipfile.ZipFile(out) as z:`

#### `tests/test_p1_project_backup.py`

- `tests/test_p1_project_backup.py:37` `zipfile.ZipFile` — `with zipfile.ZipFile(z) as src, zipfile.ZipFile(bad, "w") as dst:`
- `tests/test_p1_project_backup.py:37` `zipfile.ZipFile` — `with zipfile.ZipFile(z) as src, zipfile.ZipFile(bad, "w") as dst:`
- `tests/test_p1_project_backup.py:54` `zipfile.ZipFile` — `with zipfile.ZipFile(z, "w") as w:`

#### `tests/test_planswift.py`

- `tests/test_planswift.py:84` `zipfile.ZipFile` — `with zipfile.ZipFile(out) as z:`

#### `tests/test_pm.py`

- `tests/test_pm.py:288` `zipfile.ZipFile` — `assert "Item 29 needs paint" in zipfile.ZipFile(xl).read(`

#### `tests/test_price_import.py`

- `tests/test_price_import.py:294` `zipfile.ZipFile` — `with zipfile.ZipFile(z, "w") as zf:`

#### `tests/test_pricehistory.py`

- `tests/test_pricehistory.py:41` `sqlite3.connect` — `con = sqlite3.connect(p)`

#### `tests/test_public_scan.py`

- `tests/test_public_scan.py:44` `zipfile.ZipFile` — `with zipfile.ZipFile(app / "pack.zip", "w") as z:`

#### `tests/test_r36_db_safety.py`

- `tests/test_r36_db_safety.py:218` `sqlite3.connect` — `con = sqlite3.connect(baks[0])`

#### `tests/test_t007_hostile_files.py`

- `tests/test_t007_hostile_files.py:39` `zipfile.ZipFile` — `with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:`

### Pattern A — `pathlib` methods that read, write, create, or stat

Production sites: 45. Test sites: 188.

#### Production

#### `app/bidtab_core.py`

- `app/bidtab_core.py:269` `path.read_text` — `text = path.read_text(encoding="utf-8-sig", errors="replace")`
- `app/bidtab_core.py:534` `args.write_sample.write_text` — `args.write_sample.write_text(SAMPLE, encoding="utf-8")`
- `app/bidtab_core.py:556` `path.exists` — `if not path.exists():`
- `app/bidtab_core.py:567` `args.rates_file.exists` — `if args.rates_file and args.rates_file.exists():`
- `app/bidtab_core.py:568` `args.rates_file.read_text` — `rates = json.loads(args.rates_file.read_text(encoding="utf-8"))`
- `app/bidtab_core.py:585` `args.out.write_text` — `args.out.write_text(output, encoding="utf-8")`

#### `app/bls_core.py`

- `app/bls_core.py:121` `path.exists` — `if path.exists():`
- `app/bls_core.py:122` `path.read_text` — `return json.loads(path.read_text(encoding="utf-8"))`
- `app/bls_core.py:264` `args.cache.write_text` — `args.cache.write_text(json.dumps(cache, indent=2), encoding="utf-8")`
- `app/bls_core.py:306` `args.emit_rates.write_text` — `args.emit_rates.write_text(json.dumps(rounded, indent=2), encoding="utf-8")`

#### `app/level_core.py`

- `app/level_core.py:82` `path.read_text` — `text = path.read_text(encoding="utf-8-sig", errors="replace")`
- `app/level_core.py:107` `path.exists` — `if not path.exists():`
- `app/level_core.py:273` `path.open` — `with path.open("w", newline="", encoding="utf-8") as fh:`
- `app/level_core.py:301` `path.open` — `with path.open("w", newline="", encoding="utf-8") as fh:`

#### `app/loaded_rate.py`

- `app/loaded_rate.py:250` `args.write_presets.write_text` — `args.write_presets.write_text(json.dumps(data, indent=2), encoding="utf-8")`
- `app/loaded_rate.py:255` `args.presets.exists` — `if args.presets and args.presets.exists():`
- `app/loaded_rate.py:256` `args.presets.read_text` — `for name, vals in json.loads(args.presets.read_text(encoding="utf-8")).items():`

#### `app/vocab_core.py`

- `app/vocab_core.py:267` `path.read_text` — `text = path.read_text(encoding="utf-8-sig", errors="replace")`
- `app/vocab_core.py:304` `args.out.open` — `with args.out.open("w", newline="", encoding="utf-8") as fh:`

#### `quantisheet_backoffice/host_tests/test_backoffice_hook.py`

- `quantisheet_backoffice/host_tests/test_backoffice_hook.py:103` `exe.write_bytes` — `exe.write_bytes(b"")`

#### `tools/bidtab.py`

- `tools/bidtab.py:264` `path.read_text` — `text = path.read_text(encoding="utf-8-sig", errors="replace")`
- `tools/bidtab.py:529` `args.write_sample.write_text` — `args.write_sample.write_text(SAMPLE, encoding="utf-8")`
- `tools/bidtab.py:551` `path.exists` — `if not path.exists():`
- `tools/bidtab.py:562` `args.rates_file.exists` — `if args.rates_file and args.rates_file.exists():`
- `tools/bidtab.py:563` `args.rates_file.read_text` — `rates = json.loads(args.rates_file.read_text(encoding="utf-8"))`
- `tools/bidtab.py:580` `args.out.write_text` — `args.out.write_text(output, encoding="utf-8")`

#### `tools/costdb.py`

- `tools/costdb.py:401` `args.out.open` — `with args.out.open("w", newline="", encoding="utf-8") as fh:`

#### `tools/estimate.py`

- `tools/estimate.py:250` `db.exists` — `if not costdb or not db or not db.exists():`
- `tools/estimate.py:302` `path.read_text` — `text = path.read_text(encoding="utf-8-sig", errors="replace")`
- `tools/estimate.py:485` `path.open` — `with path.open("w", newline="", encoding="utf-8") as fh:`
- `tools/estimate.py:509` `path.open` — `with path.open("w", newline="", encoding="utf-8") as fh:`

#### `tools/font_probe.py`

- `tools/font_probe.py:29` `w.write_text` — `w.write_text(pg)`

#### `tools/import_cost.py`

- `tools/import_cost.py:80` `path.read_text` — `text = path.read_text(encoding="utf-8-sig", errors="replace")`
- `tools/import_cost.py:344` `path.exists` — `if not path.exists():`
- `tools/import_cost.py:389` `args.queue.open` — `with args.queue.open("w", newline="", encoding="utf-8") as fh:`
- `tools/import_cost.py:412` `args.new_path.open` — `with args.new_path.open("w", newline="", encoding="utf-8") as fh:`

#### `tools/labor_rate.py`

- `tools/labor_rate.py:250` `args.write_presets.write_text` — `args.write_presets.write_text(json.dumps(data, indent=2), encoding="utf-8")`
- `tools/labor_rate.py:255` `args.presets.exists` — `if args.presets and args.presets.exists():`
- `tools/labor_rate.py:256` `args.presets.read_text` — `for name, vals in json.loads(args.presets.read_text(encoding="utf-8")).items():`

#### `tools/level.py`

- `tools/level.py:77` `path.read_text` — `text = path.read_text(encoding="utf-8-sig", errors="replace")`
- `tools/level.py:102` `path.exists` — `if not path.exists():`
- `tools/level.py:268` `path.open` — `with path.open("w", newline="", encoding="utf-8") as fh:`
- `tools/level.py:296` `path.open` — `with path.open("w", newline="", encoding="utf-8") as fh:`

#### `tools/vocab.py`

- `tools/vocab.py:262` `path.read_text` — `text = path.read_text(encoding="utf-8-sig", errors="replace")`
- `tools/vocab.py:301` `args.out.open` — `with args.out.open("w", newline="", encoding="utf-8") as fh:`

#### Tests

#### `quantisheet_backoffice/tests/test_m3_p2_04_06_people.py`

- `quantisheet_backoffice/tests/test_m3_p2_04_06_people.py:64` `form.write_bytes` — `form.write_bytes(b"%PDF-1.4 filled W-4")`

#### `quantisheet_backoffice/tests/test_m4_p3_02_04_sync_wip.py`

- `quantisheet_backoffice/tests/test_m4_p3_02_04_sync_wip.py:60` `qbw.write_bytes` — `qbw.write_bytes(b"x")`
- `quantisheet_backoffice/tests/test_m4_p3_02_04_sync_wip.py:193` `big.write_text` — `big.write_text("Vendor ID,Vendor Name\n" + "V1,Example A\n" * 10)`
- `quantisheet_backoffice/tests/test_m4_p3_02_04_sync_wip.py:199` `big.read_text` — `text=big.read_text())`
- `quantisheet_backoffice/tests/test_m4_p3_02_04_sync_wip.py:203` `big.read_text` — `erpsync.import_file(office, "Vista", "vendors", text=big.read_text())`

#### `quantisheet_backoffice/tests/test_p1_02_snapshot.py`

- `quantisheet_backoffice/tests/test_p1_02_snapshot.py:33` `p.write_text` — `p.write_text(json.dumps(s))`
- `quantisheet_backoffice/tests/test_p1_02_snapshot.py:45` `p.write_text` — `p.write_text(json.dumps(s))`

#### `quantisheet_backoffice/tests/test_p1_17_exports.py`

- `quantisheet_backoffice/tests/test_p1_17_exports.py:140` `p.write_bytes` — `p.write_bytes(b"not really")`
- `quantisheet_backoffice/tests/test_p1_17_exports.py:174` `qbb.write_bytes` — `qbb.write_bytes(b"not ours")`
- `quantisheet_backoffice/tests/test_p1_17_exports.py:180` `qbb.read_bytes` — `assert qbb.read_bytes() == b"not ours"`

#### `quantisheet_backoffice/tests/test_p2_banking.py`

- `quantisheet_backoffice/tests/test_p2_banking.py:57` `p.write_text` — `p.write_text(ofx(lines))`
- `quantisheet_backoffice/tests/test_p2_banking.py:93` `p.write_text` — `p.write_text(ofx([("A1", "20261005", "-50.00", "X", ""),`
- `quantisheet_backoffice/tests/test_p2_banking.py:121` `p.write_text` — `p.write_text(ofx([("D1", "20261103", "60000.00", "DEPOSIT", "")]))`
- `quantisheet_backoffice/tests/test_p2_banking.py:142` `p.write_text` — `p.write_text(ofx(rows))`
- `quantisheet_backoffice/tests/test_p2_banking.py:165` `p.write_text` — `p.write_text(ofx([("B1", "20261020", "-312.47", "EXAMPLE LUMBER", "")]))`
- `quantisheet_backoffice/tests/test_p2_banking.py:230` `p.write_text` — `p.write_text(ofx([("D1", "20261103", "60000.00", "DEPOSIT", ""),`

#### `quantisheet_backoffice/tests/test_p2_books.py`

- `quantisheet_backoffice/tests/test_p2_books.py:152` `tmp_path.iterdir` — `files0 = sorted(p.name for p in tmp_path.iterdir())`
- `quantisheet_backoffice/tests/test_p2_books.py:159` `tmp_path.iterdir` — `assert sorted(p.name for p in tmp_path.iterdir()) == files0`

#### `quantisheet_backoffice/tests/test_p2_migrate.py`

- `quantisheet_backoffice/tests/test_p2_migrate.py:50` `p.write_text` — `p.write_text(iif_text(), encoding="utf-8")`
- `quantisheet_backoffice/tests/test_p2_migrate.py:127` `acc.write_text` — `acc.write_text("Account,Type,Detail type,Description\n"`
- `quantisheet_backoffice/tests/test_p2_migrate.py:133` `cus.write_text` — `cus.write_text("Customer,Email,Phone\nExample Medical Office,p@example.test,\n",`
- `quantisheet_backoffice/tests/test_p2_migrate.py:144` `qbw.write_bytes` — `qbw.write_bytes(b"x")`

#### `quantisheet_backoffice/tests/test_r111_qs025_migration.py`

- `quantisheet_backoffice/tests/test_r111_qs025_migration.py:78` `bk.write_bytes` — `bk.write_bytes(blob)`

#### `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py`

- `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py:85` `pdf.write_bytes` — `pdf.write_bytes(b"%PDF-1.4\n%made up\n")`
- `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py:101` `pdf.write_bytes` — `pdf.write_bytes(b"%PDF-1.4\n%made up\n")`
- `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py:147` `pdf.write_bytes` — `pdf.write_bytes(b"%PDF-1.4\n%made up\n")`
- `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py:177` `pdf.write_bytes` — `pdf.write_bytes(b"%PDF-1.4\n%made up\n")`

#### `quantisheet_backoffice/tests/test_review_fixes.py`

- `quantisheet_backoffice/tests/test_review_fixes.py:58` `mine.write_bytes` — `mine.write_bytes(b"keep me")`
- `quantisheet_backoffice/tests/test_review_fixes.py:69` `mine.read_bytes` — `assert mine.read_bytes() == b"keep me"`
- `quantisheet_backoffice/tests/test_review_fixes.py:81` `mine.write_text` — `mine.write_text("{}")`
- `quantisheet_backoffice/tests/test_review_fixes.py:303` `p.write_text` — `p.write_text(iif_text(), encoding="utf-8")`
- `quantisheet_backoffice/tests/test_review_fixes.py:347` `fake.write_text` — `fake.write_text("#!/bin/sh\n")`

#### `quantisheet_backoffice/tests/test_security_0_13_5.py`

- `quantisheet_backoffice/tests/test_security_0_13_5.py:124` `f.write_bytes` — `f.write_bytes(b"%PDF-1.4 example W-4")`

#### `quantisheet_backoffice/tests/test_threat_model_bo_fixes.py`

- `quantisheet_backoffice/tests/test_threat_model_bo_fixes.py:33` `p.write_bytes` — `p.write_bytes(backup.MAGIC + json.dumps({"password": {`

#### `quantisheet_claims/tests/test_interface.py`

- `quantisheet_claims/tests/test_interface.py:54` `p.write_text` — `p.write_text("{nope", encoding="utf-8")`

#### `quantisheet_claims/tests/test_nw16_photos.py`

- `quantisheet_claims/tests/test_nw16_photos.py:59` `t.write_text` — `t.write_text("x")`

#### `quantisheet_claims/tests/test_p1_line_library.py`

- `quantisheet_claims/tests/test_p1_line_library.py:15` `root.rglob` — `for p in root.rglob("*"):`
- `quantisheet_claims/tests/test_p1_line_library.py:71` `p.write_text` — `p.write_text("a,b\n1,2\n", encoding="utf-8")`

#### `tests/test_acrobat2.py`

- `tests/test_acrobat2.py:26` `t.write_text` — `t.write_text("Line one\nLine two <not html>\n" * 3, encoding="utf-8")`
- `tests/test_acrobat2.py:30` `h.write_text` — `h.write_text("<h1>Site Report</h1><p>All <b>good</b>.</p>",`
- `tests/test_acrobat2.py:131` `txt.write_text` — `txt.write_text("plain text file", encoding="utf-8")`

#### `tests/test_aerial_ui.py`

- `tests/test_aerial_ui.py:84` `p.write_bytes` — `p.write_bytes(_png(400, 300))`

#### `tests/test_bidbuild.py`

- `tests/test_bidbuild.py:117` `t.write_text` — `t.write_text("unit_cost,description,qty,unit,cost_type,trade\n"`
- `tests/test_bidbuild.py:131` `sov.read_text` — `rows = sov.read_text().strip().splitlines()`

#### `tests/test_bidzip.py`

- `tests/test_bidzip.py:61` `p.write_bytes` — `p.write_bytes(b"nope")`

#### `tests/test_brand_rename_2.py`

- `tests/test_brand_rename_2.py:92` `exe.write_bytes` — `exe.write_bytes(b"")`
- `tests/test_brand_rename_2.py:94` `other.write_bytes` — `other.write_bytes(b"")`

#### `tests/test_bughunt_r5.py`

- `tests/test_bughunt_r5.py:28` `p.write_bytes` — `p.write_bytes(ZERO_PAGES)`
- `tests/test_bughunt_r5.py:150` `bad.write_bytes` — `bad.write_bytes(b"%PDF-1.4\n\xff\xfe binary")`

#### `tests/test_claims_hook.py`

- `tests/test_claims_hook.py:91` `exe.write_bytes` — `exe.write_bytes(b"")`

#### `tests/test_cli_bad_pdf.py`

- `tests/test_cli_bad_pdf.py:19` `p.write_bytes` — `p.write_bytes(data)`

#### `tests/test_costlayer_wiring.py`

- `tests/test_costlayer_wiring.py:23` `p.write_text` — `p.write_text(LIB, encoding="utf-8")`

#### `tests/test_crashreport.py`

- `tests/test_crashreport.py:39` `crash.write_text` — `crash.write_text("Windows fatal exception: old one\n", encoding="utf-8")`
- `tests/test_crashreport.py:96` `crash.write_text` — `crash.write_text("--- start ---\n", encoding="utf-8")`

#### `tests/test_databackup.py`

- `tests/test_databackup.py:42` `p.write_bytes` — `p.write_bytes(z.read("backoffice/backoffice.db"))`

#### `tests/test_drop_open.py`

- `tests/test_drop_open.py:35` `t.write_text` — `t.write_text("x")`

#### `tests/test_dropbox.py`

- `tests/test_dropbox.py:287` `p.write_bytes` — `p.write_bytes(data)`
- `tests/test_dropbox.py:444` `p.write_bytes` — `p.write_bytes(b"PK excel")`
- `tests/test_dropbox.py:464` `p.write_bytes` — `p.write_bytes(raw)`
- `tests/test_dropbox.py:481` `p.write_bytes` — `p.write_bytes(data)`
- `tests/test_dropbox.py:499` `p.write_bytes` — `p.write_bytes(b"y" * 100)`
- `tests/test_dropbox.py:597` `p.write_text` — `p.write_text(json.dumps(kw))`

#### `tests/test_estimate_layouts.py`

- `tests/test_estimate_layouts.py:246` `bad.write_text` — `bad.write_text('{"hello": 1}', encoding="utf-8")`

#### `tests/test_estimating.py`

- `tests/test_estimating.py:170` `csvp.write_text` — `csvp.write_text("Code,Description,Unit,Material,Labor,Crew\n"`

#### `tests/test_fixes.py`

- `tests/test_fixes.py:147` `src.read_bytes` — `rid = versions.save_revision(str(src), src.read_bytes(),`
- `tests/test_fixes.py:151` `src.read_bytes` — `assert versions.load_revision(str(src), rid) == src.read_bytes()`

#### `tests/test_formula_guard_exporters.py`

- `tests/test_formula_guard_exporters.py:278` `src.write_text` — `src.write_text(EVIL + "\n" + AT + "\n", encoding="utf-8")`

#### `tests/test_freeze_offer.py`

- `tests/test_freeze_offer.py:30` `crash.write_text` — `crash.write_text("--- start ---\n", encoding="utf-8")`
- `tests/test_freeze_offer.py:44` `crash.write_text` — `crash.write_text("--- start ---\n", encoding="utf-8")`

#### `tests/test_freeze_watch.py`

- `tests/test_freeze_watch.py:31` `path.read_text` — `text = path.read_text(encoding="utf-8")`

#### `tests/test_gui.py`

- `tests/test_gui.py:656` `t.write_text` — `t.write_text("Memo to file", encoding="utf-8")`

#### `tests/test_heavy.py`

- `tests/test_heavy.py:164` `bad.write_text` — `bad.write_text("a,b\n1,2\n")`
- `tests/test_heavy.py:202` `p.write_text` — `p.write_text("Classification,Rate,Fringe\n"`

#### `tests/test_it_policy.py`

- `tests/test_it_policy.py:30` `path.write_text` — `path.write_text(json.dumps(kw))`
- `tests/test_it_policy.py:345` `out.read_text` — `assert json.loads(out.read_text())["edition"] == "tester"`

#### `tests/test_leveling.py`

- `tests/test_leveling.py:56` `p.write_text` — `p.write_text(TAB, encoding="utf-8")`
- `tests/test_leveling.py:118` `q.write_text` — `q.write_text('Description,Unit,Qty,Unit Price\n'`
- `tests/test_leveling.py:157` `q.write_text` — `q.write_text('Description,Unit,Qty,Unit Price\n'`

#### `tests/test_macro_preflight.py`

- `tests/test_macro_preflight.py:29` `p.read_text` — `d = json.loads(p.read_text())`
- `tests/test_macro_preflight.py:32` `p.write_text` — `p.write_text(json.dumps(d))`

#### `tests/test_master_pdfsched.py`

- `tests/test_master_pdfsched.py:146` `p.write_bytes` — `p.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 512) # an OLE file`

#### `tests/test_nov4_items.py`

- `tests/test_nov4_items.py:130` `exe.write_bytes` — `exe.write_bytes(b"MZ")`
- `tests/test_nov4_items.py:145` `exe.write_bytes` — `exe.write_bytes(b"MZ")`
- `tests/test_nov4_items.py:234` `pic.write_bytes` — `pic.write_bytes(cv2.imencode(".png", img)[1].tobytes())`
- `tests/test_nov4_items.py:241` `pic.read_bytes` — `dlg = w._view.count_from_picture(pic.read_bytes(), "Outlet", False,`

#### `tests/test_owncopy.py`

- `tests/test_owncopy.py:16` `p.write_bytes` — `p.write_bytes(b"MZ")`
- `tests/test_owncopy.py:33` `pdf.write_bytes` — `pdf.write_bytes(b"%PDF")`

#### `tests/test_p0_updater.py`

- `tests/test_p0_updater.py:21` `p.write_bytes` — `p.write_bytes(b"setup")`

#### `tests/test_p1_existing_features.py`

- `tests/test_p1_existing_features.py:30` `p.write_text` — `p.write_text("Code,Description,Unit,Material,Labor,Sub\n"`

#### `tests/test_p1_photo_library.py`

- `tests/test_p1_photo_library.py:20` `p.write_bytes` — `p.write_bytes(b"\xff\xd8\xff example photo %d" % i)`

#### `tests/test_pdf_tools_0_13_5.py`

- `tests/test_pdf_tools_0_13_5.py:370` `out.write_bytes` — `out.write_bytes(b"%PDF-1.4 example older copy")`
- `tests/test_pdf_tools_0_13_5.py:374` `out.read_bytes` — `assert out.read_bytes() == b"%PDF-1.4 example older copy"`

#### `tests/test_photofit.py`

- `tests/test_photofit.py:160` `q.write_text` — `q.write_text("not a photo")`
- `tests/test_photofit.py:179` `h.write_bytes` — `h.write_bytes(b"\0\0\0\x18ftypheic")`

#### `tests/test_pm.py`

- `tests/test_pm.py:418` `big.write_bytes` — `big.write_bytes(os.urandom(9 * 1024 * 1024))`
- `tests/test_pm.py:425` `back.read_bytes` — `assert back.read_bytes() == big.read_bytes()`
- `tests/test_pm.py:425` `big.read_bytes` — `assert back.read_bytes() == big.read_bytes()`
- `tests/test_pm.py:430` `img.write_bytes` — `img.write_bytes(fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4),`
- `tests/test_pm.py:436` `img.read_bytes` — `assert body == img.read_bytes()`

#### `tests/test_ppi_labor.py`

- `tests/test_ppi_labor.py:90` `cache.write_text` — `cache.write_text(json.dumps({s: _series(r) for s, r in RATES.items()}))`
- `tests/test_ppi_labor.py:94` `out.read_text` — `rates = json.loads(out.read_text())`

#### `tests/test_pricedb.py`

- `tests/test_pricedb.py:119` `p.write_text` — `p.write_text(bidtab_core.SAMPLE, encoding="utf-8")`

#### `tests/test_printer.py`

- `tests/test_printer.py:105` `port.write_bytes` — `port.write_bytes(b"%PDF-1.7 fake")`
- `tests/test_printer.py:118` `port.write_bytes` — `port.write_bytes(b"not a pdf") # removed, not opened`

#### `tests/test_r36_actuals_import.py`

- `tests/test_r36_actuals_import.py:102` `p.write_bytes` — `p.write_bytes(b"Code,Amount\n09 29 00,10\n\x00\x00\x00garbage")`

#### `tests/test_r36_assembly_rules.py`

- `tests/test_r36_assembly_rules.py:192` `bad.write_text` — `bad.write_text("{", encoding="utf-8")`

#### `tests/test_r36_bid_items.py`

- `tests/test_r36_bid_items.py:26` `p.write_text` — `p.write_text("Item No,Description,Unit,Quantity,Unit Price\n"`

#### `tests/test_r36_bidday.py`

- `tests/test_r36_bidday.py:64` `p.write_text` — `p.write_text("Item,Description,Unit,Qty,My plug,Test Sub A,Test Sub B\n"`

#### `tests/test_r36_db_safety.py`

- `tests/test_r36_db_safety.py:259` `src.write_text` — `src.write_text("SKU,Description,Unit,Price\nT1,Test pipe,LF,3.50\n",`

#### `tests/test_r36_price_workbook.py`

- `tests/test_r36_price_workbook.py:90` `glob.glob` — `assert not glob.glob(str(tmp_path / "*.part"))`

#### `tests/test_r36_rate_matcher.py`

- `tests/test_r36_rate_matcher.py:179` `glob.glob` — `assert glob.glob(str(tmp_path / "*.bak*")) or glob.glob(`
- `tests/test_r36_rate_matcher.py:179` `glob.glob` — `assert glob.glob(str(tmp_path / "*.bak*")) or glob.glob(`
- `tests/test_r36_rate_matcher.py:197` `p.write_text` — `p.write_text("{not json", encoding="utf-8")`

#### `tests/test_r36_safe_writes.py`

- `tests/test_r36_safe_writes.py:51` `p.write_bytes` — `p.write_bytes(b"old contents")`
- `tests/test_r36_safe_writes.py:68` `p.read_bytes` — `assert p.read_bytes() == b"old contents"`
- `tests/test_r36_safe_writes.py:76` `src.write_text` — `src.write_text(GOOD, encoding="utf-8")`
- `tests/test_r36_safe_writes.py:79` `out.read_bytes` — `old = out.read_bytes()`
- `tests/test_r36_safe_writes.py:80` `src.write_text` — `src.write_text(GOOD.replace("3.50", "4.25"), encoding="utf-8")`
- `tests/test_r36_safe_writes.py:83` `out.read_bytes` — `assert out.read_bytes() == old`
- `tests/test_r36_safe_writes.py:86` `out.read_bytes` — `assert out.read_bytes() != old`
- `tests/test_r36_safe_writes.py:106` `src.write_bytes` — `src.write_bytes(BAD[name])`
- `tests/test_r36_safe_writes.py:114` `keep.write_bytes` — `keep.write_bytes(b"{}")`
- `tests/test_r36_safe_writes.py:118` `keep.read_bytes` — `assert keep.read_bytes() == b"{}"`
- `tests/test_r36_safe_writes.py:126` `src.write_bytes` — `src.write_bytes(BAD[name])`
- `tests/test_r36_safe_writes.py:136` `src.write_bytes` — `src.write_bytes("SKU,Description,Unit,Price\nT1,Caf\xe9 pipe,LF,3\n"`
- `tests/test_r36_safe_writes.py:146` `src.write_bytes` — `src.write_bytes(BAD["unclosed.csv"])`

#### `tests/test_r36_supplier_prices.py`

- `tests/test_r36_supplier_prices.py:25` `p.write_text` — `p.write_text("Item #,Description,UOM,Unit Price,Pack,Category\n"`

#### `tests/test_r36_templates.py`

- `tests/test_r36_templates.py:82` `bad.write_text` — `bad.write_text(json.dumps({"kind": "nope", "items": []}))`
- `tests/test_r36_templates.py:85` `bad.write_text` — `bad.write_text(json.dumps({"kind": "estimate", "name": "x",`

#### `tests/test_r36_ui.py`

- `tests/test_r36_ui.py:113` `bids.write_text` — `bids.write_text("Item,Description,Unit,Qty,My plug,Test A,Test B\n"`
- `tests/test_r36_ui.py:124` `lst.write_text` — `lst.write_text("SKU,Description,Unit,Price\nX1,Test stud,EA,3.10\n",`

#### `tests/test_r36_ui_step7.py`

- `tests/test_r36_ui_step7.py:49` `csvp.write_text` — `csvp.write_text("Cost Code,Actual Cost\n09 65 00,500\n99,1\n",`
- `tests/test_r36_ui_step7.py:64` `p.write_text` — `p.write_text("foo,bar\n1,2\n", encoding="utf-8")`

#### `tests/test_r39_characterize.py`

- `tests/test_r39_characterize.py:109` `x.write_text` — `x.write_text(MSP, encoding="utf-8")`
- `tests/test_r39_characterize.py:111` `e.write_bytes` — `e.write_bytes(XER.encode("cp1252"))`

#### `tests/test_r39_master_excel.py`

- `tests/test_r39_master_excel.py:115` `p.write_bytes` — `p.write_bytes(data)`

#### `tests/test_r39_master_intake.py`

- `tests/test_r39_master_intake.py:113` `f.read_bytes` — `data = f.read_bytes()`
- `tests/test_r39_master_intake.py:123` `note.read_text` — `assert "duplicate" in note.read_text(encoding="utf-8").lower()`

#### `tests/test_release_files.py`

- `tests/test_release_files.py:30` `gh.iterdir` — `for p in gh.iterdir():`
- `tests/test_release_files.py:33` `p.read_bytes` — `p.read_bytes()).hexdigest()`

#### `tests/test_review_0_12_30.py`

- `tests/test_review_0_12_30.py:15` `p.write_bytes` — `p.write_bytes(text.encode("cp1252"))`
- `tests/test_review_0_12_30.py:21` `textio.read_text` — `assert "–" in textio.read_text(p)`
- `tests/test_review_0_12_30.py:23` `u.write_bytes` — `u.write_bytes(b"\xef\xbb\xbfa,b\n") # Excel UTF-8 BOM`
- `tests/test_review_0_12_30.py:24` `textio.read_text` — `assert textio.read_text(str(u)) == "a,b\n"`

#### `tests/test_review_0_12_32.py`

- `tests/test_review_0_12_32.py:10` `p.write_bytes` — `p.write_bytes(text.encode("cp1252"))`

#### `tests/test_review_0_13_5.py`

- `tests/test_review_0_13_5.py:85` `p.write_bytes` — `p.write_bytes(raw)`
- `tests/test_review_0_13_5.py:179` `p.write_text` — `p.write_text(text, encoding="utf-8")`
- `tests/test_review_0_13_5.py:386` `junk.write_bytes` — `junk.write_bytes(b"not a pdf at all")`

#### `tests/test_review_confidence.py`

- `tests/test_review_confidence.py:61` `log.read_text` — `lines = [json.loads(x) for x in log.read_text().splitlines()]`

#### `tests/test_review_followups.py`

- `tests/test_review_followups.py:24` `p.write_bytes` — `p.write_bytes(b"%PDF-1.7 first")`
- `tests/test_review_followups.py:27` `p.write_bytes` — `p.write_bytes(b"%PDF-1.7 second")`

#### `tests/test_review_oct15.py`

- `tests/test_review_oct15.py:220` `p.read_bytes` — `data = bytearray(p.read_bytes())`
- `tests/test_review_oct15.py:224` `bad.write_bytes` — `bad.write_bytes(bytes(data))`

#### `tests/test_review_venice.py`

- `tests/test_review_venice.py:112` `p.write_text` — `p.write_text(body, encoding="utf-8")`
- `tests/test_review_venice.py:119` `p.write_text` — `p.write_text("Code,Description\n1,Sidewalk\n2,Curb\n", encoding="utf-8")`

#### `tests/test_roof_report.py`

- `tests/test_roof_report.py:65` `txt.write_text` — `txt.write_text("hello")`

#### `tests/test_safeio.py`

- `tests/test_safeio.py:17` `p.read_bytes` — `before = p.read_bytes()`
- `tests/test_safeio.py:28` `p.read_bytes` — `assert p.read_bytes() == before`
- `tests/test_safeio.py:29` `tmp_path.iterdir` — `assert [x.name for x in tmp_path.iterdir()] == ["plan.pdf"]`
- `tests/test_safeio.py:38` `p.read_text` — `assert p.read_text() == "one"`
- `tests/test_safeio.py:40` `p.read_bytes` — `assert p.read_bytes() == b"two"`
- `tests/test_safeio.py:43` `p.write_text` — `p.write_text("three")`

#### `tests/test_sbom.py`

- `tests/test_sbom.py:49` `req.write_text` — `req.write_text(`

#### `tests/test_schedule.py`

- `tests/test_schedule.py:144` `xer.write_text` — `xer.write_text("ERMHDR\t19.12\n%T\tPROJWBS\n%F\twbs_id\twbs_name\n"`

#### `tests/test_scope_nov2.py`

- `tests/test_scope_nov2.py:110` `bad.write_text` — `bad.write_text(json.dumps({"sets": {}}))`

#### `tests/test_sealed_contacts.py`

- `tests/test_sealed_contacts.py:28` `p.write_bytes` — `p.write_bytes(blob)`

#### `tests/test_starter_costbook.py`

- `tests/test_starter_costbook.py:145` `src.write_text` — `src.write_text(SAMPLE, encoding="utf-8")`
- `tests/test_starter_costbook.py:196` `src.write_text` — `src.write_text(SAMPLE, encoding="utf-8")`

#### `tests/test_stress_findings.py`

- `tests/test_stress_findings.py:161` `script.write_text` — `script.write_text(_CHURN)`

#### `tests/test_t007_hostile_files.py`

- `tests/test_t007_hostile_files.py:29` `p.write_bytes` — `p.write_bytes(BOMB)`
- `tests/test_t007_hostile_files.py:50` `p.write_bytes` — `p.write_bytes(BOMB.decode().encode("utf-16"))`

#### `tests/test_threat_model_small_fixes.py`

- `tests/test_threat_model_small_fixes.py:20` `fake.write_bytes` — `fake.write_bytes(b"")`
- `tests/test_threat_model_small_fixes.py:36` `evil.write_bytes` — `evil.write_bytes(b"")`
- `tests/test_threat_model_small_fixes.py:42` `ok.write_bytes` — `ok.write_bytes(b"")`

#### `tests/test_updatecheck.py`

- `tests/test_updatecheck.py:43` `path.write_text` — `path.write_text(json.dumps(kw))`
- `tests/test_updatecheck.py:500` `exe.write_bytes` — `exe.write_bytes(PAYLOAD)`

#### `tests/test_v33_security.py`

- `tests/test_v33_security.py:71` `c.write_bytes` — `c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))`
- `tests/test_v33_security.py:72` `k.write_bytes` — `k.write_bytes(key.private_bytes(serialization.Encoding.PEM,`
- `tests/test_v33_security.py:314` `old.write_bytes` — `old.write_bytes(k.private_bytes(serialization.Encoding.PEM,`
- `tests/test_v33_security.py:319` `old.read_bytes` — `new = old.read_bytes()`

#### `tests/test_v35_crash_nits.py`

- `tests/test_v35_crash_nits.py:70` `p.write_text` — `p.write_text(`
- `tests/test_v35_crash_nits.py:176` `p.write_bytes` — `p.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 100)`

#### `tests/test_v35_money_security.py`

- `tests/test_v35_money_security.py:105` `f.write_bytes` — `f.write_bytes(b"\xff\xd8 jpeg")`

#### `tests/test_vocab.py`

- `tests/test_vocab.py:57` `items.write_text` — `items.write_text('4" conc sidewalk SF\n6 in conc sidewalk SF\n'`
- `tests/test_vocab.py:72` `p.write_text` — `p.write_text(bidtab_core.SAMPLE, encoding="utf-8")`
- `tests/test_vocab.py:74` `q.write_text` — `q.write_text('Description,Unit,Qty,Unit Price\n'`

#### `tests/test_winget.py`

- `tests/test_winget.py:16` `p.write_text` — `p.write_text(f"{H1} QuantiSheet-Public-Beta-Setup-{v}.exe\n"`

#### `tests/test_zoom_rfi_xfdf.py`

- `tests/test_zoom_rfi_xfdf.py:195` `path.write_text` — `path.write_text(`

### Pattern B — `os.path.join`

Production sites: 1196. Test sites: 316.

#### Production

#### `app/acrobat.py`

- `app/acrobat.py:27` `os.path.join` — `for cand in (os.path.join(os.path.dirname(exe), "tessdata"),`
- `app/acrobat.py:28` `os.path.join` — `os.path.join(os.path.dirname(os.path.dirname(exe)), "share",`
- `app/acrobat.py:165` `os.path.join` — `png = os.path.join(tmpdir, f"t{k}.png")`
- `app/acrobat.py:313` `os.path.join` — `p = os.path.join(folder, f"{base}_page{i + 1:03d}.{fmt}")`

#### `app/acrobat2.py`

- `app/acrobat2.py:108` `os.path.join` — `made = os.path.join(outdir, os.path.splitext(`
- `app/acrobat2.py:147` `os.path.join` — `out = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),`
- `app/acrobat2.py:184` `os.path.join` — `path = os.path.join(out_dir, f"{base} - {i:02d} {safe}.pdf")`
- `app/acrobat2.py:350` `os.path.join` — `os.path.join(folder, f"slide{i:04d}.png"))`
- `app/acrobat2.py:927` `os.path.join` — `out = os.path.join(out_dir, os.path.basename(src))`

#### `app/acrobat2_dialogs.py`

- `app/acrobat2_dialogs.py:100` `os.path.join` — `os.path.join(d, f) for f in os.listdir(d)`
- `app/acrobat2_dialogs.py:103` `os.path.join` — `self.out.setText(os.path.join(d, "processed"))`

#### `app/ada_ref.py`

- `app/ada_ref.py:16` `os.path.join` — `FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`

#### `app/aerial.py`

- `app/aerial.py:465` `os.path.join` — `return os.path.join(settings.DIR, "aerial_cache")`
- `app/aerial.py:479` `os.path.join` — `p = os.path.join(_cache_dir(), _cache_key(params) + ".img")`
- `app/aerial.py:496` `os.path.join` — `p = os.path.join(d, _cache_key(params) + ".img")`
- `app/aerial.py:501` `os.path.join` — `files = [os.path.join(d, n) for n in os.listdir(d)`

#### `app/assemblies.py`

- `app/assemblies.py:45` `os.path.join` — `LIBRARY_PATH = os.path.join(settings.DIR, "assemblies.json")`

#### `app/assembly_codes.py`

- `app/assembly_codes.py:39` `os.path.join` — `_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")`
- `app/assembly_codes.py:40` `os.path.join` — `TEMPLATE = os.path.join(_DATA, "assembly_codes_TEMPLATE.csv")`
- `app/assembly_codes.py:41` `os.path.join` — `EXAMPLE = os.path.join(_DATA, "assembly_codes_EXAMPLE.csv")`

#### `app/assembly_csv.py`

- `app/assembly_csv.py:36` `os.path.join` — `CATALOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `app/assembly_csv.py:260` `os.path.join` — `path = os.path.join(settings.DIR, "catalogs")`
- `app/assembly_csv.py:269` `os.path.join` — `files += [os.path.join(d, n) for n in sorted(os.listdir(d))`

#### `app/autosave.py`

- `app/autosave.py:56` `os.path.join` — `d = os.path.join(settings.DIR, "autosave")`
- `app/autosave.py:69` `os.path.join` — `return os.path.join(d, k + ".pdf"), os.path.join(d, k + ".json")`
- `app/autosave.py:69` `os.path.join` — `return os.path.join(d, k + ".pdf"), os.path.join(d, k + ".json")`
- `app/autosave.py:108` `os.path.join` — `meta = os.path.join(d, name)`

#### `app/backoffice_hook.py`

- `app/backoffice_hook.py:59` `os.path.join` — `sib = os.path.join(os.path.dirname(install), "QuantiSheetBackOffice",`
- `app/backoffice_hook.py:311` `os.path.join` — `p = os.path.join(base, name)`
- `app/backoffice_hook.py:326` `os.path.join` — `path = os.path.join(folder, "snapshot.json")`

#### `app/betalicense.py`

- `app/betalicense.py:43` `os.path.join` — `return os.path.join(base, "app", "data")`
- `app/betalicense.py:44` `os.path.join` — `return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")`
- `app/betalicense.py:49` `os.path.join` — `with open(os.path.join(_data_dir(), _PUBKEY_FILE)) as f:`
- `app/betalicense.py:102` `os.path.join` — `base = os.environ.get("LOCALAPPDATA") or os.path.join(`
- `app/betalicense.py:104` `os.path.join` — `return os.path.join(base, "QuantiSheet", ".seen")`
- `app/betalicense.py:209` `os.path.join` — `root = os.path.normpath(os.path.join(`
- `app/betalicense.py:229` `os.path.join` — `data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")`
- `app/betalicense.py:231` `os.path.join` — `with open(os.path.join(data, "build.json"), encoding="utf-8") as f:`
- `app/betalicense.py:241` `os.path.join` — `sealed = os.path.isfile(os.path.join(data, "contacts.sealed"))`

#### `app/bidform_xl_ui.py`

- `app/bidform_xl_ui.py:82` `os.path.join` — `return os.path.join(os.path.dirname(self.src),`
- `app/bidform_xl_ui.py:130` `os.path.join` — `out = out or os.path.join(os.path.dirname(self.book_path),`
- `app/bidform_xl_ui.py:173` `os.path.join` — `new_book = os.path.join(`
- `app/bidform_xl_ui.py:262` `os.path.join` — `path = os.path.join(folder, self.BR.file_name(v))`

#### `app/bidzip.py`

- `app/bidzip.py:125` `os.path.join` — `dest_dir = os.path.join(folder, kind)`
- `app/bidzip.py:128` `os.path.join` — `dest = os.path.join(dest_dir, base)`
- `app/bidzip.py:132` `os.path.join` — `dest = os.path.join(dest_dir, f"{stem} ({k}){ext}")`

#### `app/billing_ui.py`

- `app/billing_ui.py:135` `os.path.join` — `os.path.join(base, name), filt)`

#### `app/brand_paths.py`

- `app/brand_paths.py:13` `os.path.join` — `return os.path.join(documents, NEW, PRINTED)`
- `app/brand_paths.py:19` `os.path.join` — `return os.path.join(base, NEW)`

#### `app/branding.py`

- `app/branding.py:25` `os.path.join` — `if d and os.path.isfile(os.path.join(d, EXE)):`
- `app/branding.py:40` `os.path.join` — `return os.path.join(reg, EXE)`
- `app/branding.py:41` `os.path.join` — `base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")`
- `app/branding.py:42` `os.path.join` — `return os.path.join(base, NAME, EXE)`

#### `app/civil_export.py`

- `app/civil_export.py:367` `os.path.join` — `p = os.path.join(folder, f"biditems.{ext}")`
- `app/civil_export.py:372` `os.path.join` — `os.path.join(folder, f"activities.{ext}"), ACT_HEAD,`
- `app/civil_export.py:378` `os.path.join` — `os.path.join(folder, f"resources.{ext}"), RES_HEAD,`

#### `app/claims_hook.py`

- `app/claims_hook.py:63` `os.path.join` — `sib = os.path.join(os.path.dirname(install), DIR_NAME, EXE_NAME)`
- `app/claims_hook.py:131` `os.path.join` — `path = os.path.join(folder, "takeoff.json")`

#### `app/co_delta_ui.py`

- `app/co_delta_ui.py:76` `os.path.join` — `out = out or os.path.join(tempfile.mkdtemp(prefix="qs_co_"),`

#### `app/codecheck_ui.py`

- `app/codecheck_ui.py:252` `os.path.join` — `os.path.join(base, report_file_name("Code Check Report",`

#### `app/codelib.py`

- `app/codelib.py:32` `os.path.join` — `d = os.path.join(brand_paths.local_dir(), brand_paths.CODE_LIBRARY)`
- `app/codelib.py:46` `os.path.join` — `p = os.path.join(folder(), f)`
- `app/codelib.py:104` `os.path.join` — `dest = os.path.join(folder(), name + ".pdf")`

#### `app/collab/hub.py`

- `app/collab/hub.py:126` `os.path.join` — `sp = os.path.join(self.dir, "secret")`
- `app/collab/hub.py:139` `os.path.join` — `full = os.path.realpath(os.path.join(base, *parts))`
- `app/collab/hub.py:198` `os.path.join` — `meta = self._load(os.path.join(self._env_dir(env_id), "meta.json"))`
- `app/collab/hub.py:204` `os.path.join` — `self._save(os.path.join(self._env_dir(meta["id"]), "meta.json"), meta)`
- `app/collab/hub.py:266` `os.path.join` — `with open(os.path.join(d, f"p{n}.png"), "wb") as f:`
- `app/collab/hub.py:367` `os.path.join` — `index = self._load(os.path.join(root, "tokens.json"), {})`
- `app/collab/hub.py:377` `os.path.join` — `p = os.path.join(root, name, "meta.json")`
- `app/collab/hub.py:382` `os.path.join` — `self._save(os.path.join(root, "tokens.json"), index)`
- `app/collab/hub.py:647` `os.path.join` — `mp = os.path.join(d, "meta.json")`
- `app/collab/hub.py:668` `os.path.join` — `os.makedirs(os.path.join(d, "files"), exist_ok=True)`
- `app/collab/hub.py:1005` `os.path.join` — `data = self._load(os.path.join(d, name), {"items": {}})`
- `app/collab/hub.py:1517` `os.path.join` — `p = os.path.join(self._env_dir(meta["id"]),`

#### `app/collab/relay.py`

- `app/collab/relay.py:34` `os.path.join` — `WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")`
- `app/collab/relay.py:35` `os.path.join` — `HUB_DIR = os.path.join(settings.DIR, "hub") # the per-user data folder`

#### `app/collab/relaycore.py`

- `app/collab/relaycore.py:345` `os.path.join` — `full = os.path.realpath(os.path.join(base, path.lstrip("/\\")))`

#### `app/convert.py`

- `app/convert.py:32` `os.path.join` — `fp = os.path.join(out_dir, f"page_{i + 1:03d}.png")`

#### `app/costbook.py`

- `app/costbook.py:48` `os.path.join` — `path = os.path.join(settings.DIR, "costbooks")`
- `app/costbook.py:673` `os.path.join` — `SHIPPED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `app/costbook.py:711` `os.path.join` — `with open(os.path.join(SHIPPED, n), encoding="utf-8") as f:`

#### `app/count_library.py`

- `app/count_library.py:47` `os.path.join` — `return os.path.join(os.path.dirname(pricedb.path()), FILENAME)`
- `app/count_library.py:50` `os.path.join` — `return os.path.join(settings.DIR, LOCAL)`

#### `app/crashreport.py`

- `app/crashreport.py:71` `os.path.join` — `return os.path.join(log_folder(), "crashes")`
- `app/crashreport.py:81` `os.path.join` — `p = os.path.join(log_folder(), settings.LOG_NAME)`
- `app/crashreport.py:115` `os.path.join` — `os.remove(os.path.join(d, n))`
- `app/crashreport.py:130` `os.path.join` — `path = os.path.join(d, name)`
- `app/crashreport.py:167` `os.path.join` — `seen_p = os.path.join(d, "seen.json")`
- `app/crashreport.py:238` `os.path.join` — `return [os.path.join(d, n) for n in names[:newest]]`

#### `app/dashboard.py`

- `app/dashboard.py:55` `os.path.join` — `PROJECT_FILE = os.path.join(".quantisheet", "project.json")`
- `app/dashboard.py:63` `os.path.join` — `return os.path.join(d, "project.json") if d else \`
- `app/dashboard.py:64` `os.path.join` — `os.path.join(folder, PROJECT_FILE)`

#### `app/dashboard_ui.py`

- `app/dashboard_ui.py:827` `os.path.join` — `subs = [os.path.join(f, n) for n in sorted(os.listdir(f))`
- `app/dashboard_ui.py:828` `os.path.join` — `if os.path.isdir(os.path.join(f, n)) and`
- `app/dashboard_ui.py:829` `os.path.join` — `os.path.isfile(db.project_file(os.path.join(f, n)))]`

#### `app/databackup.py`

- `app/databackup.py:51` `os.path.join` — `return os.path.join(os.environ["LOCALAPPDATA"],`
- `app/databackup.py:53` `os.path.join` — `return os.path.join(os.path.expanduser("~"), ".quantisheet_backoffice")`
- `app/databackup.py:111` `os.path.join` — `full = os.path.join(dirpath, fn)`
- `app/databackup.py:116` `os.path.join` — `tmp = os.path.join(tmpdir, f"db{n}")`
- `app/databackup.py:150` `os.path.join` — `safety = os.path.join(safety_dir or os.path.dirname(`
- `app/databackup.py:163` `os.path.join` — `dest = os.path.normpath(os.path.join(root, rel))`
- `app/databackup.py:178` `os.path.join` — `docs = os.path.join(os.path.expanduser("~"), "Documents")`
- `app/databackup.py:179` `os.path.join` — `return os.path.join(docs, "QuantiSheet Backups")`
- `app/databackup.py:194` `os.path.join` — `out = os.path.join(folder, name)`
- `app/databackup.py:202` `os.path.join` — `os.remove(os.path.join(folder, f))`

#### `app/diagnostics.py`

- `app/diagnostics.py:120` `os.path.join` — `p = os.path.join(d, name)`

#### `app/dropbox_sync.py`

- `app/dropbox_sync.py:145` `os.path.join` — `p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `app/dropbox_sync.py:300` `os.path.join` — `return os.path.join(settings.DIR, WORK_DIR)`
- `app/dropbox_sync.py:310` `os.path.join` — `return os.path.join(work_root(), *parts)`
- `app/dropbox_sync.py:325` `os.path.join` — `return os.path.join(work_root(), LINKS_DIR, h + ".json")`
- `app/dropbox_sync.py:372` `os.path.join` — `return os.path.join(settings.DIR, name)`
- `app/dropbox_sync.py:428` `os.path.join` — `os.remove(os.path.join(settings.DIR, name))`

#### `app/energy.py`

- `app/energy.py:17` `os.path.join` — `FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`

#### `app/esign.py`

- `app/esign.py:160` `os.path.join` — `return os.path.join(settings.DIR, REGISTRY)`

#### `app/estimating/_io.py`

- `app/estimating/_io.py:71` `os.path.join` — `p = os.path.abspath(os.path.join(base, *[str(x) for x in parts]))`

#### `app/estimating/service.py`

- `app/estimating/service.py:29` `os.path.join` — `return os.path.join(settings.DIR, FILE_NAME)`

#### `app/estimating/starters.py`

- `app/estimating/starters.py:289` `os.path.join` — `p = os.path.join(where, templates._file_name(t["name"])) if where \`

#### `app/estimating/templates.py`

- `app/estimating/templates.py:47` `os.path.join` — `return os.path.join(settings.DIR, "estimate_templates")`
- `app/estimating/templates.py:148` `os.path.join` — `p = os.path.join(where, f)`

#### `app/estimating/ui.py`

- `app/estimating/ui.py:71` `os.path.join` — `start = name if os.path.isabs(name) else os.path.join(_data_dir(), name)`

#### `app/filedialogs.py`

- `app/filedialogs.py:24` `os.path.join` — `return os.path.join(settings.last_dir(), d) # not the install folder`

#### `app/formlib.py`

- `app/formlib.py:30` `os.path.join` — `path = os.path.join(settings.DIR, "forms")`
- `app/formlib.py:36` `os.path.join` — `return os.path.join(folder(), INDEX)`
- `app/formlib.py:86` `os.path.join` — `rel = os.path.relpath(os.path.join(dp, f), root)`
- `app/formlib.py:91` `os.path.join` — `info = inspect(os.path.join(root, rel))`
- `app/formlib.py:103` `os.path.join` — `if os.path.exists(os.path.join(root, e["file"]))]`
- `app/formlib.py:115` `os.path.join` — `return os.path.join(folder(), entry["file"])`
- `app/formlib.py:124` `os.path.join` — `dest_dir = os.path.join(folder(), cat)`
- `app/formlib.py:126` `os.path.join` — `dest = os.path.join(dest_dir, _safe(name) + ".pdf")`
- `app/formlib.py:129` `os.path.join` — `dest = os.path.join(dest_dir, f"{_safe(name)} ({n}).pdf")`
- `app/formlib.py:139` `os.path.join` — `keep = os.path.join(dest_dir, "originals")`
- `app/formlib.py:141` `os.path.join` — `source = os.path.join(keep, os.path.basename(path))`
- `app/formlib.py:165` `os.path.join` — `new_dir = os.path.join(folder(), cat)`
- `app/formlib.py:167` `os.path.join` — `new = os.path.join(new_dir, os.path.basename(e["file"]))`
- `app/formlib.py:168` `os.path.join` — `shutil.move(os.path.join(folder(), e["file"]), new)`
- `app/formlib.py:185` `os.path.join` — `os.remove(os.path.join(folder(), e["file"]))`

#### `app/formlib_ui.py`

- `app/formlib_ui.py:197` `os.path.join` — `added.append(formlib.add(os.path.join(dp, f), cat))`

#### `app/genset/draw.py`

- `app/genset/draw.py:34` `os.path.join` — `reg = os.path.join(_WIN, "arial.ttf")`
- `app/genset/draw.py:35` `os.path.join` — `bold = os.path.join(_WIN, "arialbd.ttf")`

#### `app/heavy.py`

- `app/heavy.py:32` `os.path.join` — `STARTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`

#### `app/helpcenter.py`

- `app/helpcenter.py:1205` `os.path.join` — `return os.path.join(settings.DIR, "Practice Drawings.pdf")`

#### `app/invite_boost.py`

- `app/invite_boost.py:103` `os.path.join` — `p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `app/invite_boost.py:294` `os.path.join` — `path = os.path.join(self.folder, f"{n + 1:04d}-{safe}.eml")`
- `app/invite_boost.py:297` `os.path.join` — `with open(os.path.join(self.folder, "log.jsonl"), "a",`

#### `app/issue_report.py`

- `app/issue_report.py:84` `os.path.join` — `zpath = os.path.join(folder, f"QuantiSheet-issue-{stamp}.zip")`
- `app/issue_report.py:85` `os.path.join` — `bundle = diagnostics.bundle(os.path.join(folder, "bundle.zip"))`
- `app/issue_report.py:104` `os.path.join` — `shot = os.path.join(folder, "screenshot.png")`

#### `app/jobsafe.py`

- `app/jobsafe.py:92` `os.path.join` — `return os.path.join(settings.DIR, BACKUP_DIR)`
- `app/jobsafe.py:101` `os.path.join` — `return os.path.join(_dir(), _key(path) + ".json")`
- `app/jobsafe.py:139` `os.path.join` — `with open(os.path.join(_dir(), fn), encoding="utf-8") as f:`
- `app/jobsafe.py:198` `os.path.join` — `return os.path.join(d, f"~${n}.qslock")`

#### `app/locfactors.py`

- `app/locfactors.py:52` `os.path.join` — `path = os.path.join(SHIPPED, names[-1])`

#### `app/main.py`

- `app/main.py:31` `os.path.join` — `return os.path.join(os.path.expandvars(it), user)`
- `app/main.py:44` `os.path.join` — `probe = os.path.join(log_dir, ".write-test")`
- `app/main.py:52` `os.path.join` — `path = os.path.join(log_dir, settings.LOG_NAME)`
- `app/main.py:58` `os.path.join` — `crash = os.path.join(log_dir, "crash.log")`
- `app/main.py:324` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `app/main.py:325` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `app/main.py:369` `os.path.join` — `path = practice.make(os.path.join(tempfile.mkdtemp(prefix="quantisheet-smoke-"),`
- `app/main.py:413` `os.path.join` — `out = os.path.join(tempfile.mkdtemp(prefix="quantisheet-smoke-"),`
- `app/main.py:522` `os.path.join` — `path = os.path.join(base, "splash.png")`
- `app/main.py:552` `os.path.join` — `path = os.path.join(base, name)`

#### `app/main_window.py`

- `app/main_window.py:201` `os.path.join` — `t = os.path.join(os.path.dirname(doc_path), t)`
- `app/main_window.py:2773` `os.path.join` — `folder = os.path.join(folder, os.path.basename(base))`
- `app/main_window.py:2781` `os.path.join` — `os.path.join(folder, "Drawings", f"{name} - Combined Set.pdf"))`
- `app/main_window.py:2906` `os.path.join` — `self, "Back Up My QuantiSheet Data", os.path.join(`
- `app/main_window.py:3256` `os.path.join` — `cmd = [sys.executable, os.path.join(os.path.dirname(`
- `app/main_window.py:3729` `os.path.join` — `path = os.path.join(os.path.dirname(os.path.abspath(__file__)),`
- `app/main_window.py:4530` `os.path.join` — `self._tab.suggest = os.path.join(os.path.dirname(src), name) \`
- `app/main_window.py:4795` `os.path.join` — `tmp = os.path.join(tempfile.mkdtemp(prefix="quantisheet-recover-"),`
- `app/main_window.py:5835` `os.path.join` — `cur = os.path.join(tmpdir, "current.pdf")`
- `app/main_window.py:5836` `os.path.join` — `out = os.path.join(tmpdir, "comparison.pdf")`
- `app/main_window.py:6896` `os.path.join` — `self, "Save Support Bundle", os.path.join(`
- `app/main_window.py:6947` `os.path.join` — `args = f'"{os.path.join(root, "quantisheet.py")}" printer --install'`
- `app/main_window.py:7466` `os.path.join` — `start = os.path.join(os.path.dirname(self._path) if`
- `app/main_window.py:7908` `os.path.join` — `cur = os.path.join(tempfile.mkdtemp(prefix="quantisheet-cmp-"),`

#### `app/name_memory.py`

- `app/name_memory.py:48` `os.path.join` — `return os.path.join(os.path.dirname(pricedb.path()), FILENAME)`
- `app/name_memory.py:51` `os.path.join` — `return os.path.join(settings.DIR, LOCAL)`

#### `app/ocr.py`

- `app/ocr.py:24` `os.path.join` — `cand = os.path.join(base, "Tesseract-OCR", "tesseract.exe")`

#### `app/oldnames.py`

- `app/oldnames.py:189` `os.path.join` — `base = os.environ.get("LOCALAPPDATA") or os.path.join(`
- `app/oldnames.py:191` `os.path.join` — `p = os.path.join(base, LOCAL_DIR_OLD, ".seen")`
- `app/oldnames.py:198` `os.path.join` — `new = os.path.join(folder, JOB_DIR_NEW)`
- `app/oldnames.py:199` `os.path.join` — `old = os.path.join(folder, JOB_DIR_OLD)`
- `app/oldnames.py:215` `os.path.join` — `p = os.path.join(folder, name)`

#### `app/packaged.py`

- `app/packaged.py:50` `os.path.join` — `p = os.path.join(folder, name)`

#### `app/packages.py`

- `app/packages.py:163` `os.path.join` — `return os.path.join(settings.DIR, "packages.json")`

#### `app/packages_live.py`

- `app/packages_live.py:49` `os.path.join` — `return os.path.join(settings.DIR, "carrier_keys.json")`

#### `app/panels.py`

- `app/panels.py:196` `os.path.join` — `out = os.path.join(tempfile.mkdtemp(prefix="qs-pages-"),`

#### `app/pdfa.py`

- `app/pdfa.py:38` `os.path.join` — `for p in sorted(glob.glob(os.path.join(base, "gs", "gs*", "bin",`
- `app/pdfa.py:40` `os.path.join` — `glob.glob(os.path.join(base, "gs", "gs*", "bin",`
- `app/pdfa.py:193` `os.path.join` — `src = os.path.join(tmp, "in.pdf")`

#### `app/pm/actions.py`

- `app/pm/actions.py:530` `os.path.join` — `folder = os.path.join(ctx.store.folder, "Pay Applications")`
- `app/pm/actions.py:533` `os.path.join` — `path = os.path.join(folder, report_file_name(`
- `app/pm/actions.py:1212` `os.path.join` — `path = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),`
- `app/pm/actions.py:1223` `os.path.join` — `path = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),`

#### `app/pm/bidforms.py`

- `app/pm/bidforms.py:112` `os.path.join` — `return os.path.join(settings.DIR, "bid_forms.json")`

#### `app/pm/bidletters.py`

- `app/pm/bidletters.py:161` `os.path.join` — `tmp = os.path.join(store.folder, ".pm_letters")`
- `app/pm/bidletters.py:168` `os.path.join` — `p = os.path.join(tmp, f"{no} Award - {safe(winner.get('company'))}.pdf")`
- `app/pm/bidletters.py:184` `os.path.join` — `p = os.path.join(tmp, f"{no} Regret - "`

#### `app/pm/center.py`

- `app/pm/center.py:551` `os.path.join` — `self, "Save PDF", os.path.join(self.store.folder,`
- `app/pm/center.py:817` `os.path.join` — `os.path.join(self.store.folder, name),`
- `app/pm/center.py:856` `os.path.join` — `self, "Bidding Reports", os.path.join(`
- `app/pm/center.py:1149` `os.path.join` — `self, "Export", os.path.join(self.store.folder, name),`

#### `app/pm/costui.py`

- `app/pm/costui.py:137` `os.path.join` — `self, "Save PDF", os.path.join(`
- `app/pm/costui.py:148` `os.path.join` — `self, "Export for Sage 300", os.path.join(`

#### `app/pm/docsui.py`

- `app/pm/docsui.py:179` `os.path.join` — `p = os.path.join(dp, fn)`
- `app/pm/docsui.py:190` `os.path.join` — `d = os.path.join(os.path.dirname(self.store.path), "docs", f"v{v}")`
- `app/pm/docsui.py:192` `os.path.join` — `return os.path.join(d, name)`

#### `app/pm/master/apply.py`

- `app/pm/master/apply.py:36` `os.path.join` — `d = os.path.join(os.path.dirname(store.path), "master", "received")`
- `app/pm/master/apply.py:72` `os.path.join` — `q = os.path.join(quarantine_dir(store), sha + ext)`
- `app/pm/master/apply.py:504` `os.path.join` — `return os.path.join(store.folder, p) if p else None`
- `app/pm/master/apply.py:512` `os.path.join` — `dst = os.path.join(folder, name)`
- `app/pm/master/apply.py:515` `os.path.join` — `dst = os.path.join(folder, f"{base} ({k}){ext}")`

#### `app/pm/master/dropbox_inbox.py`

- `app/pm/master/dropbox_inbox.py:48` `os.path.join` — `return os.path.join(os.path.dirname(store.path), "master_inbox")`
- `app/pm/master/dropbox_inbox.py:64` `os.path.join` — `return os.path.join(mirror_dir(store), JOURNAL)`
- `app/pm/master/dropbox_inbox.py:159` `os.path.join` — `if os.path.isfile(os.path.join(folder, sub, name)):`
- `app/pm/master/dropbox_inbox.py:174` `os.path.join` — `reason = os.path.join(folder, dest, name + ".reason.txt")`
- `app/pm/master/dropbox_inbox.py:221` `os.path.join` — `dest = _free(os.path.join(mirror_dir(store),`
- `app/pm/master/dropbox_inbox.py:240` `os.path.join` — `ob = os.path.join(base, comp, "Outbox")`
- `app/pm/master/dropbox_inbox.py:244` `os.path.join` — `p = os.path.join(ob, name)`

#### `app/pm/master/intake.py`

- `app/pm/master/intake.py:139` `os.path.join` — `dst = apply.copy_out(path, os.path.join(folder, "Processed"), name)`
- `app/pm/master/intake.py:145` `os.path.join` — `dst = apply.copy_out(path, os.path.join(folder, "Rejected"), name)`
- `app/pm/master/intake.py:151` `os.path.join` — `apply.copy_out(path, os.path.join(folder, "Processed"), name)`
- `app/pm/master/intake.py:174` `os.path.join` — `d = os.path.join(inbox, safe_name(c), "Outbox")`
- `app/pm/master/intake.py:176` `os.path.join` — `p = os.path.join(d, safe_name(f"{store.name} - {c} - schedule "`

#### `app/pm/owner_report.py`

- `app/pm/owner_report.py:362` `os.path.join` — `return os.path.join(settings.DIR, TEMPLATE_FILE)`
- `app/pm/owner_report.py:406` `os.path.join` — `dest = os.path.join(settings.DIR, name)`
- `app/pm/owner_report.py:3078` `os.path.join` — `folder = folder or os.path.join(store.folder, "Reports", "Owner")`
- `app/pm/owner_report.py:3079` `os.path.join` — `path = os.path.join(folder, file_name(rep))`

#### `app/pm/owner_report_logs.py`

- `app/pm/owner_report_logs.py:145` `os.path.join` — `if base and os.path.isdir(os.path.join(base, "app", "data", "fonts")):`
- `app/pm/owner_report_logs.py:146` `os.path.join` — `return os.path.join(base, "app", "data", "fonts")`
- `app/pm/owner_report_logs.py:147` `os.path.join` — `return os.path.join(os.path.dirname(os.path.dirname(`
- `app/pm/owner_report_logs.py:158` `os.path.join` — `with open(os.path.join(font_dir(), name), "rb") as f:`

#### `app/pm/owner_report_ui.py`

- `app/pm/owner_report_ui.py:1338` `os.path.join` — `path = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),`
- `app/pm/owner_report_ui.py:1471` `os.path.join` — `path = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),`

#### `app/pm/photofit.py`

- `app/pm/photofit.py:253` `os.path.join` — `cache = os.path.join(store.att_dir(), "cache")`
- `app/pm/photofit.py:258` `os.path.join` — `hit = os.path.join(cache, key)`

#### `app/pm/productivity.py`

- `app/pm/productivity.py:473` `os.path.join` — `return os.path.join(settings.DIR, FILE)`

#### `app/pm/project_backup.py`

- `app/pm/project_backup.py:37` `os.path.join` — `os.path.join(base, d)))`
- `app/pm/project_backup.py:39` `os.path.join` — `p = os.path.join(base, f)`
- `app/pm/project_backup.py:123` `os.path.join` — `dest = os.path.join(work, *rel.split("/"))`
- `app/pm/project_backup.py:128` `os.path.join` — `if _sha(os.path.join(work, *rel.split("/"))) != info["sha256"]:`

#### `app/pm/recovery.py`

- `app/pm/recovery.py:679` `os.path.join` — `tmp = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"), "g.pdf")`

#### `app/pm/recovery_ui.py`

- `app/pm/recovery_ui.py:620` `os.path.join` — `os.path.join(self.store.folder, name),`

#### `app/pm/report.py`

- `app/pm/report.py:414` `os.path.join` — `return record_pdf(store, key, rec, os.path.join(d, name + ".pdf"))`

#### `app/pm/scheduler.py`

- `app/pm/scheduler.py:47` `os.path.join` — `DEFAULT_FOLDER = os.path.join(os.path.expanduser("~"), "Documents",`
- `app/pm/scheduler.py:953` `os.path.join` — `self, "Save PDF", os.path.join(self.store.folder, name),`
- `app/pm/scheduler.py:998` `os.path.join` — `self, title, os.path.join(self.store.folder, name),`
- `app/pm/scheduler.py:1101` `os.path.join` — `folder = os.path.join(DEFAULT_FOLDER, safe)`
- `app/pm/scheduler.py:1104` `os.path.join` — `folder = os.path.join(DEFAULT_FOLDER, f"{safe} ({k})")`

#### `app/pm/scheduleui.py`

- `app/pm/scheduleui.py:516` `os.path.join` — `os.path.join(self.store.folder, name),`
- `app/pm/scheduleui.py:593` `os.path.join` — `os.path.join(self.store.folder, name),`
- `app/pm/scheduleui.py:607` `os.path.join` — `os.path.join(self.store.folder, name),`

#### `app/pm/scope_sheet_ui.py`

- `app/pm/scope_sheet_ui.py:1736` `os.path.join` — `os.path.join(self._default_dir(), name),`
- `app/pm/scope_sheet_ui.py:1785` `os.path.join` — `os.path.join(self._default_dir(), base),`

#### `app/pm/store.py`

- `app/pm/store.py:25` `os.path.join` — `FILE = os.path.join(".quantisheet", "project.json")`
- `app/pm/store.py:111` `os.path.join` — `self.path = os.path.join(data_dir, os.path.basename(FILE))`
- `app/pm/store.py:185` `os.path.join` — `path = os.path.join(os.path.abspath(folder), FILE)`
- `app/pm/store.py:195` `os.path.join` — `os.path.join(old, os.path.basename(FILE)))`
- `app/pm/store.py:625` `os.path.join` — `d = os.path.join(os.path.dirname(self.path), "attachments")`
- `app/pm/store.py:640` `os.path.join` — `local = os.path.join(self.att_dir(), sha + ext)`
- `app/pm/store.py:669` `os.path.join` — `local = os.path.join(self.att_dir(), ref["sha256"] +`

#### `app/pm/submittals.py`

- `app/pm/submittals.py:81` `os.path.join` — `d = os.path.join(store.folder, "Submittals")`
- `app/pm/submittals.py:83` `os.path.join` — `return os.path.join(d, safe(f"{number(rec)} - {rec.get('title', '')}")`

#### `app/pm/widgets.py`

- `app/pm/widgets.py:553` `os.path.join` — `local = os.path.join(self.store.att_dir(),`

#### `app/policy.py`

- `app/policy.py:74` `os.path.join` — `"_qs_updatecheck", os.path.join(os.path.dirname(`
- `app/policy.py:167` `os.path.join` — `return r"C:\ProgramData" if os.name == "nt" else os.path.join(`
- `app/policy.py:183` `os.path.join` — `return os.path.join(_program_data(), DATA_DIR)`
- `app/policy.py:246` `os.path.join` — `path = os.path.join(data_dir(), POLICY_FILE)`

#### `app/prebid_ui.py`

- `app/prebid_ui.py:19` `os.path.join` — `return os.path.join(os.path.dirname(name), report_file_name(`

#### `app/preflight.py`

- `app/preflight.py:243` `os.path.join` — `src = os.path.join(tmp, "in.pdf")`

#### `app/pricedb.py`

- `app/pricedb.py:157` `os.path.join` — `return p if p else os.path.join(settings.DIR, "prices.db")`
- `app/pricedb.py:162` `os.path.join` — `return os.path.join(folder, FILENAME)`
- `app/pricedb.py:166` `os.path.join` — `return os.path.join(settings.DIR, "prices-local-copy.db")`
- `app/pricedb.py:653` `os.path.join` — `return os.path.join(settings.DIR, "pricedb_seen.json")`
- `app/pricedb.py:992` `os.path.join` — `with open(os.path.join(folder, n), encoding="utf-8") as f:`
- `app/pricedb.py:1008` `os.path.join` — `os.remove(os.path.join(folder, f))`
- `app/pricedb.py:1015` `os.path.join` — `folder = os.path.join(os.path.dirname(path()), "Price backups")`
- `app/pricedb.py:1017` `os.path.join` — `dest = os.path.join(folder, _dt.datetime.now().strftime(`

#### `app/printhelper.py`

- `app/printhelper.py:42` `os.path.join` — `SPOOL_DIR = os.path.join(_PROGRAM_DATA, "QuantiSheet", "print", "spool")`
- `app/printhelper.py:43` `os.path.join` — `PORT = os.path.join(SPOOL_DIR, "job.pdf")`
- `app/printhelper.py:47` `os.path.join` — `SUBFOLDER = os.path.join("QuantiSheet", "Printed")`
- `app/printhelper.py:72` `os.path.join` — `p, k = os.path.join(folder, name), 2`
- `app/printhelper.py:74` `os.path.join` — `p = os.path.join(folder, f"{base} ({k}){ext}")`
- `app/printhelper.py:103` `os.path.join` — `w = os.path.join(d, "pythonw.exe")`
- `app/printhelper.py:113` `os.path.join` — `return f'"{_windowless(exe)}" "{os.path.join(root, "quantisheet.py")}" ' \`
- `app/printhelper.py:123` `os.path.join` — `return [_windowless(sys.executable), os.path.join(root, "quantisheet.py"),`
- `app/printhelper.py:232` `os.path.join` — `return os.path.join(os.path.expanduser("~"), "Documents")`
- `app/printhelper.py:433` `os.path.join` — `return os.path.join(brand_paths.local_dir(), "print-helper.log")`

#### `app/project_ui.py`

- `app/project_ui.py:95` `os.path.join` — `os.path.join(base, name), filt)`

#### `app/quickaccess.py`

- `app/quickaccess.py:678` `os.path.join` — `p = os.path.join(folder, f)`

#### `app/review.py`

- `app/review.py:111` `os.path.join` — `return os.path.join(settings.DIR, FEEDBACK_FILE)`

#### `app/sealed_contacts.py`

- `app/sealed_contacts.py:13` `os.path.join` — `FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`

#### `app/sets.py`

- `app/sets.py:39` `os.path.join` — `os.path.join(base, path))`
- `app/sets.py:255` `os.path.join` — `bdir = os.path.join(base, f"_before {label} {stamp}".strip()) \`
- `app/sets.py:293` `os.path.join` — `shutil.copy2(path, os.path.join(bdir, os.path.basename(path)))`
- `app/sets.py:337` `os.path.join` — `dest = os.path.join(base, f"{label} - new sheets.pdf")`

#### `app/sets_ui.py`

- `app/sets_ui.py:112` `os.path.join` — `self, "Save Set As", os.path.join(`

#### `app/settings.py`

- `app/settings.py:17` `os.path.join` — `DIR = os.path.join(os.path.expanduser("~"), DIR_NAME)`
- `app/settings.py:18` `os.path.join` — `PATH = os.path.join(DIR, "settings.json")`
- `app/settings.py:144` `os.path.join` — `for c in ("Desktop", "Documents", os.path.join("OneDrive", "Desktop"),`
- `app/settings.py:145` `os.path.join` — `os.path.join("OneDrive", "Documents")):`
- `app/settings.py:146` `os.path.join` — `if os.path.isdir(os.path.join(home, c)):`
- `app/settings.py:147` `os.path.join` — `return os.path.join(home, c)`

#### `app/shellverbs.py`

- `app/shellverbs.py:61` `os.path.join` — `return sorted((os.path.join(folder, n) for n in os.listdir(folder)`
- `app/shellverbs.py:63` `os.path.join` — `os.path.isfile(os.path.join(folder, n))),`

#### `app/sign/signer.py`

- `app/sign/signer.py:85` `os.path.join` — `key_path = path or os.path.join(DEFAULT_DIR, "signing_key.pem")`

#### `app/specrisk_ui.py`

- `app/specrisk_ui.py:112` `os.path.join` — `path = os.path.join(folder, self.review_name())`
- `app/specrisk_ui.py:137` `os.path.join` — `path = path or os.path.join(tempfile.mkdtemp(prefix="qs_risk_"),`

#### `app/specs.py`

- `app/specs.py:298` `os.path.join` — `p = os.path.join(folder, name)`

#### `app/storeupdate.py`

- `app/storeupdate.py:91` `os.path.join` — `exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),`

#### `app/subdir.py`

- `app/subdir.py:49` `os.path.join` — `return os.path.join(settings.DIR, FILE)`

#### `app/subdir_ui.py`

- `app/subdir_ui.py:323` `os.path.join` — `path = os.path.join(tempfile.gettempdir(),`

#### `app/syspaths.py`

- `app/syspaths.py:19` `os.path.join` — `return os.path.join(root, "System32", *parts)`

#### `app/theme.py`

- `app/theme.py:107` `os.path.join` — `d = os.path.join(tempfile.gettempdir(), f"quantisheet-theme-{n}")`
- `app/theme.py:122` `os.path.join` — `p = os.path.join(d, k + ".svg")`

#### `app/timelog.py`

- `app/timelog.py:26` `os.path.join` — `return os.path.join(settings.DIR, "timelog.json")`

#### `app/toolchest.py`

- `app/toolchest.py:29` `os.path.join` — `PATH = os.path.join(settings.DIR, "toolchest.json")`

#### `app/updatecheck.py`

- `app/updatecheck.py:241` `os.path.join` — `with open(os.path.join(betalicense._data_dir(), PUBKEY_FILE),`
- `app/updatecheck.py:409` `os.path.join` — `here = os.path.join(os.path.dirname(os.path.abspath(__file__)),`
- `app/updatecheck.py:460` `os.path.join` — `base = os.environ.get("LOCALAPPDATA") or os.path.join(`
- `app/updatecheck.py:462` `os.path.join` — `return os.path.join(base, "QuantiSheet", "updates")`
- `app/updatecheck.py:469` `os.path.join` — `return os.path.join(folder or download_dir(),`
- `app/updatecheck.py:619` `os.path.join` — `best = (v, os.path.join(folder, n))`
- `app/updatecheck.py:638` `os.path.join` — `os.remove(os.path.join(folder, n))`

#### `app/versions.py`

- `app/versions.py:28` `os.path.join` — `p = os.path.join(_vdir(path), "index.json")`
- `app/versions.py:41` `os.path.join` — `final = os.path.join(_vdir(path), "index.json")`
- `app/versions.py:53` `os.path.join` — `with open(os.path.join(_vdir(path), fname), "wb") as f:`
- `app/versions.py:89` `os.path.join` — `return os.path.join(_vdir(path), name)`

#### `quantisheet_backoffice/__main__.py`

- `quantisheet_backoffice/__main__.py:55` `os.path.join` — `path = os.path.join(folder, "crash.log")`

#### `quantisheet_backoffice/backup.py`

- `quantisheet_backoffice/backup.py:68` `os.path.join` — `dest = os.path.join(folder, f"backoffice-{stamp}{EXT}")`
- `quantisheet_backoffice/backup.py:72` `os.path.join` — `dest = os.path.join(folder, f"backoffice-{stamp}-{n}{EXT}")`
- `quantisheet_backoffice/backup.py:124` `os.path.join` — `return sorted(os.path.join(folder, f) for f in os.listdir(folder)`
- `quantisheet_backoffice/backup.py:213` `os.path.join` — `live = os.path.join(folder, "backoffice.sqlite")`
- `quantisheet_backoffice/backup.py:233` `os.path.join` — `db = DB(os.path.join(folder, "backoffice.sqlite"))`

#### `quantisheet_backoffice/cards.py`

- `quantisheet_backoffice/cards.py:61` `os.path.join` — `dest = store.copy_into(os.path.join(office.documents_folder(),`

#### `quantisheet_backoffice/certified.py`

- `quantisheet_backoffice/certified.py:175` `os.path.join` — `folder = os.path.join(office.output_folder(), "certified")`

#### `quantisheet_backoffice/crypto.py`

- `quantisheet_backoffice/crypto.py:75` `os.path.join` — `self.path = os.path.join(folder, "datakey.bin")`

#### `quantisheet_backoffice/exports.py`

- `quantisheet_backoffice/exports.py:333` `os.path.join` — `folder = folder or os.path.join(office.output_folder(), "exports")`

#### `quantisheet_backoffice/fileguard.py`

- `quantisheet_backoffice/fileguard.py:72` `os.path.join` — `target = os.path.realpath(os.path.join(base, subdir, safe_name(name)))`

#### `quantisheet_backoffice/host_tests/conftest.py`

- `quantisheet_backoffice/host_tests/conftest.py:16` `os.path.join` — `TESTS = os.path.join(ROOT, "tests")`
- `quantisheet_backoffice/host_tests/conftest.py:24` `os.path.join` — `"_quantisheet_tests_conftest", os.path.join(TESTS, "conftest.py"))`

#### `quantisheet_backoffice/host_tests/test_backoffice_hook.py`

- `quantisheet_backoffice/host_tests/test_backoffice_hook.py:21` `os.path.join` — `REAL_DIR = os.path.join(os.path.expanduser("~"), ".quantisheet")`

#### `quantisheet_backoffice/hr.py`

- `quantisheet_backoffice/hr.py:195` `os.path.join` — `folder = os.path.join(office.documents_folder(), "hr")`
- `quantisheet_backoffice/hr.py:197` `os.path.join` — `dest = os.path.join(folder, secrets.token_hex(12) + ".bin")`

#### `quantisheet_backoffice/ocr.py`

- `quantisheet_backoffice/ocr.py:46` `os.path.join` — `p = os.path.join(d, name)`
- `quantisheet_backoffice/ocr.py:160` `os.path.join` — `img = os.path.join(tmp, "page1.png")`

#### `quantisheet_backoffice/office.py`

- `quantisheet_backoffice/office.py:23` `os.path.join` — `self.db = DB(os.path.join(self.folder, "backoffice.sqlite"))`
- `quantisheet_backoffice/office.py:65` `os.path.join` — `store.owner_only(os.path.join(self.folder, f))`
- `quantisheet_backoffice/office.py:167` `os.path.join` — `return os.path.join(self.folder, "documents")`
- `quantisheet_backoffice/office.py:170` `os.path.join` — `return os.path.join(self.folder, "output")`

#### `quantisheet_backoffice/provider.py`

- `quantisheet_backoffice/provider.py:155` `os.path.join` — `folder = os.path.join(office.output_folder(), "payroll")`

#### `quantisheet_backoffice/r111/apdrop.py`

- `quantisheet_backoffice/r111/apdrop.py:126` `os.path.join` — `path = os.path.join(fold["path"], name)`

#### `quantisheet_backoffice/r111/apstamp.py`

- `quantisheet_backoffice/r111/apstamp.py:54` `os.path.join` — `folder = os.path.join(office.documents_folder(), "stamps")`

#### `quantisheet_backoffice/r111/paykeys.py`

- `quantisheet_backoffice/r111/paykeys.py:53` `os.path.join` — `base = os.path.join(home, "keys")`
- `quantisheet_backoffice/r111/paykeys.py:54` `os.path.join` — `path = os.path.join(base, digest)`
- `quantisheet_backoffice/r111/paykeys.py:56` `os.path.join` — `path = os.path.join(home, "keys", digest)`
- `quantisheet_backoffice/r111/paykeys.py:61` `os.path.join` — `return os.path.join(slot, "seal.bin")`
- `quantisheet_backoffice/r111/paykeys.py:65` `os.path.join` — `return os.path.join(slot, "key.bin")`
- `quantisheet_backoffice/r111/paykeys.py:126` `os.path.join` — `path = os.path.join(company_folder, "datakey.bin")`
- `quantisheet_backoffice/r111/paykeys.py:134` `os.path.join` — `path = os.path.join(company_folder, "datakey.bin")`
- `quantisheet_backoffice/r111/paykeys.py:144` `os.path.join` — `return True, os.path.join(settings.home(), "keys", name)`
- `quantisheet_backoffice/r111/paykeys.py:173` `os.path.join` — `path = os.path.join(company_folder, name)`
- `quantisheet_backoffice/r111/paykeys.py:185` `os.path.join` — `while os.path.exists(os.path.join(slot, f"key.retired-{n}")):`
- `quantisheet_backoffice/r111/paykeys.py:188` `os.path.join` — `_write_file(os.path.join(slot, f"legacy-{name}"), raw)`
- `quantisheet_backoffice/r111/paykeys.py:195` `os.path.join` — `_write_file(os.path.join(slot, name), b"sealed1:" + _fernet(seal).encrypt(key))`
- `quantisheet_backoffice/r111/paykeys.py:226` `os.path.join` — `legacy = os.path.join(company_folder, "datakey.bin")`
- `quantisheet_backoffice/r111/paykeys.py:237` `os.path.join` — `_write_file(os.path.join(slot, "legacy-datakey.bin"), raw)`
- `quantisheet_backoffice/r111/paykeys.py:268` `os.path.join` — `out.append(_open_sealed_path(os.path.join(slot, n), slot,`
- `quantisheet_backoffice/r111/paykeys.py:315` `os.path.join` — `while os.path.exists(os.path.join(slot, f"key.retired-{n}")):`
- `quantisheet_backoffice/r111/paykeys.py:317` `os.path.join` — `os.replace(live, os.path.join(slot, f"key.retired-{n}"))`
- `quantisheet_backoffice/r111/paykeys.py:516` `os.path.join` — `slot = slot_dir(os.path.join(data_dir, "server-key"))`
- `quantisheet_backoffice/r111/paykeys.py:518` `os.path.join` — `live = os.path.join(slot, "server.key")`
- `quantisheet_backoffice/r111/paykeys.py:519` `os.path.join` — `legacy = os.path.join(data_dir, "server.key")`

#### `quantisheet_backoffice/remote.py`

- `quantisheet_backoffice/remote.py:265` `os.path.join` — `folder = os.path.join(office.documents_folder(), "punch_photos")`
- `quantisheet_backoffice/remote.py:267` `os.path.join` — `photo = os.path.join(folder, hashlib.sha256(remote_id.encode())`

#### `quantisheet_backoffice/server/app.py`

- `quantisheet_backoffice/server/app.py:32` `os.path.join` — `STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")`
- `quantisheet_backoffice/server/app.py:79` `os.path.join` — `self.db = sqlite3.connect(os.path.join(data_dir, "selfservice.sqlite"),`
- `quantisheet_backoffice/server/app.py:167` `os.path.join` — `with open(os.path.join(STATIC, name), encoding="utf-8") as fh:`

#### `quantisheet_backoffice/settings.py`

- `quantisheet_backoffice/settings.py:29` `os.path.join` — `return (os.path.realpath(os.path.join(home, ".quantisheet")),)`
- `quantisheet_backoffice/settings.py:49` `os.path.join` — `h = os.path.join(os.environ["LOCALAPPDATA"], "QuantiSheetBackOffice")`
- `quantisheet_backoffice/settings.py:51` `os.path.join` — `h = os.path.join(os.path.expanduser("~"), ".quantisheet_backoffice")`
- `quantisheet_backoffice/settings.py:56` `os.path.join` — `return os.path.join(home(), "settings.json")`
- `quantisheet_backoffice/settings.py:92` `os.path.join` — `f = get("data_folder") or os.path.join(home(), "data")`
- `quantisheet_backoffice/settings.py:97` `os.path.join` — `f = get("backup_folder") or os.path.join(home(), "backups")`
- `quantisheet_backoffice/settings.py:102` `os.path.join` — `return os.path.join(data_folder(), "backoffice.sqlite")`

#### `quantisheet_backoffice/store.py`

- `quantisheet_backoffice/store.py:569` `os.path.join` — `sysdir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),`

#### `quantisheet_backoffice/timeoff.py`

- `quantisheet_backoffice/timeoff.py:364` `os.path.join` — `folder = os.path.join(office.output_folder(), "reports")`

#### `quantisheet_backoffice/wip.py`

- `quantisheet_backoffice/wip.py:120` `os.path.join` — `folder = os.path.join(office.output_folder(), "reports")`

#### `quantisheet_claims/export.py`

- `quantisheet_claims/export.py:648` `os.path.join` — `return os.path.join(settings.exports_folder(),`

#### `quantisheet_claims/photos.py`

- `quantisheet_claims/photos.py:26` `os.path.join` — `return os.path.join(base, _safe_name(claim.claim_number) + ".photos")`
- `quantisheet_claims/photos.py:30` `os.path.join` — `return os.path.join(folder_for(claim, folder), photo.sha256 + photo.ext)`

#### `quantisheet_claims/settings.py`

- `quantisheet_claims/settings.py:45` `os.path.join` — `return (os.path.realpath(os.path.join(home, ".quantisheet")),)`
- `quantisheet_claims/settings.py:67` `os.path.join` — `h = os.path.join(os.environ["APPDATA"], APP_DIR)`
- `quantisheet_claims/settings.py:69` `os.path.join` — `h = os.path.join(os.path.expanduser("~"), DOT_DIR)`
- `quantisheet_claims/settings.py:79` `os.path.join` — `return os.path.join(home(), "settings.json")`
- `quantisheet_claims/settings.py:84` `os.path.join` — `return os.path.join(home(), "prices.json")`
- `quantisheet_claims/settings.py:108` `os.path.join` — `plain = os.path.join(home_, "Documents")`
- `quantisheet_claims/settings.py:109` `os.path.join` — `if os.path.isdir(os.path.join(plain, DOCS_DIR)):`
- `quantisheet_claims/settings.py:124` `os.path.join` — `f = os.path.join(home(), "Claims")`
- `quantisheet_claims/settings.py:126` `os.path.join` — `f = os.path.join(_documents(), DOCS_DIR)`
- `quantisheet_claims/settings.py:135` `os.path.join` — `return os.path.join(claims_folder(), "Exports")`

#### `quantisheet_claims/store.py`

- `quantisheet_claims/store.py:77` `os.path.join` — `return os.path.join(folder, _safe_name(claim.claim_number) + ".claim.json")`
- `quantisheet_claims/store.py:84` `os.path.join` — `bdir = os.path.join(os.path.dirname(p), ".backup")`
- `quantisheet_claims/store.py:87` `os.path.join` — `shutil.copy2(p, os.path.join(bdir, f"{os.path.basename(p)}.{stamp}"))`
- `quantisheet_claims/store.py:91` `os.path.join` — `os.unlink(os.path.join(bdir, x))`

#### `quantisheet_claims/ui/workspace.py`

- `quantisheet_claims/ui/workspace.py:667` `os.path.join` — `bdir = os.path.join(os.path.dirname(old), ".backup")`
- `quantisheet_claims/ui/workspace.py:669` `os.path.join` — `os.replace(old, os.path.join(bdir, os.path.basename(old) + "." +`

#### `server/hub.py`

- `server/hub.py:126` `os.path.join` — `sp = os.path.join(self.dir, "secret")`
- `server/hub.py:139` `os.path.join` — `full = os.path.realpath(os.path.join(base, *parts))`
- `server/hub.py:198` `os.path.join` — `meta = self._load(os.path.join(self._env_dir(env_id), "meta.json"))`
- `server/hub.py:204` `os.path.join` — `self._save(os.path.join(self._env_dir(meta["id"]), "meta.json"), meta)`
- `server/hub.py:266` `os.path.join` — `with open(os.path.join(d, f"p{n}.png"), "wb") as f:`
- `server/hub.py:367` `os.path.join` — `index = self._load(os.path.join(root, "tokens.json"), {})`
- `server/hub.py:377` `os.path.join` — `p = os.path.join(root, name, "meta.json")`
- `server/hub.py:382` `os.path.join` — `self._save(os.path.join(root, "tokens.json"), index)`
- `server/hub.py:647` `os.path.join` — `mp = os.path.join(d, "meta.json")`
- `server/hub.py:668` `os.path.join` — `os.makedirs(os.path.join(d, "files"), exist_ok=True)`
- `server/hub.py:1005` `os.path.join` — `data = self._load(os.path.join(d, name), {"items": {}})`
- `server/hub.py:1517` `os.path.join` — `p = os.path.join(self._env_dir(meta["id"]),`

#### `server/relay_server.py`

- `server/relay_server.py:49` `os.path.join` — `sys.path.insert(0, os.path.join(os.path.dirname(`
- `server/relay_server.py:66` `os.path.join` — `WEB_DIR = os.environ.get("WEB_DIR") or os.path.join(`
- `server/relay_server.py:78` `os.path.join` — `os.path.join(os.path.dirname(`

#### `server/relaycore.py`

- `server/relaycore.py:345` `os.path.join` — `full = os.path.realpath(os.path.join(base, path.lstrip("/\\")))`

#### `tools/ada_index.py`

- `tools/ada_index.py:15` `os.path.join` — `SRC = os.path.join(HERE, "data", "ada", "pages.json")`
- `tools/ada_index.py:16` `os.path.join` — `OUT = os.path.join(HERE, "app", "data", "ada2010.json")`

#### `tools/aerial_live.py`

- `tools/aerial_live.py:35` `os.path.join` — `out = os.path.join(ROOT, ".run", "aerial_live.pdf")`

#### `tools/ai_takeoff_compare.py`

- `tools/ai_takeoff_compare.py:21` `os.path.join` — `OUT = os.path.join(ROOT, ".run", "ai_takeoff_compare")`
- `tools/ai_takeoff_compare.py:75` `os.path.join` — `if not os.path.isfile(os.path.join(old, "app", "aitakeoff.py")):`
- `tools/ai_takeoff_compare.py:78` `os.path.join` — `pdf = os.path.join(tmp, "plans.pdf")`

#### `tools/ai_takeoff_gui.py`

- `tools/ai_takeoff_gui.py:11` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tests"))`
- `tools/ai_takeoff_gui.py:12` `os.path.join` — `LOG = os.path.join(ROOT, ".run", "ai_takeoff_gui.log")`

#### `tools/ai_takeoff_run.py`

- `tools/ai_takeoff_run.py:12` `os.path.join` — `LOG = os.path.join(ROOT, ".run", "ai_takeoff_run.log")`

#### `tools/aiken_eval.py`

- `tools/aiken_eval.py:71` `os.path.join` — `XLSX_REL = os.path.join("QuantiSheet Takeoff",`
- `tools/aiken_eval.py:73` `os.path.join` — `MAP = os.path.join(ROOT, "tools", "aiken_map.json")`
- `tools/aiken_eval.py:85` `os.path.join` — `xlsx=os.path.join("QuantiSheet Takeoff",`
- `tools/aiken_eval.py:87` `os.path.join` — `map=os.path.join(ROOT, "tools", "colleton_map.json")),`
- `tools/aiken_eval.py:135` `os.path.join` — `base = os.environ.get("LOCALAPPDATA") or os.path.join(`
- `tools/aiken_eval.py:137` `os.path.join` — `return os.path.join(base, "QuantiSheetWork", SET)`
- `tools/aiken_eval.py:152` `os.path.join` — `dst = os.path.join(dst_dir, os.path.basename(src))`
- `tools/aiken_eval.py:614` `os.path.join` — `write_csv(os.path.join(out_dir, "score_groups.csv"), grows, gcols)`
- `tools/aiken_eval.py:630` `os.path.join` — `write_csv(os.path.join(out_dir, "score_items.csv"), irows,`
- `tools/aiken_eval.py:632` `os.path.join` — `write_csv(os.path.join(out_dir, "unmapped_ai.csv"), added, LINE_COLS)`
- `tools/aiken_eval.py:633` `os.path.join` — `write_csv(os.path.join(out_dir, "ai_lines.csv"), lines,`
- `tools/aiken_eval.py:641` `os.path.join` — `write_csv(os.path.join(out_dir, "submittals.csv"), props,`
- `tools/aiken_eval.py:673` `os.path.join` — `out_dir = args.out or os.path.join(work, "out")`
- `tools/aiken_eval.py:675` `os.path.join` — `card = os.path.join(out_dir, "scorecard.txt")`
- `tools/aiken_eval.py:685` `os.path.join` — `with open(os.path.join(out_dir, "console.txt"), "w") as con:`
- `tools/aiken_eval.py:695` `os.path.join` — `xlsx = args.xlsx or os.path.join(args.src, XLSX_REL)`
- `tools/aiken_eval.py:700` `os.path.join` — `lines_csv = os.path.join(out_dir, "ai_lines.csv")`
- `tools/aiken_eval.py:703` `os.path.join` — `if os.path.exists(os.path.join(out_dir, "meta.json")):`
- `tools/aiken_eval.py:704` `os.path.join` — `meta = json.load(open(os.path.join(out_dir, "meta.json")))`
- `tools/aiken_eval.py:709` `os.path.join` — `pdf, c1 = copy_in(os.path.join(args.src, DRAWINGS), work)`
- `tools/aiken_eval.py:712` `os.path.join` — `spec, c2 = copy_in(os.path.join(args.src, SPEC), work)`
- `tools/aiken_eval.py:713` `os.path.join` — `log = Log(os.path.join(out_dir, "run_log.txt"))`
- `tools/aiken_eval.py:728` `os.path.join` — `with open(os.path.join(out_dir, "summary.txt"), "w",`
- `tools/aiken_eval.py:731` `os.path.join` — `with open(os.path.join(out_dir, "problems.txt"), "w",`
- `tools/aiken_eval.py:734` `os.path.join` — `with open(os.path.join(out_dir, "checks.txt"), "w",`
- `tools/aiken_eval.py:745` `os.path.join` — `os.path.join(out_dir, "estimate_workbook.xlsx"),`
- `tools/aiken_eval.py:750` `os.path.join` — `write_csv(os.path.join(out_dir, "review.csv"), res["review"],`
- `tools/aiken_eval.py:752` `os.path.join` — `write_csv(os.path.join(out_dir, "existing.csv"), res["existing"],`
- `tools/aiken_eval.py:754` `os.path.join` — `write_csv(os.path.join(out_dir, "unfinished.csv"),`
- `tools/aiken_eval.py:760` `os.path.join` — `write_csv(os.path.join(out_dir, "sheets.csv"), srows,`
- `tools/aiken_eval.py:775` `os.path.join` — `with open(os.path.join(out_dir, "meta.json"), "w") as f:`

#### `tools/aiken_fetch.py`

- `tools/aiken_fetch.py:7` `os.path.join` — `src = os.path.join(os.environ.get("LOCALAPPDATA", ""), "QuantiSheetWork",`
- `tools/aiken_fetch.py:9` `os.path.join` — `dst = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),`
- `tools/aiken_fetch.py:15` `os.path.join` — `shutil.copy2(os.path.join(src, f), os.path.join(dst, f))`
- `tools/aiken_fetch.py:15` `os.path.join` — `shutil.copy2(os.path.join(src, f), os.path.join(dst, f))`

#### `tools/autoscale_compare.py`

- `tools/autoscale_compare.py:17` `os.path.join` — `SRC = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop",`

#### `tools/autoscale_profile.py`

- `tools/autoscale_profile.py:16` `os.path.join` — `SRC = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop",`

#### `tools/backup_folder.py`

- `tools/backup_folder.py:21` `os.path.join` — `dest = os.path.join(os.path.expanduser("~"),`
- `tools/backup_folder.py:34` `os.path.join` — `pricedb.backup(os.path.join(dest, "prices-backup.db"))`

#### `tools/beta_keys.py`

- `tools/beta_keys.py:24` `os.path.join` — `KEYS = os.environ.get("QUANTISHEET_KEYS") or os.path.join(`
- `tools/beta_keys.py:26` `os.path.join` — `PRIV = os.path.join(KEYS, "beta_signing_key.pem")`
- `tools/beta_keys.py:27` `os.path.join` — `LOG = os.path.join(KEYS, "issued_keys.csv")`
- `tools/beta_keys.py:28` `os.path.join` — `PUB = os.path.join(ROOT, "app", "data", "beta_pubkey.txt")`
- `tools/beta_keys.py:60` `os.path.join` — `with open(os.path.join(KEYS, "README.txt"), "w") as f:`
- `tools/beta_keys.py:92` `os.path.join` — `path = os.path.join(KEYS, f"Key - {safe or info['k']}.txt")`

#### `tools/bigset.py`

- `tools/bigset.py:103` `os.path.join` — `os.path.join(tmp, f"bigset-{n}.pdf")`
- `tools/bigset.py:151` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/bigset.py:152` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "s.json")`

#### `tools/build_installer.py`

- `tools/build_installer.py:30` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/build_installer.py:35` `os.path.join` — `BUILD = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser(`
- `tools/build_installer.py:37` `os.path.join` — `RELEASE = os.path.join(ROOT, "release")`
- `tools/build_installer.py:38` `os.path.join` — `GITHUB = os.path.join(RELEASE, "github") # builds for outside`
- `tools/build_installer.py:39` `os.path.join` — `LOG = os.path.join(ROOT, ".run", "build_installer.log")`
- `tools/build_installer.py:40` `os.path.join` — `STATUS = os.path.join(ROOT, ".run", "build_installer.status")`
- `tools/build_installer.py:70` `os.path.join` — `cands = [os.path.join(os.environ.get(v, ""), "Inno Setup 6", "ISCC.exe")`
- `tools/build_installer.py:72` `os.path.join` — `cands.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",`
- `tools/build_installer.py:86` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/build_installer.py:93` `os.path.join` — `os.path.join(app_dir, "**", "app", "data", "beta_pubkey.txt"),`
- `tools/build_installer.py:96` `os.path.join` — `with open(os.path.join(data, "build.json"), "w", encoding="utf-8") as f:`
- `tools/build_installer.py:110` `os.path.join` — `for f in glob.glob(os.path.join(pub, "**", "contacts.sealed"),`
- `tools/build_installer.py:115` `os.path.join` — `for f in glob.glob(os.path.join(pub, "**", name), recursive=True):`
- `tools/build_installer.py:118` `os.path.join` — `found = glob.glob(os.path.join(pub, "**", "app", "data",`
- `tools/build_installer.py:125` `os.path.join` — `with open(os.path.join(data, "build.json"), "w", encoding="utf-8") as f:`
- `tools/build_installer.py:127` `os.path.join` — `bad = [f for f in glob.glob(os.path.join(pub, "**", "*"), recursive=True)`
- `tools/build_installer.py:144` `os.path.join` — `ans = os.path.join(BUILD, "public_version.json")`
- `tools/build_installer.py:147` `os.path.join` — `rc, out = sh([os.path.join(pub, branding.EXE), "version", "--out",`
- `tools/build_installer.py:197` `os.path.join` — `for f in glob.glob(os.path.join(root, "**", "*"), recursive=True):`
- `tools/build_installer.py:230` `os.path.join` — `for base, dirs, files in os.walk(os.path.join(ROOT, d)):`
- `tools/build_installer.py:232` `os.path.join` — `out += [os.path.relpath(os.path.join(base, f), ROOT)`
- `tools/build_installer.py:235` `os.path.join` — `"splash.png") if os.path.exists(os.path.join(ROOT, f))]`
- `tools/build_installer.py:244` `os.path.join` — `os.path.join(ROOT, "installer", "wizard-side.bmp"),`
- `tools/build_installer.py:245` `os.path.join` — `os.path.join(ROOT, "installer", "wizard-small.bmp"),`
- `tools/build_installer.py:246` `os.path.join` — `os.path.join(ROOT, "splash.png"),`
- `tools/build_installer.py:267` `os.path.join` — `exe = os.path.join(BUILD, "innosetup.exe")`
- `tools/build_installer.py:276` `os.path.join` — `out = os.path.join(BUILD, "smoke.json")`
- `tools/build_installer.py:303` `os.path.join` — `with open(os.path.join(ROOT, "quantisheet_claims", "__init__.py"),`
- `tools/build_installer.py:312` `os.path.join` — `spec = os.path.join(ROOT, "quantisheet_claims.spec")`
- `tools/build_installer.py:313` `os.path.join` — `iss = os.path.join(ROOT, "installer", "quantisheet_claims.iss")`
- `tools/build_installer.py:319` `os.path.join` — `src = os.path.join(dist, "ClaimIT")`
- `tools/build_installer.py:323` `os.path.join` — `os.path.join(work, "claims"), spec], timeout=3600)`
- `tools/build_installer.py:324` `os.path.join` — `exe = os.path.join(src, "ClaimIT.exe")`
- `tools/build_installer.py:342` `os.path.join` — `out = os.path.join(RELEASE, base + ".exe")`
- `tools/build_installer.py:355` `os.path.join` — `p = os.path.join(ROOT, "installer", "version_info.txt")`
- `tools/build_installer.py:379` `os.path.join` — `private = [f for f in glob.glob(os.path.join(ROOT, "app", "**", "*"),`
- `tools/build_installer.py:412` `os.path.join` — `ship_check.require_no_local_only(os.path.join(ROOT, "app", "data"),`
- `tools/build_installer.py:414` `os.path.join` — `if not os.path.exists(os.path.join(ROOT, "app", "data",`
- `tools/build_installer.py:422` `os.path.join` — `dist, work = os.path.join(BUILD, "dist"), os.path.join(BUILD, "work")`
- `tools/build_installer.py:422` `os.path.join` — `dist, work = os.path.join(BUILD, "dist"), os.path.join(BUILD, "work")`
- `tools/build_installer.py:429` `os.path.join` — `os.path.join(ROOT, "quantisheet.spec")], timeout=3600)`
- `tools/build_installer.py:430` `os.path.join` — `app_dir = os.path.join(dist, DIST_NAME)`
- `tools/build_installer.py:431` `os.path.join` — `exe = os.path.join(app_dir, branding.EXE)`
- `tools/build_installer.py:436` `os.path.join` — `os.path.join(app_dir, "**", "*"), recursive=True)`
- `tools/build_installer.py:444` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/build_installer.py:477` `os.path.join` — `os.path.join(ROOT, "installer", iss)], timeout=3600)`
- `tools/build_installer.py:478` `os.path.join` — `made.append(os.path.join(out_dir, base + ".exe"))`
- `tools/build_installer.py:480` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/build_installer.py:485` `os.path.join` — `msi = os.path.join(out_dir, f"{base}-{__version__}.msi")`
- `tools/build_installer.py:550` `os.path.join` — `out = build_claims(iscc, os.path.join(BUILD, "dist"),`
- `tools/build_installer.py:551` `os.path.join` — `os.path.join(BUILD, "work"),`

#### `tools/build_msix.py`

- `tools/build_msix.py:25` `os.path.join` — `BUILD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "QuantiSheetBuild")`
- `tools/build_msix.py:26` `os.path.join` — `SRC = os.path.join(BUILD, "dist", "QuantiSheet-public")`
- `tools/build_msix.py:27` `os.path.join` — `LAYOUT = os.path.join(BUILD, "msix", "layout")`
- `tools/build_msix.py:28` `os.path.join` — `OUT_DIR = os.path.join(ROOT, "release", "msix")`
- `tools/build_msix.py:29` `os.path.join` — `IDENTITY = os.path.join(ROOT, "installer", "msix_identity.json")`
- `tools/build_msix.py:51` `os.path.join` — `STORE_SPLASH = os.path.join(ROOT, "splash_store.png")`
- `tools/build_msix.py:61` `os.path.join` — `found = glob.glob(os.path.join(layout, "**", "splash.png"),`
- `tools/build_msix.py:73` `os.path.join` — `found = glob.glob(os.path.join(layout, "**", "app", "data",`
- `tools/build_msix.py:168` `os.path.join` — `src = Image.open(os.path.join(ROOT, "icon.png")).convert("RGBA")`
- `tools/build_msix.py:176` `os.path.join` — `canvas.save(os.path.join(dest, name))`
- `tools/build_msix.py:193` `os.path.join` — `_logos(os.path.join(LAYOUT, "Assets"))`
- `tools/build_msix.py:196` `os.path.join` — `with open(os.path.join(LAYOUT, "AppxManifest.xml"), "w",`
- `tools/build_msix.py:204` `os.path.join` — `out = os.path.join(OUT_DIR, f"QuantiSheet-{V}.msix")`

#### `tools/check_detect.py`

- `tools/check_detect.py:10` `os.path.join` — `PS1 = os.path.join(ROOT, "installer", "it", "Detect-QuantiSheet.ps1")`
- `tools/check_detect.py:11` `os.path.join` — `PS32 = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "SysWOW64",`

#### `tools/check_installer.py`

- `tools/check_installer.py:20` `os.path.join` — `glob.glob(os.path.join(ROOT, "release", "QuantiSheet-Beta-Setup-*.exe")),`
- `tools/check_installer.py:22` `os.path.join` — `target = os.path.join(tempfile.gettempdir(), "QuantiSheetInstallCheck")`
- `tools/check_installer.py:27` `os.path.join` — `"/TASKS=", "/NOICONS", "/LOG=" + os.path.join(`
- `tools/check_installer.py:31` `os.path.join` — `exe = os.path.join(target, "QuantiSheet.exe")`
- `tools/check_installer.py:33` `os.path.join` — `print("no agreement (1.0.0):", not os.path.exists(os.path.join(`
- `tools/check_installer.py:35` `os.path.join` — `print("extras script:", os.path.exists(os.path.join(`
- `tools/check_installer.py:37` `os.path.join` — `out = os.path.join(tempfile.gettempdir(), "quantisheet-installed-smoke.json")`
- `tools/check_installer.py:49` `os.path.join` — `un = sorted(glob.glob(os.path.join(target, "unins*.exe")))`

#### `tools/check_msi.py`

- `tools/check_msi.py:20` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/check_msi.py:70` `os.path.join` — `log = os.path.join(tmp, "admin.log")`
- `tools/check_msi.py:71` `os.path.join` — `target = os.path.join(tmp, "unpacked")`
- `tools/check_msi.py:90` `os.path.join` — `a = os.path.join(dirpath, f)`
- `tools/check_msi.py:91` `os.path.join` — `b = os.path.join(inst, os.path.relpath(a, app_dir))`
- `tools/check_msi.py:103` `os.path.join` — `print(" extra", extra, os.path.exists(os.path.join(inst,`

#### `tools/check_paykey_move.py`

- `tools/check_paykey_move.py:25` `os.path.join` — `db = os.path.join(folder, "backoffice.sqlite")`
- `tools/check_paykey_move.py:34` `os.path.join` — `key = os.path.join(src, "datakey.bin")`
- `tools/check_paykey_move.py:43` `os.path.join` — `home = os.path.join(tmp, "home")`
- `tools/check_paykey_move.py:44` `os.path.join` — `copy = os.path.join(home, "company-copy")`
- `tools/check_paykey_move.py:47` `os.path.join` — `s = sqlite3.connect(os.path.join(src, "backoffice.sqlite"))`
- `tools/check_paykey_move.py:48` `os.path.join` — `d = sqlite3.connect(os.path.join(copy, "backoffice.sqlite"))`
- `tools/check_paykey_move.py:53` `os.path.join` — `shutil.copy2(key, os.path.join(copy, "datakey.bin"))`
- `tools/check_paykey_move.py:64` `os.path.join` — `moved = open(os.path.join(copy, "datakey.bin"), "rb").read(7)`
- `tools/check_paykey_move.py:66` `os.path.join` — `con = sqlite3.connect(os.path.join(copy, "backoffice.sqlite"))`

#### `tools/check_settings_test_marks.py`

- `tools/check_settings_test_marks.py:9` `os.path.join` — `P = os.path.join(os.path.expanduser("~"), ".quantisheet", "settings.json")`

#### `tools/civil_bid.py`

- `tools/civil_bid.py:21` `os.path.join` — `RUN = os.path.join(ROOT, ".run")`
- `tools/civil_bid.py:29` `os.path.join` — `settings.PATH = os.path.join(tmp, "s.json")`
- `tools/civil_bid.py:140` `os.path.join` — `job, lib, os.path.join(RUN, f"civil_bid_{name}.xlsx")))`
- `tools/civil_bid.py:143` `os.path.join` — `out = os.path.join(RUN, "civil_bid.pdf")`

#### `tools/claim_sample.py`

- `tools/claim_sample.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tests"))`
- `tools/claim_sample.py:14` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/claim_sample.py:15` `os.path.join` — `settings.PATH = os.path.join(tmp, "cfg", "s.json")`

#### `tools/clean_settings_test_recent.py`

- `tools/clean_settings_test_recent.py:10` `os.path.join` — `P = os.path.join(os.path.expanduser("~"), ".quantisheet", "settings.json")`

#### `tools/click_everything.py`

- `tools/click_everything.py:20` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/click_everything.py:65` `os.path.join` — `prog_path = os.path.join(ROOT, ".run", f"click_progress_{pi}of{pn}.txt")`
- `tools/click_everything.py:73` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/click_everything.py:74` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "s.json")`
- `tools/click_everything.py:109` `os.path.join` — `path = os.path.join(tmp, "job.pdf")`

#### `tools/climate_index.py`

- `tools/climate_index.py:13` `os.path.join` — `SRC = os.path.join(HERE, "data", "energy", "pages.json")`
- `tools/climate_index.py:14` `os.path.join` — `OUT = os.path.join(HERE, "app", "data", "climate_zones_2021.json")`

#### `tools/codesign.py`

- `tools/codesign.py:26` `os.path.join` — `KEYS = os.path.join(os.path.expanduser("~"), "QuantiSheet Keys")`
- `tools/codesign.py:27` `os.path.join` — `CONFIG = os.path.join(KEYS, "codesign.json")`
- `tools/codesign.py:51` `os.path.join` — `hits = sorted(glob.glob(os.path.join(base, "*", "x64",`

#### `tools/crash_seen.py`

- `tools/crash_seen.py:15` `os.path.join` — `crash = os.path.join(log_folder(), "crash.log")`
- `tools/crash_seen.py:19` `os.path.join` — `seen_p = os.path.join(crashreport.folder(), "seen.json")`

#### `tools/crash_wrap.py`

- `tools/crash_wrap.py:20` `os.path.join` — `script = os.path.join(ROOT, "tools", args[0] + ".py")`

#### `tools/crop.py`

- `tools/crop.py:35` `os.path.join` — `out = os.path.join(ROOT, ".run", f"crop_{pno + 1}{tag}.png")`

#### `tools/deps_check.py`

- `tools/deps_check.py:7` `os.path.join` — `ps1 = os.path.join(ROOT, "tools", "install_deps.ps1")`

#### `tools/diag.py`

- `tools/diag.py:3` `os.path.join` — `sys.path.insert(0, root); sys.path.insert(0, os.path.join(root, "tests"))`
- `tools/diag.py:8` `os.path.join` — `assemblies.LIBRARY_PATH = os.path.join(root, "trial", "_lib.json")`
- `tools/diag.py:11` `os.path.join` — `trial = os.path.join(root, "trial")`
- `tools/diag.py:12` `os.path.join` — `for f in glob.glob(os.path.join(trial, "proposal_*")) + glob.glob(os.path.join(trial, "_w*.png")):`
- `tools/diag.py:12` `os.path.join` — `for f in glob.glob(os.path.join(trial, "proposal_*")) + glob.glob(os.path.join(trial, "_w*.png")):`
- `tools/diag.py:14` `os.path.join` — `logo = os.path.join(trial, "_logo.png")`
- `tools/diag.py:27` `os.path.join` — `pdf.save(os.path.join(trial, f"proposal_{detail}.pdf"))`
- `tools/diag.py:29` `os.path.join` — `pg.get_pixmap(dpi=80).save(os.path.join(trial, f"proposal_{detail}_{i+1}.png"))`

#### `tools/diag_aiken_actgrid.py`

- `tools/diag_aiken_actgrid.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_actgrid.py:18` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`
- `tools/diag_aiken_actgrid.py:65` `os.path.join` — `out = os.path.join(ROOT, ".work", "diag", f"{num}_act.png")`

#### `tools/diag_aiken_compete.py`

- `tools/diag_aiken_compete.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_compete.py:16` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_crop.py`

- `tools/diag_aiken_crop.py:9` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_crop.py:18` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`
- `tools/diag_aiken_crop.py:27` `os.path.join` — `out = os.path.join(ROOT, ".work", "diag", f"{num}_crop.png")`

#### `tools/diag_aiken_devlegend.py`

- `tools/diag_aiken_devlegend.py:9` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_devlegend.py:17` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_ductcrop.py`

- `tools/diag_aiken_ductcrop.py:11` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_ductcrop.py:21` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`
- `tools/diag_aiken_ductcrop.py:75` `os.path.join` — `out = os.path.join(ROOT, ".work", "diag",`

#### `tools/diag_aiken_ducts.py`

- `tools/diag_aiken_ducts.py:12` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_ducts.py:19` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`
- `tools/diag_aiken_ducts.py:65` `os.path.join` — `out = os.path.join(ROOT, ".work", "diag", f"{num}_ducts.png")`

#### `tools/diag_aiken_fills.py`

- `tools/diag_aiken_fills.py:9` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_fills.py:18` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_groups.py`

- `tools/diag_aiken_groups.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_groups.py:14` `os.path.join` — `f = os.path.join(aiken_eval.work_dir(), "out", "score_groups.csv")`

#### `tools/diag_aiken_legend.py`

- `tools/diag_aiken_legend.py:8` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_legend.py:14` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_linetypes.py`

- `tools/diag_aiken_linetypes.py:9` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_linetypes.py:16` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_lod.py`

- `tools/diag_aiken_lod.py:12` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_lod.py:19` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_piperuns.py`

- `tools/diag_aiken_piperuns.py:11` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_piperuns.py:19` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_pipes.py`

- `tools/diag_aiken_pipes.py:9` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_pipes.py:16` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`
- `tools/diag_aiken_pipes.py:72` `os.path.join` — `out = os.path.join(ROOT, ".work", "diag", f"{num}_pipes.png")`

#### `tools/diag_aiken_probe.py`

- `tools/diag_aiken_probe.py:9` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_probe.py:18` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_rotlegend.py`

- `tools/diag_aiken_rotlegend.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_rotlegend.py:17` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_rows.py`

- `tools/diag_aiken_rows.py:11` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_rows.py:19` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_scale.py`

- `tools/diag_aiken_scale.py:9` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_scale.py:17` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_sched.py`

- `tools/diag_aiken_sched.py:9` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_sched.py:16` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`
- `tools/diag_aiken_sched.py:42` `os.path.join` — `out = os.path.join(ROOT, ".work", "diag", f"{num}_sched.png")`

#### `tools/diag_aiken_sf.py`

- `tools/diag_aiken_sf.py:11` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_sf.py:19` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`
- `tools/diag_aiken_sf.py:66` `os.path.join` — `out = os.path.join(ROOT, ".work", "diag", f"{num}_sf.png")`

#### `tools/diag_aiken_stage3.py`

- `tools/diag_aiken_stage3.py:11` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_stage3.py:20` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_tags.py`

- `tools/diag_aiken_tags.py:9` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_tags.py:16` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_text.py`

- `tools/diag_aiken_text.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_text.py:18` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_wallasm.py`

- `tools/diag_aiken_wallasm.py:9` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_wallasm.py:15` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_aiken_walls.py`

- `tools/diag_aiken_walls.py:18` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_walls.py:35` `os.path.join` — `pdf = os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS)`
- `tools/diag_aiken_walls.py:38` `os.path.join` — `out_dir = os.path.join(ROOT, ".work", "diag")`
- `tools/diag_aiken_walls.py:107` `os.path.join` — `outp = os.path.join(out_dir, f"{num}_t{autowalls.MAX_T_IN:g}"`

#### `tools/diag_aiken_walltypes.py`

- `tools/diag_aiken_walltypes.py:9` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_walltypes.py:15` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`
- `tools/diag_aiken_walltypes.py:55` `os.path.join` — `outp = os.path.join(ROOT, ".work", "diag", f"{num}_walltypes.png")`

#### `tools/diag_aiken_words.py`

- `tools/diag_aiken_words.py:11` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_aiken_words.py:20` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_autoscale.py`

- `tools/diag_autoscale.py:13` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_autoscale.py:19` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_crop_points.py`

- `tools/diag_crop_points.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_crop_points.py:19` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`
- `tools/diag_crop_points.py:24` `os.path.join` — `out = os.path.join(ROOT, ".run", "crops")`
- `tools/diag_crop_points.py:29` `os.path.join` — `f = os.path.join(out, f"{num}_{i}_{int(x)}_{int(y)}.png")`

#### `tools/diag_doors.py`

- `tools/diag_doors.py:14` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_doors.py:22` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_eval_lines.py`

- `tools/diag_eval_lines.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_eval_lines.py:15` `os.path.join` — `out = os.path.join(aiken_eval.work_dir(), "out")`
- `tools/diag_eval_lines.py:16` `os.path.join` — `con = os.path.join(out, "console.txt")`
- `tools/diag_eval_lines.py:22` `os.path.join` — `fp = os.path.join(out, nm)`
- `tools/diag_eval_lines.py:27` `os.path.join` — `f = os.path.join(out, "ai_lines.csv")`
- `tools/diag_eval_lines.py:38` `os.path.join` — `rv = os.path.join(out, "review.csv")`

#### `tools/diag_legend.py`

- `tools/diag_legend.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_legend.py:18` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_maximize_real.py`

- `tools/diag_maximize_real.py:20` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/diag_maximize_real.py:21` `os.path.join` — `settings.PATH = os.path.join(tmp, "cfg", "s.json")`

#### `tools/diag_pdfsched.py`

- `tools/diag_pdfsched.py:14` `os.path.join` — `for f in sorted(glob.glob(os.path.join(folder, "**", "*.pdf"),`

#### `tools/diag_ribbon_width.py`

- `tools/diag_ribbon_width.py:17` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/diag_ribbon_width.py:18` `os.path.join` — `settings.PATH = os.path.join(tmp, "cfg", "s.json")`

#### `tools/diag_sched_table.py`

- `tools/diag_sched_table.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_sched_table.py:18` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_sched_tags.py`

- `tools/diag_sched_tags.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_sched_tags.py:19` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_segs.py`

- `tools/diag_segs.py:16` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_segs.py:24` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`
- `tools/diag_segs.py:83` `os.path.join` — `out = os.path.join(ROOT, ".work", "diag", f"{num}_{orient}_{int(at)}.png")`

#### `tools/diag_tag_leaders.py`

- `tools/diag_tag_leaders.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_tag_leaders.py:18` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_tag_shapes.py`

- `tools/diag_tag_shapes.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/diag_tag_shapes.py:19` `os.path.join` — `doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))`

#### `tools/diag_textedit_dark.py`

- `tools/diag_textedit_dark.py:18` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/diag_textedit_dark.py:19` `os.path.join` — `settings.PATH = os.path.join(tmp, "cfg", "s.json")`
- `tools/diag_textedit_dark.py:36` `os.path.join` — `path = os.path.join(tmp, "doc.pdf")`
- `tools/diag_textedit_dark.py:70` `os.path.join` — `out = os.path.join(ROOT, ".run", "diag_textedit.png")`

#### `tools/docs_probe.py`

- `tools/docs_probe.py:24` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/docs_probe.py:25` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/docs_probe.py:33` `os.path.join` — `os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"))`

#### `tools/dxf_app_trial2.py`

- `tools/dxf_app_trial2.py:11` `os.path.join` — `OUT = os.path.join(ROOT, ".run", "dxf_trial")`
- `tools/dxf_app_trial2.py:12` `os.path.join` — `settings.DIR = os.path.join(OUT, "cfg"); settings.PATH = os.path.join(OUT, "cfg", "s.json"); settings._cache = None`
- `tools/dxf_app_trial2.py:12` `os.path.join` — `settings.DIR = os.path.join(OUT, "cfg"); settings.PATH = os.path.join(OUT, "cfg", "s.json"); settings._cache = None`
- `tools/dxf_app_trial2.py:17` `os.path.join` — `src = os.path.join(OUT, "src", "gdsestimating__api-cw750-details.dxf")`
- `tools/dxf_app_trial2.py:18` `os.path.join` — `pdf = os.path.join(OUT, "app_sheets.pdf")`
- `tools/dxf_app_trial2.py:42` `os.path.join` — `w.grab().save(os.path.join(OUT, f"APP_page{page + 1}.png"))`
- `tools/dxf_app_trial2.py:44` `os.path.join` — `out = w.export_dxf(os.path.join(OUT, "app_back.dxf"))`

#### `tools/fetch_ada.py`

- `tools/fetch_ada.py:13` `os.path.join` — `OUT = os.path.join(HERE, "data", "ada")`
- `tools/fetch_ada.py:14` `os.path.join` — `PDF = os.path.join(OUT, "2010-design-standards.pdf")`
- `tools/fetch_ada.py:42` `os.path.join` — `with open(os.path.join(OUT, "pages.json"), "w", encoding="utf-8") as f:`

#### `tools/fetch_climate.py`

- `tools/fetch_climate.py:14` `os.path.join` — `OUT = os.path.join(HERE, "data", "energy")`
- `tools/fetch_climate.py:15` `os.path.join` — `PDF = os.path.join(OUT, "climate-zone-by-county-2021.pdf")`
- `tools/fetch_climate.py:40` `os.path.join` — `with open(os.path.join(OUT, "pages.json"), "w", encoding="utf-8") as f:`

#### `tools/fetch_logs.py`

- `tools/fetch_logs.py:11` `os.path.join` — `out = os.path.join(ROOT, ".run", "logs")`
- `tools/fetch_logs.py:14` `os.path.join` — `p = os.path.join(settings.DIR, name)`
- `tools/fetch_logs.py:19` `os.path.join` — `with open(os.path.join(out, name), "wb") as f:`

#### `tools/find_home_writers.py`

- `tools/find_home_writers.py:14` `os.path.join` — `HOMES = [os.path.join(os.path.expanduser("~"), d)`
- `tools/find_home_writers.py:24` `os.path.join` — `p = os.path.join(h, name)`

#### `tools/find_in_backups.py`

- `tools/find_in_backups.py:12` `os.path.join` — `for b in sorted(glob.glob(os.path.join(home, "quantisheet-backup-*")) +`
- `tools/find_in_backups.py:13` `os.path.join` — `glob.glob(os.path.join(home, "pdfstudio-backup-*"))):`
- `tools/find_in_backups.py:15` `os.path.join` — `for f in glob.glob(os.path.join(b, sub, "**", "*.py"), recursive=True):`

#### `tools/find_sdk_tools.py`

- `tools/find_sdk_tools.py:14` `os.path.join` — `hits += glob.glob(os.path.join(base, "**", name), recursive=True)`

#### `tools/find_thumb_tools.py`

- `tools/find_thumb_tools.py:11` `os.path.join` — `for p in (os.path.join(win, r"Microsoft.NET\Framework64\v4.0.30319\csc.exe"),`
- `tools/find_thumb_tools.py:12` `os.path.join` — `os.path.join(win, r"Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe")):`
- `tools/find_thumb_tools.py:19` `os.path.join` — `w = glob.glob(os.path.join(win, "System32", "WinMetadata", "Windows.Data.winmd"))`
- `tools/find_thumb_tools.py:24` `os.path.join` — `rt = glob.glob(os.path.join(win, r"Microsoft.NET\Framework64\v4.0.30319",`

#### `tools/font_probe.py`

- `tools/font_probe.py:39` `os.path.join` — `p = os.path.join(r"C:\Windows\Fonts", fn)`

#### `tools/forms_add_aitem.py`

- `tools/forms_add_aitem.py:5` `os.path.join` — `src = os.path.join(ROOT, ".run", "forms_in", "Action Item List.pdf")`
- `tools/forms_add_aitem.py:9` `os.path.join` — `keep = os.path.join(formlib.folder(), "Project Management", "originals")`
- `tools/forms_add_aitem.py:11` `os.path.join` — `shutil.copyfile(os.path.join(ROOT, ".run", "forms_in", "Action Item List.xlsx"),`
- `tools/forms_add_aitem.py:12` `os.path.join` — `os.path.join(keep, "Action Item List.xlsx"))`

#### `tools/forms_check.py`

- `tools/forms_check.py:6` `os.path.join` — `out = os.path.join(ROOT, ".run", "forms_check"); os.makedirs(out, exist_ok=True)`
- `tools/forms_check.py:15` `os.path.join` — `d[0].get_pixmap(dpi=60).save(os.path.join(out, f"{e['name'][:20]}_{'clear' if clear else 'saved'}.png"))`

#### `tools/forms_install.py`

- `tools/forms_install.py:6` `os.path.join` — `SRC = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "PDF Attachments")`
- `tools/forms_install.py:41` `os.path.join` — `p = os.path.join(SRC, *rel.split("/"))`

#### `tools/forms_probe.py`

- `tools/forms_probe.py:4` `os.path.join` — `root = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "PDF Attachments")`
- `tools/forms_probe.py:10` `os.path.join` — `p = os.path.join(dp, f)`

#### `tools/genset_new_types.py`

- `tools/genset_new_types.py:23` `os.path.join` — `pdf = os.path.join(out, key + ".pdf")`

#### `tools/genset_preview.py`

- `tools/genset_preview.py:37` `os.path.join` — `pdf = os.path.join(out, key + ".pdf")`
- `tools/genset_preview.py:42` `os.path.join` — `pix.save(os.path.join(out, f"{key}_{doc[i].get_label()}.png"))`

#### `tools/genset_samples.py`

- `tools/genset_samples.py:26` `os.path.join` — `out = argv[0] if argv else os.path.join(ROOT, ".run", "genset")`
- `tools/genset_samples.py:34` `os.path.join` — `pdf = os.path.join(out, key + ".pdf")`
- `tools/genset_samples.py:64` `os.path.join` — `p.get_pixmap(dpi=40).save(os.path.join(out, f"{key}_{i+1}.png"))`

#### `tools/genset_text.py`

- `tools/genset_text.py:9` `os.path.join` — `p = sys.argv[1].strip('"') if len(sys.argv) > 1 else os.path.join(`

#### `tools/handles_probe.py`

- `tools/handles_probe.py:24` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/handles_probe.py:25` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/handles_probe.py:59` `os.path.join` — `path = os.path.join(TMP, "set.pdf")`
- `tools/handles_probe.py:88` `os.path.join` — `acrobat2.external_issue(v.doc, os.path.join(TMP, "ext.pdf"))`

#### `tools/help_screens.py`

- `tools/help_screens.py:10` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg"); settings.PATH = os.path.join(settings.DIR, "s.json"); settings._cache = None`
- `tools/help_screens.py:10` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg"); settings.PATH = os.path.join(settings.DIR, "s.json"); settings._cache = None`
- `tools/help_screens.py:13` `os.path.join` — `out = os.path.join(ROOT, ".run", "helpshots"); os.makedirs(out, exist_ok=True)`
- `tools/help_screens.py:18` `os.path.join` — `app.processEvents(); w.grab().save(os.path.join(out, n + ".png"))`

#### `tools/install_info.py`

- `tools/install_info.py:23` `os.path.join` — `p = os.path.join(d, n)`
- `tools/install_info.py:28` `os.path.join` — `for p in sorted(glob.glob(os.path.join(tmp, "Setup Log*.txt")) +`
- `tools/install_info.py:29` `os.path.join` — `glob.glob(os.path.join(tmp, "is-*")),`
- `tools/install_info.py:39` `os.path.join` — `for p in sorted(glob.glob(os.path.join(f, "*")), key=os.path.getmtime):`
- `tools/install_info.py:41` `os.path.join` — `for p in sorted(glob.glob(os.path.join(tmp, "Setup Log*.txt")),`

#### `tools/install_modulor.py`

- `tools/install_modulor.py:13` `os.path.join` — `ZIP = os.path.join(ROOT, "vendor", "modulor-40f6c2a.zip")`
- `tools/install_modulor.py:14` `os.path.join` — `SPIKE = os.path.join(ROOT, ".run", "modulor_spike", "modulor-40f6c2a.zip")`

#### `tools/install_release.py`

- `tools/install_release.py:17` `os.path.join` — `STATUS = os.path.join(ROOT, ".run", "build_installer.status")`
- `tools/install_release.py:48` `os.path.join` — `setup = os.path.join(ROOT, "release", f"QuantiSheet-Beta-Setup-{V}.exe")`
- `tools/install_release.py:51` `os.path.join` — `log = os.path.join(ROOT, ".run", "install_release.log")`
- `tools/install_release.py:76` `os.path.join` — `want = os.path.join(ROOT, "release", f"ClaimIT-Setup-{CV}.exe")`
- `tools/install_release.py:80` `os.path.join` — `glob.glob(os.path.join(ROOT, "release", "ClaimIT-Setup-*.exe")),`
- `tools/install_release.py:85` `os.path.join` — `"/LOG=" + os.path.join(ROOT, ".run",`
- `tools/install_release.py:88` `os.path.join` — `cexe = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",`

#### `tools/iscc_check.py`

- `tools/iscc_check.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/iscc_check.py:15` `os.path.join` — `src = os.path.join(os.environ.get("LOCALAPPDATA", ""), "QuantiSheetBuild",`
- `tools/iscc_check.py:21` `os.path.join` — `os.path.join(ROOT, "installer", name + ".iss")],`

#### `tools/legend_timing.py`

- `tools/legend_timing.py:17` `os.path.join` — `OUT = os.path.join(ROOT, ".run", "legend_timing.txt")`
- `tools/legend_timing.py:28` `os.path.join` — `pdf = os.path.join(tmp, "plans.pdf")`

#### `tools/log_tail.py`

- `tools/log_tail.py:13` `os.path.join` — `p = os.path.join(settings.DIR, settings.LOG_NAME)`

#### `tools/lookahead_sample.py`

- `tools/lookahead_sample.py:15` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/lookahead_sample.py:16` `os.path.join` — `settings.PATH = os.path.join(tmp, "cfg", "s.json")`
- `tools/lookahead_sample.py:17` `os.path.join` — `s = ProjectStore(os.path.join(tmp, "Station 9 Repairs"))`

#### `tools/make_admx.py`

- `tools/make_admx.py:10` `os.path.join` — `"policy", os.path.join(ROOT, "app", "policy.py"))`
- `tools/make_admx.py:160` `os.path.join` — `d = os.path.join(ROOT, "installer", "policy")`
- `tools/make_admx.py:161` `os.path.join` — `os.makedirs(os.path.join(d, "en-US"), exist_ok=True)`
- `tools/make_admx.py:162` `os.path.join` — `for path, lines in ((os.path.join(d, "QuantiSheet.admx"), admx),`
- `tools/make_admx.py:163` `os.path.join` — `(os.path.join(d, "en-US", "QuantiSheet.adml"), adml)):`

#### `tools/make_costsummary_golden.py`

- `tools/make_costsummary_golden.py:18` `os.path.join` — `real = os.path.realpath(os.path.join(os.path.expanduser("~"), _name))`
- `tools/make_costsummary_golden.py:92` `os.path.join` — `with open(os.path.join(out, "golden_costsummary.json"), "w") as fh:`
- `tools/make_costsummary_golden.py:94` `os.path.join` — `with open(os.path.join(out, "golden_snapshot.json"), "w") as fh:`

#### `tools/make_fix_diffs.py`

- `tools/make_fix_diffs.py:31` `os.path.join` — `a = read(os.path.join(backup, rel))`
- `tools/make_fix_diffs.py:32` `os.path.join` — `b = read(os.path.join(ROOT, rel))`

#### `tools/make_msi.py`

- `tools/make_msi.py:120` `os.path.join` — `exe = os.path.join(app_dir, EXE)`
- `tools/make_msi.py:135` `os.path.join` — `icon = os.path.join(ROOT, "icon.ico")`
- `tools/make_msi.py:181` `os.path.join` — `p = os.path.join(path, n)`
- `tools/make_msi.py:186` `os.path.join` — `p = os.path.join(path, n)`
- `tools/make_msi.py:195` `os.path.join` — `extra = {"docs": [os.path.join(ROOT, "docs", "IT_DEPLOYMENT.md"),`
- `tools/make_msi.py:196` `os.path.join` — `os.path.join(ROOT, "installer", "it",`
- `tools/make_msi.py:198` `os.path.join` — `"policy": [os.path.join(ROOT, "installer", "policy",`
- `tools/make_msi.py:200` `os.path.join` — `"policy/en-US": [os.path.join(ROOT, "installer", "policy",`
- `tools/make_msi.py:206` `os.path.join` — `if os.path.isdir(os.path.join(app_dir, *rel.split("/"))):`
- `tools/make_msi.py:225` `os.path.join` — `os.path.join(ROOT, "installer", "policy"),`
- `tools/make_msi.py:231` `os.path.join` — `os.path.join(ROOT, "installer", "policy",`

#### `tools/make_update_key.py`

- `tools/make_update_key.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/make_update_key.py:13` `os.path.join` — `KEYS = os.environ.get("QUANTISHEET_KEYS") or os.path.join(`
- `tools/make_update_key.py:15` `os.path.join` — `make_update_manifest.new_key(os.path.join(KEYS, "update_signing_key.pem"))`

#### `tools/make_update_manifest.py`

- `tools/make_update_manifest.py:30` `os.path.join` — `return os.path.join(ROOT, "app", "data", "update_pubkey.txt")`

#### `tools/make_winget.py`

- `tools/make_winget.py:101` `os.path.join` — `ap.add_argument("--sums", default=os.path.join(ROOT, "release", "github",`
- `tools/make_winget.py:105` `os.path.join` — `out = a.out or os.path.join(ROOT, "release", "github", "winget",`
- `tools/make_winget.py:110` `os.path.join` — `with open(os.path.join(out, name), "w", encoding="utf-8",`

#### `tools/md5list.py`

- `tools/md5list.py:7` `os.path.join` — `for dp, dn, fn in os.walk(os.path.join(ROOT, base)):`
- `tools/md5list.py:11` `os.path.join` — `p = os.path.join(dp, f)`

#### `tools/modern_screens.py`

- `tools/modern_screens.py:11` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tests"))`
- `tools/modern_screens.py:22` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/modern_screens.py:23` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/modern_screens.py:32` `os.path.join` — `out = argv[0] if argv else os.path.join(ROOT, ".run", "modernshots")`
- `tools/modern_screens.py:40` `os.path.join` — `pdf = os.path.join(TMP, "A-101 Floor Plan.pdf")`
- `tools/modern_screens.py:52` `os.path.join` — `p = os.path.join(out, name)`

#### `tools/modulor_spike.py`

- `tools/modulor_spike.py:21` `os.path.join` — `ZIP = os.path.join(ROOT, ".run", "modulor_spike", "modulor-40f6c2a.zip")`
- `tools/modulor_spike.py:23` `os.path.join` — `BASE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),`
- `tools/modulor_spike.py:25` `os.path.join` — `VENV = os.path.join(BASE, "venv")`
- `tools/modulor_spike.py:26` `os.path.join` — `PY = os.path.join(VENV, "Scripts", "python.exe") if os.name == "nt" else \`
- `tools/modulor_spike.py:27` `os.path.join` — `os.path.join(VENV, "bin", "python")`
- `tools/modulor_spike.py:28` `os.path.join` — `OUT = os.path.join(ROOT, ".run", "modulor_spike", "out")`
- `tools/modulor_spike.py:133` `os.path.join` — `script = os.path.join(BASE, "spike_check.py")`
- `tools/modulor_spike.py:146` `os.path.join` — `pdf = os.path.join(OUT, "plan.pdf")`
- `tools/modulor_spike.py:148` `os.path.join` — `summary = dxf.to_pdf(os.path.join(OUT, "plan.dxf"), pdf)`
- `tools/modulor_spike.py:154` `os.path.join` — `svg = fitz.open(os.path.join(OUT, "plan.svg"))`
- `tools/modulor_spike.py:163` `os.path.join` — `script = os.path.join(BASE, "frozen_check.py")`
- `tools/modulor_spike.py:169` `os.path.join` — `dist = os.path.join(BASE, "dist")`
- `tools/modulor_spike.py:176` `os.path.join` — `"--workpath", os.path.join(BASE, "build"),`
- `tools/modulor_spike.py:183` `os.path.join` — `exe = os.path.join(dist, f"spike_{attempt}", f"spike_{attempt}.exe")`

#### `tools/move_meeting_shots.py`

- `tools/move_meeting_shots.py:7` `os.path.join` — `SRC = os.path.join(os.path.expanduser("~"), "QS_r36_test", "gui45")`
- `tools/move_meeting_shots.py:8` `os.path.join` — `DST = os.path.join(os.path.expanduser("~"), "QS_r36_test", "_to_delete",`
- `tools/move_meeting_shots.py:14` `os.path.join` — `s, d = os.path.join(SRC, n), os.path.join(DST, n)`
- `tools/move_meeting_shots.py:14` `os.path.join` — `s, d = os.path.join(SRC, n), os.path.join(DST, n)`

#### `tools/msi_trial.py`

- `tools/msi_trial.py:14` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/msi_trial.py:21` `os.path.join` — `app_dir = os.path.join(os.environ["LOCALAPPDATA"], "QuantiSheetBuild",`
- `tools/msi_trial.py:23` `os.path.join` — `out = os.path.join(ROOT, ".run", "msitrial", "QuantiSheet-trial.msi")`

#### `tools/nav_screens.py`

- `tools/nav_screens.py:10` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg"); settings.PATH = os.path.join(settings.DIR, "s.json"); settings._cache = None`
- `tools/nav_screens.py:10` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg"); settings.PATH = os.path.join(settings.DIR, "s.json"); settings._cache = None`
- `tools/nav_screens.py:14` `os.path.join` — `out = os.path.join(ROOT, ".run", "navshots"); os.makedirs(out, exist_ok=True)`
- `tools/nav_screens.py:20` `os.path.join` — `win.open_path(practice.make(os.path.join(TMP, f"p-{mode}.pdf"))); app.processEvents(); win.fit_page()`
- `tools/nav_screens.py:24` `os.path.join` — `win.grab().save(os.path.join(out, f"{mode}.png"))`

#### `tools/new_screens.py`

- `tools/new_screens.py:13` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tests"))`
- `tools/new_screens.py:25` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/new_screens.py:26` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/new_screens.py:64` `os.path.join` — `out = argv[0] if argv else os.path.join(ROOT, ".run", "newshots")`
- `tools/new_screens.py:74` `os.path.join` — `p = os.path.join(out, name + ".png")`
- `tools/new_screens.py:83` `os.path.join` — `win.open_path(spec_pdf(os.path.join(TMP, "03 30 00.pdf")))`
- `tools/new_screens.py:103` `os.path.join` — `path = os.path.join(TMP, "plan.pdf")`
- `tools/new_screens.py:118` `os.path.join` — `s = ProjectStore(os.path.join(TMP, "Clinic"))`
- `tools/new_screens.py:208` `os.path.join` — `p = os.path.join(out, name)`

#### `tools/or_font_diag.py`

- `tools/or_font_diag.py:39` `os.path.join` — `path = os.path.join(folder, "C-101 example.pdf")`
- `tools/or_font_diag.py:43` `os.path.join` — `p.insert_font(fontname="SheetF", fontfile=os.path.join(`
- `tools/or_font_diag.py:183` `os.path.join` — `settings.DIR = os.path.join(folder, "cfg")`
- `tools/or_font_diag.py:184` `os.path.join` — `settings.PATH = os.path.join(folder, "cfg", "s.json")`
- `tools/or_font_diag.py:189` `os.path.join` — `store = ProjectStore(os.path.join(folder, "Job"))`
- `tools/or_font_diag.py:194` `os.path.join` — `p = os.path.join(folder, f"ph{i}.jpg")`
- `tools/or_font_diag.py:204` `os.path.join` — `out = os.path.join(folder, "report.pdf")`

#### `tools/owner_logs_sample.py`

- `tools/owner_logs_sample.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tests"))`
- `tools/owner_logs_sample.py:17` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/owner_logs_sample.py:18` `os.path.join` — `settings.PATH = os.path.join(tmp, "cfg", "s.json")`
- `tools/owner_logs_sample.py:22` `os.path.join` — `s = ProjectStore(os.path.join(tmp, "Job"))`

#### `tools/owner_report_sample.py`

- `tools/owner_report_sample.py:10` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tests"))`
- `tools/owner_report_sample.py:14` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/owner_report_sample.py:15` `os.path.join` — `settings.PATH = os.path.join(tmp, "cfg", "s.json")`
- `tools/owner_report_sample.py:24` `os.path.join` — `s = ProjectStore(os.path.join(tmp, "Job"))`
- `tools/owner_report_sample.py:37` `os.path.join` — `p = os.path.join(tmp, f"site{i:02d}.jpg")`

#### `tools/page_turn_probe.py`

- `tools/page_turn_probe.py:27` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/page_turn_probe.py:28` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/page_turn_probe.py:32` `os.path.join` — `SRC = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop",`
- `tools/page_turn_probe.py:41` `os.path.join` — `copy = os.path.join(TMP, "plant-copy.pdf")`

#### `tools/perf.py`

- `tools/perf.py:17` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/perf.py:75` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/perf.py:76` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "s.json")`
- `tools/perf.py:79` `os.path.join` — `os.path.join(tmp, f"perf-{n}.pdf")`
- `tools/perf.py:192` `os.path.join` — `out = os.path.join(tmp, "saved.pdf")`

#### `tools/perf_gate.py`

- `tools/perf_gate.py:30` `os.path.join` — `BUDGETS = os.path.join(ROOT, "tools", "perf_budgets.json")`
- `tools/perf_gate.py:31` `os.path.join` — `LAST = os.path.join(ROOT, ".run", "perf_last.json")`
- `tools/perf_gate.py:44` `os.path.join` — `os.path.join(ROOT, "tools", tool + ".py"),`
- `tools/perf_gate.py:74` `os.path.join` — `log = os.path.join(ROOT, ".run", "perf_gate.log")`

#### `tools/pip_install.py`

- `tools/pip_install.py:8` `os.path.join` — `req = os.path.join(ROOT, "requirements.txt")`

#### `tools/pm2_diag.py`

- `tools/pm2_diag.py:99` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/pm2_diag.py:100` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/pm2_diag.py:105` `os.path.join` — `toolchest.PATH = os.path.join(settings.DIR, "tc.json")`
- `tools/pm2_diag.py:272` `os.path.join` — `src = os.path.join(TMP, "G701 Change Order.pdf")`
- `tools/pm2_diag.py:367` `os.path.join` — `path = sample(os.path.join(TMP, f"plan_{tag}.pdf"))`
- `tools/pm2_diag.py:420` `os.path.join` — `path = sample(os.path.join(TMP, "plan_app.pdf"))`
- `tools/pm2_diag.py:467` `os.path.join` — `path = sample(os.path.join(TMP, f"qt_{len(os.listdir(TMP))}.pdf"))`
- `tools/pm2_diag.py:490` `os.path.join` — `src = make_form(os.path.join(TMP, "co.pdf"))`

#### `tools/pm_screens.py`

- `tools/pm_screens.py:188` `os.path.join` — `out = argv[0] if argv else os.path.join(ROOT, ".run", "pmshots")`
- `tools/pm_screens.py:192` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/pm_screens.py:193` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "s.json")`
- `tools/pm_screens.py:201` `os.path.join` — `store = ProjectStore(os.path.join(tmp, "Aiken Spay-Neuter Clinic"))`
- `tools/pm_screens.py:214` `os.path.join` — `p = os.path.join(out, f"{mode}-{name}.png")`
- `tools/pm_screens.py:251` `os.path.join` — `p = os.path.join(out, "light-new-rfi.png")`
- `tools/pm_screens.py:259` `os.path.join` — `p = os.path.join(out, "light-jump.png")`
- `tools/pm_screens.py:265` `os.path.join` — `p = os.path.join(out, "rfi-001.pdf")`
- `tools/pm_screens.py:268` `os.path.join` — `p = os.path.join(out, "daily-log.pdf")`

#### `tools/practice_dropbox_inbox.py`

- `tools/practice_dropbox_inbox.py:23` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tests"))`
- `tools/practice_dropbox_inbox.py:59` `os.path.join` — `p = os.path.join(tmp, "Acme update.xlsx")`
- `tools/practice_dropbox_inbox.py:64` `os.path.join` — `junk = os.path.join(tmp, "not a schedule.xlsx")`

#### `tools/preview_simple_menu.py`

- `tools/preview_simple_menu.py:21` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/preview_simple_menu.py:22` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/preview_simple_menu.py:44` `os.path.join` — `top().save(os.path.join(out, f"now_{tab}.png"))`
- `tools/preview_simple_menu.py:53` `os.path.join` — `top().save(os.path.join(out, f"now_{tab}.png"))`
- `tools/preview_simple_menu.py:56` `os.path.join` — `src = os.path.join(ROOT, ".run", "preview", "simple_menu.py")`
- `tools/preview_simple_menu.py:69` `os.path.join` — `top().save(os.path.join(out, f"simple_{tab.replace(' ', '_').replace('&', 'and')}.png"))`
- `tools/preview_simple_menu.py:74` `os.path.join` — `p.grab().save(os.path.join(out, "simple_all_tools_panel.png"))`

#### `tools/printer_trial.py`

- `tools/printer_trial.py:20` `os.path.join` — `PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")`
- `tools/printer_trial.py:23` `os.path.join` — `OUT = os.path.join(ROOT, ".run", "printer_admin.out")`
- `tools/printer_trial.py:36` `os.path.join` — `script = os.path.join(ROOT, ".run", "printer_admin.ps1")`
- `tools/printer_trial.py:41` `os.path.join` — `f.write(f"& '{PY}' '{os.path.join(ROOT, 'quantisheet.py')}' "`
- `tools/printer_trial.py:68` `os.path.join` — `script = os.path.join(ROOT, ".run", "printer_admin.ps1")`
- `tools/printer_trial.py:91` `os.path.join` — `docs = os.path.join(os.path.expanduser("~"), "Documents")`
- `tools/printer_trial.py:102` `os.path.join` — `return os.path.join(docs, printhelper.SUBFOLDER)`
- `tools/printer_trial.py:107` `os.path.join` — `before = set(glob.glob(os.path.join(folder, "*.pdf")))`
- `tools/printer_trial.py:115` `os.path.join` — `new = set(glob.glob(os.path.join(folder, "*.pdf"))) - before`
- `tools/printer_trial.py:134` `os.path.join` — `p = subprocess.run([PY, os.path.join(ROOT, "quantisheet.py"),`
- `tools/printer_trial.py:231` `os.path.join` — `log = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),`

#### `tools/probe_msi.py`

- `tools/probe_msi.py:27` `os.path.join` — `for hit in glob.glob(os.path.join(base, "WiX Toolset*", "bin",`
- `tools/probe_msi.py:30` `os.path.join` — `tools = os.path.join(os.environ.get("USERPROFILE", ""), ".dotnet",`
- `tools/probe_msi.py:36` `os.path.join` — `for hit in glob.glob(os.path.join(base, "Inno Setup*", "ISCC.exe")):`

#### `tools/probe_open.py`

- `tools/probe_open.py:207` `os.path.join` — `pdf = os.path.join(tmp, "plans.pdf")`

#### `tools/profile_open.py`

- `tools/profile_open.py:20` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/profile_open.py:21` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "s.json")`

#### `tools/profile_start.py`

- `tools/profile_start.py:35` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/profile_start.py:36` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "s.json")`

#### `tools/profile_ui.py`

- `tools/profile_ui.py:16` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/profile_ui.py:50` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/profile_ui.py:51` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "s.json")`
- `tools/profile_ui.py:54` `os.path.join` — `path = os.path.join(tmp, "p.pdf")`

#### `tools/profile_walls.py`

- `tools/profile_walls.py:3` `os.path.join` — `sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/profile_walls.py:7` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg"); settings.PATH = os.path.join(settings.DIR, "s.json"); settings._cache = None`
- `tools/profile_walls.py:7` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg"); settings.PATH = os.path.join(settings.DIR, "s.json"); settings._cache = None`
- `tools/profile_walls.py:12` `os.path.join` — `p = os.path.join(tmp, "job.pdf"); perf.make(p, 3)`

#### `tools/pymupdf2_trial.py`

- `tools/pymupdf2_trial.py:18` `os.path.join` — `MAIN = os.path.join(ROOT, ".venv")`
- `tools/pymupdf2_trial.py:19` `os.path.join` — `VENV = os.path.join(ROOT, ".venv-pm2")`
- `tools/pymupdf2_trial.py:24` `os.path.join` — `return os.path.join(venv, "Scripts" if WIN else "bin",`
- `tools/pymupdf2_trial.py:60` `os.path.join` — `with open(os.path.join(new_site, "zz_main_venv.pth"), "w",`

#### `tools/rail_click_probe.py`

- `tools/rail_click_probe.py:15` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tests"))`
- `tools/rail_click_probe.py:28` `os.path.join` — `REAL = os.path.join(os.path.expanduser("~"), ".quantisheet", "settings.json")`
- `tools/rail_click_probe.py:37` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/rail_click_probe.py:38` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/rail_click_probe.py:115` `os.path.join` — `pdf = os.path.join(TMP, "A-101.pdf")`
- `tools/rail_click_probe.py:120` `os.path.join` — `big = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop",`
- `tools/rail_click_probe.py:124` `os.path.join` — `copy = os.path.join(TMP, "plant-copy.pdf")`

#### `tools/release_files.py`

- `tools/release_files.py:59` `os.path.join` — `rel = os.path.join(root, "release")`
- `tools/release_files.py:60` `os.path.join` — `gh = os.path.join(rel, "github")`
- `tools/release_files.py:63` `os.path.join` — `pub = sorted(p for p in glob.glob(os.path.join(gh, "*"))`
- `tools/release_files.py:66` `os.path.join` — `sums = os.path.join(gh, "SHA256SUMS.txt")`
- `tools/release_files.py:73` `os.path.join` — `src = os.path.join(root, "docs", f"GITHUB_RELEASE_{version}.md")`
- `tools/release_files.py:74` `os.path.join` — `dst = os.path.join(gh, "RELEASE_NOTES.md")`
- `tools/release_files.py:80` `os.path.join` — `setup = os.path.join(rel, f"{NAME}-Beta-Setup-{version}.exe")`
- `tools/release_files.py:82` `os.path.join` — `claims = sorted(glob.glob(os.path.join(rel, "ClaimIT-Setup-*.exe")),`
- `tools/release_files.py:86` `os.path.join` — `rd = os.path.join(rel, "READ ME FIRST.txt")`

#### `tools/release_hashes.py`

- `tools/release_hashes.py:12` `os.path.join` — `for d in ("release", os.path.join("release", "github")):`
- `tools/release_hashes.py:13` `os.path.join` — `for p in sorted(glob.glob(os.path.join(ROOT, d, f"*{V}*"))):`

#### `tools/rename_old_names.py`

- `tools/rename_old_names.py:14` `os.path.join` — `old = os.path.join(home, "PDF Studio Keys")`
- `tools/rename_old_names.py:15` `os.path.join` — `new = os.path.join(home, "QuantiSheet Keys")`
- `tools/rename_old_names.py:25` `os.path.join` — `OUT = os.path.join(ROOT, "_to_delete")`
- `tools/rename_old_names.py:35` `os.path.join` — `src = os.path.join(ROOT, *parts)`
- `tools/rename_old_names.py:38` `os.path.join` — `dst = os.path.join(OUT, *parts)`
- `tools/rename_old_names.py:44` `os.path.join` — `print("moved:", os.path.join(*parts), "-> _to_delete")`

#### `tools/render_probe.py`

- `tools/render_probe.py:15` `os.path.join` — `DEFAULT = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop",`

#### `tools/review_copy.py`

- `tools/review_copy.py:23` `os.path.join` — `BASE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser(`
- `tools/review_copy.py:25` `os.path.join` — `COPY = os.path.join(BASE, "copy")`
- `tools/review_copy.py:26` `os.path.join` — `BARE = os.path.join(BASE, "copy_without")`
- `tools/review_copy.py:38` `os.path.join` — `p = os.path.join(d, n)`
- `tools/review_copy.py:58` `os.path.join` — `path = os.path.join(root, *rel.split("/"))`
- `tools/review_copy.py:89` `os.path.join` — `diff = os.path.join(COPY, "host_changes.diff")`
- `tools/review_copy.py:96` `os.path.join` — `py = os.path.join(ROOT, ".venv", "Scripts" if os.name == "nt" else "bin",`
- `tools/review_copy.py:104` `os.path.join` — `APPDATA=os.path.join(home, "AppData", "Roaming"),`
- `tools/review_copy.py:105` `os.path.join` — `LOCALAPPDATA=os.path.join(home, "AppData", "Local"),`
- `tools/review_copy.py:106` `os.path.join` — `QS_BACKOFFICE_HOME=os.path.join(home, "bo"),`
- `tools/review_copy.py:127` `os.path.join` — `shutil.rmtree(os.path.join(BARE, module), ignore_errors=True)`

#### `tools/room_debug.py`

- `tools/room_debug.py:19` `os.path.join` — `OUT = os.path.join(ROOT, ".run", "room_debug")`
- `tools/room_debug.py:33` `os.path.join` — `pdf = os.path.join(tmp, "plans.pdf")`

#### `tools/rooms_debug.py`

- `tools/rooms_debug.py:19` `os.path.join` — `OUT = os.path.join(ROOT, ".run", "rooms_debug")`
- `tools/rooms_debug.py:101` `os.path.join` — `cv2.imwrite(os.path.join(OUT, f"{p}_{safe}.png"),`

#### `tools/rooms_real.py`

- `tools/rooms_real.py:17` `os.path.join` — `OUT = os.path.join(ROOT, ".run", "rooms_real")`
- `tools/rooms_real.py:51` `os.path.join` — `cv2.imwrite(os.path.join(OUT, f"{p}_mask.png"),`
- `tools/rooms_real.py:70` `os.path.join` — `cv2.imwrite(os.path.join(OUT, f"{p}.png"), img[:, :, ::-1])`

#### `tools/run_tests.py`

- `tools/run_tests.py:9` `os.path.join` — `out = os.path.join(ROOT, "test-results.txt")`

#### `tools/runner.py`

- `tools/runner.py:16` `os.path.join` — `RUN = os.path.join(ROOT, ".run")`
- `tools/runner.py:17` `os.path.join` — `PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")`
- `tools/runner.py:31` `os.path.join` — `script = os.path.join(ROOT, "tools", parts[1] + ".py")`
- `tools/runner.py:110` `os.path.join` — `alive = os.path.join(RUN, "runner.alive")`
- `tools/runner.py:130` `os.path.join` — `stop = os.path.join(RUN, "STOP")`
- `tools/runner.py:134` `os.path.join` — `with open(os.path.join(RUN, "runner.alive"), "w") as f:`
- `tools/runner.py:140` `os.path.join` — `req = os.path.join(RUN, name)`
- `tools/runner.py:157` `os.path.join` — `os.remove(os.path.join(RUN, "runner.alive"))`

#### `tools/sbom.py`

- `tools/sbom.py:95` `os.path.join` — `return os.path.join(root or repo_root(), "release")`
- `tools/sbom.py:153` `os.path.join` — `path = os.path.join(root, rel)`
- `tools/sbom.py:158` `os.path.join` — `path = os.path.join(root, rel)`
- `tools/sbom.py:264` `os.path.join` — `path = os.path.join(root, "app", "__init__.py")`
- `tools/sbom.py:374` `os.path.join` — `cdx = os.path.join(out_dir, CDX_NAME)`
- `tools/sbom.py:375` `os.path.join` — `txt = os.path.join(out_dir, TXT_NAME)`

#### `tools/scanset.py`

- `tools/scanset.py:19` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/scanset.py:55` `os.path.join` — `path = os.path.join(tmp, f"scanset-{n}.pdf")`
- `tools/scanset.py:96` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/scanset.py:97` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "s.json")`

#### `tools/schedule_real.py`

- `tools/schedule_real.py:16` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/schedule_real.py:17` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "s.json")`
- `tools/schedule_real.py:36` `os.path.join` — `st = ProjectStore(os.path.join(TMP, "job"))`

#### `tools/screenshot.py`

- `tools/screenshot.py:25` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/screenshot.py:26` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/screenshot.py:65` `os.path.join` — `out = argv[0] if argv else os.path.join(ROOT, ".run", "shots")`
- `tools/screenshot.py:68` `os.path.join` — `sample_plan(os.path.join(TMP, "A-101 Floor Plan.pdf"))`
- `tools/screenshot.py:75` `os.path.join` — `p = os.path.join(out, name + ".png")`
- `tools/screenshot.py:98` `os.path.join` — `dlg.grab().save(os.path.join(out, f"{mode}-palette.png"))`
- `tools/screenshot.py:99` `os.path.join` — `shots.append(os.path.join(out, f"{mode}-palette.png"))`

#### `tools/serve_upload.py`

- `tools/serve_upload.py:21` `os.path.join` — `UP = os.path.join(ROOT, "release", "r2_upload")`
- `tools/serve_upload.py:22` `os.path.join` — `STATE = os.path.join(ROOT, ".run", "serve_upload.json")`
- `tools/serve_upload.py:29` `os.path.join` — `p = os.path.join(UP, d, "team")`
- `tools/serve_upload.py:53` `os.path.join` — `p = os.path.join(self.folder, name)`

#### `tools/setup_costbooks.py`

- `tools/setup_costbooks.py:19` `os.path.join` — `path = os.path.join(os.path.dirname(os.path.dirname(`
- `tools/setup_costbooks.py:30` `os.path.join` — `old = os.path.join(assembly_csv.user_dir(), "RSMeans.csv")`

#### `tools/sheet_probe.py`

- `tools/sheet_probe.py:29` `os.path.join` — `files += [os.path.join(d, f) for f in fs if f.lower().endswith(".pdf")]`

#### `tools/ship_check.py`

- `tools/ship_check.py:138` `os.path.join` — `rels.append(os.path.relpath(os.path.join(base, f), root))`
- `tools/ship_check.py:219` `os.path.join` — `p = os.path.join(base, n)`

#### `tools/shot_measure.py`

- `tools/shot_measure.py:20` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/shot_measure.py:21` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/shot_measure.py:29` `os.path.join` — `cp = os.path.join(TMP, "copy.pdf")`

#### `tools/shot_project_calendar.py`

- `tools/shot_project_calendar.py:16` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/shot_project_calendar.py:17` `os.path.join` — `settings.PATH = os.path.join(tmp, "cfg", "s.json")`
- `tools/shot_project_calendar.py:27` `os.path.join` — `s = ProjectStore(os.path.join(tmp, "Example Clinic"))`
- `tools/shot_project_calendar.py:58` `os.path.join` — `out = os.path.join(ROOT, ".work", "diag", f"project_calendar_{mode}.png")`

#### `tools/shot_scheduler.py`

- `tools/shot_scheduler.py:19` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/shot_scheduler.py:20` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/shot_scheduler.py:41` `os.path.join` — `folder=os.path.join(TMP, "job"),`

#### `tools/shot_takeoff.py`

- `tools/shot_takeoff.py:19` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/shot_takeoff.py:20` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/shot_takeoff.py:28` `os.path.join` — `cp = os.path.join(TMP, "copy.pdf")`

#### `tools/shot_timeoff.py`

- `tools/shot_timeoff.py:15` `os.path.join` — `os.environ["QS_BACKOFFICE_HOME"] = os.path.join(tmp, "home")`
- `tools/shot_timeoff.py:29` `os.path.join` — `o = make_office(os.path.join(tmp, "data"))`
- `tools/shot_timeoff.py:62` `os.path.join` — `out = os.path.join(ROOT, ".work", "diag", f"timeoff_{mode}.png")`

#### `tools/show_logs.py`

- `tools/show_logs.py:16` `os.path.join` — `p = os.path.join(DIR, name)`

#### `tools/sig_check.py`

- `tools/sig_check.py:16` `os.path.join` — `exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),`

#### `tools/sign_team_update.py`

- `tools/sign_team_update.py:23` `os.path.join` — `KEY = os.path.join(os.path.expanduser("~"), "QuantiSheet Keys",`
- `tools/sign_team_update.py:33` `os.path.join` — `src = os.path.join(ROOT, "release", SETUP)`
- `tools/sign_team_update.py:37` `os.path.join` — `out = os.path.join(ROOT, "release", "r2_upload", folder, "team")`
- `tools/sign_team_update.py:39` `os.path.join` — `notes = os.path.join(ROOT, "docs", f"TEAM_NOTES_{V}.txt")`
- `tools/sign_team_update.py:41` `os.path.join` — `cmd = [sys.executable, os.path.join(ROOT, "tools",`
- `tools/sign_team_update.py:44` `os.path.join` — `"--out", os.path.join(out, "version.json")]`
- `tools/sign_team_update.py:50` `os.path.join` — `shutil.copy2(src, os.path.join(out, SETUP))`
- `tools/sign_team_update.py:55` `os.path.join` — `print(" ", n, os.path.getsize(os.path.join(out, n)), "bytes")`

#### `tools/site_layers_probe.py`

- `tools/site_layers_probe.py:15` `os.path.join` — `out = os.path.join(ROOT, ".run", "site_layers")`
- `tools/site_layers_probe.py:30` `os.path.join` — `open(os.path.join(out, key + ".png"), "wb").write(data)`
- `tools/site_layers_probe.py:35` `os.path.join` — `doc.save(os.path.join(out, "site_page.pdf"))`
- `tools/site_layers_probe.py:36` `os.path.join` — `doc[0].get_pixmap(dpi=40).save(os.path.join(out, "site_page.png"))`

#### `tools/smoke_backoffice.py`

- `tools/smoke_backoffice.py:6` `os.path.join` — `QS_BACKOFFICE_HOME=os.path.join(home, "bo"), QT_QPA_PLATFORM="offscreen")`
- `tools/smoke_backoffice.py:11` `os.path.join` — `o = officemod.Office(os.path.join(home, "bo"))`
- `tools/smoke_backoffice.py:13` `os.path.join` — `snap = os.path.join(os.path.dirname(officemod.__file__), "tests", "data", "golden_snapshot.json")`
- `tools/smoke_backoffice.py:40` `os.path.join` — `out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(home, "smoke.png")`

#### `tools/smoke_src.py`

- `tools/smoke_src.py:11` `os.path.join` — `out = os.path.join(tempfile.mkdtemp(), "smoke.json")`

#### `tools/snap_probe.py`

- `tools/snap_probe.py:16` `os.path.join` — `SRC = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop",`

#### `tools/stage3_shots.py`

- `tools/stage3_shots.py:11` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tests"))`
- `tools/stage3_shots.py:22` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/stage3_shots.py:23` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/stage3_shots.py:30` `os.path.join` — `out = argv[0] if argv else os.path.join(ROOT, ".run", "stage3")`
- `tools/stage3_shots.py:35` `os.path.join` — `jobs = os.path.join(ROOT, ".run", "stage3", "Jobs",`
- `tools/stage3_shots.py:42` `os.path.join` — `p = os.path.join(jobs, n)`
- `tools/stage3_shots.py:55` `os.path.join` — `p = os.path.join(out, name)`
- `tools/stage3_shots.py:61` `os.path.join` — `sp = QPixmap(os.path.join(ROOT, "splash.png"))`
- `tools/stage3_shots.py:63` `os.path.join` — `app_main._stamp_version(sp).save(os.path.join(out, "0_splash.png"))`

#### `tools/stdio_probe.py`

- `tools/stdio_probe.py:39` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/stdio_probe.py:40` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/stdio_probe.py:47` `os.path.join` — `path = os.path.join(TMP, "set.pdf")`
- `tools/stdio_probe.py:97` `os.path.join` — `acrobat2.external_issue(v.doc, os.path.join(TMP, f"e{i}.pdf"))`

#### `tools/stress_new.py`

- `tools/stress_new.py:31` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/stress_new.py:32` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/stress_new.py:67` `os.path.join` — `plans = os.path.join(TMP, "plans.pdf")`
- `tools/stress_new.py:68` `os.path.join` — `specs = os.path.join(TMP, "specs.pdf")`
- `tools/stress_new.py:82` `os.path.join` — `st = scheduler.create_schedule("Stress 600", os.path.join(TMP, "s"),`
- `tools/stress_new.py:121` `os.path.join` — `path = os.path.join(TMP, "lib.csv")`
- `tools/stress_new.py:141` `os.path.join` — `cost_rollup.export(os.path.join(TMP, "sum.xlsx"), r)`
- `tools/stress_new.py:259` `os.path.join` — `out = os.path.join(TMP, "external.pdf")`
- `tools/stress_new.py:298` `os.path.join` — `w.export_heavybid(folder=os.path.join(TMP, "hb"), soil="B")`
- `tools/stress_new.py:393` `os.path.join` — `with open(os.path.join(ROOT, ".run", "stress_new.json"), "w",`

#### `tools/sync_server.py`

- `tools/sync_server.py:21` `os.path.join` — `yield (os.path.join(ROOT, "app", "collab", name),`
- `tools/sync_server.py:22` `os.path.join` — `os.path.join(ROOT, "server", name))`

#### `tools/testfiles.py`

- `tools/testfiles.py:22` `os.path.join` — `files = sorted(glob.glob(os.path.join(ROOT, "tests",`

#### `tools/theme_probe.py`

- `tools/theme_probe.py:19` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/theme_probe.py:20` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "s.json")`

#### `tools/thumbs.py`

- `tools/thumbs.py:20` `os.path.join` — `SRC = os.path.join(ROOT, "thumbs")`
- `tools/thumbs.py:21` `os.path.join` — `OUT = os.path.join(os.environ.get("LOCALAPPDATA", ""), "QuantiSheet", "thumbs")`
- `tools/thumbs.py:22` `os.path.join` — `DLL = os.path.join(OUT, "QuantiSheetThumbs.dll")`
- `tools/thumbs.py:23` `os.path.join` — `TEST_EXE = os.path.join(OUT, "thumbtest.exe")`
- `tools/thumbs.py:30` `os.path.join` — `FW = os.path.join(WIN, r"Microsoft.NET\Framework64\v4.0.30319")`
- `tools/thumbs.py:37` `os.path.join` — `p = os.path.join(WIN, "System32", "WinMetadata", n + ".winmd")`
- `tools/thumbs.py:43` `os.path.join` — `hits = [os.path.join(FW, n)] + sorted(glob.glob(os.path.join(`
- `tools/thumbs.py:43` `os.path.join` — `hits = [os.path.join(FW, n)] + sorted(glob.glob(os.path.join(`
- `tools/thumbs.py:46` `os.path.join` — `hits += sorted(glob.glob(os.path.join(FW, "WPF", n)))`
- `tools/thumbs.py:54` `os.path.join` — `csc = os.path.join(FW, "csc.exe")`
- `tools/thumbs.py:59` `os.path.join` — `[os.path.join(SRC, "QuantiSheetThumbs.cs")],`
- `tools/thumbs.py:61` `os.path.join` — `[os.path.join(SRC, "thumbtest.cs")]):`
- `tools/thumbs.py:70` `os.path.join` — `out = os.path.join(ROOT, ".run", "test_thumb.png")`

#### `tools/tidy.py`

- `tools/tidy.py:13` `os.path.join` — `TOOLS = os.path.join(ROOT, "tools")`
- `tools/tidy.py:14` `os.path.join` — `SCRATCH = os.path.join(TOOLS, "scratch")`
- `tools/tidy.py:26` `os.path.join` — `full = os.path.join(TOOLS, name)`
- `tools/tidy.py:29` `os.path.join` — `moves.append((full, os.path.join(SCRATCH, name)))`
- `tools/tidy.py:31` `os.path.join` — `full = os.path.join(ROOT, name)`
- `tools/tidy.py:33` `os.path.join` — `moves.append((full, os.path.join(SCRATCH, name)))`
- `tools/tidy.py:35` `os.path.join` — `full = os.path.join(ROOT, name)`
- `tools/tidy.py:46` `os.path.join` — `with open(os.path.join(SCRATCH, "README.txt"), "w") as f:`

#### `tools/time_installed.py`

- `tools/time_installed.py:79` `os.path.join` — `exe = os.path.join(os.environ.get("LOCALAPPDATA", ""),`
- `tools/time_installed.py:99` `os.path.join` — `marks = os.path.join(tempfile.gettempdir(), f"quantisheet-marks-{i}.json")`

#### `tools/time_launch.py`

- `tools/time_launch.py:21` `os.path.join` — `cmd = [sys.executable, os.path.join(ROOT, "quantisheet.py")]`
- `tools/time_launch.py:31` `os.path.join` — `out = os.path.join(tempfile.mkdtemp(), "timing.json")`

#### `tools/trade_screens.py`

- `tools/trade_screens.py:4` `os.path.join` — `sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))`
- `tools/trade_screens.py:12` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg"); settings.PATH = os.path.join(settings.DIR, "s.json")`
- `tools/trade_screens.py:12` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg"); settings.PATH = os.path.join(settings.DIR, "s.json")`
- `tools/trade_screens.py:18` `os.path.join` — `out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, ".run", "tradeshots")`
- `tools/trade_screens.py:27` `os.path.join` — `path = os.path.join(TMP, "M-101 Plumbing.pdf"); d.save(path)`
- `tools/trade_screens.py:33` `os.path.join` — `app.processEvents(); f = os.path.join(out, n + ".png"); w.grab().save(f); shots.append(f)`

#### `tools/trial_copy.py`

- `tools/trial_copy.py:21` `os.path.join` — `return os.path.join(os.path.expanduser("~"), "quantisheet-" + name)`
- `tools/trial_copy.py:36` `os.path.join` — `ov = os.path.join(ROOT, ".run", "trial_overlay", name)`
- `tools/trial_copy.py:40` `os.path.join` — `src = os.path.join(base, f)`
- `tools/trial_copy.py:42` `os.path.join` — `out = os.path.join(d, rel)`
- `tools/trial_copy.py:83` `os.path.join` — `with open(os.path.join(d, f"trial-full-{start:%H%M%S}.txt"), "w",`

#### `tools/trial_excel_roundtrip.py`

- `tools/trial_excel_roundtrip.py:14` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tests"))`
- `tools/trial_excel_roundtrip.py:31` `os.path.join` — `path = os.path.join(tmp, "Acme update.xlsx")`

#### `tools/trial_master_real.py`

- `tools/trial_master_real.py:25` `os.path.join` — `settings.DIR = os.path.join(tmp, "cfg")`
- `tools/trial_master_real.py:26` `os.path.join` — `settings.PATH = os.path.join(tmp, "cfg", "s.json")`
- `tools/trial_master_real.py:37` `os.path.join` — `for f in glob.glob(os.path.join(folder, "**", "*.pdf"), recursive=True):`
- `tools/trial_master_real.py:49` `os.path.join` — `s = ProjectStore(os.path.join(tmp, "NMB trial"))`
- `tools/trial_master_real.py:79` `os.path.join` — `q = os.path.join(tmp, os.path.basename(f))`

#### `tools/trial_run.py`

- `tools/trial_run.py:20` `os.path.join` — `OUT = os.path.join(os.path.dirname(os.path.abspath(REPORT)), "trial_output")`
- `tools/trial_run.py:131` `os.path.join` — `fresh, os.path.join(OUT, "split"), every=100, base="spec")))`
- `tools/trial_run.py:133` `os.path.join` — `acrobat.export_text(fresh, os.path.join(OUT, "spec.txt"))))`
- `tools/trial_run.py:135` `os.path.join` — `acrobat.export_word(fresh, os.path.join(OUT, "spec.docx"))))`
- `tools/trial_run.py:137` `os.path.join` — `fresh, os.path.join(OUT, "spec.xlsx")))`
- `tools/trial_run.py:141` `os.path.join` — `step("reduce file size", lambda: f"{acrobat.reduce_size(fitz.open(SRC), os.path.join(OUT, 'spec_small.pdf')) / 1e6:.1f} MB")`
- `tools/trial_run.py:144` `os.path.join` — `os.path.join(OUT, f"spec_marked{g}.pdf"), garbage=g, deflate=True),`

#### `tools/try_patch.py`

- `tools/try_patch.py:65` `os.path.join` — `shutil.copytree(os.path.join(ROOT, d), os.path.join(tmp, d),`
- `tools/try_patch.py:65` `os.path.join` — `shutil.copytree(os.path.join(ROOT, d), os.path.join(tmp, d),`
- `tools/try_patch.py:67` `os.path.join` — `shutil.copytree(os.path.join(ROOT, "tools"),`
- `tools/try_patch.py:68` `os.path.join` — `os.path.join(tmp, "tools"),`
- `tools/try_patch.py:72` `os.path.join` — `os.path.isfile(os.path.join(ROOT, f)):`
- `tools/try_patch.py:73` `os.path.join` — `shutil.copy2(os.path.join(ROOT, f), tmp)`
- `tools/try_patch.py:75` `os.path.join` — `src = os.path.join(pdir, sub)`
- `tools/try_patch.py:78` `os.path.join` — `shutil.copy2(os.path.join(src, n),`
- `tools/try_patch.py:79` `os.path.join` — `os.path.join(tmp, sub, n))`
- `tools/try_patch.py:106` `os.path.join` — `if os.path.exists(os.path.join(tmp, t))],`

#### `tools/uac_check.py`

- `tools/uac_check.py:20` `os.path.join` — `os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", name),`
- `tools/uac_check.py:21` `os.path.join` — `os.path.join(os.path.expanduser("~"), "Desktop", name),`
- `tools/uac_check.py:22` `os.path.join` — `os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",`
- `tools/uac_check.py:24` `os.path.join` — `os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop",`

#### `tools/unpack_incoming.py`

- `tools/unpack_incoming.py:13` `os.path.join` — `INC = os.path.join(ROOT, "_incoming")`
- `tools/unpack_incoming.py:14` `os.path.join` — `OUT = os.path.join(INC, "plans")`
- `tools/unpack_incoming.py:19` `os.path.join` — `src = os.path.join(INC, name)`
- `tools/unpack_incoming.py:28` `os.path.join` — `dst = os.path.join(OUT, base)`

#### `tools/user_session.py`

- `tools/user_session.py:33` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/user_session.py:34` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/user_session.py:92` `os.path.join` — `pdf = argv[0] if argv else os.path.join(`
- `tools/user_session.py:94` `os.path.join` — `out = argv[1] if len(argv) > 1 else os.path.join(ROOT, ".run",`
- `tools/user_session.py:131` `os.path.join` — `p = os.path.join(out, name + ".png")`
- `tools/user_session.py:354` `os.path.join` — `target = os.path.join(TMP, "session-copy.pdf")`
- `tools/user_session.py:371` `os.path.join` — `target = os.path.join(TMP, "quantities.csv")`
- `tools/user_session.py:404` `os.path.join` — `with open(os.path.join(out, "session.json"), "w", encoding="utf-8") as f:`

#### `tools/venice_check.py`

- `tools/venice_check.py:10` `os.path.join` — `SRC = os.path.join(ROOT, "trial_output", "venice")`
- `tools/venice_check.py:13` `os.path.join` — `shutil.copytree(os.path.join(ROOT, "app"), os.path.join(tmp, "app"),`
- `tools/venice_check.py:13` `os.path.join` — `shutil.copytree(os.path.join(ROOT, "app"), os.path.join(tmp, "app"),`
- `tools/venice_check.py:15` `os.path.join` — `os.makedirs(os.path.join(tmp, "tests"))`
- `tools/venice_check.py:16` `os.path.join` — `for f in os.listdir(os.path.join(SRC, "app")):`
- `tools/venice_check.py:17` `os.path.join` — `shutil.copy(os.path.join(SRC, "app", f), os.path.join(tmp, "app", f))`
- `tools/venice_check.py:17` `os.path.join` — `shutil.copy(os.path.join(SRC, "app", f), os.path.join(tmp, "app", f))`
- `tools/venice_check.py:18` `os.path.join` — `for f in os.listdir(os.path.join(SRC, "tests")):`
- `tools/venice_check.py:19` `os.path.join` — `shutil.copy(os.path.join(SRC, "tests", f),`
- `tools/venice_check.py:20` `os.path.join` — `os.path.join(tmp, "tests", f))`
- `tools/venice_check.py:30` `os.path.join` — `"mods=" + repr([f[:-3] for f in os.listdir(os.path.join(SRC, 'app'))`

#### `tools/verify_update.py`

- `tools/verify_update.py:41` `os.path.join` — `up = os.path.join(ROOT, "release", "r2_upload")`
- `tools/verify_update.py:42` `os.path.join` — `local = next((os.path.join(up, d, "team") for d in os.listdir(up)`
- `tools/verify_update.py:43` `os.path.join` — `if os.path.isdir(os.path.join(up, d, "team"))), None)`
- `tools/verify_update.py:45` `os.path.join` — `with open(os.path.join(local, "version.json"), "rb") as f:`
- `tools/verify_update.py:53` `os.path.join` — `exe = os.path.join(local or "", os.path.basename(p)) if local \`
- `tools/verify_update.py:55` `os.path.join` — `rel = os.path.join(ROOT, "release", "QuantiSheet-Beta-Setup-"`

#### `tools/width_probe.py`

- `tools/width_probe.py:11` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tests"))`
- `tools/width_probe.py:23` `os.path.join` — `settings.DIR = os.path.join(TMP, "cfg")`
- `tools/width_probe.py:24` `os.path.join` — `settings.PATH = os.path.join(settings.DIR, "settings.json")`
- `tools/width_probe.py:36` `os.path.join` — `pdf = os.path.join(TMP, "A-101.pdf")`

#### `tools/zip_release.py`

- `tools/zip_release.py:11` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tools/zip_release.py:14` `os.path.join` — `REL = os.path.join(ROOT, "release")`
- `tools/zip_release.py:16` `os.path.join` — `setup = os.path.join(REL, f"{NAME}-Beta-Setup-{V}.exe")`
- `tools/zip_release.py:17` `os.path.join` — `notes = os.path.join(REL, f"{NAME} {V} - Whats New.pdf")`
- `tools/zip_release.py:22` `os.path.join` — `.lower() == "desktop" else os.path.join(os.path.expanduser("~"), "Desktop")`
- `tools/zip_release.py:23` `os.path.join` — `out = os.path.join(desk, f"{NAME} {V} for the team.zip")`
- `tools/zip_release.py:28` `os.path.join` — `claims = sorted(glob.glob(os.path.join(REL, "ClaimIT-Setup-*.exe")),`
- `tools/zip_release.py:40` `os.path.join` — `with open(os.path.join(desk, f"{NAME} {V} SHA256.txt"), "w") as f:`
- `tools/zip_release.py:55` `os.path.join` — `for p in glob.glob(os.path.join(REL, "*")):`
- `tools/zip_release.py:60` `os.path.join` — `GH = os.path.join(REL, "github")`
- `tools/zip_release.py:71` `os.path.join` — `server = os.path.join(REL, f"{NAME}-Beta-Server-Setup-{V}.exe")`
- `tools/zip_release.py:74` `os.path.join` — `msi = os.path.join(REL, f"{NAME}-Beta-{V}.msi")`

#### `tools/zip_source.py`

- `tools/zip_source.py:48` `os.path.join` — `p = os.path.join(ROOT, f)`
- `tools/zip_source.py:53` `os.path.join` — `for base, dirs, files in os.walk(os.path.join(ROOT, d)):`
- `tools/zip_source.py:56` `os.path.join` — `p = os.path.join(base, f)`
- `tools/zip_source.py:68` `os.path.join` — `os.path.join(ROOT, ".run", "source.zip"))`

#### Tests

#### `quantisheet_backoffice/tests/conftest.py`

- `quantisheet_backoffice/tests/conftest.py:29` `os.path.join` — `bad = os.path.realpath(os.path.join(os.path.expanduser("~"), name))`

#### `quantisheet_backoffice/tests/test_m4_store_rules.py`

- `quantisheet_backoffice/tests/test_m4_store_rules.py:38` `os.path.join` — `src = open(os.path.join(PKG, m + ".py"), encoding="utf-8").read()`
- `quantisheet_backoffice/tests/test_m4_store_rules.py:41` `os.path.join` — `src = open(os.path.join(PKG, "localai.py"), encoding="utf-8").read()`

#### `quantisheet_backoffice/tests/test_p1_01_isolation.py`

- `quantisheet_backoffice/tests/test_p1_01_isolation.py:20` `os.path.join` — `REAL = os.path.join(os.path.expanduser("~"), ".quantisheet")`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:29` `os.path.join` — `yield os.path.join(d, f)`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:35` `os.path.join` — `open(os.path.join(REAL, "settings.json"))`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:57` `os.path.join` — `written = [os.path.join(d, f) for d, _, fs in os.walk(tmp_path) for f in fs]`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:121` `os.path.join` — `text = open(os.path.join(PKG, "THIRD_PARTY_NOTICES.txt"),`

#### `quantisheet_backoffice/tests/test_p1_04_storage.py`

- `quantisheet_backoffice/tests/test_p1_04_storage.py:60` `os.path.join` — `raw = open(os.path.join(office.folder, "backoffice.sqlite"), "rb").read()`
- `quantisheet_backoffice/tests/test_p1_04_storage.py:62` `os.path.join` — `con = sqlite3.connect(os.path.join(office.folder, "backoffice.sqlite"))`

#### `quantisheet_backoffice/tests/test_p1_07_jobcost.py`

- `quantisheet_backoffice/tests/test_p1_07_jobcost.py:10` `os.path.join` — `DATA = os.path.join(os.path.dirname(__file__), "data")`
- `quantisheet_backoffice/tests/test_p1_07_jobcost.py:70` `os.path.join` — `snap = interface.load_snapshot(os.path.join(DATA, "golden_snapshot.json"))`
- `quantisheet_backoffice/tests/test_p1_07_jobcost.py:72` `os.path.join` — `golden = json.load(open(os.path.join(DATA, "golden_costsummary.json")))`

#### `quantisheet_backoffice/tests/test_p1_17_exports.py`

- `quantisheet_backoffice/tests/test_p1_17_exports.py:159` `os.path.join` — `text = open(os.path.join(root, f), encoding="utf-8").read()`

#### `quantisheet_backoffice/tests/test_r111_menu.py`

- `quantisheet_backoffice/tests/test_r111_menu.py:7` `os.path.join` — `ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "r111")`
- `quantisheet_backoffice/tests/test_r111_menu.py:33` `os.path.join` — `path = os.path.join(ROOT, name)`

#### `quantisheet_backoffice/tests/test_r111_qs025_migration.py`

- `quantisheet_backoffice/tests/test_r111_qs025_migration.py:45` `os.path.join` — `assert open(os.path.join(slot, "legacy-datakey.bin"), "rb").read() == raw`

#### `quantisheet_backoffice/tests/test_r111_qs025_paykeys.py`

- `quantisheet_backoffice/tests/test_r111_qs025_paykeys.py:16` `os.path.join` — `stub = open(os.path.join(company, "datakey.bin"), "rb").read()`
- `quantisheet_backoffice/tests/test_r111_qs025_paykeys.py:40` `os.path.join` — `os.path.join(office.folder, "datakey.bin")))`

#### `quantisheet_backoffice/tests/test_r111_qs025_sample.py`

- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:15` `os.path.join` — `SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(`
- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:29` `os.path.join` — `db = DB(os.path.join(folder, "backoffice.sqlite"))`
- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:39` `os.path.join` — `before = open(os.path.join(SAMPLE, "datakey.bin"), "rb").read()`
- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:48` `os.path.join` — `stub = open(os.path.join(folder, "datakey.bin"), "rb").read()`
- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:54` `os.path.join` — `assert open(os.path.join(SAMPLE, "datakey.bin"), "rb").read() == before`
- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:63` `os.path.join` — `assert open(os.path.join(folder, "datakey.bin"), "rb").read() == \`
- `quantisheet_backoffice/tests/test_r111_qs025_sample.py:64` `os.path.join` — `open(os.path.join(SAMPLE, "datakey.bin"), "rb").read()`

#### `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py`

- `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py:117` `os.path.join` — `SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(`
- `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py:121` `os.path.join` — `@pytest.mark.skipif(not os.path.isfile(os.path.join(`
- `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py:124` `os.path.join` — `r = sagejc.read_pdf(os.path.join(SAMPLE, "job_cost_report.pdf"))`
- `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py:156` `os.path.join` — `@pytest.mark.skipif(not os.path.isfile(os.path.join(`
- `quantisheet_backoffice/tests/test_r111_sagejc_multijob.py:162` `os.path.join` — `r = sagejc.read_pdf(os.path.join(SAMPLE, "job_cost_report.pdf"))`

#### `quantisheet_backoffice/tests/test_review_fixes.py`

- `quantisheet_backoffice/tests/test_review_fixes.py:76` `os.path.join` — `p = os.path.join(d, "snapshot.json")`
- `quantisheet_backoffice/tests/test_review_fixes.py:92` `os.path.join` — `p = os.path.join(d, "snapshot.json")`
- `quantisheet_backoffice/tests/test_review_fixes.py:183` `os.path.join` — `bad = os.path.join(os.path.expanduser("~"), name, "1099.csv")`
- `quantisheet_backoffice/tests/test_review_fixes.py:381` `os.path.join` — `t = open(os.path.join(d, f), encoding="utf-8").read()`

#### `quantisheet_backoffice/tests/test_t004_encryption_at_rest.py`

- `quantisheet_backoffice/tests/test_t004_encryption_at_rest.py:114` `os.path.join` — `for i, ln in enumerate(open(os.path.join(base, f),`

#### `quantisheet_claims/tests/test_interface.py`

- `quantisheet_claims/tests/test_interface.py:10` `os.path.join` — `DATA = os.path.join(os.path.dirname(__file__), "data", "sample_snapshot.json")`

#### `quantisheet_claims/tests/test_isolation.py`

- `quantisheet_claims/tests/test_isolation.py:49` `os.path.join` — `written = [os.path.join(d, f) for d, _, fs in os.walk(tmp_path) for f in fs]`
- `quantisheet_claims/tests/test_isolation.py:55` `os.path.join` — `real = os.path.join(os.path.expanduser("~"), name)`
- `quantisheet_claims/tests/test_isolation.py:65` `os.path.join` — `os.path.join(os.path.expanduser("~"), name))`
- `quantisheet_claims/tests/test_isolation.py:69` `os.path.join` — `settings.check_safe(os.path.join(os.path.expanduser("~"), name,`
- `quantisheet_claims/tests/test_isolation.py:86` `os.path.join` — `yield os.path.join(d, f)`
- `quantisheet_claims/tests/test_isolation.py:107` `os.path.join` — `src = open(os.path.join(PKG, name), encoding="utf-8").read()`

#### `quantisheet_claims/tests/test_store_recipes.py`

- `quantisheet_claims/tests/test_store_recipes.py:28` `os.path.join` — `bdir = os.path.join(os.path.dirname(p), ".backup")`

#### `quantisheet_claims/tests/test_v022.py`

- `quantisheet_claims/tests/test_v022.py:197` `os.path.join` — `src = open(os.path.join(root, "tools", "install_release.py"),`

#### `quantisheet_claims/tests/test_v02_window.py`

- `quantisheet_claims/tests/test_v02_window.py:386` `os.path.join` — `bak = os.path.join(os.path.dirname(old), ".backup")`

#### `quantisheet_claims/tests/test_window.py`

- `quantisheet_claims/tests/test_window.py:12` `os.path.join` — `DATA = os.path.join(os.path.dirname(__file__), "data", "sample_snapshot.json")`
- `quantisheet_claims/tests/test_window.py:109` `os.path.join` — `spec = open(os.path.join(root, "quantisheet_claims.spec"),`
- `quantisheet_claims/tests/test_window.py:112` `os.path.join` — `src = open(os.path.join(root, "claimit_launch.py"),`

#### `tests/conftest.py`

- `tests/conftest.py:26` `os.path.join` — `os.environ[_k] = os.path.join(_TEST_HOME, _k)`
- `tests/conftest.py:61` `os.path.join` — `_pd = os.path.join(os.environ.get("HOME") or "", "ProgramData")`
- `tests/conftest.py:67` `os.path.join` — `os.path.join(os.path.dirname(__file__),`

#### `tests/sample_data/make_samples.py`

- `tests/sample_data/make_samples.py:222` `os.path.join` — `os.path.join(HERE, "job_cost_report.pdf"),`
- `tests/sample_data/make_samples.py:223` `os.path.join` — `os.path.join(HERE, "job_cost_report.prn"),`
- `tests/sample_data/make_samples.py:432` `os.path.join` — `folder = os.path.join(HERE, "payroll_company")`
- `tests/sample_data/make_samples.py:434` `os.path.join` — `db_path = os.path.join(folder, "backoffice.sqlite")`
- `tests/sample_data/make_samples.py:435` `os.path.join` — `key_path = os.path.join(folder, "datakey.bin")`
- `tests/sample_data/make_samples.py:442` `os.path.join` — `db = DB(os.path.join(tmp, "backoffice.sqlite"))`
- `tests/sample_data/make_samples.py:476` `os.path.join` — `os.replace(os.path.join(tmp, "backoffice.sqlite"), db_path)`
- `tests/sample_data/make_samples.py:477` `os.path.join` — `os.replace(os.path.join(tmp, "datakey.bin"), key_path)`
- `tests/sample_data/make_samples.py:495` `os.path.join` — `path = os.path.join(HERE, name)`

#### `tests/test_ai_features.py`

- `tests/test_ai_features.py:20` `os.path.join` — `"civil_real", os.path.join(ROOT, "tools", "civil_real.py"))`

#### `tests/test_aitakeoff_wiring_phase2.py`

- `tests/test_aitakeoff_wiring_phase2.py:192` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tests/test_aitakeoff_wiring_phase2.py:379` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tests/test_aitakeoff_wiring_phase2.py:470` `os.path.join` — `rel = os.path.join("QuantiSheet Takeoff",`
- `tests/test_aitakeoff_wiring_phase2.py:474` `os.path.join` — `p = os.path.join(base, rel)`
- `tests/test_aitakeoff_wiring_phase2.py:481` `os.path.join` — `with open(os.path.join(ROOT, "tools", "aiken_map.json"),`

#### `tests/test_autoscale.py`

- `tests/test_autoscale.py:92` `os.path.join` — `path = os.path.join(os.path.dirname(__file__), "..", "trial", "autotakeoff_demo.pdf")`

#### `tests/test_betalicense.py`

- `tests/test_betalicense.py:127` `os.path.join` — `"beta_keys", os.path.join(root, "tools", "beta_keys.py"))`

#### `tests/test_bidbuild.py`

- `tests/test_bidbuild.py:15` `os.path.join` — `TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(`

#### `tests/test_brand_rename.py`

- `tests/test_brand_rename.py:94` `os.path.join` — `os.path.join(".pdfstudio", "project.json")) # read only: not moved`
- `tests/test_brand_rename.py:141` `os.path.join` — `with open(os.path.join(costbook.SHIPPED, names[0]),`

#### `tests/test_branding_v34.py`

- `tests/test_branding_v34.py:11` `os.path.join` — `path = os.path.join(ROOT, rel)`
- `tests/test_branding_v34.py:18` `os.path.join` — `path = _read(os.path.join("installer", "wizard-side.bmp"))`
- `tests/test_branding_v34.py:27` `os.path.join` — `path = _read(os.path.join("installer", "wizard-small.bmp"))`
- `tests/test_branding_v34.py:35` `os.path.join` — `path = _read(os.path.join("installer", "wizard-header.bmp"))`
- `tests/test_branding_v34.py:49` `os.path.join` — `text = open(_read(os.path.join("installer", "quantisheet.iss")),`
- `tests/test_branding_v34.py:58` `os.path.join` — `text = open(_read(os.path.join("tools", "build_installer.py")),`
- `tests/test_branding_v34.py:71` `os.path.join` — `text = open(_read(os.path.join("app", "main.py")), encoding="utf-8").read()`
- `tests/test_branding_v34.py:81` `os.path.join` — `text = open(_read(os.path.join("app", "main.py")), encoding="utf-8").read()`

#### `tests/test_build_msix.py`

- `tests/test_build_msix.py:11` `os.path.join` — `"build_msix", os.path.join(ROOT, "tools", "build_msix.py"))`
- `tests/test_build_msix.py:32` `os.path.join` — `with open(os.path.join(ROOT, "installer", "msix_identity.json"),`
- `tests/test_build_msix.py:103` `os.path.join` — `store = os.path.join(root, "splash_store.png")`
- `tests/test_build_msix.py:104` `os.path.join` — `company = os.path.join(root, "splash.png")`

#### `tests/test_button_slots.py`

- `tests/test_button_slots.py:15` `os.path.join` — `for root, _, files in os.walk(os.path.join(ROOT, "app")):`
- `tests/test_button_slots.py:19` `os.path.join` — `p = os.path.join(root, f)`

#### `tests/test_civiltakeoff.py`

- `tests/test_civiltakeoff.py:19` `os.path.join` — `"civil_real", os.path.join(ROOT, "tools", "civil_real.py"))`

#### `tests/test_claims_hook.py`

- `tests/test_claims_hook.py:18` `os.path.join` — `REAL_DIR = os.path.join(os.path.expanduser("~"), ".quantisheet")`

#### `tests/test_copy_text.py`

- `tests/test_copy_text.py:37` `os.path.join` — `d = fitz.open(_pdf(os.path.join(os.environ.get("TMP", "/tmp"),`

#### `tests/test_costbook_columns.py`

- `tests/test_costbook_columns.py:152` `os.path.join` — `path = os.path.join(costbook.SHIPPED, "QuantiSheet Starter 2026.json")`

#### `tests/test_crashreport.py`

- `tests/test_crashreport.py:100` `os.path.join` — `seen = os.path.join(crashreport.folder(), "seen.json")`

#### `tests/test_dashboard.py`

- `tests/test_dashboard.py:59` `os.path.join` — `folder = os.path.join(str(root), name)`
- `tests/test_dashboard.py:60` `os.path.join` — `os.makedirs(os.path.join(folder, ".quantisheet"), exist_ok=True)`
- `tests/test_dashboard.py:71` `os.path.join` — `with open(os.path.join(folder, db.PROJECT_FILE), "w",`
- `tests/test_dashboard.py:246` `os.path.join` — `with open(os.path.join(folder, db.PROJECT_FILE), encoding="utf-8") as f:`
- `tests/test_dashboard.py:364` `os.path.join` — `bad = os.path.join(str(tmp_path), "Bad")`
- `tests/test_dashboard.py:365` `os.path.join` — `os.makedirs(os.path.join(bad, ".quantisheet"))`
- `tests/test_dashboard.py:366` `os.path.join` — `with open(os.path.join(bad, db.PROJECT_FILE), "w") as f:`
- `tests/test_dashboard.py:369` `os.path.join` — `with open(os.path.join(worse, db.PROJECT_FILE), "w") as f:`
- `tests/test_dashboard.py:371` `os.path.join` — `nothing = os.path.join(str(tmp_path), "NotAProject")`
- `tests/test_dashboard.py:373` `os.path.join` — `gone = os.path.join(str(tmp_path), "Gone")`
- `tests/test_dashboard.py:381` `os.path.join` — `assert os.path.isfile(os.path.join(bad, db.PROJECT_FILE))`
- `tests/test_dashboard.py:382` `os.path.join` — `assert not os.path.exists(os.path.join(bad, db.PROJECT_FILE +`
- `tests/test_dashboard.py:389` `os.path.join` — `path = os.path.join(f, db.PROJECT_FILE)`
- `tests/test_dashboard.py:585` `os.path.join` — `bad = os.path.join(str(tmp_path), "Bad")`
- `tests/test_dashboard.py:586` `os.path.join` — `os.makedirs(os.path.join(bad, ".quantisheet"))`
- `tests/test_dashboard.py:587` `os.path.join` — `with open(os.path.join(bad, db.PROJECT_FILE), "w") as f:`

#### `tests/test_datecalc.py`

- `tests/test_datecalc.py:150` `os.path.join` — `src = open(os.path.join(os.path.dirname(__file__), "..", "app",`

#### `tests/test_dropbox.py`

- `tests/test_dropbox.py:307` `os.path.join` — `assert p == os.path.join(str(home), "Dropbox", "Jobs",`
- `tests/test_dropbox.py:311` `os.path.join` — `assert bad.startswith(os.path.join(str(home), "Dropbox") + os.sep)`
- `tests/test_dropbox.py:536` `os.path.join` — `assert not os.path.exists(os.path.join(str(home), dbx.TOKEN_FILE_PLAIN))`
- `tests/test_dropbox.py:541` `os.path.join` — `st = os.stat(os.path.join(str(home), dbx.TOKEN_FILE_PLAIN))`
- `tests/test_dropbox.py:558` `os.path.join` — `p = os.path.join(str(home), dbx.TOKEN_FILE_DPAPI)`
- `tests/test_dropbox.py:561` `os.path.join` — `assert not os.path.exists(os.path.join(str(home), dbx.TOKEN_FILE_PLAIN))`
- `tests/test_dropbox.py:690` `os.path.join` — `doc = open(os.path.join(root, "docs", "IT_DEPLOYMENT.md"),`
- `tests/test_dropbox.py:698` `os.path.join` — `src = open(os.path.join(os.path.dirname(dbx.__file__), "dropbox_ui.py"),`

#### `tests/test_formlib.py`

- `tests/test_formlib.py:90` `os.path.join` — `os.makedirs(os.path.join(formlib.folder(), "Bidding"))`
- `tests/test_formlib.py:91` `os.path.join` — `_form(os.path.join(formlib.folder(), "Bidding", "ITB.pdf"), False)`

#### `tests/test_genset_restaurant.py`

- `tests/test_genset_restaurant.py:1186` `os.path.join` — `d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `tests/test_genset_restaurant.py:1188` `os.path.join` — `with open(os.path.join(d, name + ".json"), encoding="utf-8") as f:`

#### `tests/test_genset_types.py`

- `tests/test_genset_types.py:13` `os.path.join` — `GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",`
- `tests/test_genset_types.py:18` `os.path.join` — `with open(os.path.join(GOLDEN, "cases.json"), encoding="utf-8") as f:`
- `tests/test_genset_types.py:47` `os.path.join` — `with open(os.path.join(GOLDEN, name + ".json"), encoding="utf-8") as f:`
- `tests/test_genset_types.py:56` `os.path.join` — `with open(os.path.join(GOLDEN, "derived.json"), encoding="utf-8") as f:`
- `tests/test_genset_types.py:66` `os.path.join` — `with open(os.path.join(GOLDEN, "house_1story.json"),`

#### `tests/test_heavy.py`

- `tests/test_heavy.py:291` `os.path.join` — `html = open(os.path.join(os.path.dirname(hubmod.__file__), "web",`

#### `tests/test_help_111.py`

- `tests/test_help_111.py:71` `os.path.join` — `text = open(os.path.join(ROOT, rel), encoding="utf-8").read()`

#### `tests/test_help_nov3.py`

- `tests/test_help_nov3.py:36` `os.path.join` — `p = os.path.join(os.path.dirname(helpcenter.__file__), "data",`
- `tests/test_help_nov3.py:45` `os.path.join` — `p = os.path.join(os.path.dirname(helpcenter.__file__), "data",`

#### `tests/test_hosted_relay.py`

- `tests/test_hosted_relay.py:18` `os.path.join` — `"relay_server", os.path.join(ROOT, "server", "relay_server.py"))`

#### `tests/test_it_policy.py`

- `tests/test_it_policy.py:187` `os.path.join` — `admx = open(os.path.join(root, "installer", "policy",`
- `tests/test_it_policy.py:189` `os.path.join` — `adml = open(os.path.join(root, "installer", "policy", "en-US",`
- `tests/test_it_policy.py:191` `os.path.join` — `doc = open(os.path.join(root, "docs", "IT_DEPLOYMENT.md"),`
- `tests/test_it_policy.py:271` `os.path.join` — `iss = open(os.path.join(root, "installer", "quantisheet_server.iss"),`
- `tests/test_it_policy.py:273` `os.path.join` — `doc = open(os.path.join(root, "docs", "IT_DEPLOYMENT.md"),`

#### `tests/test_leveling.py`

- `tests/test_leveling.py:13` `os.path.join` — `TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(`

#### `tests/test_msi.py`

- `tests/test_msi.py:7` `os.path.join` — `sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(`
- `tests/test_msi.py:23` `os.path.join` — `iss = open(os.path.join(root, "installer", "quantisheet_server.iss"),`

#### `tests/test_no_rival_names.py`

- `tests/test_no_rival_names.py:34` `os.path.join` — `for p in glob.glob(os.path.join(ROOT, pkg, "**", "*.py"),`
- `tests/test_no_rival_names.py:48` `os.path.join` — `for p in glob.glob(os.path.join(ROOT, "app", "**", "*." + ext),`
- `tests/test_no_rival_names.py:50` `os.path.join` — `os.path.join(ROOT, "installer", "**", "*." + ext),`

#### `tests/test_nov4_items.py`

- `tests/test_nov4_items.py:97` `os.path.join` — `data = timelog.add({}, os.path.join(folder, "Plans.pdf"), "A-1",`
- `tests/test_nov4_items.py:99` `os.path.join` — `timelog.add(data, os.path.join(folder, "Plans.pdf"), "A-2", "review",`
- `tests/test_nov4_items.py:120` `os.path.join` — `"codesign", os.path.join(here, "..", "tools", "codesign.py"))`
- `tests/test_nov4_items.py:167` `os.path.join` — `src = open(os.path.join(here, "..", "tools", "build_installer.py"),`

#### `tests/test_openwith.py`

- `tests/test_openwith.py:9` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tests/test_openwith.py:19` `os.path.join` — `text = open(os.path.join(ROOT, "installer", name),`

#### `tests/test_owner_report.py`

- `tests/test_owner_report.py:524` `os.path.join` — `p.insert_font(fontname="SheetF", fontfile=os.path.join(`
- `tests/test_owner_report.py:933` `os.path.join` — `full = os.path.getsize(os.path.join(orl.font_dir(),`

#### `tests/test_owner_report_fonts.py`

- `tests/test_owner_report_fonts.py:58` `os.path.join` — `p.insert_font(fontname="SrcF", fontfile=os.path.join(`

#### `tests/test_owner_report_logs.py`

- `tests/test_owner_report_logs.py:547` `os.path.join` — `full = os.path.getsize(os.path.join(L.font_dir(),`
- `tests/test_owner_report_logs.py:560` `os.path.join` — `assert os.path.isfile(os.path.join(L.font_dir(), name)), name`
- `tests/test_owner_report_logs.py:561` `os.path.join` — `with open(os.path.join(L.font_dir(), "OFL.txt"), encoding="utf-8") as f:`

#### `tests/test_p1_own_wording_payapp.py`

- `tests/test_p1_own_wording_payapp.py:35` `os.path.join` — `src = open(os.path.join(root, "app", f), encoding="utf-8").read()`

#### `tests/test_p1_roles.py`

- `tests/test_p1_roles.py:70` `os.path.join` — `rows += [json.loads(x) for x in open(os.path.join(base, f),`

#### `tests/test_packages.py`

- `tests/test_packages.py:56` `os.path.join` — `assert os.path.isfile(os.path.join(str(tmp_path), "packages.json"))`

#### `tests/test_packages_live.py`

- `tests/test_packages_live.py:40` `os.path.join` — `assert os.path.isfile(os.path.join(str(cfg), "carrier_keys.json"))`

#### `tests/test_patent_design_rules.py`

- `tests/test_patent_design_rules.py:12` `os.path.join` — `APP = os.path.join(os.path.dirname(__file__), "..", "app")`
- `tests/test_patent_design_rules.py:16` `os.path.join` — `with open(os.path.join(APP, name), encoding="utf-8") as f:`

#### `tests/test_pdf_tools_0_13_5.py`

- `tests/test_pdf_tools_0_13_5.py:501` `os.path.join` — `note = mw.repaired_notice(os.path.join("C:", "Example plans.pdf"))`

#### `tests/test_photofit.py`

- `tests/test_photofit.py:287` `os.path.join` — `d = os.path.join(self.folder, "att")`
- `tests/test_photofit.py:292` `os.path.join` — `return os.path.join(self.att_dir(), ref["sha256"] + ref["ext"])`
- `tests/test_photofit.py:314` `os.path.join` — `cached = os.listdir(os.path.join(store.att_dir(), "cache"))`

#### `tests/test_pipe_pricing.py`

- `tests/test_pipe_pricing.py:26` `os.path.join` — `b = costbook.Book(costbook.load(os.path.join(`

#### `tests/test_pm.py`

- `tests/test_pm.py:76` `os.path.join` — `assert filecmp.cmp(os.path.join(ROOT, "app", "collab", "hub.py"),`
- `tests/test_pm.py:77` `os.path.join` — `os.path.join(ROOT, "server", "hub.py"), shallow=False)`
- `tests/test_pm.py:384` `os.path.join` — `"relay_server", os.path.join(ROOT, "server", "relay_server.py"))`

#### `tests/test_price_import.py`

- `tests/test_price_import.py:24` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tests/test_price_import.py:273` `os.path.join` — `data = os.path.join(ROOT, "app", "data")`
- `tests/test_price_import.py:276` `os.path.join` — `os.path.join(data, "costbooks"), "app/data/costbooks", tags) == []`
- `tests/test_price_import.py:311` `os.path.join` — `with open(os.path.join(ROOT, rel), encoding="utf-8") as f:`

#### `tests/test_pricedb.py`

- `tests/test_pricedb.py:50` `os.path.join` — `out = os.path.join(settings.DIR, "export.json")`
- `tests/test_pricedb.py:111` `os.path.join` — `with open(os.path.join(folder, "Old.json"), "w", encoding="utf-8") as f:`

#### `tests/test_printer.py`

- `tests/test_printer.py:39` `os.path.join` — `assert ph.PORT.endswith(os.path.join("print", "spool", "job.pdf"))`
- `tests/test_printer.py:40` `os.path.join` — `assert os.path.join("QuantiSheet", "print", "spool") in ph.PORT`
- `tests/test_printer.py:48` `os.path.join` — `assert os.path.join("QuantiSheet", "print", "spool") in ph.SPOOL_DIR`
- `tests/test_printer.py:49` `os.path.join` — `assert ph.SUBFOLDER == os.path.join("QuantiSheet", "Printed")`
- `tests/test_printer.py:94` `os.path.join` — `server = open(os.path.join(root, "installer", "quantisheet_server.iss"),`
- `tests/test_printer.py:161` `os.path.join` — `msi = open(os.path.join(root, "tools", "make_msi.py"),`
- `tests/test_printer.py:164` `os.path.join` — `iss = open(os.path.join(root, "installer", "quantisheet_server.iss"),`

#### `tests/test_public_scan.py`

- `tests/test_public_scan.py:7` `os.path.join` — `sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(`

#### `tests/test_r111_service_menu.py`

- `tests/test_r111_service_menu.py:52` `os.path.join` — `for base in (os.path.join(ROOT, "app", "service"),):`
- `tests/test_r111_service_menu.py:57` `os.path.join` — `path = os.path.join(dirpath, name)`

#### `tests/test_r111_workorder.py`

- `tests/test_r111_workorder.py:194` `os.path.join` — `assert os.path.isfile(os.path.join(`

#### `tests/test_r34_startup_lock.py`

- `tests/test_r34_startup_lock.py:14` `os.path.join` — `with open(os.path.join(ROOT, "quantisheet.py"), encoding="utf-8") as f:`

#### `tests/test_r36_assembly_rules.py`

- `tests/test_r36_assembly_rules.py:188` `os.path.join` — `assert os.listdir(os.path.join(settings.DIR, "backups"))`
- `tests/test_r36_assembly_rules.py:190` `os.path.join` — `AR.save(r, os.path.join(os.path.dirname(_io.__file__), "r.json"))`

#### `tests/test_r36_db_safety.py`

- `tests/test_r36_db_safety.py:197` `os.path.join` — `assert not glob.glob(os.path.join(settings.DIR, "backups", "*"))`
- `tests/test_r36_db_safety.py:215` `os.path.join` — `baks = glob.glob(os.path.join(settings.DIR, "backups", "*.db"))`

#### `tests/test_r36_parametric.py`

- `tests/test_r36_parametric.py:88` `os.path.join` — `PM.save(m, os.path.join(_io.APP_DIR, "data", "plant.json"))`

#### `tests/test_r36_price_workbook.py`

- `tests/test_r36_price_workbook.py:121` `os.path.join` — `WP.write_priced(p, res["rows"], dest=os.path.join(`

#### `tests/test_r36_quote_pdf_own.py`

- `tests/test_r36_quote_pdf_own.py:21` `os.path.join` — `GOLDEN = os.path.join(HERE, "data", "r36_quote_pdf_golden.json")`

#### `tests/test_r36_rate_matcher.py`

- `tests/test_r36_rate_matcher.py:180` `os.path.join` — `os.path.join(settings.DIR, "backups", "*"))`
- `tests/test_r36_rate_matcher.py:182` `os.path.join` — `boq.save_matches(m, os.path.join(os.path.dirname(_io.__file__),`

#### `tests/test_r36_safe_writes.py`

- `tests/test_r36_safe_writes.py:87` `os.path.join` — `baks = glob.glob(os.path.join(settings.DIR, "backups", "*.json"))`
- `tests/test_r36_safe_writes.py:177` `os.path.join` — `os.symlink(str(away), os.path.join(settings.DIR, "estimate_templates"),`
- `tests/test_r36_safe_writes.py:192` `os.path.join` — `for bad in (str(pf / "x.json"), os.path.join(_io.APP_DIR, "x.json"),`
- `tests/test_r36_safe_writes.py:194` `os.path.join` — `os.path.join(settings.DIR, "settings.json")):`
- `tests/test_r36_safe_writes.py:218` `os.path.join` — `assert seen == [("save", os.path.join(settings.DIR, "Estimate check.csv")),`

#### `tests/test_r36_service.py`

- `tests/test_r36_service.py:78` `os.path.join` — `assert path == os.path.join(settings.DIR, "service_records.json")`
- `tests/test_r36_service.py:84` `os.path.join` — `service.save(s, os.path.join(_io.APP_DIR, "x.json"))`
- `tests/test_r36_service.py:101` `os.path.join` — `assert service.load(os.path.join(settings.DIR, "none.json")) == \`

#### `tests/test_r36_supplier_prices.py`

- `tests/test_r36_supplier_prices.py:60` `os.path.join` — `SP.save(pl, os.path.join(_io.APP_DIR, "data", "yard.json"))`
- `tests/test_r36_supplier_prices.py:92` `os.path.join` — `raise AssertionError(os.path.join(dp, f))`

#### `tests/test_r36_templates.py`

- `tests/test_r36_templates.py:74` `os.path.join` — `assert os.path.dirname(p) == os.path.join(settings.DIR,`
- `tests/test_r36_templates.py:91` `os.path.join` — `templates.save(tpl, os.path.join(_io.APP_DIR, "data", "x.json"))`

#### `tests/test_r39_characterize.py`

- `tests/test_r39_characterize.py:21` `os.path.join` — `DATA = os.path.join(os.path.dirname(__file__), "data", "r39")`
- `tests/test_r39_characterize.py:96` `os.path.join` — `path = os.path.join(DATA, name + ".json")`

#### `tests/test_r39_master_cycle.py`

- `tests/test_r39_master_cycle.py:55` `os.path.join` — `pdf = os.path.join(s.folder, "plan.pdf")`

#### `tests/test_r39_master_drafts.py`

- `tests/test_r39_master_drafts.py:14` `os.path.join` — `PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(`
- `tests/test_r39_master_drafts.py:70` `os.path.join` — `src = open(os.path.join(dp, f), encoding="utf-8").read()`

#### `tests/test_r39_master_flow.py`

- `tests/test_r39_master_flow.py:187` `os.path.join` — `q = os.path.join(s.folder, ".quantisheet", "master", "received")`

#### `tests/test_r39_master_ui.py`

- `tests/test_r39_master_ui.py:54` `os.path.join` — `pdf = os.path.join(s.folder, "Drawings", "plan.pdf")`

#### `tests/test_rebrand.py`

- `tests/test_rebrand.py:36` `os.path.join` — `p = os.path.join(ROOT, *item.split("/"))`
- `tests/test_rebrand.py:45` `os.path.join` — `yield os.path.relpath(os.path.join(base, n),`
- `tests/test_rebrand.py:54` `os.path.join` — `with open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8",`
- `tests/test_rebrand.py:71` `os.path.join` — `for base, dirs, names in os.walk(os.path.join(ROOT, item)):`
- `tests/test_rebrand.py:75` `os.path.join` — `bad.append(os.path.join(base, n))`
- `tests/test_rebrand.py:80` `os.path.join` — `iss = open(os.path.join(ROOT, "installer", "quantisheet.iss"),`
- `tests/test_rebrand.py:85` `os.path.join` — `te = open(os.path.join(ROOT, "quantisheet_backoffice", "timeentry.py"),`
- `tests/test_rebrand.py:104` `os.path.join` — `with open(os.path.join(ROOT, *p), encoding="utf-8-sig") as f:`
- `tests/test_rebrand.py:128` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tests/test_rebrand.py:155` `os.path.join` — `assert branding.installed_exe(base) == os.path.join(`

#### `tests/test_relay_hardening.py`

- `tests/test_relay_hardening.py:22` `os.path.join` — `"relay_server", os.path.join(ROOT, "server", "relay_server.py"))`
- `tests/test_relay_hardening.py:38` `os.path.join` — `assert filecmp.cmp(os.path.join(ROOT, "app", "collab", name),`
- `tests/test_relay_hardening.py:39` `os.path.join` — `os.path.join(ROOT, "server", name), shallow=False)`

#### `tests/test_release_files.py`

- `tests/test_release_files.py:8` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`
- `tests/test_release_files.py:66` `os.path.join` — `t = open(os.path.join(ROOT, "installer", iss), encoding="utf-8",`
- `tests/test_release_files.py:77` `os.path.join` — `with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as f:`

#### `tests/test_review_0_12_32.py`

- `tests/test_review_0_12_32.py:45` `os.path.join` — `with open(os.path.join(root, name), encoding="utf-8") as f:`

#### `tests/test_review_0_13_6.py`

- `tests/test_review_0_13_6.py:42` `os.path.join` — `src = open(os.path.join(os.path.dirname(os.path.dirname(`

#### `tests/test_review_f11_f14.py`

- `tests/test_review_f11_f14.py:14` `os.path.join` — `with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:`
- `tests/test_review_f11_f14.py:28` `os.path.join` — `assert os.path.isfile(os.path.join(costbook.SHIPPED,`

#### `tests/test_review_oct16.py`

- `tests/test_review_oct16.py:45` `os.path.join` — `assert open(os.path.join(root, a), "rb").read() == \`
- `tests/test_review_oct16.py:46` `os.path.join` — `open(os.path.join(root, b), "rb").read()`
- `tests/test_review_oct16.py:104` `os.path.join` — `for dirpath, _d, files in os.walk(os.path.join(root, "app")):`
- `tests/test_review_oct16.py:107` `os.path.join` — `assert "mktemp(" not in open(os.path.join(dirpath, f),`
- `tests/test_review_oct16.py:133` `os.path.join` — `assert os.listdir(os.path.join(str(tmp_path), ".pm_letters")) == []`

#### `tests/test_review_oct17.py`

- `tests/test_review_oct17.py:19` `os.path.join` — `OLD_STARTER = os.path.join(HERE, "heavy_starter_old_samples.json")`

#### `tests/test_review_venice.py`

- `tests/test_review_venice.py:19` `os.path.join` — `f"_tool_{name}", os.path.join(ROOT, "tools", name + ".py"))`
- `tests/test_review_venice.py:187` `os.path.join` — `assert seen and seen[0].endswith(os.path.join("tests", "28.py"))`

#### `tests/test_roof.py`

- `tests/test_roof.py:207` `os.path.join` — `path = os.path.join(os.path.dirname(roof.__file__), "roof.py")`

#### `tests/test_roof_flow.py`

- `tests/test_roof_flow.py:140` `os.path.join` — `src = open(os.path.join(os.path.dirname(os.path.dirname(`

#### `tests/test_room_bench_passage.py`

- `tests/test_room_bench_passage.py:116` `os.path.join` — `os.path.join(_HERE, "..", "_incoming", "plans",`
- `tests/test_room_bench_passage.py:118` `os.path.join` — `os.path.join(_HERE, "..", "..", "..", "..", "plans",`

#### `tests/test_rooms_real.py`

- `tests/test_rooms_real.py:8` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`

#### `tests/test_sample_data.py`

- `tests/test_sample_data.py:14` `os.path.join` — `SAMPLE = os.path.join(HERE, "sample_data")`
- `tests/test_sample_data.py:26` `os.path.join` — `with open(os.path.join(SAMPLE, name), encoding="utf-8") as fh:`
- `tests/test_sample_data.py:98` `os.path.join` — `path = os.path.join(SAMPLE, "job_cost_report.pdf")`
- `tests/test_sample_data.py:134` `os.path.join` — `@pytest.mark.skipif(not os.path.isfile(os.path.join(`
- `tests/test_sample_data.py:151` `os.path.join` — `folder = os.path.join(SAMPLE, "payroll_company")`
- `tests/test_sample_data.py:152` `os.path.join` — `blob = open(os.path.join(folder, "datakey.bin"), "rb").read()`
- `tests/test_sample_data.py:156` `os.path.join` — `raw = open(os.path.join(folder, "backoffice.sqlite"), "rb").read()`
- `tests/test_sample_data.py:164` `os.path.join` — `path = os.path.join(SAMPLE, name)`
- `tests/test_sample_data.py:173` `os.path.join` — `pay_db = os.path.join(SAMPLE, "payroll_company", "backoffice.sqlite")`

#### `tests/test_sbom.py`

- `tests/test_sbom.py:10` `os.path.join` — `path = os.path.join(ROOT, "tools", "sbom.py")`
- `tests/test_sbom.py:221` `os.path.join` — `assert sbom.default_out(ROOT) == os.path.join(ROOT, "release")`

#### `tests/test_scope_sheet_ui.py`

- `tests/test_scope_sheet_ui.py:205` `os.path.join` — `_path = os.path.join(store.folder, "A-101.pdf")`

#### `tests/test_security_0_13_5.py`

- `tests/test_security_0_13_5.py:287` `os.path.join` — `root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",`
- `tests/test_security_0_13_5.py:293` `os.path.join` — `fly_text = open(os.path.join(root, "fly.toml"), encoding="utf-8").read()`
- `tests/test_security_0_13_5.py:300` `os.path.join` — `render = open(os.path.join(root, "render.yaml"), encoding="utf-8").read()`
- `tests/test_security_0_13_5.py:304` `os.path.join` — `readme = open(os.path.join(root, "README.md"), encoding="utf-8").read()`
- `tests/test_security_0_13_5.py:425` `os.path.join` — `with open(os.path.join(folder, db.PROJECT_FILE), "w",`

#### `tests/test_sets.py`

- `tests/test_sets.py:89` `os.path.join` — `assert os.path.exists(os.path.join(rep["backup"], "Arch.pdf"))`

#### `tests/test_shellverbs.py`

- `tests/test_shellverbs.py:68` `os.path.join` — `iss = open(os.path.join(HERE, "..", "installer", "quantisheet.iss"),`

#### `tests/test_ship_check.py`

- `tests/test_ship_check.py:9` `os.path.join` — `sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(`
- `tests/test_ship_check.py:98` `os.path.join` — `with open(os.path.join(root, "installer", iss),`
- `tests/test_ship_check.py:102` `os.path.join` — `with open(os.path.join(root, "quantisheet.spec"), encoding="utf-8") as f:`
- `tests/test_ship_check.py:178` `os.path.join` — `top = os.path.join(root, sub)`
- `tests/test_ship_check.py:183` `os.path.join` — `rel = os.path.relpath(os.path.join(base, f), root)`

#### `tests/test_start_and_dialogs.py`

- `tests/test_start_and_dialogs.py:25` `os.path.join` — `d = os.path.join(os.path.expanduser("~"), ".quantisheet-test-real")`
- `tests/test_start_and_dialogs.py:36` `os.path.join` — `shutil.rmtree(os.path.join(os.path.expanduser("~"),`
- `tests/test_start_and_dialogs.py:41` `os.path.join` — `real = os.path.join(_real_dir(), "plans.pdf")`
- `tests/test_start_and_dialogs.py:43` `os.path.join` — `tmp = os.path.join(tempfile.mkdtemp(prefix="quantisheet-smoke-"),`
- `tests/test_start_and_dialogs.py:58` `os.path.join` — `mail = os.path.join(tempfile.mkdtemp(prefix="outlook-"), "C-101.pdf")`
- `tests/test_start_and_dialogs.py:63` `os.path.join` — `old = os.path.join(tempfile.mkdtemp(), "smoke.pdf")`
- `tests/test_start_and_dialogs.py:74` `os.path.join` — `return (os.path.join(_real_dir(), "picked.pdf"), "PDF (*.pdf)")`
- `tests/test_start_and_dialogs.py:87` `os.path.join` — `assert seen[-1] == os.path.join(_real_dir(), "report.pdf")`
- `tests/test_start_and_dialogs.py:111` `os.path.join` — `src = open(os.path.join(os.path.dirname(__file__), "..", "app",`
- `tests/test_start_and_dialogs.py:123` `os.path.join` — `p = os.path.join(_real_dir(), f"job{i}.pdf")`
- `tests/test_start_and_dialogs.py:146` `os.path.join` — `assert settings._is_temp(os.path.join(base, "tmpa7oas68l", "smoke.pdf"))`
- `tests/test_start_and_dialogs.py:147` `os.path.join` — `assert settings._is_temp(os.path.join(base, "quantisheet-x", "a.pdf"))`
- `tests/test_start_and_dialogs.py:149` `os.path.join` — `assert not settings._is_temp(os.path.join(base, "tmp_plans", "C-101.pdf"))`
- `tests/test_start_and_dialogs.py:150` `os.path.join` — `assert not settings._is_temp(os.path.join(base, "templates", "A.pdf"))`
- `tests/test_start_and_dialogs.py:151` `os.path.join` — `assert not settings._is_temp(os.path.join(base, "tmpa7oas68lx", "A.pdf"))`
- `tests/test_start_and_dialogs.py:155` `os.path.join` — `p = os.path.join(_real_dir(), "Twice.pdf")`
- `tests/test_start_and_dialogs.py:165` `os.path.join` — `os.path.join(real, "sub/report.pdf")`
- `tests/test_start_and_dialogs.py:167` `os.path.join` — `os.path.join(real, "report.pdf")`
- `tests/test_start_and_dialogs.py:173` `os.path.join` — `p = os.path.join(_real_dir(), "Once.pdf")`
- `tests/test_start_and_dialogs.py:201` `os.path.join` — `assert a[2] == os.path.join(settings.last_dir(), "out/r.pdf")`
- `tests/test_start_and_dialogs.py:212` `os.path.join` — `assert not settings._is_temp(os.path.join(base, "tmp_outlook", "x.pdf"))`
- `tests/test_start_and_dialogs.py:213` `os.path.join` — `assert not settings._is_temp(os.path.join(base, "tmp3dmodels", "x.pdf"))`
- `tests/test_start_and_dialogs.py:214` `os.path.join` — `assert not settings._is_temp(os.path.join(base, "tmpabcdefgh", "x.pdf"))`
- `tests/test_start_and_dialogs.py:215` `os.path.join` — `assert settings._is_temp(os.path.join(base, "tmpabcdefgh", "smoke.pdf"))`
- `tests/test_start_and_dialogs.py:216` `os.path.join` — `assert settings._is_temp(os.path.join(base, "tmpab12cd34", "smoke.pdf"))`
- `tests/test_start_and_dialogs.py:217` `os.path.join` — `assert settings._is_temp(os.path.join(base, "pdfs_ocr_1", "a.pdf"))`
- `tests/test_start_and_dialogs.py:218` `os.path.join` — `assert not settings._is_temp(os.path.join(base, "quantisheet_jobs", "a.pdf"))`

#### `tests/test_starter_costbook.py`

- `tests/test_starter_costbook.py:15` `os.path.join` — `STARTER = os.path.join(costbook.SHIPPED, "QuantiSheet Starter 2026.json")`

#### `tests/test_store_privacy.py`

- `tests/test_store_privacy.py:19` `os.path.join` — `iss = open(os.path.join(ROOT, "installer", "quantisheet.iss"),`
- `tests/test_store_privacy.py:35` `os.path.join` — `text = open(os.path.join(ROOT, "installer", name),`

#### `tests/test_t003_t002_links_office.py`

- `tests/test_t003_t002_links_office.py:79` `os.path.join` — `os.path.join("system32", "windowspowershell", "v1.0",`

#### `tests/test_updatecheck.py`

- `tests/test_updatecheck.py:399` `os.path.join` — `with open(os.path.join(ROOT, "app", "updatecheck.py"),`
- `tests/test_updatecheck.py:406` `os.path.join` — `iss = open(os.path.join(ROOT, "installer", "quantisheet.iss"),`
- `tests/test_updatecheck.py:496` `os.path.join` — `sys.path.insert(0, os.path.join(ROOT, "tools"))`

#### `tests/test_v33_security.py`

- `tests/test_v33_security.py:34` `os.path.join` — `"relay_server", os.path.join(ROOT, "server", "relay_server.py"))`
- `tests/test_v33_security.py:42` `os.path.join` — `f"_tool_{name}", os.path.join(ROOT, "tools", name + ".py"))`
- `tests/test_v33_security.py:197` `os.path.join` — `text = open(os.path.join(ROOT, "server", name)).read()`
- `tests/test_v33_security.py:210` `os.path.join` — `html = open(os.path.join(ROOT, "app", "collab", "web", "index.html"),`
- `tests/test_v33_security.py:346` `os.path.join` — `src = open(os.path.join(ROOT, "app", "main_window.py"),`
- `tests/test_v33_security.py:357` `os.path.join` — `assert os.path.getsize(os.path.join(ROOT, "tools", "bls.py")) < 2000`

#### `tests/test_v35_money_security.py`

- `tests/test_v35_money_security.py:385` `os.path.join` — `sw = open(os.path.join(root, "app", "collab", "web", "sw.js"),`

#### `tests/test_v35_windows_save.py`

- `tests/test_v35_windows_save.py:62` `os.path.join` — `name = os.path.join("x", "Plan.pdf")`
- `tests/test_v35_windows_save.py:63` `os.path.join` — `assert safeio.same_file(D, os.path.join("x", "Plan.pdf"))`
- `tests/test_v35_windows_save.py:64` `os.path.join` — `assert not safeio.same_file(D, os.path.join("x", "Other.pdf"))`

#### `tests/test_vocab.py`

- `tests/test_vocab.py:13` `os.path.join` — `TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(`

#### `tests/test_winget.py`

- `tests/test_winget.py:7` `os.path.join` — `sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(`

### Pattern C — `os.path.relpath` and `os.path.commonpath`

Production sites: 39. Test sites: 6.

#### Production

#### `app/collab/hub.py`

- `app/collab/hub.py:141` `os.path.commonpath` — `inside = os.path.commonpath([full, base]) == base`

#### `app/collab/relaycore.py`

- `app/collab/relaycore.py:347` `os.path.commonpath` — `if os.path.commonpath([full, base]) != base:`

#### `app/databackup.py`

- `app/databackup.py:112` `os.path.relpath` — `rel = os.path.relpath(full, root).replace("\\", "/")`

#### `app/estimating/_io.py`

- `app/estimating/_io.py:49` `os.path.commonpath` — `return os.path.commonpath([_real(p), f]) == f`

#### `app/formlib.py`

- `app/formlib.py:86` `os.path.relpath` — `rel = os.path.relpath(os.path.join(dp, f), root)`
- `app/formlib.py:143` `os.path.relpath` — `source = os.path.relpath(source, folder())`
- `app/formlib.py:149` `os.path.relpath` — `"file": os.path.relpath(dest, folder()),`
- `app/formlib.py:169` `os.path.relpath` — `e["file"] = os.path.relpath(new, folder())`

#### `app/formlib_ui.py`

- `app/formlib_ui.py:189` `os.path.relpath` — `rel = os.path.relpath(dp, path)`

#### `app/pm/docsui.py`

- `app/pm/docsui.py:182` `os.path.relpath` — `"name": os.path.relpath(p, root), "path": p,`

#### `app/pm/master/apply.py`

- `app/pm/master/apply.py:78` `os.path.relpath` — `rec.update(sha256=sha, evidence=os.path.relpath(q, store.folder))`

#### `app/pm/project_backup.py`

- `app/pm/project_backup.py:42` `os.path.relpath` — `yield p, os.path.relpath(p, folder).replace(os.sep, "/")`

#### `app/sets.py`

- `app/sets.py:32` `os.path.relpath` — `return os.path.relpath(path, base)`

#### `server/hub.py`

- `server/hub.py:141` `os.path.commonpath` — `inside = os.path.commonpath([full, base]) == base`

#### `server/relaycore.py`

- `server/relaycore.py:347` `os.path.commonpath` — `if os.path.commonpath([full, base]) != base:`

#### `tools/build_installer.py`

- `tools/build_installer.py:200` `os.path.relpath` — `rel = os.path.relpath(f, root)`
- `tools/build_installer.py:232` `os.path.relpath` — `out += [os.path.relpath(os.path.join(base, f), ROOT)`
- `tools/build_installer.py:252` `os.path.relpath` — `+ ", ".join(os.path.relpath(p, ROOT) for p in missing))`
- `tools/build_installer.py:254` `os.path.relpath` — `log(" branding:", os.path.relpath(p, ROOT),`
- `tools/build_installer.py:406` `os.path.relpath` — `", ".join(os.path.relpath(f, ROOT)`
- `tools/build_installer.py:499` `os.path.relpath` — `log(f" {os.path.relpath(m, ROOT)} "`

#### `tools/check_msi.py`

- `tools/check_msi.py:91` `os.path.relpath` — `b = os.path.join(inst, os.path.relpath(a, app_dir))`
- `tools/check_msi.py:94` `os.path.relpath` — `missing.append(os.path.relpath(a, app_dir))`
- `tools/check_msi.py:96` `os.path.relpath` — `differ.append(os.path.relpath(a, app_dir))`

#### `tools/find_in_backups.py`

- `tools/find_in_backups.py:20` `os.path.relpath` — `hits.append(f"{os.path.relpath(f, b)}:{i}")`

#### `tools/forms_probe.py`

- `tools/forms_probe.py:15` `os.path.relpath` — `rec = {"file": os.path.relpath(p, root), "pages": d.page_count, "encrypted": d.is_encrypted,`

#### `tools/make_update_manifest.py`

- `tools/make_update_manifest.py:40` `os.path.commonpath` — `if os.path.commonpath([os.path.abspath(key_path), ROOT]) == ROOT:`

#### `tools/md5list.py`

- `tools/md5list.py:12` `os.path.relpath` — `rel = os.path.relpath(p, ROOT).replace("\\", "/")`

#### `tools/release_hashes.py`

- `tools/release_hashes.py:20` `os.path.relpath` — `print(h.hexdigest().upper(), os.path.relpath(p, ROOT))`

#### `tools/sheet_probe.py`

- `tools/sheet_probe.py:41` `os.path.relpath` — `f"{os.path.relpath(f, target)}", flush=True)`

#### `tools/ship_check.py`

- `tools/ship_check.py:138` `os.path.relpath` — `rels.append(os.path.relpath(os.path.join(base, f), root))`
- `tools/ship_check.py:220` `os.path.relpath` — `files.append((os.path.relpath(p, root), p))`

#### `tools/sync_server.py`

- `tools/sync_server.py:37` `os.path.relpath` — `print("out of date:", os.path.relpath(d, ROOT))`
- `tools/sync_server.py:42` `os.path.relpath` — `print("updated", os.path.relpath(dst, ROOT))`

#### `tools/tidy.py`

- `tools/tidy.py:50` `os.path.relpath` — `print("move", os.path.relpath(a, ROOT), "->",`
- `tools/tidy.py:51` `os.path.relpath` — `os.path.relpath(b, ROOT))`
- `tools/tidy.py:55` `os.path.relpath` — `print("delete", os.path.relpath(d, ROOT))`

#### `tools/trial_copy.py`

- `tools/trial_copy.py:41` `os.path.relpath` — `rel = os.path.relpath(src, ov)`

#### `tools/zip_source.py`

- `tools/zip_source.py:57` `os.path.relpath` — `rel = os.path.relpath(p, ROOT).replace("\\", "/")`

#### Tests

#### `quantisheet_backoffice/tests/test_p1_01_isolation.py`

- `quantisheet_backoffice/tests/test_p1_01_isolation.py:107` `os.path.relpath` — `hits.append((os.path.relpath(p, PKG), b))`
- `quantisheet_backoffice/tests/test_p1_01_isolation.py:114` `os.path.relpath` — `hits = [os.path.relpath(p, PKG) for p in _files((".py",))`

#### `tests/test_no_rival_names.py`

- `tests/test_no_rival_names.py:36` `os.path.relpath` — `rel = os.path.relpath(p, ROOT)`
- `tests/test_no_rival_names.py:53` `os.path.relpath` — `bad += [f"{os.path.relpath(p, ROOT)}:{i}" for i, ln in`

#### `tests/test_rebrand.py`

- `tests/test_rebrand.py:45` `os.path.relpath` — `yield os.path.relpath(os.path.join(base, n),`

#### `tests/test_ship_check.py`

- `tests/test_ship_check.py:183` `os.path.relpath` — `rel = os.path.relpath(os.path.join(base, f), root)`

### Pattern D — `pathlib` `as_posix` / `as_uri` (and Path methods only when the receiver is a Path)

None.

### Pattern E — `tempfile`

Production sites: 118. Test sites: 13.

#### Production

#### `app/acrobat.py`

- `app/acrobat.py:153` `tempfile.mkdtemp` — `tmpdir = tempfile.mkdtemp(prefix="pdfs_ocr_")`

#### `app/acrobat2.py`

- `app/acrobat2.py:105` `tempfile.mkdtemp` — `outdir = tempfile.mkdtemp(prefix="quantisheet-lo-")`
- `app/acrobat2.py:147` `tempfile.mkdtemp` — `out = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),`
- `app/acrobat2.py:347` `tempfile.mkdtemp` — `folder = tempfile.mkdtemp(prefix="quantisheet-ppt-")`

#### `app/backoffice_hook.py`

- `app/backoffice_hook.py:302` `tempfile.gettempdir` — `base = tempfile.gettempdir()`
- `app/backoffice_hook.py:325` `tempfile.mkdtemp` — `folder = tempfile.mkdtemp(prefix="quantisheet-backoffice-")`

#### `app/bidform_xl_ui.py`

- `app/bidform_xl_ui.py:261` `tempfile.mkdtemp` — `self.folder, os.W_OK) else tempfile.mkdtemp(prefix="qs_br_")`

#### `app/claims_hook.py`

- `app/claims_hook.py:130` `tempfile.mkdtemp` — `folder = tempfile.mkdtemp(prefix="quantisheet-claims-")`

#### `app/co_delta_ui.py`

- `app/co_delta_ui.py:76` `tempfile.mkdtemp` — `out = out or os.path.join(tempfile.mkdtemp(prefix="qs_co_"),`

#### `app/count_library.py`

- `app/count_library.py:78` `tempfile.mkstemp` — `fd, tmp = tempfile.mkstemp(prefix=".countlib_", suffix=".tmp", dir=folder)`

#### `app/databackup.py`

- `app/databackup.py:96` `tempfile.mkdtemp` — `tmpdir = tempfile.mkdtemp(prefix="qs-backup-")`

#### `app/heavy.py`

- `app/heavy.py:798` `tempfile.mkstemp` — `fd, tmp = tempfile.mkstemp(suffix=".xlsx")`
- `app/heavy.py:1015` `tempfile.mkstemp` — `fd, tmp = tempfile.mkstemp(suffix=".xlsx")`

#### `app/issue_report.py`

- `app/issue_report.py:81` `tempfile.mkdtemp` — `folder = folder or tempfile.mkdtemp(prefix="qs_issue_")`

#### `app/mail.py`

- `app/mail.py:147` `tempfile.mkstemp` — `fd, path = tempfile.mkstemp(suffix=".eml", prefix="quantisheet-")`

#### `app/main.py`

- `app/main.py:322` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="quantisheet-smoke-")`
- `app/main.py:369` `tempfile.mkdtemp` — `path = practice.make(os.path.join(tempfile.mkdtemp(prefix="quantisheet-smoke-"),`
- `app/main.py:413` `tempfile.mkdtemp` — `out = os.path.join(tempfile.mkdtemp(prefix="quantisheet-smoke-"),`

#### `app/main_window.py`

- `app/main_window.py:166` `tempfile.mkstemp` — `fd, p = tempfile.mkstemp(prefix=".qs-wtest-", dir=folder)`
- `app/main_window.py:4795` `tempfile.mkdtemp` — `tmp = os.path.join(tempfile.mkdtemp(prefix="quantisheet-recover-"),`
- `app/main_window.py:5834` `tempfile.mkdtemp` — `tmpdir = tempfile.mkdtemp(prefix="quantisheet-compare-")`
- `app/main_window.py:7908` `tempfile.mkdtemp` — `cur = os.path.join(tempfile.mkdtemp(prefix="quantisheet-cmp-"),`

#### `app/name_memory.py`

- `app/name_memory.py:75` `tempfile.mkstemp` — `fd, tmp = tempfile.mkstemp(prefix=".names_", suffix=".tmp", dir=folder)`

#### `app/ocr.py`

- `app/ocr.py:46` `tempfile.mkstemp` — `fd, tmp = tempfile.mkstemp(suffix=".png")`

#### `app/panels.py`

- `app/panels.py:196` `tempfile.mkdtemp` — `out = os.path.join(tempfile.mkdtemp(prefix="qs-pages-"),`

#### `app/pdfa.py`

- `app/pdfa.py:192` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="quantisheet-pdfa-")`

#### `app/pm/actions.py`

- `app/pm/actions.py:1212` `tempfile.mkdtemp` — `path = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),`
- `app/pm/actions.py:1223` `tempfile.mkdtemp` — `path = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),`

#### `app/pm/owner_report_ui.py`

- `app/pm/owner_report_ui.py:1338` `tempfile.mkdtemp` — `path = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),`
- `app/pm/owner_report_ui.py:1471` `tempfile.mkdtemp` — `path = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),`

#### `app/pm/project_backup.py`

- `app/pm/project_backup.py:119` `tempfile.mkdtemp` — `work = tempfile.mkdtemp(prefix=".qs-restore-", dir=parent)`

#### `app/pm/recovery.py`

- `app/pm/recovery.py:679` `tempfile.mkdtemp` — `tmp = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"), "g.pdf")`

#### `app/pm/report.py`

- `app/pm/report.py:413` `tempfile.mkdtemp` — `d = tempfile.mkdtemp(prefix="quantisheet-")`

#### `app/prebid.py`

- `app/prebid.py:602` `tempfile.mkstemp` — `fd, tmp = tempfile.mkstemp(suffix=".xlsx")`

#### `app/preflight.py`

- `app/preflight.py:242` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="quantisheet-pdfx-")`

#### `app/settings.py`

- `app/settings.py:94` `tempfile.gettempdir` — `tmp = os.path.normcase(os.path.realpath(tempfile.gettempdir()))`

#### `app/sign/embed.py`

- `app/sign/embed.py:40` `tempfile.mkstemp` — `fd, tmp = tempfile.mkstemp(suffix=".pdf",`

#### `app/sign/signer.py`

- `app/sign/signer.py:162` `tempfile.mkstemp` — `fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=out_dir)`

#### `app/specrisk_ui.py`

- `app/specrisk_ui.py:111` `tempfile.mkdtemp` — `folder = tempfile.mkdtemp(prefix="qs_review_")`
- `app/specrisk_ui.py:137` `tempfile.mkdtemp` — `path = path or os.path.join(tempfile.mkdtemp(prefix="qs_risk_"),`

#### `app/subdir_ui.py`

- `app/subdir_ui.py:323` `tempfile.gettempdir` — `path = os.path.join(tempfile.gettempdir(),`

#### `app/theme.py`

- `app/theme.py:107` `tempfile.gettempdir` — `d = os.path.join(tempfile.gettempdir(), f"quantisheet-theme-{n}")`

#### `app/voice.py`

- `app/voice.py:288` `tempfile.mkstemp` — `fd, phr = tempfile.mkstemp(suffix=".txt", prefix="pdfs_voice_")`
- `app/voice.py:291` `tempfile.mkstemp` — `fd, ps = tempfile.mkstemp(suffix=".ps1", prefix="pdfs_voice_")`

#### `quantisheet_backoffice/__main__.py`

- `quantisheet_backoffice/__main__.py:24` `tempfile.mkdtemp` — `folder = tempfile.mkdtemp(prefix="qsbo-selftest-")`
- `quantisheet_backoffice/__main__.py:53` `tempfile.gettempdir` — `folder = tempfile.gettempdir()`

#### `quantisheet_backoffice/backup.py`

- `quantisheet_backoffice/backup.py:87` `tempfile.mkstemp` — `fd, tmp = tempfile.mkstemp(prefix=".qsbo-dump-", dir=office.folder)`
- `quantisheet_backoffice/backup.py:209` `tempfile.mkstemp` — `fd, tmp = tempfile.mkstemp(prefix=".qsbo-restore-", dir=folder)`

#### `quantisheet_backoffice/handoff.py`

- `quantisheet_backoffice/handoff.py:18` `tempfile.gettempdir` — `tmp = os.path.realpath(tempfile.gettempdir())`

#### `quantisheet_backoffice/ocr.py`

- `quantisheet_backoffice/ocr.py:158` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="qsbo-ocr-")`

#### `quantisheet_backoffice/settings.py`

- `quantisheet_backoffice/settings.py:118` `tempfile.mkstemp` — `fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")`

#### `quantisheet_claims/settings.py`

- `quantisheet_claims/settings.py:184` `tempfile.mkstemp` — `fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")`

#### `tools/ai_takeoff_compare.py`

- `tools/ai_takeoff_compare.py:77` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="qs_ait_cmp_")`

#### `tools/bigset.py`

- `tools/bigset.py:101` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="quantisheet-bigset-")`

#### `tools/check_installer.py`

- `tools/check_installer.py:22` `tempfile.gettempdir` — `target = os.path.join(tempfile.gettempdir(), "QuantiSheetInstallCheck")`
- `tools/check_installer.py:28` `tempfile.gettempdir` — `tempfile.gettempdir(), "quantisheet-setup.log")],`
- `tools/check_installer.py:37` `tempfile.gettempdir` — `out = os.path.join(tempfile.gettempdir(), "quantisheet-installed-smoke.json")`

#### `tools/check_msi.py`

- `tools/check_msi.py:68` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="quantisheet-msi-")`

#### `tools/check_paykey_move.py`

- `tools/check_paykey_move.py:42` `tempfile.TemporaryDirectory` — `with tempfile.TemporaryDirectory(prefix="qs-paykey-check-") as tmp:`

#### `tools/civil_bid.py`

- `tools/civil_bid.py:27` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="civilbid-")`

#### `tools/claim_sample.py`

- `tools/claim_sample.py:13` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp()`

#### `tools/click_everything.py`

- `tools/click_everything.py:71` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="quantisheet-click-")`

#### `tools/diag_maximize_real.py`

- `tools/diag_maximize_real.py:15` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="qs_mx_")`

#### `tools/diag_ribbon_width.py`

- `tools/diag_ribbon_width.py:15` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="qs_rw_")`

#### `tools/diag_textedit_dark.py`

- `tools/diag_textedit_dark.py:15` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="qs_te_")`

#### `tools/docs_probe.py`

- `tools/docs_probe.py:23` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-docs-")`

#### `tools/handles_probe.py`

- `tools/handles_probe.py:23` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-handles-")`

#### `tools/help_screens.py`

- `tools/help_screens.py:9` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp()`

#### `tools/iscc_check.py`

- `tools/iscc_check.py:17` `tempfile.mkdtemp` — `out = tempfile.mkdtemp(prefix="iscc-")`

#### `tools/legend_timing.py`

- `tools/legend_timing.py:27` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="qs_leg_t_")`

#### `tools/lookahead_sample.py`

- `tools/lookahead_sample.py:14` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp()`

#### `tools/make_costsummary_golden.py`

- `tools/make_costsummary_golden.py:25` `tempfile.mkdtemp` — `folder = tempfile.mkdtemp(prefix="quantisheet-golden-")`

#### `tools/modern_screens.py`

- `tools/modern_screens.py:21` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-modern-")`

#### `tools/nav_screens.py`

- `tools/nav_screens.py:9` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp()`

#### `tools/new_screens.py`

- `tools/new_screens.py:24` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-new-")`

#### `tools/or_font_diag.py`

- `tools/or_font_diag.py:164` `tempfile.mkdtemp` — `folder = tempfile.mkdtemp(prefix="or_font_diag_")`

#### `tools/owner_logs_sample.py`

- `tools/owner_logs_sample.py:16` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp()`

#### `tools/owner_report_sample.py`

- `tools/owner_report_sample.py:13` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp()`

#### `tools/page_turn_probe.py`

- `tools/page_turn_probe.py:26` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-turns-")`

#### `tools/perf.py`

- `tools/perf.py:73` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="quantisheet-perf-")`

#### `tools/perf_gate.py`

- `tools/perf_gate.py:40` `tempfile.mkstemp` — `fd, js = tempfile.mkstemp(suffix=".json")`

#### `tools/pm2_diag.py`

- `tools/pm2_diag.py:37` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="pm2_diag_")`

#### `tools/pm_screens.py`

- `tools/pm_screens.py:190` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="quantisheet-pm-")`

#### `tools/practice_dropbox_inbox.py`

- `tools/practice_dropbox_inbox.py:37` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="qs_dbx_practice_")`

#### `tools/preview_simple_menu.py`

- `tools/preview_simple_menu.py:20` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-preview-")`

#### `tools/probe_open.py`

- `tools/probe_open.py:206` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="qs_probe_")`

#### `tools/profile_open.py`

- `tools/profile_open.py:19` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-prof-")`

#### `tools/profile_start.py`

- `tools/profile_start.py:34` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="quantisheet-start-")`

#### `tools/profile_ui.py`

- `tools/profile_ui.py:48` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="quantisheet-prof-")`

#### `tools/profile_walls.py`

- `tools/profile_walls.py:5` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp()`

#### `tools/rail_click_probe.py`

- `tools/rail_click_probe.py:36` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-railprobe-")`

#### `tools/review_copy.py`

- `tools/review_copy.py:99` `tempfile.mkdtemp` — `home = tempfile.mkdtemp(prefix="qs-review-home-")`

#### `tools/room_debug.py`

- `tools/room_debug.py:32` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="qs_room_dbg_")`

#### `tools/runner.py`

- `tools/runner.py:42` `tempfile.TemporaryFile` — `with tempfile.TemporaryFile(mode="w+b") as out:`

#### `tools/scanset.py`

- `tools/scanset.py:54` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="quantisheet-scanset-")`

#### `tools/schedule_real.py`

- `tools/schedule_real.py:15` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="sched-real-")`

#### `tools/screenshot.py`

- `tools/screenshot.py:24` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-shots-")`

#### `tools/shot_measure.py`

- `tools/shot_measure.py:19` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-shot-")`

#### `tools/shot_project_calendar.py`

- `tools/shot_project_calendar.py:14` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="pc_shot_")`

#### `tools/shot_scheduler.py`

- `tools/shot_scheduler.py:18` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-sched-")`

#### `tools/shot_takeoff.py`

- `tools/shot_takeoff.py:18` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-shot-")`

#### `tools/shot_timeoff.py`

- `tools/shot_timeoff.py:14` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="bo_shot_")`

#### `tools/smoke_backoffice.py`

- `tools/smoke_backoffice.py:4` `tempfile.mkdtemp` — `home = tempfile.mkdtemp(prefix="qsbo-smoke-")`

#### `tools/smoke_src.py`

- `tools/smoke_src.py:11` `tempfile.mkdtemp` — `out = os.path.join(tempfile.mkdtemp(), "smoke.json")`

#### `tools/stage3_shots.py`

- `tools/stage3_shots.py:21` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-stage3-")`

#### `tools/stdio_probe.py`

- `tools/stdio_probe.py:38` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-stdio-")`

#### `tools/stress_new.py`

- `tools/stress_new.py:30` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-stress-")`

#### `tools/theme_probe.py`

- `tools/theme_probe.py:18` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="quantisheet-theme-probe-")`

#### `tools/time_installed.py`

- `tools/time_installed.py:99` `tempfile.gettempdir` — `marks = os.path.join(tempfile.gettempdir(), f"quantisheet-marks-{i}.json")`

#### `tools/time_launch.py`

- `tools/time_launch.py:31` `tempfile.mkdtemp` — `out = os.path.join(tempfile.mkdtemp(), "timing.json")`

#### `tools/trade_screens.py`

- `tools/trade_screens.py:11` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp()`

#### `tools/trial_excel_roundtrip.py`

- `tools/trial_excel_roundtrip.py:17` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="ms_excel_")`

#### `tools/trial_master_real.py`

- `tools/trial_master_real.py:24` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="ms_trial_")`

#### `tools/try_patch.py`

- `tools/try_patch.py:62` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="qs_trypatch_")`

#### `tools/user_session.py`

- `tools/user_session.py:32` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-session-")`

#### `tools/venice_check.py`

- `tools/venice_check.py:11` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="venice-")`

#### `tools/verify_update.py`

- `tools/verify_update.py:48` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="qs_verify_upd_")`

#### `tools/width_probe.py`

- `tools/width_probe.py:22` `tempfile.mkdtemp` — `TMP = tempfile.mkdtemp(prefix="quantisheet-width-")`

#### Tests

#### `quantisheet_backoffice/tests/test_review_fixes.py`

- `quantisheet_backoffice/tests/test_review_fixes.py:75` `tempfile.mkdtemp` — `d = tempfile.mkdtemp(prefix="quantisheet-backoffice-")`
- `quantisheet_backoffice/tests/test_review_fixes.py:91` `tempfile.mkdtemp` — `d = tempfile.mkdtemp(prefix="quantisheet-backoffice-")`

#### `tests/conftest.py`

- `tests/conftest.py:20` `tempfile.mkdtemp` — `_TEST_HOME = tempfile.mkdtemp(prefix="qs_test_home_")`

#### `tests/sample_data/make_samples.py`

- `tests/sample_data/make_samples.py:440` `tempfile.mkdtemp` — `tmp = tempfile.mkdtemp(prefix="qs-sample-pay-")`

#### `tests/test_start_and_dialogs.py`

- `tests/test_start_and_dialogs.py:43` `tempfile.mkdtemp` — `tmp = os.path.join(tempfile.mkdtemp(prefix="quantisheet-smoke-"),`
- `tests/test_start_and_dialogs.py:58` `tempfile.mkdtemp` — `mail = os.path.join(tempfile.mkdtemp(prefix="outlook-"), "C-101.pdf")`
- `tests/test_start_and_dialogs.py:63` `tempfile.mkdtemp` — `old = os.path.join(tempfile.mkdtemp(), "smoke.pdf")`
- `tests/test_start_and_dialogs.py:78` `tempfile.gettempdir` — `settings.set("last_dir", tempfile.gettempdir()) # temp is never used`
- `tests/test_start_and_dialogs.py:80` `tempfile.gettempdir` — `assert seen[-1] != tempfile.gettempdir() and os.path.isdir(seen[-1])`
- `tests/test_start_and_dialogs.py:89` `tempfile.gettempdir` — `QFileDialog.getOpenFileName(None, "Open", tempfile.gettempdir())`
- `tests/test_start_and_dialogs.py:90` `tempfile.gettempdir` — `assert seen[-1] == tempfile.gettempdir()`
- `tests/test_start_and_dialogs.py:145` `tempfile.gettempdir` — `base = tempfile.gettempdir()`
- `tests/test_start_and_dialogs.py:211` `tempfile.gettempdir` — `base = tempfile.gettempdir()`

## Dynamic calls the AST walk does not bind

These lines mention `getattr` on `os`, `shutil`, or `pathlib`. Read them before assuming the inventory is the whole set.

- `app/safeio.py:25` fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))

