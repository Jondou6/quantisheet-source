"""Your own copy on a shared computer (Nov 3, Jon: "our IT guy is a pain",
updates must not need IT).

The all-users copy (server setup / MSI, in Program Files) can only be
updated by an administrator. So when it finds an update it offers to
install the person's OWN copy instead - the personal setup needs no
administrator rights, and that copy updates itself from then on. Once
someone has their own copy, starting the shared one (its icon, or a PDF
opened with it) opens their own copy instead, so nobody keeps working in
the out-of-date shared one. Setting "open_own_copy" False turns that off.
"""
import os
import sys

S_OPEN_OWN = "open_own_copy"


def _norm(p):
    return os.path.normcase(os.path.abspath(p or ""))


def program_dirs():
    out = []
    for k in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        v = os.environ.get(k)
        if v and _norm(v) not in out:
            out.append(_norm(v))
    return out


def current_exe():
    return sys.executable if getattr(sys, "frozen", False) else ""


def shared_copy(exe=None, dirs=None):
    """Is `exe` (default: this program) the all-users copy in Program
    Files? A source run never is."""
    exe = current_exe() if exe is None else exe
    if not exe:
        return False
    e = _norm(exe)
    return any(e.startswith(d.rstrip("\\/") + os.sep)
               for d in (program_dirs() if dirs is None else dirs))


def own_copy(exe=None, dirs=None, candidate=None):
    """This person's own installed copy (the personal setup's), or None -
    never the shared copy itself."""
    if candidate is None:
        from . import branding
        candidate = branding.installed_exe()
    exe = current_exe() if exe is None else exe
    if not candidate or not os.path.isfile(candidate):
        return None
    if shared_copy(candidate, dirs) or (exe and _norm(candidate) ==
                                        _norm(exe)):
        return None
    return candidate


def wanted():
    try:
        from . import settings
        return settings.get(S_OPEN_OWN, True) is not False
    except Exception:                                     # noqa: BLE001
        return True


def redirect(argv, exe=None, run=None, dirs=None, candidate=None):
    """At start-up of the shared copy: open the person's own copy instead
    (passing on the files to open). True when it did - the caller then
    stops."""
    if not shared_copy(exe, dirs) or not wanted():
        return False
    own = own_copy(exe, dirs, candidate)
    if not own:
        return False
    files = [a for a in (argv or [])[1:]
             if not a.startswith("-") and os.path.exists(a)]
    if run is None:
        import subprocess
        run = lambda a: subprocess.Popen(a, close_fds=True)  # noqa: E731
    try:
        run([own] + files)
    except OSError:
        return False
    return True
