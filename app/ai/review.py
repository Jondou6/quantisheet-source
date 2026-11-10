"""AI review helpers backed by a local Ollama model.

Nothing leaves the computer: requests go to Ollama on localhost.
"""
import http.client
import json
import logging
import os
import re
import socket
import threading
import urllib.error
import urllib.request

MODEL = os.environ.get("QUANTISHEET_OLLAMA_MODEL", "llama3.2")
HOST = os.environ.get("QUANTISHEET_OLLAMA_HOST", "http://localhost:11434")
TEXT_LIMIT = 24000          # characters of document text sent to the model
# seconds to wait for a reply. A big prompt on a computer without a strong
# graphics card (a conference-room PC, a laptop) can take many minutes, and
# these reviews run in the background, so wait up to 15 minutes.
TIMEOUT = float(os.environ.get("QUANTISHEET_OLLAMA_TIMEOUT") or 900)
KEEP_ALIVE = "30m"          # keep the model loaded between chunks
CONTEXT = 8192              # tokens; Ollama's default is too small for this


def to_page(page, rect):
    from ..annotate import to_page as _tp
    return _tp(page, rect)


log = logging.getLogger(__name__)


class AIError(RuntimeError):
    pass


def _allowed_host(host):
    """The IT department's AI settings (policy.py): off, or another host."""
    from .. import policy
    try:
        policy.check("ai")
    except policy.Blocked as e:
        raise AIError(str(e)) from None
    it_host = policy.get("AIHost")
    host = it_host or host
    if not re.match(r"^https?://[^/\s]+/?$", str(host or "")):
        raise AIError(f"The AI address isn't a plain http(s) host: "
                      f"{str(host)[:80]}")
    if not it_host:
        # this PC only - document text never leaves it - unless the IT
        # department has named an AI server (outside review via Chief,
        # Nov 7 - H7: any address in QUANTISHEET_OLLAMA_HOST was used)
        from . import models
        try:
            return models.check_local(str(host))
        except models.NotLocalError:
            raise AIError("The AI review only talks to the AI on this PC "
                          f"(not {str(host)[:60]}). Your IT department can "
                          "name an AI server in the QuantiSheet policy.") \
                from None
    return str(host).rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None                 # an answer that redirects is an error


class Cancel:
    """Lets another thread end a model request that is still waiting:
    its connection is shut, so Ollama stops working on it and the next
    request isn't queued behind it (Venice, Nov 9 - F15: a skipped part
    kept the model busy and every later part waited longer).

    A socket is registered as soon as the TCP connection exists - for
    https before the TLS handshake - so a cancel also ends a request stuck
    in its handshake (Venice N1). The TCP connect itself isn't covered;
    to the local AI it is immediate. Closing races the reader's own close
    safely: in CPython both read the handle and mark it gone in one step
    under the interpreter lock, so only one of them ever closes it (N2);
    a TLS socket the reader closed first raises ValueError, which is
    ignored (P4-2). finish() forgets the sockets of a request that ended
    normally. A token is for one run: once cancelled it stays cancelled,
    and run_cancellable() needs a Cancel (it calls finish())."""

    def __init__(self):
        self._lock = threading.Lock()
        self._socks = []
        self.cancelled = False

    def register(self, sock):
        with self._lock:
            if self.cancelled:
                raise ConnectionAbortedError("request cancelled")
            self._socks.append(sock)

    def finish(self):
        with self._lock:
            self._socks = []

    def cancel(self):
        with self._lock:
            self.cancelled = True
            socks, self._socks = self._socks, []
        for sk in socks:
            try:
                sk.shutdown(socket.SHUT_RDWR)
            except (OSError, ValueError):
                pass
            # keep the shutdown: with the response still holding the
            # socket (makefile), close() alone would wait and never wake
            # the reader. Then the handle itself is closed: on Windows a
            # shutdown doesn't wake a thread waiting in recv. detach()
            # first so nothing closes that number again later. A TLS
            # socket the reader already closed raises ValueError, not
            # OSError (Venice, Nov 9 - P4-2)
            try:
                fd = sk.detach()
                if fd is not None and fd >= 0:
                    socket.close(fd)
            except (OSError, ValueError):
                pass

    def cancel_soon(self):
        """cancel() on a throwaway thread: never holds up the window
        (Venice N3)."""
        threading.Thread(target=self.cancel, name="ai-cancel",
                         daemon=True).start()


_local = threading.local()


def run_cancellable(token, fn, *args, **kw):
    """fn(*args) with its model requests ended by token.cancel()."""
    _local.cancel = token
    try:
        return fn(*args, **kw)
    finally:
        _local.cancel = None
        token.finish()


def _token():
    token = getattr(_local, "cancel", None)
    if token is not None and token.cancelled:
        raise ConnectionAbortedError("request cancelled")
    return token


class _Closing:
    def close(self):
        """A TLS socket that cancel() already closed raises ValueError on
        close(); urllib closes the connection while handling the real
        error, and that ValueError would replace it (Venice, Nov 9 -
        P4-3)."""
        try:
            super().close()
        except ValueError:
            # only the closed-socket case is expected; anything else is
            # logged rather than silently dropped (F5-4)
            log.debug("closing a connection cancel() already closed",
                      exc_info=True)
            self.sock = None


class _Conn(_Closing, http.client.HTTPConnection):
    def connect(self):
        token = _token()
        super().connect()
        if token is not None:
            token.register(self.sock)


class _ConnS(_Closing, http.client.HTTPSConnection):
    def connect(self):
        """HTTPSConnection.connect, split so the TLS socket is registered
        before the handshake. HTTPConnection.connect makes the TCP
        connection and, if a tunnel was set, the CONNECT through it. The
        AI opener has no proxy (ProxyHandler({})), but the name checked is
        the tunnel host when there is one, as the standard library does
        (Venice, Nov 9 - P4-1)."""
        token = _token()
        http.client.HTTPConnection.connect(self)
        # a cancel during the TCP connect or a tunnel's CONNECT can't
        # interrupt it (nothing is registered yet); it is honoured here,
        # before any handshake is spent (Venice, Nov 9 - F5-1)
        if token is not None and token.cancelled:
            raise ConnectionAbortedError("request cancelled")
        # wrap, take ownership, then register - so a cancel at any point
        # finds the socket the connection will close (P4-4)
        sock = self._context.wrap_socket(
            self.sock, server_hostname=self._tunnel_host or self.host,
            do_handshake_on_connect=False)
        self.sock = sock
        if token is not None:
            token.register(sock)         # raises if already cancelled
        try:
            sock.do_handshake()
        except (OSError, ValueError) as e:
            # a handshake on a socket closed by cancel() raises ValueError
            # ("closed socket"): say what happened instead (P4-3), keeping
            # the real error as the cause (F5-3)
            if token is not None and token.cancelled:
                raise ConnectionAbortedError("request cancelled") from e
            raise


_SSL_CONTEXT = None                # tests: a context for a test certificate


class _HTTP(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_Conn, req)


class _HTTPS(urllib.request.HTTPSHandler):
    def __init__(self):
        super().__init__(context=_SSL_CONTEXT)

    def https_open(self, req):
        return self.do_open(_ConnS, req, context=self._context)


def _opener():
    """Straight to the AI host: no system/env proxy (document text must
    not pass through one) and no redirects to another address (threat
    model T-009, as Back Office's local AI already does). Connections can
    be ended from another thread (Cancel)."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                       _NoRedirect(), _HTTP(), _HTTPS())


def _slow(model):
    return (f"The local AI ({model}) didn't answer within "
            f"{TIMEOUT / 60:g} minutes. This computer may be too slow for it "
            "(no strong graphics card), or the model is still loading. Try "
            "again - the model stays loaded for 30 minutes after a run.")


def _ollama(prompt, model=MODEL, host=HOST, json_mode=False):
    host = _allowed_host(host)
    body = {"model": model, "prompt": prompt, "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": {"num_ctx": CONTEXT, "temperature": 0.2}}
    if json_mode:
        body["format"] = "json"
    req = urllib.request.Request(f"{host}/api/generate",
                                 json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        raw = _send(req, model)
    except AIError:
        tok = getattr(_local, "cancel", None)
        if tok is not None and tok.cancelled:
            raise AIError("Stopped before the model answered.") from None
        raise
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise AIError("Ollama sent a reply that isn't JSON. Is "
                      f"{host} really Ollama?") from e
    return _response(data)


def _send(req, model):
    try:
        with _opener().open(req, timeout=TIMEOUT) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:200]
        if e.code == 404:
            raise AIError(f"The AI model '{model}' isn't installed. See "
                          "Help > Help Center & Tutorials > Set up the local "
                          f"AI (ollama pull {model}).") from e
        raise AIError(f"Ollama error {e.code}: {detail}") from e
    except TimeoutError as e:
        raise AIError(_slow(model)) from e
    except (urllib.error.URLError, ConnectionError) as e:
        if isinstance(getattr(e, "reason", None), TimeoutError):
            raise AIError(_slow(model)) from e
        raise AIError("The local AI isn't running on this PC. See Help > "
                      "Help Center & Tutorials > Set up the local AI "
                      f"(Ollama, model {model}).") from e
    except (http.client.HTTPException, OSError) as e:
        if getattr(e, "errno", None) == 28:              # ENOSPC
            raise AIError("The disk is full, so the local AI can't run. "
                          "Free some space and try again.") from e
        raise AIError(f"Lost the connection to Ollama ({e.__class__.__name__})."
                      " Try again.") from e


def _response(data):
    if not isinstance(data, dict):
        raise AIError("Ollama sent an unexpected reply.")
    if "response" not in data:
        err = str(data.get("error") or "no response in the reply")[:200]
        raise AIError(f"Ollama error: {err}")
    if not isinstance(data["response"], str):
        raise AIError("Ollama sent an unexpected reply.")
    return data["response"]


def stream(prompt, on_text=None, model=None, host=HOST, num_ctx=2048,
           num_predict=220, timeout=None):
    """A short generation, streamed: on_text(piece) is called as tokens
    arrive (from the calling thread). Returns the whole reply. The model
    stays loaded for 30 minutes so the next draft starts at once (v36)."""
    model = model or MODEL
    host = _allowed_host(host)
    body = {"model": model, "prompt": prompt, "stream": True,
            "keep_alive": KEEP_ALIVE,
            "options": {"num_ctx": num_ctx, "num_predict": num_predict,
                        "temperature": 0.1}}
    req = urllib.request.Request(f"{host}/api/generate",
                                 json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    out = []
    try:
        with _opener().open(req, timeout=timeout or TIMEOUT) as r:
            for line in r:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("error"):
                    raise AIError(f"Ollama error: {str(d['error'])[:200]}")
                piece = d.get("response") or ""
                if piece:
                    out.append(piece)
                    if on_text:
                        on_text(piece)
                if d.get("done"):
                    break
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise AIError(f"The AI model '{model}' isn't installed. See "
                          "Help > Help Center & Tutorials > Set up the local "
                          f"AI (ollama pull {model}).") from e
        raise AIError(f"Ollama error {e.code}") from e
    except (TimeoutError, urllib.error.URLError, ConnectionError,
            http.client.HTTPException, OSError) as e:
        if isinstance(e, AIError):
            raise
        raise AIError("Can't reach Ollama (the draft above is complete "
                      "without it).") from e
    return "".join(out)


def _text_info(doc, limit=TEXT_LIMIT):
    """Document text with page markers, plus how much of it fits:
    (text, {"sent", "total", "pages", "page_count", "cut"})."""
    parts = [f"[Page {i + 1}]\n{p.get_text()}" for i, p in enumerate(doc)]
    full = "\n".join(parts)
    pages, pos = 0, 0
    for part in parts:
        pos += len(part) + (1 if pages else 0)
        if pos > limit:
            break
        pages += 1
    sent = min(len(full), limit)
    return full[:limit], {"sent": sent, "total": len(full), "pages": pages,
                          "page_count": len(parts),
                          "cut": len(full) > limit}


def page_parts(doc):
    """Each page's text with its marker, read once (on the GUI thread)."""
    return [f"[Page {i + 1}]\n{p.get_text()}" for i, p in enumerate(doc)]


def chunks(parts, first=0, last=None, limit=None):
    """Pages first..last (0-based, inclusive) cut into parts that each fit
    the model: [(text, first page, last page)]. A page longer than the
    limit is split into pieces of its own ("[Page 7, piece 2 of 3]") -
    nothing is dropped, so "the whole document" means all of its text
    (Chief's re-test, Nov 7: a 36,036-character page lost its tail)."""
    limit = TEXT_LIMIT if limit is None else limit
    last = len(parts) - 1 if last is None else min(last, len(parts) - 1)
    out, buf, a = [], [], first
    size = 0

    def flush(end):
        nonlocal buf, size
        if buf:
            out.append(("\n".join(buf), a, end))
        buf, size = [], 0

    for i in range(max(0, first), last + 1):
        t = parts[i]
        if len(t) > limit:
            flush(i - 1)
            head = f"[Page {i + 1}, piece {{k}} of {{n}}]\n"
            room = max(100, limit - len(head) - 8)
            body = t
            pieces = [body[k:k + room] for k in range(0, len(body), room)]
            for k, piece in enumerate(pieces, 1):
                out.append((head.format(k=k, n=len(pieces)) + piece, i, i))
            a = i + 1
            continue
        if buf and size + len(t) + 1 > limit:
            flush(i - 1)
            a = i
        if not buf:
            a = i
        buf.append(t)
        size += len(t) + 1
    flush(last)
    return out


def range_note(parts, first, last, n):
    """'Pages 1-9 of 687 (2% of the text), in 1 part.'"""
    total = sum(len(p) for p in parts) or 1
    last = min(last, len(parts) - 1)
    share = sum(len(parts[i]) for i in range(first, last + 1))
    np = len(parts)
    where = (f"The whole document ({np} page{'s' if np != 1 else ''})"
             if first == 0 and last == len(parts) - 1 else
             f"Pages {first + 1}-{last + 1} of {len(parts)} "
             f"({100 * share / total:.0f}% of the text)")
    slow = SLOW if n > 1 else ""
    return f"{where}, in {n} part{'s' if n != 1 else ''}{slow}."


def _k(n):
    return f"{n / 1000:.0f}k" if n >= 10000 else f"{n:,}"


# said before a run, taken off the line once it has finished
SLOW = " - one model call each, so it can take a while"


def coverage_note(info):
    """'Reviewed 24k of 900k characters (pages 1-3 of 120 in full).'"""
    if not info["cut"]:
        return f"Reviewed the whole document ({info['total']:,} characters)."
    pct = 100 * info["sent"] / info["total"] if info["total"] else 100
    return (f"Reviewed {_k(info['sent'])} of {_k(info['total'])} characters "
            f"({pct:.0f}%): pages 1-{max(info['pages'], 1)} of "
            f"{info['page_count']}. The rest was not reviewed.")


def doc_text_info(doc):
    return _text_info(doc)


def _text(doc, limit=TEXT_LIMIT):
    """Document text with page markers. Returns (text, truncated)."""
    text, info = _text_info(doc, limit)
    return text, info["cut"]


def _items(raw, key):
    """Pull a list out of the model's JSON reply, tolerating sloppy output.
    A reply that can't be read at all (cut off mid-string - often at an
    inch mark like 8") is reported, never taken as "no suggestions"
    (Grok r5 #13)."""
    try:
        data = json.loads(raw)
    except ValueError:
        m = re.search(r"\[.*\]", raw, re.S)
        try:
            data = json.loads(m.group(0)) if m else None
        except ValueError:
            data = None
        if data is None:
            if raw and raw.strip():
                raise AIError("The AI reply was cut off or garbled, so "
                              "nothing was used. Try again, or on fewer "
                              "pages.")
            data = []
    if isinstance(data, dict):
        data = data.get(key, [])
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


# The *_text functions take text already extracted on the GUI thread, so
# the slow model call can run in the background without touching the
# document (PyMuPDF documents must not be used from two threads at once).

def doc_text(doc):
    return _text(doc)


def summarize(doc):
    text, info = _text_info(doc)
    return summarize_text(text, info["cut"], coverage_note(info))


SUMMARY_PROMPT = (
    "Summarize this document in 5 bullet points, then list any spec numbers "
    "and fire ratings mentioned. Use only what the text below says: if a "
    "date, author, file format or sheet is not written in it, leave it out "
    "- never guess, and never list the same sheet twice. Write an "
    "abbreviation (RCP, MEP, GWB...) as it is written; spell it out only "
    "when the spelled-out words are in the text. Give a sheet number or a "
    "drawing scale only exactly as the text writes it. ")


def set_sheets(doc):
    """Sheet numbers read from each page's title block, in page order -
    the sheets that are in this set (read on the window's thread)."""
    from .. import sheets
    out = []
    for page in doc:
        try:
            r = page.rect
            num, _t = sheets.sheet_info(sheets.page_words(page), r.width,
                                        r.height)
        except Exception:                                 # noqa: BLE001
            num = ""
        if num and num not in out:
            out.append(num)
    return out


# a letter may follow the number (A-101A, M-501A, A-100.5A): taken whole,
# so a made-up one is checked too (Venice, Nov 9 - F5-7)
# - but not on a bare letter-digit-letter (H2O, B2B are not sheets)
_SHEET_REF = re.compile(
    r"\b([A-Z]{1,2}(?:-\d{1,3}|\d{2,3})(?:\.\d{1,2})?[A-Z]?|"
    r"[A-Z]{1,2}-?\d{1,3}(?:\.\d{1,2})?)\b")
# refrigerants read like sheet numbers (R-410A, R-22, R-454B): never sheets
# (every 400- and 500-series blend, with any letter: R-410B too)
_REFRIGERANT = re.compile(
    r"^R-?(?:11|12|22|32|123|134A|290|[45]\d\d[A-Z]?|600A?|717|744|"
    r"1234(?:YF|ZE))$")
# A sheet number as a summary may write it (Chief's round 7, Nov 9): any
# case with a hyphen (a-101a), four digits with a hyphen (A-1011), one or
# two letters after it, with or without a hyphen (A-101AA, A-101-A), and
# "/B" alternates (A-101A/B). Without a hyphen only capitals count - "co2"
# and "b12" are not sheets.
_SHEET_ANY = re.compile(
    r"(?<![\w-])([A-Za-z]{1,2})(-?)(\d{1,4})((?:\.\d{1,2})?)"
    r"((?:-?[A-Za-z]{1,2})?)((?:/[A-Za-z](?![\w-]))*)(?!\w)")


def _in_mark(text, at):
    """Whether position `at` is inside a "(no such sheet...: A-101B)" mark
    this check wrote (a second run leaves those names alone)."""
    open_ = text.rfind("(", 0, at)
    if open_ < 0 or ")" in text[open_:at]:
        return False
    return text.startswith(("(no such sheet", "(not in the part"), open_)


def _sheet_keys(m):
    """The sheets one _SHEET_ANY match names, as (shown, key) pairs - key
    without hyphens or dots, in capitals - or [] when it isn't a sheet."""
    pre, hyphen, digits, dec, suf, alts = m.groups()
    if not hyphen and (pre != pre.upper() or len(digits) > 3 or
                       suf != suf.upper() or
                       (suf and len(digits) < 2)):     # H2O, B2B
        return []
    suf = suf.lstrip("-").upper()
    base = pre.upper() + "-" + digits + dec
    names = [base + suf] + [base + a.upper() for a in alts.split("/") if a]
    return [(n, n.replace("-", "").replace(".", "")) for n in names]


def referenced_sheets(text, in_set):
    """Sheet numbers the text mentions that aren't in the set. Only the
    disciplines the set itself uses count (A-302 next to A-101), so an
    accessory model number such as B-233 is never taken for a sheet
    (Chief's re-test, Nov 7). With no set sheets known, none."""
    from .. import sheets
    if not in_set:
        return []
    prefixes = {re.match(r"[A-Z]+", x).group(0) for x in in_set
                if re.match(r"[A-Z]+", x)}
    have = {x.replace("-", "").replace(".", "") for x in in_set}
    out = []
    for m in _SHEET_REF.finditer(text or ""):
        sh = m.group(1)
        if not sheets.DISCIPLINE.match(sh) or sh.startswith("ZZ"):
            continue
        if re.match(r"[A-Z]+", sh).group(0) not in prefixes:
            continue
        if sh.replace("-", "").replace(".", "") in have or sh in out:
            continue
        out.append(sh)
    return out


_W = r"[A-Za-z][\w&/'-]*"
_WORDS = rf"(?:{_W}\s+){{0,5}}{_W}"
# "CB" for ceiling / CB for Ceiling Board / 'DS' as door (the real
# model line, Chief's round 4: '"CB" for ceiling, "DS" for door, and
# "OH" for overhead')
# checked loosely: only when quoted or when the words spell it
_FOR_RX = re.compile(
    rf"[\"'\u201c\u2018]?\b([A-Z]{{2,6}})\b[\"'\u201d\u2019]?"
    rf"\s+(?:for|as)\s+(?:a\s+|an\s+|the\s+)?[\"']?({_WORDS})[\"']?")
_EXPAND = (
    # Words Words (ABC)
    (re.compile(rf"\b({_WORDS})\s*\(([A-Z]{{2,6}})\)"), False),
    # ABC (Words Words) / ABC (for Words)
    (re.compile(rf"\b([A-Z]{{2,6}})\s*\((?:for\s+)?({_WORDS})\)"), True),
    # ABC = Words / ABC: Words / ABC - Words
    (re.compile(rf"\b([A-Z]{{2,6}})\s*(?:=|:|-|–)\s*[\"']?({_WORDS})[\"']?"),
     True),
    (_FOR_RX, True),
    # ABC stands for / means / refers to / is (a|an|the) Words
    (re.compile(rf"\b([A-Z]{{2,6}})\b,?\s+(?:stands for|means|refers to|"
                rf"is short for|indicates|denotes|represents|marks|"
                rf"designates|labels|is used for|is)\s+(?:a\s+|an\s+|the\s+)?[\"']?"
                rf"({_WORDS})[\"']?"), True),
)


_SEP = r"[\s=:/\-\u2013(),.;]{1,4}"


def _defined_near(source, acro, words, reach=80):
    """Whether the document itself defines `acro` as `words`, the way a
    legend or label does: the abbreviation, a separator, then the words
    (up to three words may come between: "ET/FOLD DOWN EXAM TABLE"), or
    the words then the abbreviation ("REFLECTED CEILING PLAN (RCP)").
    Just being on the same sheet isn't enough (Chief's round 4, Nov 7: DS
    became a door and CB a ceiling because DOOR and CEILING were printed
    near them). `reach` is kept for old callers."""
    src = " ".join((source or "").split())
    w = r"\s+".join(re.escape(x) for x in words.split())
    if not w:
        return False
    a = rf"(?-i:{re.escape(acro)})"                # as written: DS, not ds
    gap = r"(?:[\w&'-]+\s+){0,3}"
    # words in between only after a legend mark (= : /), not a space:
    # "CB 2X4 ACT CEILING" doesn't make CB a ceiling
    tag = r"(?:-\d+[A-Z]?)?"                      # AHU-1, RTU-2A
    # a bare space between them counts only when the words spell it
    # ("RCP REFLECTED CEILING PLAN"); "DS DOOR HARDWARE" is two labels
    ws = words.split()
    spelled = ("".join(x[0] for x in ws).upper() == acro.upper())
    sep = _SEP if spelled else r"\s*[=:/(),.;\-\u2013]\s*"
    after = (rf"(?<![\w-]){a}{tag}(?![\w-])(?:\s*[=:/]\s*{gap}|{sep})"
             rf"{w}\b")
    before = rf"\b{w}{sep}{a}{tag}(?![\w-])"
    return bool(re.search(after, src, re.I) or
                re.search(before, src, re.I))


def check_expansions(reply, source):
    """Take out spelled-out abbreviations the document doesn't define
    itself (Chief's re-tests, Nov 7: RCP became "Roofing Construction
    Plan" on a sheet titled REFLECTED CEILING PLAN; ET became "Electrical"
    where the sheet says ET/FOLD DOWN EXAM TABLE; DS became "Drywall").
    An expansion stays only when the document puts the abbreviation and
    those words together. Returns (reply, removed)."""
    removed = []

    def spells(acro, ws):
        """The words could be what `acro` stands for: their first letters
        make it, or one word holds its letters in order (DS, downspout)."""
        if len(ws) == len(acro) and \
                "".join(w[0] for w in ws).upper() == acro:
            return True
        if len(ws) == 1:
            it = iter(ws[0].upper())
            return ws[0][0].upper() == acro[0] and \
                all(ch in it for ch in acro)
        return False

    def fix(m, acro_first, loose=False):
        acro, words = (m.group(1), m.group(2)) if acro_first else \
            (m.group(2), m.group(1))
        ws = words.split()
        if not ws:
            return m.group(0)
        rest = []
        paren = m.group(0).rstrip().endswith(")")
        if loose:
            # "X for Y": a meaning only when X is quoted ('"DS" for door')
            # or Y spells X ("RTU for rooftop unit"); "use RCP for
            # reference" is left alone
            quoted = m.group(0)[:1] in "\"'\u201c\u2018"
            n = len(acro) if len(ws) >= len(acro) and \
                spells(acro, ws[:len(acro)]) else 1
            for k in range(min(len(ws), len(acro)), 0, -1):
                if _defined_near(source, acro, " ".join(ws[:k])):
                    return m.group(0)           # the document says so
            if not (quoted or spells(acro, ws[:n])):
                return m.group(0)
            ws, rest = ws[:n], ws[n:]
            removed.append(f"{acro} = {' '.join(ws)}")
            return acro + ((" " + " ".join(rest)) if rest else "")
        if not acro_first:
            # "the Reflected Ceiling Plan (RCP)": the words that spell it;
            # "the door (DS)": from the last word that starts like it
            ws = ws[-len(acro):] if len(ws) > len(acro) else ws
            while len(ws) > 1 and ws[0][0].upper() != acro[0]:
                ws = ws[1:]
        elif not paren and len(ws) > len(acro):
            # "AHU - Air Handling Unit replaced on the roof": only the
            # words that could spell it are the expansion; the rest stays
            ws, rest = ws[:len(acro)], ws[len(acro):]
        if ws[0][0].upper() != acro[0]:
            return m.group(0)                   # not an expansion of it
        words = " ".join(ws)
        if _defined_near(source, acro, words):
            return m.group(0)                   # the document says so
        removed.append(f"{acro} = {words}")
        if acro_first:
            return acro + ((" " + " ".join(rest)) if rest else "")
        keep = m.group(1).split()
        keep = keep[:len(keep) - len(ws)]
        return (" ".join(keep) + " " if keep else "") + acro
    out = reply
    for i, (rx, acro_first) in enumerate(_EXPAND):
        out = rx.sub(lambda m, f=acro_first, lo=(rx is _FOR_RX):
                     fix(m, f, lo), out)
    return out, removed


_SCALE = re.compile(
    r"(?<![\d/])(\d{1,2}(?:/\d{1,3})?|\d{1,2}\s+\d/\d)\s*"
    r"(?:\"|\u201d|''|-?\s*in(?:ch(?:es)?)?\.?)\s*"
    r"(?:=|equals|to|:)\s*1\s*(?:'|\u2019|-?\s*f(?:oo|ee)?t\.?)"
    r"(?:\s*-?\s*0\s*(?:\"|\u201d)?)?", re.I)
_SCALE_WORDS = re.compile(
    r"(?<![\d/])(\d{1,2}/\d{1,3})\s*(?:\"|\u201d|-?\s*inch)\s*scale",
    re.I)
_SCALE_OF = re.compile(
    r"scale(?:\s+of)?\s*:?\s*(\d{1,2}/\d{1,3})\s*(?:\"|\u201d|-?\s*inch)"
    r"(?!\s*(?:=|equals|to)\s*1)", re.I)


def _scales(text):
    """The architectural scales written in `text`, as fractions: {"1/4"}."""
    out = set()
    for rx in (_SCALE, _SCALE_WORDS, _SCALE_OF):
        for m in rx.finditer(text or ""):
            out.add(" ".join(m.group(1).split()))
    return out


# Already marked (a second run), or a shorter match of a longer number:
# left alone. Checked on what follows the match, so it works on Python
# 3.10 (no atomic groups; Venice, Nov 9 - N9). _SHEET_REF takes the
# decimal itself (A-100.5 is one match and is checked); this only skips a
# short match inside a longer one. For scales, a shorter match of
# 1/8" = 1'-0" can stop at 1' - the -0" after it is allowed for (P4-7).
_MARKED_SHEET = re.compile(r"(?:\.?\d)|(?:\.\d+)?\s*\((?:no such|not in)")
_MARKED_SCALE = re.compile(
    r"\s*(?:-?\s*0\s*)?[\"\u201d]?\s*\(this scale")


def check_facts(reply, source, in_set=(), cut=False):
    """Mark sheet numbers and drawing scales the summary states that the
    document doesn't have (Chief's round 5, Nov 9: it named a sheet A-100
    and a floor-plan scale that weren't in a set of A-101 and A-102 at
    1/4"). `cut`: only part of the document was read, so what isn't in
    `source` may still be further on - the mark then says "not in the
    part reviewed", never that it doesn't exist (Venice, Nov 9 - F13).
    Returns (reply, flagged)."""
    from .. import sheets
    flagged = []
    src = source or ""
    have = {x.replace("-", "").replace(".", "").upper()
            for x in list(in_set or []) +
            [m.group(1) for m in _SHEET_REF.finditer(src)]}
    for m in _SHEET_ANY.finditer(src):
        have |= {k for _n, k in _sheet_keys(m)}
    # the document's A-101A also covers a summary that says A-101
    have |= {x.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for x in have
             if x[-1:].isalpha() and re.search(r"\d[A-Z]{1,2}$", x)}
    sheet_note = ("not in the part reviewed" if cut else
                  "no such sheet in the drawings")
    scale_note = ("this scale isn't in the part reviewed" if cut else
                  "this scale isn't in the drawings")

    def sheet(m):
        if _MARKED_SHEET.match(m.string, m.end()):
            return m.group(0)
        names = _sheet_keys(m)
        if not names:
            return m.group(0)
        if _in_mark(m.string, m.start()):
            return m.group(0)                # a name inside our own mark
        first = names[0][0]
        # the discipline letters decide (A, M, FP...), whatever follows
        gate = f"{m.group(1).upper()}-{m.group(3)[:3]}"
        if not sheets.DISCIPLINE.match(gate) or first.startswith("ZZ"):
            return m.group(0)
        if _REFRIGERANT.match(first.replace("-", "")) or \
                _REFRIGERANT.match(first):
            return m.group(0)
        missing = [n for n, k in names if k not in have]
        if not missing:
            return m.group(0)
        for n in missing:
            if n not in flagged:
                flagged.append(n)
        if len(names) == 1:
            return f"{m.group(0)} ({sheet_note})"
        return f"{m.group(0)} ({sheet_note}: {', '.join(missing)})"
    reply = _SHEET_ANY.sub(sheet, reply)
    real = _scales(src)

    def scale(m):
        if _MARKED_SCALE.match(m.string, m.end()):
            return m.group(0)
        frac = " ".join(m.group(1).split())
        if frac in real:
            return m.group(0)
        what = f'scale {frac}"'
        if what not in flagged:
            flagged.append(what)
        return m.group(0) + f" ({scale_note})"
    for rx in (_SCALE, _SCALE_WORDS, _SCALE_OF):
        reply = rx.sub(scale, reply)
    return reply, flagged


def _mark_referenced(reply, refs):
    """A referenced sheet named in the summary is marked as not in the set
    (the body called A-302 included while the footer said it wasn't)."""
    for sh in refs:
        reply = re.sub(rf"\b{re.escape(sh)}\b(?! \(referenced)",
                       f"{sh} (referenced, not in this set)", reply)
    return reply


def summarize_text(text, cut=False, note=None, in_set=None):
    """The model's summary with what it read stated first, the sheets in
    the set apart from the sheets only referenced, and a reminder that it
    is an unchecked draft (Chief's estimator test and re-test, Nov 7: it
    stated a date, an author, a file format and an abbreviation's meaning
    that weren't there, and counted referenced sheets as included)."""
    in_set = list(in_set or [])
    refs = referenced_sheets(text, in_set)
    facts = ""
    if in_set:
        facts += ("Sheets in this set (from the title blocks): " +
                  ", ".join(in_set) + ". ")
        facts += ("Any other sheet number in the text is a reference to a "
                  "sheet that is NOT in this set - never call it included. ")
    refs_now = referenced_sheets(text, in_set)
    if refs_now:
        facts += ("Referenced only, NOT in this set: " +
                  ", ".join(refs_now) + ". ")
    reply = _ollama(SUMMARY_PROMPT + facts + "\n\n" + text)
    reply, removed = check_expansions(reply.strip(), text)
    reply = _mark_referenced(reply, refs)
    reply, made_up = check_facts(reply, text, in_set, cut=cut)
    head = note or ("Reviewed the whole document." if not cut else
                    f"Only the first {TEXT_LIMIT:,} characters were "
                    "reviewed.")
    tail = []
    if in_set:
        tail.append("Sheets in this set: " + ", ".join(in_set) + ".")
    if refs:
        tail.append("Referenced, not in this set: " + ", ".join(refs) + ".")
    if removed:
        tail.append("Taken out - spelled out by the AI, not in the "
                    "document: " + "; ".join(removed) + ".")
    if made_up:
        tail.append(("Not in the part reviewed - stated by the AI: " if cut
                     else "Not in the document - stated by the AI: ") +
                    "; ".join(made_up) + ".")
    tail.append("AI draft from the local model - check it against the "
                "drawings; it can state things the document doesn't say.")
    return f"{head}\n\n{reply}\n\n" + "\n".join(tail)


def redline_proposals(doc):
    return redline_from_text(_text(doc)[0])


def spec_check(doc):
    return spec_from_text(_text(doc)[0])


MIN_OLD = 4               # shortest "old" text a redline may strike
MAX_HITS = 3              # an "old" found more often than this is skipped
RISKY = re.compile(r"\b(NOT|NO|BY OTHERS|ALLOWED|N\.?I\.?C\.?|EXCLUDED?|"
                   r"OPTIONAL|ALTERNATE)\b", re.I)


def risky(edit):
    """An edit that may change scope or meaning (adds or removes NOT, BY
    OTHERS, EXCLUDED...): shown unticked, for a person to decide."""
    return bool(RISKY.search(str(edit.get("old", ""))) or
                RISKY.search(str(edit.get("new", ""))))


def redline_from_text(text):
    raw = _ollama(
        'Propose edits to this document. Reply with JSON: {"edits": '
        '[{"old": exact text to replace, copied verbatim from the document, '
        '"new": replacement, "reason": why}]}. Only clear improvements.'
        "\n\nDocument:\n\n" + text, json_mode=True)
    edits = _items(raw, "edits")
    # a 1-3 character "old" (e.g. "8") matches all over a drawing set and
    # struck 286 places on 38 pages (Grok r5 #10)
    return [e for e in edits
            if len(str(e.get("old", "")).strip()) >= MIN_OLD]


def spec_from_text(text):
    raw = _ollama(
        "Find contradictions, missing fire ratings, and spec inconsistencies "
        'in this document. Reply with JSON: {"findings": [{"finding": '
        'description, "page": page number, "quote": a short exact phrase '
        'from that page}]}.\n\nDocument:\n\n' + text, json_mode=True)
    return _items(raw, "findings")


def redline_marks(doc, edits):
    """Strike out each `old` phrase, with the proposed text as the
    annotation's comment (standard PDF review markup, not text drawn over
    the page). Returns (page, kind, payload) marks."""
    marks = []
    for e in edits:
        old = str(e.get("old", "")).strip()
        if not old:
            continue
        note = f"Replace with: {e.get('new', '')}"
        if e.get("reason"):
            note += f"\nReason: {e['reason']}"
        if len(old) < MIN_OLD:
            continue
        hits = []
        for pno, page in enumerate(doc):
            for r in page.search_for(old):       # unrotated = op coords
                hits.append((pno, "add_strike", {"rect": list(r),
                                                 "note": note}))
            if len(hits) > MAX_HITS:
                break
        if len(hits) > MAX_HITS:                # not one clear place: skip
            log.info("redline: %r found more than %d times - skipped",
                     old, MAX_HITS)
            continue
        marks.extend(hits)
    return marks


def _page_of(f, doc):
    for key in ("page", "page_hint"):
        v = f.get(key)
        m = re.search(r"\d+", str(v)) if v is not None else None
        if m and 1 <= int(m.group(0)) <= doc.page_count:
            return int(m.group(0)) - 1
    return None


def spec_marks(doc, findings):
    """A sticky note per finding, beside the quoted text when it can be
    found, otherwise at the top of the named page (or page 1)."""
    marks = []
    for f in findings:
        text = str(f.get("finding", "")).strip()
        if not text:
            continue
        pno, pt = _page_of(f, doc), None
        quote = str(f.get("quote") or f.get("page_hint") or "").strip()
        if quote and not re.fullmatch(r"(page\s*)?\d+", quote, re.I):
            pages = [pno] if pno is not None else range(doc.page_count)
            for i in pages:
                hits = doc[i].search_for(quote)
                if hits:
                    h = hits[0]                      # unrotated = op coords
                    pno, pt = i, [h.x0, h.y0]
                    break
        if pno is None:
            pno = 0
        if pt is None:
            pt = [20, 20 + 24 * sum(1 for m in marks if m[0] == pno)]
        marks.append((pno, "add_note", {"pt": pt, "text": text}))
    return marks


# kept for callers of the original API
def apply_redline(doc, edits):
    from .. import annotate
    marks = redline_marks(doc, edits)
    return sum(annotate.apply_op(doc, annotate.new_op(k, p, **pl))
               for p, k, pl in marks)


def apply_spec_findings(doc, findings):
    from .. import annotate
    marks = spec_marks(doc, findings)
    return sum(annotate.apply_op(doc, annotate.new_op(k, p, **pl))
               for p, k, pl in marks)


def translate_texts(texts, language, batch=25):
    """Translate markup comments with the local model. Returns a list the
    same length as `texts` (an item comes back unchanged if the model
    skipped it)."""
    out = list(texts)
    for start in range(0, len(texts), batch):
        chunk = texts[start:start + batch]
        items = [{"id": i, "text": t} for i, t in enumerate(chunk)]
        raw = _ollama(
            f"Translate the 'text' of each item into {language}. Keep "
            "numbers, units, dimensions, sheet and spec references exactly "
            'as they are. Reply with JSON: {"items": [{"id": same id, '
            '"text": translation}]}.\n\n' + json.dumps({"items": items},
                                                       ensure_ascii=False),
            json_mode=True)
        for d in _items(raw, "items"):
            try:
                i = int(d.get("id"))
            except (TypeError, ValueError):
                continue
            t = d.get("text")
            if 0 <= i < len(chunk) and isinstance(t, str) and t.strip():
                out[start + i] = t.strip()
    return out
