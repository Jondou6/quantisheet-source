"""One time (Jon, Oct 30): Chief's r45 test screenshots that caught Jon's
meeting are moved, not deleted, into QS_r36_test\\_to_delete\\gui45 for
Jon to delete. Only these four named files; nothing else is touched."""
import os
import shutil

SRC = os.path.join(os.path.expanduser("~"), "QS_r36_test", "gui45")
DST = os.path.join(os.path.expanduser("~"), "QS_r36_test", "_to_delete",
                   "gui45")
NAMES = ("09_area.png", "10_count.png", "11b_textbox_typing.png",
         "pull45.zip")
os.makedirs(DST, exist_ok=True)
for n in NAMES:
    s, d = os.path.join(SRC, n), os.path.join(DST, n)
    if not os.path.isfile(s):
        print("not there:", s)
    elif os.path.exists(d):
        print("already moved, left:", s)
    else:
        shutil.move(s, d)
        print("moved:", n, "->", DST)
