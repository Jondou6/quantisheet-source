"""Real-phone round trip of the Phase 3 work ticket (Nov 5, Chief): a
made-up work order kept in its own test store (.run/phone_test - not
the program's data folder), one ticket PDF for a tech's phone, and the
read-back of what comes back.

    python tools/phone_ticket_test.py make OUT.pdf
    python tools/phone_ticket_test.py read RETURNED.pdf"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
STORE = os.path.join(ROOT, ".run", "phone_test", "work_orders.json")


def main():
    from app.service import ticket_pdf, workorder
    cmd, path = sys.argv[1], sys.argv[2].strip('"')
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    comp = {"name": "QuantiSheet TEST (made up)", "address": "",
            "phone": "", "email": "", "website": "", "license": "",
            "logo": "", "signer": "", "title": ""}
    if cmd == "make":
        st = workorder.blank()
        workorder.set_rates(st, "100", "40")
        w = workorder.add(st, customer="Test Customer (made up)",
                          site="123 Sample Lane (made up)",
                          complaint="TEST - no heat (made-up work order)",
                          tech="Test Tech")
        out = ticket_pdf.make(st, w, path, comp=comp)
        workorder.save(st, STORE)
        print(json.dumps({"ticket": "QS-" + out["token"], "file": path,
                          "work_order": workorder.get(st, w)["number"]}))
        return
    st = workorder.load(STORE)
    ret = ticket_pdf.read(st, path)
    print(json.dumps({k: ret[k] for k in ("token", "number", "how",
                                          "values", "unread", "note")},
                     indent=1))
    try:
        got = ticket_pdf.apply(st, ret)
        workorder.save(st, STORE)
        print("applied:", json.dumps(got))
    except ticket_pdf.TicketError as e:
        print("not applied:", e)


if __name__ == "__main__":
    main()
