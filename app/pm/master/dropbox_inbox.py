"""Q3 (Jon, Oct 28): the subs' inbox is a Dropbox folder. Subs upload
through a Dropbox link (a file request or a shared folder) into
<Dropbox folder>/<Company>/; QuantiSheet reads that folder with the
person's own Dropbox sign-in (File > Dropbox) - the Dropbox desktop app
isn't needed.

The inbox setting is "dropbox:/<path>". Each sync:
  1. results back to Dropbox: a file QuantiSheet has dealt with moves to
     <Company>/Processed/ or <Company>/Rejected/ (plus <name>.reason.txt)
  2. new files: downloaded into a local mirror of the inbox
     (master_inbox/<Company>/ beside the project file), where intake.scan
     treats them exactly like files in a local inbox
  3. packets: files QuantiSheet wrote to the mirror's <Company>/Outbox/
     are uploaded to <Company>/Outbox/ in Dropbox

Nothing in Dropbox is ever deleted; a file is only moved inside the
inbox folder. A folder with no matching Directory company is left alone,
as with a local inbox. No Qt here."""
import json
import os
import threading

from . import model

PREFIX = "dropbox:"
SYSTEM = ("processed", "rejected", "outbox")
SKIP_SUFFIX = (".tmp", ".part", ".crdownload", ".partial")
JOURNAL = "_dropbox.json"
_LOCKS = {}


def is_remote(inbox):
    return str(inbox or "").strip().lower().startswith(PREFIX)


def remote_root(inbox):
    from ... import dropbox_sync as dbx
    return dbx.normalize(str(inbox).strip()[len(PREFIX):])


def as_setting(dropbox_path):
    from ... import dropbox_sync as dbx
    return PREFIX + (dbx.normalize(dropbox_path) or "/")


def mirror_dir(store):
    # beside the project file (inside the project's own data folder)
    return os.path.join(os.path.dirname(store.path), "master_inbox")


def local_inbox(store):
    """The folder intake.scan reads: the inbox itself, or the mirror of a
    Dropbox inbox."""
    inbox = model.config(store).get("inbox") or ""
    return mirror_dir(store) if is_remote(inbox) else inbox


def _lock(store):
    k = os.path.normcase(os.path.realpath(store.folder))
    return _LOCKS.setdefault(k, threading.Lock())


def _jpath(store):
    return os.path.join(mirror_dir(store), JOURNAL)


def _load(store):
    try:
        with open(_jpath(store), encoding="utf-8") as f:
            j = json.load(f)
    except (OSError, ValueError):
        j = {}
    j.setdefault("pulled", {})      # local path -> {"remote", "rev"}
    j.setdefault("seen", {})        # remote path_lower -> rev
    j.setdefault("uploaded", {})    # local outbox path -> [size, mtime]
    return j


def _save(store, j):
    os.makedirs(mirror_dir(store), exist_ok=True)
    p = _jpath(store)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(j, f, indent=1)
    os.replace(p + ".tmp", p)


def _skip(name):
    n = name.lower()
    return name.startswith(("~$", ".")) or n.endswith(SKIP_SUFFIX) or \
        n.endswith(".reason.txt")


def _client():
    from ... import dropbox_sync as dbx
    dbx.check_allowed()
    c = dbx.Client()
    if not c.key or not c.tokens.get("refresh_token"):
        raise dbx.NotSignedIn("Sign in to Dropbox first (File > Dropbox) - "
                              "the schedule inbox is a Dropbox folder.")
    return c


def _free(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def sync(store, client=None):
    """One round trip with the Dropbox inbox. Returns {"pulled": [local],
    "moved": [remote], "uploaded": [remote], "skipped": [text],
    "errors": [text]}. Only one sync per project runs at a time (a
    second caller gets a "busy" note and returns at once)."""
    out = {"pulled": [], "moved": [], "uploaded": [], "skipped": [],
           "errors": []}
    inbox = model.config(store).get("inbox") or ""
    if not is_remote(inbox):
        return out
    lk = _lock(store)
    if not lk.acquire(blocking=False):
        out["skipped"].append("Dropbox inbox check already running")
        return out
    try:
        c = client or _client()
        root = remote_root(inbox)
        j = _load(store)
        _push_results(store, c, root, j, out)
        _pull(store, c, root, j, out)
        _push_outbox(store, c, root, j, out)
        _save(store, j)
    except Exception as ex:                               # noqa: BLE001
        out["errors"].append(f"Dropbox inbox: {ex}")
    finally:
        lk.release()
    return out


def _join(*parts):
    from ... import dropbox_sync as dbx
    p = ""
    for x in parts:
        p = dbx.join(p, x)
    return p


def _push_results(store, c, root, j, out):
    """Files intake has finished with: their mirror copy left the company
    folder for Processed/ or Rejected/ - do the same in Dropbox."""
    for local, info in list(j["pulled"].items()):
        if os.path.isfile(local):
            continue                  # not taken yet
        folder, name = os.path.split(local)
        dest = None
        for sub in ("Rejected", "Processed"):
            if os.path.isfile(os.path.join(folder, sub, name)):
                dest = sub
                break
        remote = info["remote"]
        if dest is None:              # gone from the mirror some other way
            j["pulled"].pop(local, None)
            continue
        company_dir = remote.rsplit("/", 1)[0]
        target = _join(company_dir, dest, remote.rsplit("/", 1)[1])
        try:
            res = c.rpc("files/move_v2", {"from_path": remote,
                                          "to_path": target,
                                          "autorename": True})
            target = (res.get("metadata") or {}).get("path_display") or \
                target
            reason = os.path.join(folder, dest, name + ".reason.txt")
            if os.path.isfile(reason):
                c.upload(reason, target + ".reason.txt", mode="add")
            out["moved"].append(target)
        except Exception as ex:                           # noqa: BLE001
            from ... import dropbox_sync as dbx
            if not isinstance(ex, dbx.NotFound):
                out["errors"].append(f"Couldn't move {remote} to {dest}: "
                                     f"{ex}")
                continue
        j["pulled"].pop(local, None)


def _pull(store, c, root, j, out):
    from . import intake
    names = {intake.safe_name(n).casefold(): n
             for n in model.companies(store)}
    try:
        tops = c.list_folder(root)
    except Exception as ex:                               # noqa: BLE001
        out["errors"].append(f"Can't read the Dropbox folder {root or '/'}: "
                             f"{ex}")
        return
    pending = {v["remote"].lower() for v in j["pulled"].values()}
    for top in sorted(tops, key=lambda e: e.get("name", "").lower()):
        if top.get(".tag") != "folder" or \
                top.get("name", "").lower() in SYSTEM:
            continue
        company = names.get(top["name"].casefold())
        if company is None:
            out["skipped"].append(f"{top['name']}: not a company in the "
                                  "Directory - left alone")
            continue
        try:
            files = c.list_folder(top.get("path_display") or
                                  top["path_lower"])
        except Exception as ex:                           # noqa: BLE001
            out["errors"].append(f"Can't read {top.get('path_display')}: "
                                 f"{ex}")
            continue
        for f in sorted(files, key=lambda e: e.get("name", "")):
            if f.get(".tag") != "file" or _skip(f.get("name", "")):
                continue
            rp = f.get("path_display") or f["path_lower"]
            if rp.lower() in pending or \
                    j["seen"].get(rp.lower()) == f.get("rev"):
                continue
            dest = _free(os.path.join(mirror_dir(store),
                                      intake.safe_name(company),
                                      intake.safe_name(f["name"])))
            try:
                c.download(rp, dest)
            except Exception as ex:                       # noqa: BLE001
                out["errors"].append(f"Couldn't download {rp}: {ex}")
                continue
            j["pulled"][dest] = {"remote": rp, "rev": f.get("rev")}
            j["seen"][rp.lower()] = f.get("rev")
            out["pulled"].append(dest)


def _push_outbox(store, c, root, j, out):
    from . import intake
    base = mirror_dir(store)
    if not os.path.isdir(base):
        return
    for comp in sorted(os.listdir(base)):
        ob = os.path.join(base, comp, "Outbox")
        if not os.path.isdir(ob):
            continue
        for name in sorted(os.listdir(ob)):
            p = os.path.join(ob, name)
            if not os.path.isfile(p) or _skip(name):
                continue
            st = os.stat(p)
            sig = [st.st_size, st.st_mtime_ns]
            if j["uploaded"].get(p) == sig:
                continue
            target = _join(root, intake.safe_name(comp), "Outbox", name)
            try:
                c.upload(p, target, mode="overwrite")
            except TypeError:
                c.upload(p, target)
            except Exception as ex:                       # noqa: BLE001
                out["errors"].append(f"Couldn't upload {name}: {ex}")
                continue
            j["uploaded"][p] = sig
            out["uploaded"].append(target)


def make_sub_folders(store, client=None):
    """One folder per sub (every Directory company that owns activities)
    under the Dropbox inbox, so Jon can make a file request for each.
    Folders that are already there are left alone. Returns
    {"made": [path], "had": [path], "errors": [text]}."""
    from ... import dropbox_sync as dbx
    from . import intake
    out = {"made": [], "had": [], "errors": []}
    inbox = model.config(store).get("inbox") or ""
    if not is_remote(inbox):
        out["errors"].append("The inbox isn't a Dropbox folder (Settings > "
                             "Dropbox…).")
        return out
    c = client or _client()
    root = remote_root(inbox)
    for comp in model.companies(store):
        if not model.slice_ids(store, comp):
            continue
        p = _join(root, intake.safe_name(comp))
        try:
            if c.get_metadata(p) is not None:
                out["had"].append(p)
                continue
            c.create_folder(p)
            out["made"].append(p)
        except dbx.DropboxError as ex:
            out["errors"].append(f"{p}: {ex}")
    return out


def signed_in():
    """(True, account name) when QuantiSheet has a Dropbox sign-in."""
    try:
        from ... import dropbox_sync as dbx
        c = dbx.Client()
        ok = bool(c.key and c.tokens.get("refresh_token"))
        return ok, (c.tokens.get("name") or "") if ok else ""
    except Exception:                                     # noqa: BLE001
        return False, ""


def sync_in_background(store, done=None):
    """For the 60 s background poll: the network part runs on a worker
    thread so QuantiSheet never waits on Dropbox; `done(result)` is called
    on that thread when it finishes."""
    def work():
        r = sync(store)
        if done:
            done(r)
    t = threading.Thread(target=work, name="master-dropbox-inbox",
                         daemon=True)
    t.start()
    return t
