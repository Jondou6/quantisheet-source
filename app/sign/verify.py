from .embed import read_audit


def verify_document(src, online=False):
    """Check every signature in a PDF.

    For each signature:
      intact     the signed bytes are unchanged and the signature maths holds
      trusted    the signer's certificate chains to a trusted root
                 (self-signed certificates never do)
      covers_whole_file
                 False means content was added after signing; that is normal
                 for later signatures and annotations, but worth a look
      valid      intact (the original reported only this, under this name)

    online=True lets the checker fetch revocation data from the internet.
    """
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    results = []
    with open(src, "rb") as f:
        reader = PdfFileReader(f, strict=False)
        try:            # long-term validation data kept in the file (DSS)
            ltv = "/DSS" in reader.root
        except Exception:                                 # noqa: BLE001
            ltv = False
        for sig in reader.embedded_signatures:
            entry = {"field": getattr(sig, "field_name", "?")}
            try:
                st = validate_pdf_signature(
                    sig, signer_validation_context=ValidationContext(
                        allow_fetching=online))
                intact = bool(st.intact) and bool(getattr(st, "valid", True))
                coverage = getattr(st, "coverage", None)
                entry.update({
                    "valid": intact,
                    "intact": intact,
                    "trusted": bool(getattr(st, "trusted", False)),
                    "covers_whole_file": getattr(coverage, "name", "") ==
                    "ENTIRE_FILE",
                    "coverage": getattr(coverage, "name", str(coverage)),
                    "signer": _signer(st),
                    "signed_at": str(getattr(st, "signer_reported_dt", "") or ""),
                })
                entry.update(_cert_facts(st))
                entry["ltv"] = ltv
                entry["message"] = describe(entry)
            except Exception as e:
                entry.update({"valid": False, "error": str(e)})
            results.append(entry)
    log = read_audit(src)
    if log:
        results.append({"audit_entries": len(log.entries),
                        "audit_chain_valid": log.verify()})
    return results


def _cert_facts(st):
    """Venice #4 (Nov 4): when the certificate was valid, whether the
    signature carries a trusted timestamp, and whether it holds the data
    to check it years from now (long-term validation)."""
    out = {}
    try:
        cert = st.signing_cert
        nb = cert["tbs_certificate"]["validity"]["not_before"].native
        na = cert["tbs_certificate"]["validity"]["not_after"].native
        out["cert_valid_from"] = nb.date().isoformat()
        out["cert_valid_to"] = na.date().isoformat()
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc)
        out["cert_expired"] = na < now
        signed = getattr(st, "signer_reported_dt", None)
        if signed is not None and signed.tzinfo is None:
            signed = signed.replace(tzinfo=_dt.timezone.utc)
        out["cert_valid_when_signed"] = bool(
            signed is None or nb <= signed <= na)
        out["self_signed"] = cert.subject == cert.issuer
    except Exception:                                     # noqa: BLE001
        pass
    ts = getattr(st, "timestamp_validity", None)
    out["timestamped"] = ts is not None
    out["timestamp_trusted"] = bool(getattr(ts, "trusted", False)) if ts \
        else False
    try:
        mod = getattr(st, "modification_level", None)
        out["modification_level"] = getattr(mod, "name", "") if mod else ""
    except Exception:                                     # noqa: BLE001
        pass
    return out


def describe(e):
    """One plain line for a signature, e.g. "Signed by X, but the
    certificate expired on 2026-03-01"."""
    if e.get("error"):
        return f"Couldn't check this signature: {e['error'][:120]}"
    who = e.get("signer") or "someone"
    if not e.get("intact"):
        return f"Signed by {who}, but the file was changed in the signed " \
               "part - this signature is not valid."
    bits = [f"Signed by {who}"]
    if e.get("cert_valid_when_signed") is False:
        bits.append("but the certificate wasn't valid on the signing date")
    elif e.get("cert_expired"):
        bits.append(f"certificate expired on {e.get('cert_valid_to')} "
                    "(it was valid when signed)")
    if e.get("self_signed"):
        bits.append("self-signed - it proves the file wasn't changed, not "
                    "who signed it")
    elif not e.get("trusted"):
        bits.append("the certificate isn't from an authority this PC trusts")
    if e.get("timestamped"):
        bits.append("with a trusted timestamp" if e.get("timestamp_trusted")
                    else "with a timestamp this PC doesn't trust")
    else:
        bits.append("no trusted timestamp (the signing time is the "
                    "signer's own clock)")
    if not e.get("covers_whole_file"):
        bits.append("changes were added after signing")
    if not e.get("ltv"):
        bits.append("no long-term check data in the file (it may not be "
                    "checkable once the certificate expires)")
    return ", ".join(bits) + "."


def _signer(st):
    try:
        return st.signing_cert.subject.human_friendly
    except Exception:
        return ""
