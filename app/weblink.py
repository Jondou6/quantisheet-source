"""quantisheet:// links (Jon, Nov 25: the browser extension "Open in
QuantiSheet").

The extension saves a PDF to this computer, then opens

    quantisheet://open?path=<the saved file>

Windows starts QuantiSheet with that link as its argument (the setup
registers the link type), and files() turns it into the file to open.
Nothing is downloaded or run from a link: it can only name a PDF that is
already on this computer. Anything else - another kind of file, a network
(UNC) path, a web address, a file that doesn't exist - is ignored.
"""
import os
from urllib.parse import parse_qs, unquote, urlsplit

SCHEME = "quantisheet"
MAX_LINK = 2000


def path_from(link):
    """The local PDF a quantisheet://open link names, or None."""
    if not isinstance(link, str) or len(link) > MAX_LINK:
        return None
    try:
        u = urlsplit(link.strip().strip('"'))
    except ValueError:
        return None
    if u.scheme.lower() != SCHEME or \
            (u.netloc or u.path.strip("/")).lower() != "open":
        return None
    raw = (parse_qs(u.query).get("path") or [""])[0]
    path = unquote(raw) if "%" in raw else raw
    if not path or "\x00" in path:
        return None
    # this computer's own drives only: no \\server\share, no //host, no
    # web address or device path
    if path.startswith(("\\\\", "//")) or "://" in path:
        return None
    if not os.path.isabs(path) or not path.lower().endswith(".pdf"):
        return None
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        return None
    return path


def files(argv):
    """The PDFs named by quantisheet:// links among the arguments."""
    out = []
    for a in argv[1:]:
        if isinstance(a, str) and a.lower().startswith(SCHEME + ":"):
            p = path_from(a)
            if p:
                out.append(p)
    return out
