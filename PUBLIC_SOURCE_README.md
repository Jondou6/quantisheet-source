# QuantiSheet

This directory is the corresponding source for QuantiSheet release main
(commit 3c101ffab5c522f8c37168d6585e4722f6f8bc9e).

QuantiSheet is a program for reviewing and marking up PDFs, measuring
quantities from drawings, estimating, signing documents, and collaborating
on a drawing live. It has a desktop application, a small web page for a
phone on the same network, and a command line.

## Licence

QuantiSheet is released under the GNU Affero General Public License,
version 3 (AGPL-3.0). You may copy, modify, and share this source under
that licence. The licence text is published by the Free Software Foundation:
https://www.gnu.org/licenses/agpl-3.0.html

If you run a modified version on a server for other people, that licence
requires you to offer them the corresponding source.

## Build

Python 3.12 is the version the project uses. Python 3.10 or newer can run
it. From this directory:

    python -m venv .venv

On macOS or Linux, activate that environment and install the dependencies:

    source .venv/bin/activate
    pip install -r requirements.txt
    ./build.sh

On Windows, activate it with `.venv\Scripts\activate`, install the same
requirements file, and run `build.bat`.

The program is written to `dist/QuantiSheet/`.

To run the tests, install pytest (`pip install pytest`) and run `pytest`.
On a machine with no display, set QT_QPA_PLATFORM=offscreen first.
