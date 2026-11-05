"""Master Schedule (0.13.10, HELD): subcontractor schedule updates for the
project's one master schedule.

Subs send an update (the Excel template first; MS Project XML and P6 XER
later, through a NEW read/match/diff path - schedule._merge() and the
Scheduler's Import button are not used or changed). Each file is checked
as a whole (rejected with every reason, never partly applied), matched
to the master activities the sub owns ("Owning subcontractor"), diffed,
and its impact worked out on a what-if copy. Updates that move no
activity's finish later and only change progress are accepted on their
own (and can be reverted); everything else waits in Jon's review queue.
Nothing is ever sent to a sub: messages are drafts Jon opens in Outlook.

Pure Python (no Qt) except ui.py; app/master_hook.py is the only thing
the main window imports.
"""
