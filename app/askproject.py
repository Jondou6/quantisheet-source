"""Ask the Project (Nov 23, Jon: features like our competitors', built
ourselves). A question in plain words is answered from the job's own
papers: the open PDF (specs or drawings) and the Project Center records -
RFIs, submittals, daily logs, meetings and issues. The best-matching
passages are found here by word matching (no AI needed); when the AI on
this PC (Ollama) is running it writes a short answer from those passages
only, citing them by number. Nothing leaves the PC.

    chunks = sources(doc, store)          -> [{"ref", "where", "text"}]
    hits = search(question, chunks, k)    -> best chunks, best first
    out = answer(question, chunks, ask)   -> {"answer", "hits", "ai"}
"""
import math
import re
from collections import Counter

CHUNK = 700                 # characters per passage
AI_CHARS = 6000             # passages sent to the local AI
STOP = set("""a an and are as at be by can do does for from has have how i
in into is it its may must of on or our shall should that the their there
these this to was we what when where which who will with would you your
any all about please tell me give show list find much many""".split())

RECORDS = (("rfi", "RFI", ("subject", "question", "suggestion", "answer",
                           "spec", "drawing", "location", "status")),
           ("submittal", "Submittal", ("title", "spec", "type", "status",
                                       "description")),
           ("daily", "Daily log", ("date", "work", "safety",
                                   "inspections_note")),
           ("meeting", "Meeting", ("title", "date", "notes", "minutes",
                                   "items")),
           ("issue", "Issue", ("title", "description", "status",
                               "resolution")))


def _words(text):
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9'\-./]*", (text or "").lower()):
        w = w.strip("'.-/")
        if not w or w in STOP:
            continue
        for suf in ("ings", "ing", "ies", "es", "ed", "s"):
            if len(w) > len(suf) + 3 and w.endswith(suf):
                w = w[:-len(suf)] + ("y" if suf == "ies" else "")
                break
        out.append(w)
    return out


def _split(text, size=CHUNK):
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= size:
        return [text] if text else []
    parts, cur = [], ""
    for s in re.split(r"(?<=[.;:])\s+", text):
        if len(cur) + len(s) > size and cur:
            parts.append(cur.strip())
            cur = ""
        cur += s + " "
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _flat(v):
    if isinstance(v, list):
        return " ".join(_flat(x) for x in v)
    if isinstance(v, dict):
        return " ".join(_flat(x) for x in v.values())
    return "" if v is None else str(v)


def sources(doc=None, store=None, doc_name=""):
    """Passages to search: each page of the open PDF in pieces, and each
    Project Center record."""
    chunks = []
    if doc is not None:
        for p in range(doc.page_count):
            try:
                t = doc[p].get_text() or ""
            except Exception:                             # noqa: BLE001
                continue
            for piece in _split(t):
                chunks.append({"ref": ("page", p),
                               "where": f"{doc_name or 'PDF'} p. {p + 1}",
                               "text": piece})
    if store is not None:
        for coll, label, keys in RECORDS:
            try:
                recs = store.list(coll)
            except Exception:                             # noqa: BLE001
                continue
            for r in recs:
                no = r.get("_no") or r.get("number") or r.get("_n") or ""
                body = " ".join(f"{k}: {_flat(r.get(k))}" for k in keys
                                if _flat(r.get(k)).strip())
                for piece in _split(body, CHUNK * 2):
                    chunks.append({"ref": (coll, r.get("_id") or r.get("id")),
                                   "where": f"{label} {no}".strip(),
                                   "text": piece})
    for c in chunks:
        c["_w"] = Counter(_words(c["text"]))
    return chunks


def search(question, chunks, k=6):
    """The passages that best match the question (BM25 word scoring, plus
    a bonus for the question's words appearing together)."""
    q = _words(question)
    if not q or not chunks:
        return []
    n = len(chunks)
    avg = sum(sum(c["_w"].values()) for c in chunks) / n or 1
    df = Counter()
    for c in chunks:
        for w in set(q):
            if w in c["_w"]:
                df[w] += 1
    scored = []
    for c in chunks:
        tf, ln, s = c["_w"], sum(c["_w"].values()) or 1, 0.0
        for w in set(q):
            if w not in tf:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * ln / avg))
        if s <= 0:
            continue
        low = c["text"].lower()
        for a, b in zip(q, q[1:]):
            if re.search(re.escape(a) + r"\w*\W+(?:\w+\W+){0,2}" +
                         re.escape(b), low):
                s += 1.0
        scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return [dict(c, score=round(s, 3)) for s, c in scored[:k]]


def prompt(question, hits):
    src, n = [], 0
    for i, h in enumerate(hits, 1):
        t = f"[{i}] ({h['where']}) {h['text']}"
        if n + len(t) > AI_CHARS:
            break
        src.append(t)
        n += len(t)
    return ("You answer questions about a construction project using ONLY "
            "the numbered sources below (from the project's specifications, "
            "drawings and records). Answer in 1 to 4 sentences and cite the "
            "sources you used like [1] or [2]. If the sources don't answer "
            "the question, say: Not found in the project documents. Do not "
            "guess and do not add numbers that are not in the sources.\n\n"
            "SOURCES:\n" + "\n".join(src) + f"\n\nQUESTION: {question}\n"
            "ANSWER:")


def answer(question, chunks, ask=None, use_ai=True, k=6):
    """{"answer": text or "", "hits": passages, "ai": bool, "error"}."""
    hits = search(question, chunks, k)
    out = {"answer": "", "hits": hits, "ai": False, "error": ""}
    if not hits:
        out["answer"] = "Nothing in the project documents matches that."
        return out
    if not use_ai:
        return out
    if ask is None:
        from .ai import review

        def ask(pr):
            return review.stream(pr, num_ctx=4096, num_predict=220)
    try:
        text = re.sub(r"\s+", " ", ask(prompt(question, hits)) or "").strip()
    except Exception as e:                                # noqa: BLE001
        out["error"] = str(e)
        return out
    # a citation to a source that wasn't given is dropped, not trusted
    text = re.sub(r"\[(\d+)\]", lambda m: m.group(0)
                  if 1 <= int(m.group(1)) <= len(hits) else "", text)
    # a model that answered with sources sometimes adds "Not found..." at
    # the end as well - keep the answer, drop the contradiction
    if re.search(r"\[\d+\]", text):
        text = re.sub(r"\s*Not found in the project documents\.?\s*$", "",
                      text).strip()
    out.update(answer=text, ai=True)
    return out
