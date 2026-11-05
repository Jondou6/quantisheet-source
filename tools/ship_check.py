"""Files that must never ship (review 0.12.35 #21): research briefs and
reviews, notes for Claude, real client documents (private/), and anything
Xactimate / SageSure / EagleView (no ESX import/export, no Xactimate data,
no aerial roof reports), and licensed cost-book data (RSMeans, Gordian,
Craftsman's National Construction Estimator) - the data, not the code that
imports a customer's own copy (app/rsmeans.py).

The source folder on Jon's PC has these at its top level; they stay out of
the build because the spec only packages app/ and named assets. This
module is the explicit check on top of that: the build, the release zip
and the source zip call it on what they are about to package and stop if
anything matches. It works on names and paths only, so it can be tested
without the files.

A folder named exactly "private" is refused anywhere in the tree (only
code may be in one), and review documents are refused in every folder
(review of tonight's changes #6).

    problems(paths) -> ["<path>: <why>"]    (empty when clean)
    scan_tree(root) -> the same for every file under root
    require_clean(paths_or_root, what)       raises RuntimeError
"""
import fnmatch
import os
import re

DOC_EXT = (".md", ".pdf", ".docx", ".doc", ".txt", ".rtf", ".html", ".htm")

# names that never ship, wherever they are (case doesn't matter)
NEVER_NAMES = [
    "*deep_dive*", "*deep-dive*", "*deepdive*",
    "for_claude_*", "for_claude.*",
    "*xactimate*", "*sagesure*", "*eagleview*",
    "*.esx",
]
# licensed cost-book data (review 0.12.38 #11): RSMeans / Gordian, Craftsman
# National Construction Estimator. Refused as data or documents only -
# app/rsmeans.py is the importer (code, no prices) and ships; the licensed
# export it reads ("RSMeans assemblies.txt") never does. Craftsman is
# matched with its book's name, so a "craftsman" house style would pass.
LICENSED_DATA_NAMES = [
    "*rsmeans*", "*rs means*", "*rs_means*", "*rs-means*", "*rs.means*",
    "*gordian*",
    "*craftsman*estimator*", "*craftsman book*", "*craftsman_book*",
    "*national construction estimator*", "*national_construction_estimator*",
    "*national estimator*", "*national_estimator*",
    # BNi Building News / eConverge (review 0.12.39 #6): "bni" only as a
    # word, so "combined" or "ebnight" style names aren't caught
    "bni", "bni[_ .-]*", "*[_ .-]bni", "*[_ .-]bni[_ .-]*",
    "*building news*", "*building_news*", "*buildingnews*",
    "*econverge*", "*e-converge*", "*e_converge*",
]
# research briefs: ROOF_PLAN_TAKEOFF_BRIEF.md and the like (a document,
# not a module - app/genset/brief.py is code)
_BRIEF = re.compile(r"(^|[_\- ])brief([_\- .]|$)", re.I)
_REVIEW = re.compile(r"review", re.I)
_REVIEW_WORD = re.compile(r"(^|[^a-z])review", re.I)
# files that may sit in a folder named private/ outside app/ and docs/
# (code, not client documents)
CODE_EXT = (".py", ".pyc", ".pyo", ".pyd", ".pyi", ".pxd", ".pyx",
            ".so", ".dll", ".dylib", ".h", ".hpp", ".hxx", ".c", ".cc",
            ".cpp", ".cxx", ".inl", ".js", ".mjs", ".qml", ".qmltypes",
            ".qmlc", ".jsc")

# documents allowed at the top of a package / zip
TOP_OK = ["readme.md", "license*", "licence*", "* - whats new.pdf",
          "beta-agreement.txt", "read me first.txt", "sha256sums.txt",
          "* sha256.txt", "third_party_notices*", "notice*"]


def _parts(path):
    p = str(path).replace("\\", "/").strip("/")
    while p.startswith("./"):
        p = p[2:]
    parts = [x for x in p.split("/") if x not in ("", ".")]
    # PyInstaller one-folder builds put everything under _internal/
    if parts and parts[0].lower() == "_internal":
        parts = parts[1:]
    return parts


def why(path):
    """Why `path` (relative to the package / zip root) must not ship, or
    None when it may."""
    parts = _parts(path)
    if not parts:
        return None
    name = parts[-1].lower()
    for pat in NEVER_NAMES:
        if fnmatch.fnmatch(name, pat):
            return f"matches {pat!r} (research / third-party data)"
    if not name.endswith(CODE_EXT):
        for pat in LICENSED_DATA_NAMES:
            if fnmatch.fnmatch(name, pat):
                return f"matches {pat!r} (licensed cost data)"
    is_doc = name.endswith(DOC_EXT)
    if is_doc and _BRIEF.search(os.path.splitext(name)[0]):
        return "a research brief"
    ours = len(parts) == 1 or parts[0].lower() in ("app", "docs")
    in_private = "private" in (x.lower() for x in parts[:-1])
    if ours and in_private:
        return "in a private/ folder (real client documents)"
    if len(parts) > 1 and parts[0].lower() == "private":
        return "in a private/ folder (real client documents)"
    # anywhere else (tests/, data/, server/, installer/, quantisheet_claims/,
    # third-party packages in a build): a folder named exactly "private"
    # holds client documents - only code may sit in one (Qt's private
    # headers, a package's private modules). "_private.py" or
    # "privateapi/" is not such a folder.
    if in_private and not name.endswith(CODE_EXT):
        return "in a private/ folder (real client documents)"
    if ours and is_doc and _REVIEW.search(name):
        return "a review"
    # outside app/ and docs/ (a word match, so "preview.html" in a
    # third-party package passes)
    if is_doc and _REVIEW_WORD.search(name):
        return "a review"
    if len(parts) == 1 and name.endswith((".md", ".pdf", ".docx", ".doc")) \
            and not any(fnmatch.fnmatch(name, p) for p in TOP_OK):
        return "a top-level document (briefs and reviews stay out)"
    return None


def problems(paths):
    out = []
    for p in paths:
        w = why(p)
        if w:
            out.append(f"{str(p).replace(os.sep, '/')}: {w}")
    return out


def scan_tree(root):
    """problems() for every file under `root` (paths relative to it)."""
    rels = []
    for base, _dirs, files in os.walk(root):
        for f in files:
            rels.append(os.path.relpath(os.path.join(base, f), root))
    return problems(rels)


def require_clean(paths_or_root, what="the build"):
    """Raise RuntimeError naming the files when any must not ship."""
    if isinstance(paths_or_root, (str, os.PathLike)):
        found = scan_tree(paths_or_root)
    else:
        found = problems(paths_or_root)
    if found:
        raise RuntimeError(
            f"{what} would include files that must never ship "
            f"({len(found)}): " + "; ".join(found[:8]) +
            (" ..." if len(found) > 8 else ""))
    return []


# Inno Setup [Files] Excludes for the same names (belt and braces; the
# build fails before Inno runs if any are there)
INNO_EXCLUDES = ("*DEEP_DIVE*,*DEEP-DIVE*,FOR_CLAUDE_*,*XACTIMATE*,"
                 "*SAGESURE*,*EAGLEVIEW*,*.esx,*_BRIEF.md,*_BRIEF.pdf")


# ---- licensed price data by content (Import Your Own Price List) ---------
# A cost book imported from a customer's own licensed price list is
# local-only: its book says "local_only": true and every row carries
# license "local-only" (app/priceimport.py). Such data must never ship in
# the installer, the portable / team zips or app/data/costbooks, so the
# build reads inside the data files it packages (names alone can't tell).
LOCAL_ONLY_MARKERS = (b'"local_only": true', b'"local_only":true',
                      b'"license": "local-only"', b'"license":"local-only"')
DATA_EXT = (".json", ".csv", ".tsv", ".db", ".sqlite", ".sqlite3", ".txt",
            ".xlsx", ".xlsm")
MAX_SCAN = 200 * 1024 * 1024


def _scan_data(rel, data, tags):
    low = rel.lower()
    found = []
    if low.endswith((".db", ".sqlite", ".sqlite3")):
        # a price database: an item row's license column holds local-only
        if b"local-only" in data or b'"local_only": true' in data:
            found.append(f"{rel}: a price database with local-only "
                         "(licensed) rows")
    elif any(m in data for m in LOCAL_ONLY_MARKERS):
        found.append(f"{rel}: a cost book or row tagged local-only "
                     "(licensed price data)")
    for t in tags:
        if t and t.encode("utf-8") in data:
            found.append(f"{rel}: has the licensed source tag {t!r}")
    return found


def local_only_problems(root, tags=()):
    """["<path>: <why>"] for every data file under `root` (a folder, a .zip
    or one file; zip members and .xlsx sheets are read too) holding a
    local-only cost book or row, or any of the source `tags`."""
    import zipfile
    out = []

    def scan(rel, data):
        if rel.lower().endswith((".zip", ".xlsx", ".xlsm")):
            try:
                import io
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for n in z.namelist():
                        if n.lower().endswith(DATA_EXT + (".xml", ".zip")):
                            scan(f"{rel}!{n}", z.read(n))
            except zipfile.BadZipFile:
                pass
            return
        if rel.lower().endswith(DATA_EXT + (".xml",)):
            out.extend(_scan_data(rel, data, tags))

    if os.path.isfile(root):
        files = [(os.path.basename(root), root)]
    else:
        files = []
        for base, _dirs, names in os.walk(root):
            for n in names:
                p = os.path.join(base, n)
                files.append((os.path.relpath(p, root), p))
    for rel, p in files:
        if not rel.lower().endswith(DATA_EXT + (".zip",)):
            continue
        try:
            if os.path.getsize(p) > MAX_SCAN:
                continue
            with open(p, "rb") as f:
                scan(rel.replace(os.sep, "/"), f.read())
        except OSError as e:
            out.append(f"{rel}: couldn't read ({e.__class__.__name__})")
    return out


def require_no_local_only(root, what="the build", tags=()):
    """Raise RuntimeError when `root` holds local-only (licensed) price
    data."""
    found = local_only_problems(root, tags)
    if found:
        raise RuntimeError(
            f"{what} would include licensed, local-only price data "
            f"({len(found)}): " + "; ".join(found[:8]) +
            (" ..." if len(found) > 8 else ""))
    return []
