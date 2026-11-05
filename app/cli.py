from . import safeio
import argparse
import json
import sys


def _emit(obj, as_json):
    if as_json:
        print(json.dumps(obj, indent=2, default=str))
    else:
        for k, v in obj.items():
            print(f"{k}: {v}")


def _pages(spec, count):
    """'1,3,5-7' (1-based, as people count pages) -> 0-based indexes."""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a) - 1, int(b)))
        else:
            out.append(int(part) - 1)
    bad = [i + 1 for i in out if not 0 <= i < count]
    if bad:
        raise ValueError(f"page(s) {bad} out of range 1-{count}")
    return out


def build_parser():
    ap = argparse.ArgumentParser(
        prog="quantisheet",
        description="QuantiSheet command line. Run with no arguments to open "
                    "the desktop app.")
    ap.add_argument("--json", action="store_true",
                    help="print results as JSON")
    sub = ap.add_subparsers(dest="cmd", metavar="command")

    p = sub.add_parser("rules", help="apply the default auto-markup rules")
    p.add_argument("src"); p.add_argument("out")
    p = sub.add_parser("rule", help='apply one plain-English rule, e.g. '
                                    '"underline every fire rating in red"')
    p.add_argument("text"); p.add_argument("src"); p.add_argument("out")
    p = sub.add_parser("autocount", help="number every occurrence of a label")
    p.add_argument("src"); p.add_argument("out")
    p.add_argument("--label", required=True)
    p = sub.add_parser("bates", help="add Bates numbers")
    p.add_argument("src"); p.add_argument("out")
    p.add_argument("--prefix", default="DOC")
    p.add_argument("--start", type=int, default=1)
    p = sub.add_parser("watermark", help="add a diagonal watermark")
    p.add_argument("src"); p.add_argument("out")
    p.add_argument("--text", default="DRAFT")
    p.add_argument("--opacity", type=float, default=0.25)
    p = sub.add_parser("compress", help="rewrite smaller")
    p.add_argument("src"); p.add_argument("out")
    p = sub.add_parser("merge", help="combine PDFs")
    p.add_argument("out"); p.add_argument("inputs", nargs="+")
    p = sub.add_parser("compare", help="text diff of two PDFs, as a PDF")
    p.add_argument("a"); p.add_argument("b"); p.add_argument("out")
    p = sub.add_parser("extract", help="copy pages, e.g. 1,3,5-7")
    p.add_argument("src"); p.add_argument("out"); p.add_argument("pages")
    p = sub.add_parser("versions", help="list saved revisions")
    p.add_argument("src")
    p = sub.add_parser("ocr", help="print OCR text (needs Tesseract)")
    p.add_argument("src")
    p = sub.add_parser("toimages", help="render pages to PNG")
    p.add_argument("src"); p.add_argument("outdir")
    p.add_argument("--dpi", type=int, default=150)
    p = sub.add_parser("fromimages", help="images to PDF")
    p.add_argument("out"); p.add_argument("images", nargs="+")
    p = sub.add_parser("sign", help="digitally sign")
    p.add_argument("src"); p.add_argument("out")
    p.add_argument("--reason", default="Approved")
    p.add_argument("--name", default="QuantiSheet User")
    p.add_argument("--key", help="PEM private key (default: your own "
                                 "self-signed key in ~/.quantisheet)")
    p.add_argument("--cert", help="PEM certificate for --key")
    p = sub.add_parser("verify", help="check signatures (exit 2 if broken)")
    p.add_argument("src")
    p.add_argument("--online", action="store_true",
                   help="allow fetching revocation data")
    p = sub.add_parser("audit", help="add an entry to the embedded audit trail")
    p.add_argument("src"); p.add_argument("out")
    p.add_argument("--action", default="note")
    p.add_argument("--actor", default="cli")
    p.add_argument("--detail", default="audit entry added")
    p = sub.add_parser("takeoff", help="measure a line and/or area")
    p.add_argument("src"); p.add_argument("out")
    p.add_argument("--cal", nargs=5, required=True,
                   metavar=("X1", "Y1", "X2", "Y2", "REAL"),
                   help="two points (PDF units) and their real distance")
    p.add_argument("--unit", default="ft")
    p.add_argument("--line", nargs=4, metavar=("X1", "Y1", "X2", "Y2"))
    p.add_argument("--poly", help='points as "x,y;x,y;x,y"')
    p.add_argument("--page", type=int, default=1, help="1-based page number")
    p = sub.add_parser("relay", help="run the collaboration relay")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--http-port", type=int, default=8766)
    p.add_argument("--token", help="require this token from every client "
                   "(needed unless --host is 127.0.0.1)")
    p.add_argument("--token-file", help="read the token from this file; "
                   "made with a new random token if it doesn't exist "
                   "(QuantiSheet Server Setup uses this)")
    p.add_argument("--log", help="also write the relay's log to this file")
    p.add_argument("--make-token", action="store_true",
                   help="only make the --token-file (if missing) and stop")
    p.add_argument("--data-dir", help="where shared projects are kept "
                   "(default: this user's profile)")
    p.add_argument("--cert", help="TLS certificate (PEM) - with --key the "
                   "relay is wss:// and https://")
    p.add_argument("--key", help="the certificate's private key (PEM)")
    p = sub.add_parser("sanitize", help="remove hidden information and "
                       "prove it: exit 0 when clean, 2 when not")
    p.add_argument("src")
    p.add_argument("--out", required=True)
    p.add_argument("--strip-job", action="store_true",
                   help="also remove QuantiSheet's job data (scales, takeoff)")
    p.add_argument("--hidden-text", choices=["auto", "yes", "no"],
                   default="auto", help="remove invisible text (auto: only "
                   "when the file has some)")
    p.add_argument("--manifest", help="write the proof as JSON here")
    p = sub.add_parser("diagnostics", help="support bundle for the help "
                       "desk (no keys, passwords or email addresses)")
    p.add_argument("--out", help="zip file to write (default: "
                   "QuantiSheet-support-<date>.zip here)")
    p.add_argument("--print", dest="show", action="store_true",
                   help="print the report instead of writing a zip")
    p = sub.add_parser("policy", help="show the IT (Group Policy) settings "
                       "in effect")
    p = sub.add_parser("version", help="version and edition of this copy")
    p.add_argument("--out", help="also write it as JSON to this file (the "
                   "windowed program has no console when a script runs it)")
    p = sub.add_parser("genset", help="Generate Set from a brief (same as "
                       "python -m app.genset); exit 2 when no set is made",
                       add_help=False)
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p = sub.add_parser("prebid", help="pre-bid checklist: exit 0 when ready "
                       "to lock, 3 when not")
    p.add_argument("src")
    p.add_argument("--json", dest="pjson", action="store_true",
                   help="print the checklist as JSON")
    return ap


def _pdf_read_errors():
    """pyHanko's read errors (corrupt / non-PDF input) as an except tuple."""
    try:
        from pyhanko.pdf_utils.misc import PdfError
    except ImportError:  # pragma: no cover
        return ()
    return (PdfError,)


def _token_from_file(path):
    """The relay token kept in a file (made once, then reused, so clients
    keep working after a restart)."""
    import os
    import secrets
    try:
        with open(path, encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            return tok
    except FileNotFoundError:
        pass
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tok = secrets.token_urlsafe(24)
    with open(path, "w", encoding="utf-8") as f:
        f.write(tok + "\n")
    return tok


def _sanitize(a, opened):
    """Clean, save, then check the SAVED file (what will be sent), so the
    proof is about the file on disk and not the copy in memory."""
    import fitz
    import hashlib
    from . import acrobat2
    hid = {"auto": None, "yes": True, "no": False}[a.hidden_text]
    doc = opened(a.src)
    failed = acrobat2.sanitize(doc, keep_job=not a.strip_job, hidden_text=hid)
    safeio.atomic_save(doc, a.out)
    doc.close()
    saved = fitz.open(a.out)
    rows = acrobat2.verify_clean(saved, hidden_text=hid is not False)
    saved.close()
    with open(a.out, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    ok = not failed and all(st == "PASS" for st, _i, _d in rows)
    rep = {"out": a.out, "clean": ok, "sha256": sha,
           "steps_failed": failed,
           "checks": [{"status": st, "item": i, "detail": d}
                      for st, i, d in rows]}
    if a.manifest:
        with open(a.manifest, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        print("CLEAN" if ok else "NOT CLEAN")
        for st, i, d in rows:
            print(f"  {st}  {i}" + (f" - {d}" if d else ""))
        for k in failed:
            print(f"  FAIL  step could not run: {k}")
        print(f"sha256: {sha}")
    return 0 if ok else 2


def _printer(argv):
    """`printer --install [--all-users] | --remove | --user-on | --user-off
    | --status` and `print-helper [--once]` (0.12.26): the "QuantiSheet"
    printer. Kept apart from the PDF commands - no PDF libraries load."""
    ap = argparse.ArgumentParser(prog="quantisheet " + argv[0])
    if argv[0] == "printer":
        g = ap.add_mutually_exclusive_group(required=True)
        for opt in ("--install", "--remove", "--user-on", "--user-off",
                    "--status"):
            g.add_argument(opt, action="store_true")
        ap.add_argument("--all-users", action="store_true",
                        help="with --install: every user's helper starts "
                        "at sign-in")
        a = ap.parse_args(argv[1:])
        from . import printer_setup
        try:
            if a.install:
                rows = printer_setup.install(all_users=a.all_users)
            elif a.remove:
                rows = printer_setup.remove()
            elif a.user_on:
                rows = printer_setup.user_on()
            elif a.user_off:
                rows = printer_setup.user_off()
            else:
                rows = printer_setup.status()
        except (RuntimeError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        for k, v in rows.items():
            print(f"{k}: {v}")
        return 0
    ap.add_argument("--once", action="store_true", help="one job, then stop")
    ap.add_argument("--app", help=argparse.SUPPRESS)   # 0.12.24 tasks
    a = ap.parse_args(argv[1:])
    from . import printhelper
    if a.once:
        printhelper.serve(once=True)
        return 0
    return printhelper.run_helper()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] in (["printer"], ["print-helper"]):
        return _printer(argv)
    if argv[:1] == ["genset"]:
        # its own options (--brief, --sf ...) go straight through
        from .genset.__main__ import main as genset_main
        return genset_main(argv[1:])
    ap = build_parser()
    a = ap.parse_args(argv)
    try:
        return _run(a, ap)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _run(a, ap):
    import fitz
    from . import rules as rules_mod
    from . import takeoff, autocount, versions, convert, page_ops
    from . import ocr as ocr_mod
    j = a.json

    def opened(path):
        doc = fitz.open(path)
        if doc.needs_pass:
            raise ValueError(f"{path} is password-protected")
        return doc

    if a.cmd == "rules":
        doc = opened(a.src); n = rules_mod.apply_rules(doc)
        safeio.atomic_save(doc, a.out); doc.close(); _emit({"out": a.out, "marks": n}, j)
    elif a.cmd == "rule":
        r = rules_mod.parse_nl_rule(a.text)
        doc = opened(a.src); n = rules_mod.apply_rules(doc, [r])
        safeio.atomic_save(doc, a.out); doc.close(); _emit({"rule": r, "marks": n}, j)
    elif a.cmd == "autocount":
        doc = opened(a.src)
        hits = autocount.find_by_label(doc, a.label)
        n = autocount.apply_counts(doc, hits)
        safeio.atomic_save(doc, a.out); doc.close(); _emit({"out": a.out, "count": n}, j)
    elif a.cmd == "bates":
        doc = opened(a.src)
        n = page_ops.bates_number(doc, a.prefix, a.start)
        safeio.atomic_save(doc, a.out); doc.close(); _emit({"out": a.out, "pages": n}, j)
    elif a.cmd == "watermark":
        doc = opened(a.src)
        page_ops.add_watermark(doc, a.text, a.opacity)
        safeio.atomic_save(doc, a.out); doc.close(); _emit({"out": a.out}, j)
    elif a.cmd == "compress":
        doc = opened(a.src)
        page_ops.compress(doc, a.out); doc.close(); _emit({"out": a.out}, j)
    elif a.cmd == "merge":
        page_ops.merge(a.inputs, a.out); _emit({"out": a.out}, j)
    elif a.cmd == "compare":
        versions.compare(a.a, a.b, a.out); _emit({"out": a.out}, j)
    elif a.cmd == "extract":
        doc = opened(a.src)
        pages = _pages(a.pages, doc.page_count)
        out = page_ops.extract_pages(doc, pages)
        safeio.atomic_save(out, a.out); out.close(); doc.close()
        _emit({"out": a.out, "pages": [p + 1 for p in pages]}, j)
    elif a.cmd == "versions":
        _emit({"revisions": versions.list_revisions(a.src)}, j)
    elif a.cmd == "ocr":
        _emit({"text": ocr_mod.ocr_document(a.src)}, j)
    elif a.cmd == "toimages":
        _emit({"images": convert.pdf_to_images(a.src, a.outdir, a.dpi)}, j)
    elif a.cmd == "fromimages":
        convert.images_to_pdf(a.images, a.out); _emit({"out": a.out}, j)
    elif a.cmd == "sign":
        from .sign import signer
        if bool(a.key) != bool(a.cert):
            raise ValueError("--key and --cert must be given together")
        try:
            signer.sign_pdf(a.src, a.out, reason=a.reason,
                            signer_name=a.name, key_path=a.key,
                            cert_path=a.cert)
        except _pdf_read_errors() as e:
            raise ValueError(f"can't read PDF {a.src}: {e}") from e
        _emit({"out": a.out}, j)
    elif a.cmd == "verify":
        from .sign import verify
        try:
            res = verify.verify_document(a.src, online=a.online)
        except _pdf_read_errors() as e:
            raise ValueError(f"can't read PDF {a.src}: {e}") from e
        sigs = [r for r in res if "field" in r]
        _emit({"signatures": len(sigs), "results": res}, j)
        return 0 if all(r.get("valid") for r in sigs) and all(
            r.get("audit_chain_valid", True) for r in res) else 2
    elif a.cmd == "audit":
        from .sign import embed
        from .sign.audit import AuditLog
        log = embed.read_audit(a.src) or AuditLog()
        log.add(a.action, a.actor, a.detail)
        embed.embed_audit(a.src, a.out, log)
        _emit({"out": a.out, "entries": len(log.entries)}, j)
    elif a.cmd == "takeoff":
        doc = opened(a.src)
        if not 1 <= a.page <= doc.page_count:
            raise ValueError(f"page {a.page} out of range 1-{doc.page_count}")
        page = doc[a.page - 1]
        x1, y1, x2, y2, real = [float(v) for v in a.cal]
        cal = takeoff.Calibration(fitz.Point(x1, y1), fitz.Point(x2, y2),
                                  real, a.unit)
        res = {"unit": a.unit}
        if a.line:
            lx1, ly1, lx2, ly2 = [float(v) for v in a.line]
            res["distance"] = takeoff.annotate_distance(
                page, cal, fitz.Point(lx1, ly1), fitz.Point(lx2, ly2))
        if a.poly:
            pts = [fitz.Point(*[float(c) for c in p.split(",")])
                   for p in a.poly.split(";")]
            res["area"] = takeoff.annotate_area(page, cal, pts)
        safeio.atomic_save(doc, a.out); doc.close(); _emit({"out": a.out, **res}, j)
    elif a.cmd == "prebid":
        from . import prebid
        doc = opened(a.src)
        rep = prebid.check(doc)
        lk = prebid.lock_state(doc)
        doc.close()
        if j or getattr(a, "pjson", False):
            print(json.dumps(dict(rep.to_dict(), locked=lk), indent=2,
                             default=str))
        else:
            c = rep.counts()
            print("PASS" if rep.ok else "NOT READY")
            print(f"sheets reviewed: {c['sheets'] - c['unreviewed_sheets']}"
                  f" of {c['sheets']}")
            print(f"markups accounted for: "
                  f"{c['markups'] - c['open_markups']} of {c['markups']}")
            print(f"revision clouds accounted for: "
                  f"{c['clouds'] - c['unaccounted_clouds']} of "
                  f"{c['clouds']}")
            for it in (rep.unreviewed_sheets + rep.open_markups +
                       rep.unaccounted_clouds):
                print(f"  {it['sheet']}: {it['label']}")
        return 0 if rep.ok else 3
    elif a.cmd == "sanitize":
        return _sanitize(a, opened)
    elif a.cmd == "diagnostics":
        import datetime
        import os
        from . import diagnostics
        if a.show:
            print(json.dumps(diagnostics.report(), indent=2, default=str))
        else:
            out = a.out or os.path.abspath(
                f"QuantiSheet-support-{datetime.date.today():%Y%m%d}.zip")
            diagnostics.bundle(out)
            _emit({"out": out}, j)
    elif a.cmd == "version":
        from . import __version__, betalicense
        info = {"version": __version__, "edition": betalicense.edition(),
                "key_required": betalicense.required()}
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(info, f)
        _emit(info, j)
    elif a.cmd == "policy":
        from . import policy
        rows = policy.masked()
        if j:
            print(json.dumps(rows, indent=2))
        elif not rows:
            print("No IT policy settings on this computer.")
        else:
            for k, v in rows.items():
                print(f"{k}: {v}")
    elif a.cmd == "relay":
        from .collab import relay
        if a.log:
            import logging
            import os
            os.makedirs(os.path.dirname(os.path.abspath(a.log)),
                        exist_ok=True)
            logging.basicConfig(
                level=logging.INFO, filename=a.log, encoding="utf-8",
                format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        if a.make_token:
            if not a.token_file:
                raise ValueError("--make-token needs --token-file")
            _token_from_file(a.token_file)
            _emit({"token_file": a.token_file}, j)
            return 0
        if a.token_file and not a.token:
            a.token = _token_from_file(a.token_file)
        ctx = None
        if a.cert or a.key:
            if not (a.cert and a.key):
                raise ValueError("--cert and --key must be given together")
            ctx = relay.tls_context(a.cert, a.key)
            if ctx is None:
                raise ValueError("certificate or key file not found")
        ip = relay.lan_ip()
        s = "s" if ctx else ""
        print(f"Relay on ws{s}://{ip}:{a.port}  (phones: "
              f"http{s}://{ip}:{a.http_port}/)", flush=True)
        try:
            relay.run_relay(a.host, a.port, a.http_port, a.token,
                            data_dir=a.data_dir, ssl_ctx=ctx)
        except KeyboardInterrupt:
            pass
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
