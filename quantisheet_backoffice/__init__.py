"""QuantiSheet Back Office: an optional add-on program beside app/.

QuantiSheet starts it as a separate process through
app/backoffice_hook.py and hands it one read-only JSON snapshot per job.
This package never imports the host's app package and keeps its own
settings, data folder and tests.
"""
__version__ = "0.4.0"
APP_NAME = "QuantiSheet Back Office"
