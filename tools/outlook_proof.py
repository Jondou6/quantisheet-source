"""Make the Outlook proof's manifest for the https address its page is
served from (outlook_addin_proof/README.md):

    python tools/outlook_proof.py manifest https://<host>/<folder>

Writes outlook_addin_proof/manifest.xml. Nothing is hosted, installed or
submitted by this."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, "outlook_addin_proof")


def manifest(host):
    host = host.rstrip("/")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::\d+)?(?:/[A-Za-z0-9._~/-]*)?",
                        host):
        raise SystemExit("give the https address the files are served "
                         "from, for example https://example.com/proof")
    with open(os.path.join(HERE, "manifest.template.xml"),
              encoding="utf-8") as f:
        text = f.read()
    origin = re.match(r"https://[^/]+", host).group(0)
    text = text.replace("<AppDomain>__HOST__</AppDomain>",
                        f"<AppDomain>{origin}</AppDomain>")
    return text.replace("__HOST__", host)


def main(argv):
    if len(argv) != 2 or argv[0] != "manifest":
        print(__doc__)
        return 2
    out = os.path.join(HERE, "manifest.xml")
    with open(out, "w", encoding="utf-8") as f:
        f.write(manifest(argv[1]))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
