# Quarterly restore drill

Do this once a quarter. It checks that a scratch Windows login, one that has never run QuantiSheet, can get three things back:

1. The data backup zip.
2. The payroll key file (`.qskey`).
3. A job's estimate.

Use made-up material only. Do not use a customer drawing, a real person's email, a real payroll file, or a path from a live job. The examples below (`Drill Example`, `Example Warehouse.pdf`, account `qs-drill`) are placeholders.

This drill was checked against the source. It was not clicked through on Windows. Anything that depends on that live click is marked **UNVERIFIED**.

## What to copy before you switch logins

On the everyday login, prepare three files and copy them to removable media (a folder you name, for example `QS-Drill`):

1. A data zip you just made (section 1).
2. A payroll key backup you just made (section 2).
3. A made-up job PDF, `Example Warehouse.pdf`, with a few estimate lines. Write down the Code, Description, Quantity, Unit Cost, and Total for each line.

Also set **Edit > Author Name…** to `Drill Example` before you make the data zip. That name is stored in the per-user settings, which the zip includes, so it is an easy thing to look for after the restore.

Sign in as a local Windows user that is not used for real work. `qs-drill` is a fine account name. Do not restore over the everyday login.

The menu bar is hidden behind the ribbon. Press **F10** to open the menus (Alt by itself does the same). **Tools** is on that menu. **File** is also on the ribbon's application button.

## 1. Data backup zip

On the everyday login: **F10 > Tools > Back Up My QuantiSheet Data…**

The save dialog is titled "Back Up My QuantiSheet Data". Unless someone has already picked a folder, it opens in `Documents\QuantiSheet Backups`. The suggested file name is `QuantiSheet data YYYY-MM-DD.zip`. Copy that zip to the removable disk. A weekly zip is also written in that Documents folder (the last four are kept). Use the zip you just saved so you know which one the drill restored.

The zip holds the per-user data folder (settings, Tool Chest, assemblies, cost books, price database, packages, time log, signing key, and job data that lives in that folder) and the Back Office data folder when there is one. It does not hold autosave copies, pre-save file copies, map tiles, or logs. It does not hold `Example Warehouse.pdf` unless that PDF was saved inside one of those folders. Keep the disk private: the zip contains the signing key and Back Office data.

On `qs-drill`: install or open QuantiSheet the same way that login will run it, then **F10 > Tools > Restore QuantiSheet Data From a Backup…** and choose the zip.

The open dialog is titled "Restore QuantiSheet Data". Confirm the question. QuantiSheet then says: "Restored. Close QuantiSheet and open it again." What was already in the scratch profile is saved first, beside the zip, as `QuantiSheet data before restore <date time>.zip`.

Quit, open QuantiSheet again, and choose **Edit > Author Name…**. The box is already filled in. It should read `Drill Example`. Cancel so you don't change it. If it shows the Windows account name instead, the setting did not come back.

Pass: the author name is back, and QuantiSheet opened after the restart.

## 2. Payroll key (`.qskey`)

Make the key backup on the everyday login, before you switch.

There is no top-level menu named Back Office. Open Back Office in either of these ways (the item is there only when Back Office is installed):

- Project tab, Office group, button **Back Office**.
- **F10 > Module > QuantiSheet Back Office…**

In Back Office, click **Payroll Key & Approvals** in the list on the left. That is a page name, not a menu-bar item.

On that page:

- **Back Up Payroll Key…** (everyday login). The save dialog is titled "Back Up Payroll Key". The suggested name is `payroll-key.qskey`. The filter is "Payroll key backup (*.qskey)". The password is at least 10 characters, typed twice. It is not stored, and the file does not hold the key in the clear. Copy the `.qskey` to the removable disk.
- **Restore Payroll Key…** (scratch login, after the step below). The dialog is titled "Restore Payroll Key". The password is asked once.

If the key is missing when Back Office opens the company, a warning offers **Restore From Key Backup…**. That button is on the startup message, not on a menu.

### The data zip is not the payroll-key restore

The sealed key is under the Back Office home: `%LOCALAPPDATA%\QuantiSheetBackOffice\keys`, or `QS_BACKOFFICE_HOME\keys` when that variable is set. The data zip copies that home, so it copies `keys`. On Windows the seal is DPAPI for the Windows user who created it. The scratch login cannot unprotect it.

Opening those restored files does not raise the missing-key error that shows **Restore From Key Backup…**. The DPAPI failure is a different error. Installing the `.qskey` also tries to open a key file that is already sitting in `keys` before it writes the new one, so a sealed file from the other Windows user can block the restore.

On `qs-drill`, after the data restore and after QuantiSheet is closed:

1. Rename `%LOCALAPPDATA%\QuantiSheetBackOffice\keys` to `keys-from-other-windows-user`. Do not delete the `.qskey` on the removable disk. If `QS_BACKOFFICE_HOME` is set, rename `keys` inside that folder instead.
2. Open Back Office. The company file came back with the data zip, and its stub says the key was moved, but the slot file is gone. Back Office should offer **Restore From Key Backup…** and should not make a new key.
3. Choose the `.qskey` and type the password.

**UNVERIFIED:** the rename-then-restore sequence was read from `paykeys.py`, `crypto.py`, and `__main__.py`. It was not run on Windows, so the exact text of a DPAPI error (if the `keys` folder is left in place) is not recorded here.

Pass: Back Office opens the company on `qs-drill` after the `.qskey` restore.

## 3. Open the job and check the estimate

The estimate is inside the job PDF, in the embedded file `quantisheet_estimate.json` ("estimate and prices"). Bring `Example Warehouse.pdf` from the removable disk.

There is no command named "Open a Job". Use **File > Open…** (the status bar says "Open a PDF to begin (File > Open)"). Nearby commands that are not this step: **Open Recent**, **Open Project Folder…**, and **Open Bid Download (.zip) as a Job…**.

Show the estimate with **View > Estimate**, or the same **Estimate** item on the Takeoff menu. Both show and hide the Estimate panel. Compare Code, Description, Quantity, Unit Cost, and Total with the notes from the start of the drill. The panel's columns are Code, Description, Cost Type, Type, Count, Quantity, Unit, Waste %, Multiplier, Adjusted, Mat, Lab, Eqp, Sub, Unit Cost, Total.

Pass: those lines match the notes. Do not edit the PDF to make them match.

## Names that do not match the short form

The menu text for the data zip is **Back Up My QuantiSheet Data…** and **Restore QuantiSheet Data From a Backup…**. Both end with an ellipsis (`…`). A note that only says "Restore" matches the title of the message box after a restore, not the menu item.

**Payroll Key & Approvals** is the page in Back Office's left-hand list. Open Back Office from the Project button **Back Office** or from **Module > QuantiSheet Back Office…**, then click that page. The buttons are **Back Up Payroll Key…**, **Restore Payroll Key…**, and **Rotate Payroll Key**.

`quantisheet_backoffice/r111/menu.py` lists "Back up payroll key" and "Restore payroll key" with the place "Settings". That file is a wiring list. Nothing in it is attached to a menu. Do not look on the Settings page for this drill. The page a person uses is **Payroll Key & Approvals**.

## Record

Write the date, the scratch account name, pass or fail for each of the three parts, and where the removable disk was put. Do not put customer names, emails, or real job paths in the notes.

## Strings checked against the source

A test reads each line below. The text after the `|` is copied from that file.

CHECK app/main_window.py | Back Up My QuantiSheet Data…
CHECK app/main_window.py | Restore QuantiSheet Data From a Backup…
CHECK app/main_window.py | Author Name…
CHECK app/main_window.py | Open…
CHECK app/main_window.py | Open Recent
CHECK app/main_window.py | Open Project Folder…
CHECK app/main_window.py | Open Bid Download (.zip) as a Job…
CHECK app/main_window.py | Open a PDF to begin (File > Open)
CHECK app/backoffice_hook.py | QuantiSheet Back Office…
CHECK app/quickaccess.py | Back Office
CHECK app/quickaccess.py | menus_popup
CHECK quantisheet_backoffice/ui/main_window.py | Payroll Key & Approvals
CHECK quantisheet_backoffice/r111/ui.py | Back Up Payroll Key…
CHECK quantisheet_backoffice/r111/ui.py | Restore Payroll Key…
CHECK quantisheet_backoffice/r111/ui.py | Rotate Payroll Key
CHECK quantisheet_backoffice/r111/ui.py | payroll-key.qskey
CHECK quantisheet_backoffice/__main__.py | Restore From Key Backup…
CHECK quantisheet_backoffice/r111/menu.py | Restore payroll key
CHECK app/jobdata.py | quantisheet_estimate.json
CHECK app/docks.py | Unit Cost
