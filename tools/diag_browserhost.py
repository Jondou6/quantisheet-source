"""Play the browser's part against the installed QuantiSheet: start it the
way a browser starts its add-on's program, send a made-up PDF down the
pipe, and print the answers. Also says where each browser is told to find
the program.

    python tools/diag_browserhost.py
"""
import base64
import json
import os
import struct
import subprocess
import sys
import winreg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
ORIGIN = "chrome-extension://klfflmcmedeghfecpbdmfajjhdbhigap/"


def registered():
    exe = None
    for b in (r"Google\Chrome", r"BraveSoftware\Brave-Browser",
              r"Microsoft\Edge"):
        key = rf"Software\{b}\NativeMessagingHosts\com.quantisheet.open"
        try:
            mp = winreg.QueryValue(winreg.HKEY_CURRENT_USER, key)
            with open(mp, encoding="utf-8") as f:
                m = json.load(f)
            path = os.path.join(os.path.dirname(mp), m["path"])
            print(b, "->", os.path.basename(mp), "->",
                  os.path.basename(path), "exists:", os.path.isfile(path),
                  "| add-ons allowed:", len(m["allowed_origins"]))
            exe = exe or path
        except (OSError, ValueError, KeyError) as e:
            print(b, "-> not registered", type(e).__name__)
    return exe


def main():
    exe = registered()
    if not exe:
        return 1
    p = subprocess.Popen([exe, ORIGIN, "--parent-window=0"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)

    def ask(msg):
        body = json.dumps(msg).encode()
        p.stdin.write(struct.pack("<I", len(body)) + body)
        p.stdin.flush()
        head = p.stdout.read(4)
        if len(head) < 4:
            return "no answer (it stopped, exit code %s) %s" % (
                p.poll(), p.stderr.read()[-300:])
        return json.loads(p.stdout.read(struct.unpack("<I", head)[0]))

    import fitz
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Made-up PDF sent down the "
                               "browser's pipe.")
    pdf = doc.tobytes()
    doc.close()
    print("hello:", ask({"type": "hello"}))
    print("begin:", ask({"type": "begin", "name": "Made-up pipe test.pdf"}))
    half = len(pdf) // 2
    for part in (pdf[:half], pdf[half:]):
        print("data:", ask({"type": "data",
                            "b64": base64.b64encode(part).decode()}))
    r = ask({"type": "end"})
    if isinstance(r, dict) and r.get("path"):
        ok = os.path.isfile(r["path"]) and \
            open(r["path"], "rb").read() == pdf
        r = dict(r, path=os.path.join(*r["path"].split(os.sep)[-2:]))
        print("end:", r, "| saved file is the PDF sent:", ok)
    else:
        print("end:", r)
    p.stdin.close()
    try:
        print("it stopped with exit code", p.wait(timeout=10))
    except subprocess.TimeoutExpired:
        print("it did not stop when the pipe closed")
        p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
