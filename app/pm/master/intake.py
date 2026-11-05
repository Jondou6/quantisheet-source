"""The watched shared folder (design 3.2) and update packets (3.1).

Layout (Q3 default, configurable later): <inbox>/<Company>/ for each
sub. A file is taken only when its size and modified time are unchanged
since the previous poll and it can be opened; Office lock files (~$),
.tmp/.part files, hidden files and OneDrive placeholders that aren't
downloaded are skipped. Every file ends in <Company>/Processed/ or
<Company>/Rejected/ (with <name>.reason.txt); <Company>/Outbox/ holds
the packets QuantiSheet prepares and is never read as a submission.
Polling, not a file watcher: watchers are unreliable on OneDrive and
network shares. A folder with no matching Directory company is left
alone."""
import os
import re

from . import apply, cycle, drafts, dropbox_inbox, model
from .formats import excel

SYSTEM = ("processed", "rejected", "outbox")
SKIP_SUFFIX = (".tmp", ".part", ".crdownload", ".partial")
# Windows: FILE_ATTRIBUTE_OFFLINE / RECALL_ON_OPEN / RECALL_ON_DATA_ACCESS
_PLACEHOLDER = 0x1000 | 0x40000 | 0x400000


_STATES = {}          # project folder -> {path: (size, mtime)} between polls


def state_for(store):
    """One poll memory per project, shared by the open window and the
    hook's background poll (so a file isn't 'first seen' twice)."""
    return _STATES.setdefault(os.path.normcase(os.path.realpath(
        store.folder)), {})


def safe_name(text):
    t = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(text or "")).strip(" .")
    return t or "_"


def _skip(name, st):
    n = name.lower()
    if name.startswith(("~$", ".")) or n.endswith(SKIP_SUFFIX):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _PLACEHOLDER)


def _openable(path):
    try:
        with open(path, "rb"):
            pass
        if os.name == "nt":                 # still being written by Excel
            os.rename(path, path)
        return True
    except OSError:
        return False


def scan(store, state, now=None, sync=True):
    """One poll. `state` (a dict the caller keeps between polls) remembers
    each file's size / modified time. Returns {"picked": [submission],
    "waiting": [path], "duplicates": [path], "skipped": [text],
    "errors": [text]}.

    A Dropbox inbox ("dropbox:/...", Q3) is synced first (sync=False
    when the caller already did it, e.g. on a worker thread) and its
    local mirror is scanned; mirror files are whole when they appear
    (downloaded to .part, checked, then moved in), so they're taken on
    the first poll."""
    out = {"picked": [], "waiting": [], "duplicates": [], "skipped": [],
           "errors": []}
    inbox = model.config(store).get("inbox") or ""
    if not inbox:
        out["errors"].append("No inbox folder is set (Master Schedule > "
                             "Settings).")
        return out
    if not model.can_approve(store):
        out["errors"].append("The project manager's QuantiSheet checks the "
                             "schedule inbox (your login isn't the PM).")
        return out
    remote = dropbox_inbox.is_remote(inbox)
    if remote:
        if sync:
            r = dropbox_inbox.sync(store)
            out["errors"].extend(r["errors"])
            out["skipped"].extend(r["skipped"])
        inbox = dropbox_inbox.mirror_dir(store)
        os.makedirs(inbox, exist_ok=True)
    try:
        tops = sorted(os.scandir(inbox), key=lambda e: e.name.lower())
    except OSError as ex:
        out["errors"].append(f"Can't read the inbox folder {inbox}: {ex}")
        return out
    names = {safe_name(c).casefold(): c for c in model.companies(store)}
    seen = set()
    for top in tops:
        if not top.is_dir() or top.name.lower() in SYSTEM:
            continue
        company = names.get(top.name.casefold())
        if company is None:
            out["skipped"].append(f"{top.name}: not a company in the "
                                  "Directory - left alone")
            continue
        try:
            files = sorted(os.scandir(top.path), key=lambda e: e.name)
        except OSError as ex:
            out["errors"].append(f"Can't read {top.path}: {ex}")
            continue
        for f in files:
            if not f.is_file():
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            if _skip(f.name, st):
                continue
            seen.add(f.path)
            sig = (st.st_size, st.st_mtime_ns)
            if (not remote and state.get(f.path) != sig) or \
                    not _openable(f.path):
                state[f.path] = sig
                out["waiting"].append(f.path)
                continue
            state.pop(f.path, None)
            _take(store, f.path, company, top.path, out, now)
    for k in [k for k in state if k not in seen]:
        state.pop(k, None)
    return out


def _take(store, path, company, folder, out, now):
    name = os.path.basename(path)
    try:
        sub = apply.receive(store, path, company, channel="folder", now=now)
    except Exception as ex:                          # noqa: BLE001
        out["errors"].append(f"{name}: {ex}")
        return
    if sub.get("duplicate_of"):
        dst = apply.copy_out(path, os.path.join(folder, "Processed"), name)
        _note(dst, f"Duplicate of {model.label(sub)} (same file, already "
              "received) - not processed again.\n")
        out["duplicates"].append(path)
        return
    if sub["status"] == "Rejected":
        dst = apply.copy_out(path, os.path.join(folder, "Rejected"), name)
        _note(dst, f"{model.label(sub)} rejected - nothing from this file "
              "was applied. Every reason:\n" +
              "".join(f"- {r.get('where')}: {r.get('text')}\n"
                      for r in sub.get("reasons") or []))
    else:
        apply.copy_out(path, os.path.join(folder, "Processed"), name)
    out["picked"].append(sub)


def _note(dst, text):
    with open(dst + ".reason.txt", "w", encoding="utf-8") as f:
        f.write(text)


def prepare_packets(store, cycle_date=None, today=None):
    """One template per sub in <inbox>/<Company>/Outbox/, plus a reminder
    DRAFT for each (kept in the module's outbox; nothing is sent)."""
    cfg = model.config(store)
    if not (cfg.get("inbox") or ""):
        raise ValueError("Set the inbox folder first.")
    inbox = dropbox_inbox.local_inbox(store)
    if cycle_date is None:
        cycle_date = cycle.next_date(cfg["cycle"], today).isoformat()
    cycle_date = str(cycle_date)[:10]
    out, ob = [], list(cfg.get("outbox") or [])
    for c in model.companies(store):
        if not model.slice_ids(store, c):
            continue
        d = os.path.join(inbox, safe_name(c), "Outbox")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, safe_name(f"{store.name} - {c} - schedule "
                                      f"update {cycle_date}") + ".xlsx")
        out.append(excel.generate(store, c, p, cycle=cycle_date))
        r = drafts.reminder(store, c, cycle_date,
                            link=(cfg.get("upload_links") or {}).get(c))
        r["attachments"] = [p]
        ob.append(r)
    model.set_config(store, outbox=ob[-500:])
    return out
