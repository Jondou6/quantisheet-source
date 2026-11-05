"""AI review helpers backed by a local Ollama model.

Nothing leaves the computer: requests go to Ollama on localhost.
"""
import http.client
import json
import logging
import os
import re
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
    host = policy.get("AIHost") or host
    if not re.match(r"^https?://[^/\s]+/?$", str(host or "")):
        raise AIError(f"The AI address isn't a plain http(s) host: "
                      f"{str(host)[:80]}")
    return str(host).rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None                 # an answer that redirects is an error


def _opener():
    """Straight to the AI host: no system/env proxy (document text must
    not pass through one) and no redirects to another address (threat
    model T-009, as Back Office's local AI already does)."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                       _NoRedirect())


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
        with _opener().open(req, timeout=TIMEOUT) as r:
            raw = r.read()
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
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise AIError("Ollama sent a reply that isn't JSON. Is "
                      f"{host} really Ollama?") from e
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


def _k(n):
    return f"{n / 1000:.0f}k" if n >= 10000 else f"{n:,}"


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


def summarize_text(text, cut=False, note=None):
    reply = _ollama("Summarize this document in 5 bullet points, then list "
                    "any spec numbers and fire ratings mentioned:\n\n" + text)
    if cut:
        reply += "\n\n(Note: " + (note or (
            "the document was too long, so only the first "
            f"{TEXT_LIMIT:,} characters were reviewed.")) + ")"
    return reply


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
