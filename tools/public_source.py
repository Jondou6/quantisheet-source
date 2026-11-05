"""Export one clean public snapshot of QuantiSheet.

    python tools/public_source.py <ref> <empty-folder>
    python tools/public_source.py --scan <folder>

`git archive` copies the tracked tree of <ref> and nothing else, so the
private history never goes in. Paths on the never-publish list, and
anything .gitignore covers, are left out. The folder is then scanned.
A problem exits non-zero and prints a list. The commands for the snapshot
commit are printed and are not run. Nothing is pushed.

The scrub list is tools/public_source_scrub.json. It stays out of the
snapshot because it contains the strings it looks for.
"""
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRUB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "public_source_scrub.json")
AUTHOR = "QuantiSheet <noreply@quantisheet.invalid>"
AUTHOR_NAME = "QuantiSheet"
AUTHOR_EMAIL = "noreply@quantisheet.invalid"
PUBLIC_REPO = "quantisheet-source"
README_NAME = "PUBLIC_SOURCE_README.md"
MAX_SCAN = 80 * 1024 * 1024

# Left out of every snapshot, whether or not .gitignore still says so.
ALWAYS_PREFIXES = ("server/data",)
ALWAYS_EXACT = (
    "app/onboard.py",            # never from git; only the release's copy
    "tools/unlock_code.py",
    "tools/public_source_scrub.json",
)
ALWAYS_GLOBS = (
    ".env*",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "company_*.json",
)

# A drive letter, slashes, then a Users directory, then the next folder
# name. Written so this file does not itself match the pattern it searches
# for. Placeholder names (docs and made-up test paths) are allowed.
_WIN_USER = re.compile(br"(?i)[A-Za-z]:[\\/]+users[\\/]+([^\\/\s\"'`)]*)")
PLACEHOLDER_USERS = {b"public", b"default", b"all users", b"x", b"name",
                     b"user", b"username", b"someone", b"you", b"me",
                     b"exampleuser", b"example", b"tester", b"test"}


def _placeholder_user(name):
    n = name.strip().lower()
    return (n in PLACEHOLDER_USERS or n[:1] in (b"<", b"%", b"{", b"$")
            or b"example" in n)

# Files the program ships with that are not in git. They are copied into
# the snapshot from the release's own copy (export(add=...) / --add), and
# the snapshot is incomplete without them. Owner's decision (Nov 4):
# testers get the full corresponding source, the sign-in gate included.
REQUIRED_UNTRACKED = ("app/onboard.py",)


def _username_re():
    """The private Windows username, as a whole token.

    The two halves are written apart so this file does not contain the
    name it looks for. A longer token that merely begins with those
    letters (the support address the owner decided to keep) does not match.
    """
    token = ("jon" + "do").encode("ascii")
    return re.compile(br"(?i)(?<![A-Za-z0-9])" + token + br"(?![A-Za-z0-9])")


_USERNAME = _username_re()


class PublicSourceError(Exception):
    pass


# ---------------------------------------------------------------- gitignore
class _Rule:
    def __init__(self, regex, dir_only, negated):
        self.regex = regex
        self.dir_only = dir_only
        self.negated = negated


def _glob_to_regex(pat):
    """A gitignore glob, as a regex body matched against a whole path."""
    i, n = 0, len(pat)
    out = []
    while i < n:
        if pat.startswith("**", i):
            rest = pat[i + 2:]
            if rest.startswith("/"):
                out.append("(?:[^/]*/)*")
                i += 3
                continue
            if rest == "":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 2
            continue
        c = pat[i]
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def _parse_rule(base, line):
    line = line.rstrip("\r\n")
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    negated = line.startswith("!")
    pat = line[1:] if negated else line
    dir_only = pat.endswith("/")
    if dir_only:
        pat = pat[:-1]
    if not pat:
        return None
    if pat.startswith("/"):
        pat = pat[1:]
        anchored = True
    else:
        anchored = "/" in pat
    body = _glob_to_regex(pat)
    if base:
        prefix = re.escape(base.strip("/")) + "/"
    else:
        prefix = ""
    if anchored:
        expr = "^" + prefix + body + "$"
    else:
        expr = "^" + prefix + "(?:.*/)?" + body + "$"
    return _Rule(re.compile(expr), dir_only, negated)


class GitIgnore:
    """Last matching .gitignore rule wins. A file inside an ignored
    directory is ignored."""

    def __init__(self, rules):
        self.rules = rules

    def ignored(self, path):
        path = path.replace("\\", "/").strip("/")
        if not path:
            return False
        parts = path.split("/")
        for i in range(len(parts) - 1):
            if self._final("/".join(parts[:i + 1]), is_dir=True):
                return True
        return self._final(path, is_dir=False)

    def _final(self, path, is_dir):
        result = False
        for rule in self.rules:
            if rule.dir_only and not is_dir:
                continue
            if rule.regex.match(path):
                result = not rule.negated
        return result


def _rules_from_text(base, text):
    rules = []
    for line in text.splitlines():
        rule = _parse_rule(base, line)
        if rule is not None:
            rules.append(rule)
    return rules


def ignore_from_text(pairs):
    """`pairs` is (directory, gitignore text). directory '' is the root."""
    rules = []
    for base, text in pairs:
        rules.extend(_rules_from_text(base, text))
    return GitIgnore(rules)


def ignore_from_ref(repo, ref):
    names = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", ref],
        cwd=repo, text=True).splitlines()
    pairs = []
    for name in names:
        if name != ".gitignore" and not name.endswith("/.gitignore"):
            continue
        blob = subprocess.check_output(
            ["git", "show", f"{ref}:{name}"], cwd=repo)
        base = name[: -len(".gitignore")].strip("/")
        pairs.append((base, blob.decode("utf-8", "replace")))
    return ignore_from_text(pairs)


def ignore_from_tree(root):
    pairs = []
    for dirpath, _dirs, files in os.walk(root):
        if ".gitignore" not in files:
            continue
        rel = os.path.relpath(dirpath, root).replace("\\", "/")
        base = "" if rel == "." else rel
        with open(os.path.join(dirpath, ".gitignore"),
                  encoding="utf-8", errors="replace") as f:
            pairs.append((base, f.read()))
    return ignore_from_text(pairs)


# ---------------------------------------------------------------- exclude
def exclude_reason(rel, ignore):
    """Why `rel` must not be in a snapshot, or None when it may."""
    rel = rel.replace("\\", "/").strip("/")
    if not rel:
        return None
    for prefix in ALWAYS_PREFIXES:
        if rel == prefix or rel.startswith(prefix + "/"):
            return prefix + "/"
    if rel in ALWAYS_EXACT:
        return rel
    base = rel.rsplit("/", 1)[-1]
    for pat in ALWAYS_GLOBS:
        if fnmatch.fnmatch(base.lower(), pat.lower()):
            return pat
    if ignore is not None and ignore.ignored(rel):
        return "gitignore"
    return None


# ---------------------------------------------------------------- scrub
def load_scrub(path=None):
    path = path or SCRUB_PATH
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise PublicSourceError(f"{path} has no entries list")
    return data


def enabled_strings(scrub):
    """(entry id, string) for entries the scan enforces."""
    out = []
    for entry in scrub["entries"]:
        if not entry.get("enabled"):
            continue
        for text in entry.get("strings") or []:
            if isinstance(text, str) and text:
                out.append((str(entry.get("id") or "scrub"), text))
    return out


# ---------------------------------------------------------------- scan
def _line_of(data, index):
    return data[:index].count(b"\n") + 1


def _first(data, needle):
    """Byte index of needle, case-insensitive for ASCII, or -1."""
    if isinstance(needle, str):
        needle = needle.encode("utf-8")
    return data.lower().find(needle.lower())


def scan(root, ignore=None, scrub=None, allow=()):
    """A list of problems in `root`. Empty when the snapshot is clean.

    `ignore` defaults to the .gitignore files inside `root`. `scrub`
    defaults to the list next to this tool.
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise PublicSourceError(f"not a folder: {root}")
    if ignore is None:
        ignore = ignore_from_tree(root)
    if scrub is None:
        scrub = load_scrub()
    strings = enabled_strings(scrub)
    findings = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        if rel_dir != ".":
            why = exclude_reason(rel_dir, ignore)
            if why:
                findings.append(f"{rel_dir}: excluded path ({why})")
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = name if rel_dir == "." else rel_dir + "/" + name
            why = None if rel in allow else exclude_reason(rel, ignore)
            if why:
                findings.append(f"{rel}: excluded path ({why})")
                continue
            if os.path.islink(path):
                findings.append(f"{rel}: symbolic link")
                continue
            try:
                size = os.path.getsize(path)
            except OSError as e:
                findings.append(f"{rel}: could not read ({e.__class__.__name__})")
                continue
            if size > MAX_SCAN:
                findings.append(
                    f"{rel}: file is too large to scan ({size} bytes)")
                continue
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError as e:
                findings.append(f"{rel}: could not read ({e.__class__.__name__})")
                continue
            if len(data) == 32 and not _is_text(data):
                findings.append(f"{rel}: 32-byte binary secret")
            _scan_bytes(rel, data, strings, findings)
    findings.sort()
    return findings


def _is_text(data):
    for b in data:
        if b in (9, 10, 13):
            continue
        if b < 32 or b >= 127:
            return False
    return True


def _scan_bytes(rel, data, strings, findings):
    seen_lines = set()
    for hit in _USERNAME.finditer(data):
        line = _line_of(data, hit.start())
        if ("user", line) not in seen_lines:
            seen_lines.add(("user", line))
            findings.append(f"{rel}:{line}: username")
    seen_lines = set()
    for hit in _WIN_USER.finditer(data):
        if _placeholder_user(hit.group(1)):
            continue
        line = _line_of(data, hit.start())
        if line not in seen_lines:
            seen_lines.add(line)
            findings.append(f"{rel}:{line}: Windows user path")
    reported = set()
    for entry_id, text in strings:
        idx = _first(data, text)
        if idx < 0:
            continue
        item = (entry_id, _line_of(data, idx))
        if item in reported:
            continue
        reported.add(item)
        findings.append(
            f"{rel}:{item[1]}: scrubbed string ({entry_id})")


# ---------------------------------------------------------------- readme
def readme_text(ref, sha):
    label = _label(ref, sha)
    return f"""# QuantiSheet

This directory is the corresponding source for QuantiSheet release {label}
(commit {sha}).

QuantiSheet is a program for reviewing and marking up PDFs, measuring
quantities from drawings, estimating, signing documents, and collaborating
on a drawing live. It has a desktop application, a small web page for a
phone on the same network, and a command line.

## Licence

QuantiSheet is released under the GNU Affero General Public License,
version 3 (AGPL-3.0). You may copy, modify, and share this source under
that licence. The licence text is published by the Free Software Foundation:
https://www.gnu.org/licenses/agpl-3.0.html

If you run a modified version on a server for other people, that licence
requires you to offer them the corresponding source.

## Build

Python 3.12 is the version the project uses. Python 3.10 or newer can run
it. From this directory:

    python -m venv .venv

On macOS or Linux, activate that environment and install the dependencies:

    source .venv/bin/activate
    pip install -r requirements.txt
    ./build.sh

On Windows, activate it with `.venv\\Scripts\\activate`, install the same
requirements file, and run `build.bat`.

The program is written to `dist/QuantiSheet/`.

To run the tests, install pytest (`pip install pytest`) and run `pytest`.
On a machine with no display, set QT_QPA_PLATFORM=offscreen first.
"""


def _label(ref, sha):
    if ref.upper() == "HEAD" or re.fullmatch(r"[0-9a-fA-F]{7,40}", ref):
        return sha
    return ref


# ---------------------------------------------------------------- export
def _git_sha(repo, ref):
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
            cwd=repo, text=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip()
        raise PublicSourceError(
            f"not a commit: {ref}" + (f" ({err})" if err else "")) from e
    return out.strip()


def _inside(path, root):
    path = os.path.realpath(path)
    root = os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def _extract(repo, sha, outdir, ignore):
    """Write the archive into outdir. Returns paths that were left out."""
    proc = subprocess.Popen(
        ["git", "archive", "--format=tar", sha],
        cwd=repo, stdout=subprocess.PIPE)
    left_out = []
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for member in tar:
                name = member.name.replace("\\", "/").lstrip("/")
                while name.startswith("./"):
                    name = name[2:]
                if not name or name.startswith("/") or ".." in name.split("/"):
                    raise PublicSourceError(
                        f"git archive produced an unsafe path: {member.name}")
                is_dir = member.isdir() or name.endswith("/")
                rel = name.rstrip("/")
                if exclude_reason(rel, ignore):
                    left_out.append(rel + ("/" if is_dir and rel else ""))
                    continue
                try:
                    tar.extract(member, outdir, set_attrs=False, filter="data")
                except (tarfile.FilterError, tarfile.AbsolutePathError,
                        tarfile.OutsideDestinationError) as e:
                    raise PublicSourceError(
                        f"refusing to extract {name}: {e}") from e
    finally:
        rc = proc.wait()
    if rc != 0:
        raise PublicSourceError(f"git archive failed ({rc})")
    return left_out


def commit_commands(outdir, ref, sha):
    """The snapshot commit, for a new repository folder. Not executed."""
    label = _label(ref, sha)
    message = f"QuantiSheet {label} corresponding source"
    quoted_out = '"' + outdir.replace('"', "") + '"'
    return "\n".join([
        "Snapshot commit, in a NEW repository folder (not run):",
        f"cd {quoted_out}",
        "git init -b main",
        "git add --all",
        "git -c user.name=" + AUTHOR_NAME
        + " -c user.email=" + AUTHOR_EMAIL
        + ' commit --author="' + AUTHOR + '" -m "' + message + '"',
        "",
        "Publishing to the public repository " + PUBLIC_REPO
        + " (not run, and this tool never pushes):",
        "git remote add origin <url of " + PUBLIC_REPO + ">",
        "git push -u origin main",
        'git tag -a "' + label + '" -m "' + message + '"',
        'git push origin "' + label + '"',
    ])


def export(ref, outdir, repo=None, scrub_path=None, add=None):
    """Export `ref` into an empty `outdir`. Returns a result dict.

    `add` maps snapshot paths to files on disk for what the program ships
    but git does not hold (REQUIRED_UNTRACKED); each is copied in and
    scanned like the rest.

    The scan findings are in `findings`. `ok` is true when that list is
    empty. This function does not commit and does not push.
    """
    repo = os.path.abspath(repo or ROOT)
    outdir = os.path.abspath(outdir)
    if _inside(outdir, repo):
        raise PublicSourceError(
            f"{outdir} is inside the source repository; "
            "choose a folder outside it")
    if os.path.isdir(outdir) and os.listdir(outdir):
        raise PublicSourceError(f"{outdir} is not empty")
    os.makedirs(outdir, exist_ok=True)
    sha = _git_sha(repo, ref)
    ignore = ignore_from_ref(repo, sha)
    left_out = _extract(repo, sha, outdir, ignore)
    add = dict(add or {})
    added = []
    for rel, src in sorted(add.items()):
        rel = rel.replace("\\", "/").strip("/")
        if not rel or ".." in rel.split("/") or (
                rel in ALWAYS_EXACT and rel not in REQUIRED_UNTRACKED):
            raise PublicSourceError(f"can't add {rel!r} to a snapshot")
        if not os.path.isfile(src):
            raise PublicSourceError(f"--add {rel}: no file at {src}")
        dest = os.path.join(outdir, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(src, dest)
        added.append(rel)
    scrub = load_scrub(scrub_path)
    readme = os.path.join(outdir, README_NAME)
    with open(readme, "w", encoding="utf-8", newline="\n") as f:
        f.write(readme_text(ref, sha))
    # Scan with the tree's own gitignore plus the never-publish list.
    findings = scan(outdir, ignore=ignore_from_tree(outdir), scrub=scrub,
                    allow=set(added))
    for rel in REQUIRED_UNTRACKED:
        if rel not in added:
            findings.append(
                f"{rel}: missing - the program ships it; pass "
                f"--add {rel}=<the release build's copy>")
    findings.sort()
    return {
        "added": added,
        "ok": not findings,
        "findings": findings,
        "left_out": left_out,
        "outdir": outdir,
        "ref": ref,
        "sha": sha,
        "commands": commit_commands(outdir, ref, sha),
    }


def _print_result(result):
    print(f"snapshot of {result['ref']} ({result['sha']})")
    print(f"folder: {result['outdir']}")
    n = len(result["left_out"])
    print(f"left out {n} path(s) covered by .gitignore or the never-publish list")
    for rel in result["left_out"]:
        print(f"  left out {rel}")
    for rel in result.get("added") or ():
        print(f"  added {rel} (shipped in the program, not in git)")
    if result["findings"]:
        print(f"public source scan failed, {len(result['findings'])} finding(s):")
        for line in result["findings"]:
            print(f"  {line}")
        print("No snapshot commit: the scan failed. Do not publish this folder.")
        return
    files = 0
    for _base, _dirs, names in os.walk(result["outdir"]):
        files += len(names)
    print(f"public source scan passed ({files} files)")
    print()
    print(result["commands"])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(argv) == 2 and argv[0] == "--scan":
            findings = scan(argv[1])
            if findings:
                print(f"public source scan failed, {len(findings)} finding(s):")
                for line in findings:
                    print(f"  {line}")
                return 1
            print("public source scan passed")
            return 0
        add = {}
        while "--add" in argv:
            i = argv.index("--add")
            if i + 1 >= len(argv) or "=" not in argv[i + 1]:
                print("--add needs SNAPSHOT_PATH=FILE", file=sys.stderr)
                return 2
            rel, _eq, src = argv[i + 1].partition("=")
            add[rel] = src
            del argv[i:i + 2]
        if len(argv) != 2:
            print("usage: python tools/public_source.py <ref> <empty-folder>"
                  " [--add app/onboard.py=FILE]", file=sys.stderr)
            print("       python tools/public_source.py --scan <folder>",
                  file=sys.stderr)
            return 2
        result = export(argv[0], argv[1], add=add)
    except PublicSourceError as e:
        print(f"public source: {e}", file=sys.stderr)
        return 2
    _print_result(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
