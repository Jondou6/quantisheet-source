"""Model choice and compiler settings, stored in the user's data folder.

The office machine this is aimed at has 16 GB of memory and no graphics
card the local model can use, so the default chunk is short and the run
reports progress. A 7B-class instruct model is the recommendation for
reading a section. The small model already used elsewhere in the program
stays the fallback. With AI switched off the compiler still builds a
complete schedule from templates and the deterministic read.
"""
import json
import os

RECOMMENDED_MODEL = "qwen2.5:7b-instruct"
FALLBACK_MODEL = "llama3.2"
CHUNK_CHARS = 3500
SETTINGS_NAME = "schedacc_settings.json"


def defaults():
    return {
        "model": RECOMMENDED_MODEL,
        "fallback_model": FALLBACK_MODEL,
        "allow_ai": True,
        "chunk_chars": CHUNK_CHARS,
        "near_critical_days": 10,
        "note": ("Recommended model is a 7B or 8B instruct model. "
                 "The smaller fallback is used when that model is not "
                 "installed. Turn AI off to build from templates and the "
                 "deterministic read only."),
    }


def path_for(directory):
    return os.path.join(directory, SETTINGS_NAME)


def load(directory=None):
    out = defaults()
    if not directory:
        return out
    try:
        with open(path_for(directory), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return out
    if isinstance(data, dict):
        for key in out:
            if key in data and key != "note":
                out[key] = data[key]
    return out


def save(directory, settings):
    os.makedirs(directory, exist_ok=True)
    data = defaults()
    data.update({k: v for k, v in (settings or {}).items() if k != "note"})
    dest = path_for(directory)
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, dest)
    return data
