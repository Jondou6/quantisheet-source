"""Hostile-file rules for every XML the program reads (threat model
T-007): a size cap, and no DOCTYPE or ENTITY declaration in ANY encoding
(expat itself reads the file and refuses one, so UTF-16 or other
encodings can't slip past a byte search) - which stops entity-expansion
("billion laughs") and external-entity tricks. Zip members (xlsx) are
size-checked before they are read."""
import os
import xml.etree.ElementTree as ET
from xml.parsers import expat

MAX_BYTES = 50 * 1024 * 1024        # an XML file or one zip member
MAX_RATIO = 200                      # zip member: uncompressed / packed


class HostileFile(ValueError):
    pass


def _refuse(*_a):
    raise HostileFile("The file contains a DOCTYPE / ENTITY declaration, "
                      "so it isn't read (protects against entity-expansion "
                      "attacks).")


def check_bytes(data, max_bytes=None):
    max_bytes = max_bytes or MAX_BYTES
    if len(data) > max_bytes:
        raise HostileFile(f"The file is too big ({len(data):,} bytes; the "
                          f"limit is {max_bytes:,}).")
    p = expat.ParserCreate()
    p.StartDoctypeDeclHandler = _refuse
    p.EntityDeclHandler = _refuse
    p.UnparsedEntityDeclHandler = _refuse
    p.ExternalEntityRefHandler = lambda *a: _refuse()
    try:
        p.Parse(data, True)
    except HostileFile:
        raise
    except expat.ExpatError as e:
        raise ET.ParseError(str(e)) from None
    return data


def fromstring(data, max_bytes=None):
    """ET.fromstring after the checks above."""
    return ET.fromstring(check_bytes(data, max_bytes))


def read(path, max_bytes=None):
    max_bytes = max_bytes or MAX_BYTES
    size = os.path.getsize(path)
    if size > max_bytes:
        raise HostileFile(f"The file is too big ({size:,} bytes; the limit "
                          f"is {max_bytes:,}).")
    with open(path, "rb") as f:
        return f.read()


def parse(path, max_bytes=None):
    """An ElementTree of the file at `path`, after the checks."""
    return ET.ElementTree(fromstring(read(path, max_bytes), max_bytes))


def zip_read(z, name, max_bytes=None):
    """One member of an open ZipFile, refusing a zip bomb."""
    max_bytes = max_bytes or MAX_BYTES
    info = z.getinfo(name)
    if info.file_size > max_bytes or (
            info.compress_size and
            info.file_size / max(info.compress_size, 1) > MAX_RATIO and
            info.file_size > 1024 * 1024):
        raise HostileFile(f"{name} in the file is too big when unpacked "
                          f"({info.file_size:,} bytes).")
    return z.read(name)
