"""Back up and restore a Project Center job folder with an integrity check
(P1: "Backup ZIP with SHA256 manifest; restore verifies every hash").

backup() zips every file of the job folder with manifest.json listing
each file's SHA-256 and size. restore() reads the manifest, refuses the
whole zip if any file is missing, extra, changed or would land outside
the target (a "../" path), unpacks into a new temp folder next to the
target, checks every hash again, and only then moves it into place - so
a damaged backup never half-replaces a job."""
import datetime as _dt
import hashlib
import json
import os
import shutil
import tempfile
import zipfile

MANIFEST = "manifest.json"
SKIP_SUFFIX = (".tmp", ".lock")


class BackupError(RuntimeError):
    pass


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _files(folder):
    for base, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not os.path.islink(
            os.path.join(base, d)))
        for f in sorted(files):
            p = os.path.join(base, f)
            if f.endswith(SKIP_SUFFIX) or os.path.islink(p):
                continue
            yield p, os.path.relpath(p, folder).replace(os.sep, "/")


def backup(folder, out_path, now=None):
    """Zip the job folder to out_path with a SHA-256 manifest. Returns the
    manifest."""
    if not os.path.isdir(folder):
        raise BackupError(f"No job folder at {folder}")
    entries = {}
    tmp = out_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for p, rel in _files(folder):
            if rel == MANIFEST:
                continue
            entries[rel] = {"sha256": _sha(p), "size": os.path.getsize(p)}
            z.write(p, rel)
        man = {"kind": "QuantiSheet project backup", "version": 1,
               "created": (now or _dt.datetime.now()).isoformat(
                   timespec="seconds"),
               "job": os.path.basename(os.path.abspath(folder)),
               "files": entries}
        z.writestr(MANIFEST, json.dumps(man, indent=1, sort_keys=True))
    os.replace(tmp, out_path)
    return man


def _safe(rel):
    n = os.path.normpath(rel)
    return not (os.path.isabs(rel) or n.startswith("..") or ":" in rel or
                rel.startswith(("/", "\\")))


def verify(zip_path):
    """(manifest, problems) - problems is [] when every file matches."""
    probs = []
    with zipfile.ZipFile(zip_path) as z:
        try:
            man = json.loads(z.read(MANIFEST))
        except KeyError:
            raise BackupError("This isn't a QuantiSheet project backup "
                              "(no manifest).") from None
        except ValueError:
            raise BackupError("The backup's manifest is damaged.") from None
        files = man.get("files") or {}
        names = {i.filename for i in z.infolist()
                 if not i.is_dir()} - {MANIFEST}
        for rel in sorted(names - set(files)):
            probs.append(f"{rel}: in the zip but not in the manifest")
        for rel, info in sorted(files.items()):
            if not _safe(rel):
                probs.append(f"{rel}: unsafe path")
                continue
            if rel not in names:
                probs.append(f"{rel}: missing")
                continue
            h = hashlib.sha256()
            with z.open(rel) as f:
                for b in iter(lambda: f.read(1 << 20), b""):
                    h.update(b)
            if h.hexdigest() != info.get("sha256"):
                probs.append(f"{rel}: changed (hash doesn't match)")
    return man, probs


def restore(zip_path, target, overwrite=False):
    """Restore the backup into `target`. Refused - nothing changed - when
    any file fails the check or `target` holds a job and not overwrite.
    The old job, when replaced, is kept beside it (<target>.before-
    restore-<time>). Returns the number of files restored."""
    man, probs = verify(zip_path)
    if probs:
        raise BackupError("The backup didn't pass its check, so nothing "
                          "was restored:\n" + "\n".join(probs[:20]))
    if os.path.exists(target) and os.listdir(target) and not overwrite:
        raise BackupError(f"{target} already holds a job.")
    parent = os.path.dirname(os.path.abspath(target))
    os.makedirs(parent, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".qs-restore-", dir=parent)
    try:
        with zipfile.ZipFile(zip_path) as z:
            for rel in man["files"]:
                dest = os.path.join(work, *rel.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(rel) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
        for rel, info in man["files"].items():          # once more, on disk
            if _sha(os.path.join(work, *rel.split("/"))) != info["sha256"]:
                raise BackupError(f"{rel} didn't unpack correctly; nothing "
                                  "was restored.")
        if os.path.exists(target):
            keep = target.rstrip("/\\") + _dt.datetime.now().strftime(
                ".before-restore-%Y%m%d-%H%M%S")
            os.replace(target, keep)
        os.replace(work, target)
        work = None
        return len(man["files"])
    finally:
        if work and os.path.isdir(work):
            shutil.rmtree(work, ignore_errors=True)
