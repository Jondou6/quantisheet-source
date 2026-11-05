"""Install the cost books that ship with QuantiSheet and, if given, import
an RSMeans assemblies export:  python tools/setup_costbooks.py [file.txt]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))

from app import (assemblies, assembly_csv, costbook, pricedb,  # noqa
                 proposal, rsmeans, settings)


def main(argv):
    print("installed:", costbook.install_shipped() or "(already current)")
    print("company address:", repr(proposal.company().get("address", "")))
    if len(argv) > 1:
        path = " ".join(argv[1:]).strip('"')
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), path)
        r = rsmeans.import_file(path, make_default=True)
        print(f"RSMeans: {r['assemblies']} assemblies -> {r['catalog']}")
        print(f"book: {r['book']} -> {r['book_path']}")
        print(f"calibrated {len(r['calibrated'])} catalog assemblies; "
              f"skipped {len(r['skipped'])}:")
        for s in r["skipped"]:
            print("   ", s)
        # the RSMeans catalog now lives in the price database; the old
        # local file is set aside (renamed, not deleted)
        old = os.path.join(assembly_csv.user_dir(), "RSMeans.csv")
        if os.path.exists(old):
            os.replace(old, old + ".old")
            print("set aside", old, "->", old + ".old")
    for n in costbook.list_books():
        if n.startswith("RSMeans + RSMeans + "):      # made by an old bug
            costbook.delete(n)
            print("removed duplicate book", n)
    d = settings.get("default_costbook") or {}
    if str(d.get("name", "")).startswith("RSMeans + RSMeans + "):
        costbook.set_default(costbook.find("RSMeans + QuantiSheet Starter "
                                           "2026"), d.get("region"))
    print("price database:", pricedb.path())
    print("default:", settings.get("default_costbook"))
    print("library:", len(assemblies.library()), "assemblies")
    print("books:", list(costbook.list_books()))


if __name__ == "__main__":
    main(sys.argv)
