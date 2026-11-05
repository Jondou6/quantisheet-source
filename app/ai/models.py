"""What this PC already has installed for the local AI, and whether a
bigger model would fit.

Ollama's model list is read from its HTTP API on this computer only.
Any other address is refused before a connection is opened. Nothing in
this module downloads a model: there is no request other than the model
list, and `download_warning` only returns text for the caller to show.

GB below means 1024 x 1024 x 1024 bytes, the same way the rest of
QuantiSheet reports disk space.
"""
import ipaddress
import json
import os
import shutil
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_HOST = "http://127.0.0.1:11434"
GB = 1024 ** 3
WARN_BYTES = GB                 # warn when a download is over this
TAGS_TIMEOUT = 5                # the model list is a small local request
MAX_BODY = 2 * 1024 * 1024      # a real model list is a few kilobytes
_LOCAL_NAME = "localhost"

__all__ = [
    "DEFAULT_HOST",
    "GB",
    "WARN_BYTES",
    "TAGS_TIMEOUT",
    "NotLocalError",
    "OllamaError",
    "InstalledModel",
    "DiskSpace",
    "SizeAdvice",
    "Inventory",
    "check_local",
    "list_installed",
    "disk_use",
    "free_disk",
    "machine_ram_bytes",
    "recommend_size",
    "download_warning",
    "format_bytes",
    "inventory",
]


class NotLocalError(ValueError):
    """The address is not Ollama on this PC. Nothing was contacted."""


class OllamaError(RuntimeError):
    """Ollama on this PC did not return a model list. Nothing was downloaded."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 30x answer is refused. Following it could leave this PC."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OllamaError(
            "Ollama tried to send the model list to another address. "
            "That was refused. Nothing was downloaded.")


class InstalledModel:
    """One model Ollama says is installed. `size_bytes` is the size
    Ollama reported for it (0 is not used: a missing size is an error)."""

    def __init__(self, name, size_bytes, digest="", parameter_size="",
                 quantization="", family="", modified_at=""):
        self.name = name
        self.size_bytes = size_bytes
        self.digest = digest
        self.parameter_size = parameter_size
        self.quantization = quantization
        self.family = family
        self.modified_at = modified_at

    @property
    def size_label(self):
        return format_bytes(self.size_bytes)

    def __eq__(self, other):
        if not isinstance(other, InstalledModel):
            return NotImplemented
        return (self.name, self.size_bytes, self.digest,
                self.parameter_size, self.quantization, self.family,
                self.modified_at) == (
            other.name, other.size_bytes, other.digest,
            other.parameter_size, other.quantization, other.family,
            other.modified_at)

    def __repr__(self):
        return f"InstalledModel({self.name!r}, {self.size_label})"


class DiskSpace:
    """Free space on one drive. `free_bytes` is what a normal user can use."""

    def __init__(self, path, total_bytes, free_bytes):
        self.path = path
        self.total_bytes = total_bytes
        self.free_bytes = free_bytes

    @property
    def free_label(self):
        return format_bytes(self.free_bytes)

    def __repr__(self):
        return f"DiskSpace({self.path!r}, {self.free_label} free)"


class SizeAdvice:
    """Largest model file that should be loaded on this PC.

    `ram_bytes` is the memory the advice was based on. `max_bytes` is the
    biggest file to download. `parameter_label` is plain language for that
    size ('about 3 billion parameters'). `reason` is the sentence to show.
    """

    def __init__(self, ram_bytes, max_bytes, parameter_label, reason):
        self.ram_bytes = ram_bytes
        self.max_bytes = max_bytes
        self.parameter_label = parameter_label
        self.reason = reason

    @property
    def max_label(self):
        return format_bytes(self.max_bytes)

    def __repr__(self):
        return f"SizeAdvice(up to {self.max_label})"


class Inventory:
    """One snapshot: installed models, the disk they use, free disk, and
    the size that fits this PC's memory. It does not change over time."""

    def __init__(self, models, used_bytes, disk, advice):
        self.models = tuple(models)
        self.used_bytes = used_bytes
        self.disk = disk
        self.advice = advice

    @property
    def used_label(self):
        return format_bytes(self.used_bytes)


# (minimum RAM, largest model file, words for the reason). A Q4 model
# needs about its file size of memory while it is loaded, and QuantiSheet
# still has to open the drawings, so the cap stays well under the RAM.
# The first row that fits wins. Under 8 GB, only a very small model.
_BANDS = (
    (64 * GB, 20 * GB, "about 32 billion parameters"),
    (32 * GB, 12 * GB, "about 14 billion parameters"),
    (16 * GB, 5 * GB, "about 7 to 8 billion parameters"),
    (8 * GB, 2 * GB, "about 3 billion parameters"),
    (0, 1 * GB, "a very small model"),
)


def format_bytes(n):
    """'2.0 GB', '512.0 MB', or '12 bytes'. GB/MB are powers of 1024."""
    n = _nonneg_int(n, "n")
    if n >= GB:
        return f"{n / GB:.1f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    if n == 1:
        return "1 byte"
    return f"{n} bytes"


def check_local(host):
    """Return `host` with no trailing slash when it is this PC.

    Accepted: http or https, hostname exactly 'localhost', or a loopback
    address (127.0.0.0/8, ::1, or an IPv4-mapped loopback). No user name,
    password, path, query, or fragment — the only request this module
    makes is the model list on that host.

    'localhost' is allowed only when every address it resolves to is
    loopback. Anything else raises NotLocalError and does not connect.
    """
    if not isinstance(host, str):
        raise NotLocalError(
            "The model list only talks to Ollama on this PC.")
    raw = host.strip()
    if (not raw or any(ord(c) < 32 or ord(c) == 127 for c in raw)
            or any(c in raw for c in " @\\")):
        raise NotLocalError(
            "The model list only talks to Ollama on this PC.")
    try:
        parsed = urllib.parse.urlparse(raw)
        port = parsed.port
    except ValueError:
        raise NotLocalError(
            "The model list only talks to Ollama on this PC.") from None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise NotLocalError(
            "The model list only talks to Ollama on this PC.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise NotLocalError(
            "The model list only talks to Ollama on this PC.")
    if parsed.path not in ("", "/"):
        raise NotLocalError(
            "The model list only talks to Ollama on this PC. "
            "Pass the host, not a path.")
    name = parsed.hostname
    if not _is_this_pc(name):
        raise NotLocalError(
            f"{name} is not this PC. The model list never contacts "
            "another computer.")
    return _rebuild(parsed.scheme, name, port)


def list_installed(host=DEFAULT_HOST, timeout=TAGS_TIMEOUT):
    """Models Ollama has installed on this PC, in the order it listed them.

    Each item is an InstalledModel. The size is what Ollama reported.
    Raises NotLocalError for a host that is not this PC (no connection is
    opened) and OllamaError when Ollama does not answer. Never downloads.
    """
    base = check_local(host)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("timeout must be a number of seconds.")
    if timeout <= 0:
        raise ValueError("timeout must be a number of seconds.")
    raw = _get(base + "/api/tags", timeout)
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise OllamaError(
            "Ollama's reply was not a model list. Nothing was downloaded."
        ) from e
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise OllamaError(
            "Ollama's reply was not a model list. Nothing was downloaded.")
    return [_model(item) for item in data["models"]]


def disk_use(models):
    """Bytes the models occupy, added up from the sizes Ollama reported.

    This is the sum of those reported sizes, not a second look at the
    Ollama folder (manifests and copies are not counted again).
    """
    total = 0
    for model in models:
        if not isinstance(model, InstalledModel):
            raise TypeError("disk_use expects models from list_installed.")
        total += model.size_bytes
    return total


def free_disk(path=None):
    """Free space on the drive that holds `path` (the home folder if omitted).

    Returns a DiskSpace. Raises OllamaError when the path is not there.
    """
    if path is None:
        path = os.path.expanduser("~")
    path = os.fspath(path)
    if not os.path.exists(path):
        raise OllamaError(
            f"Can't check free disk space: {path} is not there.")
    usage = shutil.disk_usage(path)
    return DiskSpace(os.path.abspath(path), int(usage.total), int(usage.free))


def machine_ram_bytes():
    """Installed memory in bytes, as the operating system reports it.

    Windows: GlobalMemoryStatusEx. Other systems: the page count the
    kernel reports. This is the machine's memory, not a container limit.
    """
    if sys.platform == "win32":
        return _windows_ram_bytes()
    return _posix_ram_bytes()


def recommend_size(ram_bytes=None):
    """A model size that should fit `ram_bytes` with room left over.

    `ram_bytes` is a number of bytes (not gigabytes). Omit it to read this
    PC. The suggestion:

        64 GB or more  -> up to 20 GB (about 32 billion parameters)
        32 GB or more  -> up to 12 GB (about 14 billion parameters)
        16 GB or more  -> up to 5 GB  (about 7 to 8 billion parameters)
        8 GB or more   -> up to 2 GB  (about 3 billion parameters)
        under 8 GB     -> up to 1 GB  (a very small model)

    The cap is also kept to half the memory or less. A PC that reports no
    memory gets a cap of 0. This does not download anything.
    """
    if ram_bytes is None:
        ram = machine_ram_bytes()
    else:
        ram = _nonneg_int(ram_bytes, "ram_bytes")
    cap, label = _BANDS[-1][1], _BANDS[-1][2]
    for minimum, band_cap, band_label in _BANDS:
        if ram >= minimum:
            cap, label = band_cap, band_label
            break
    if ram == 0:
        cap = 0
        reason = ("This PC reported no installed memory, so no model "
                  "size can be recommended.")
    else:
        cap = min(cap, ram // 2)
        if cap <= 0:
            reason = (f"This PC has {format_bytes(ram)} of memory, which "
                      "is too little for a local model.")
        else:
            reason = (f"This PC has {format_bytes(ram)} of memory. "
                      f"A model up to {format_bytes(cap)} ({label}) leaves "
                      "room for QuantiSheet and the drawings. A larger "
                      "model is likely to run out of memory.")
    return SizeAdvice(ram, cap, label, reason)


def download_warning(size_bytes, free_bytes=None):
    """Text to show before a download larger than 1 GB.

    Returns '' when `size_bytes` is 1 GB or smaller, so the caller shows
    a warning only when this is not empty. `free_bytes`, when passed, is
    mentioned, and the text says when it is not enough. This function
    does not download anything, and neither does the rest of the module.
    """
    size = _nonneg_int(size_bytes, "size_bytes")
    free = None
    if free_bytes is not None:
        free = _nonneg_int(free_bytes, "free_bytes")
    if size <= WARN_BYTES:
        return ""
    label = format_bytes(size)
    if label == "1.0 GB":
        sentence = "This download is just over 1 GB."
    else:
        sentence = f"This download is {label}, which is over 1 GB."
    if free is None:
        room = ""
    elif free < size:
        room = f" Only {format_bytes(free)} free, which is not enough."
    else:
        room = f" This PC has {format_bytes(free)} free."
    if free is not None and free < size:
        tail = (" Free up disk space before downloading. "
                "Nothing has been downloaded yet.")
    else:
        tail = (" It needs that much free disk and can take a long time. "
                "Nothing has been downloaded yet.")
    return sentence + room + tail


def inventory(host=DEFAULT_HOST, disk_path=None, ram_bytes=None,
              timeout=TAGS_TIMEOUT):
    """The model picker in one call: installed models, their disk use,
    free disk, and the size that fits this PC's memory. Never downloads.
    """
    models = list_installed(host, timeout=timeout)
    return Inventory(models, disk_use(models), free_disk(disk_path),
                     recommend_size(ram_bytes))


def _nonneg_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{name} must be a whole number of bytes, zero or more.")
    if value < 0:
        raise ValueError(
            f"{name} must be a whole number of bytes, zero or more.")
    return value


def _is_loopback_ip(text):
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return False
    if addr.is_loopback:
        return True
    mapped = getattr(addr, "ipv4_mapped", None)
    return bool(mapped is not None and mapped.is_loopback)


def _is_this_pc(hostname):
    if _is_loopback_ip(hostname):
        return True
    if hostname.lower() != _LOCAL_NAME:
        return False
    # The name "localhost" is only trusted when it actually points here.
    # No other name is looked up, so a caller's hostname is never sent out.
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    addresses = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr:
            addresses.append(sockaddr[0])
    return bool(addresses) and all(_is_loopback_ip(a) for a in addresses)


def _rebuild(scheme, hostname, port):
    if hostname.lower() == _LOCAL_NAME:
        shown = _LOCAL_NAME
    else:
        addr = ipaddress.ip_address(hostname)
        if addr.version == 6:
            shown = f"[{addr.compressed}]"
        else:
            shown = str(addr)
    if port is None:
        return f"{scheme}://{shown}"
    return f"{scheme}://{shown}:{port}"


def _get(url, timeout):
    request = urllib.request.Request(
        url, method="GET", headers={"Accept": "application/json",
                                    "User-Agent": "QuantiSheet-model-list"})
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return _read_capped(response)
    except OllamaError:
        raise
    except urllib.error.HTTPError as e:
        raise OllamaError(
            f"Ollama on this PC returned an error ({e.code}) for the "
            "model list. Nothing was downloaded.") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError,
            OSError) as e:
        raise OllamaError(
            "Can't reach Ollama on this PC. Start it and try again. "
            "Nothing was downloaded.") from e


def _read_capped(response):
    chunks = []
    total = 0
    while True:
        block = response.read(65536)
        if not block:
            break
        total += len(block)
        if total > MAX_BODY:
            raise OllamaError(
                "Ollama's model list was far too large to trust. "
                "Nothing was downloaded.")
        chunks.append(block)
    return b"".join(chunks)


def _model(item):
    if not isinstance(item, dict):
        raise OllamaError(
            "Ollama's model list has an entry that isn't a model.")
    name = item.get("name") or item.get("model") or ""
    if not isinstance(name, str) or not name.strip():
        raise OllamaError(
            "Ollama's model list has an entry with no name.")
    name = name.strip()
    if "size" not in item:
        raise OllamaError(f"Ollama didn't say how big {name} is.")
    size = item["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise OllamaError(f"Ollama reported a bad size for {name}.")
    details = item.get("details") or {}
    if not isinstance(details, dict):
        details = {}
    digest = item.get("digest") or ""
    modified = item.get("modified_at") or ""
    return InstalledModel(
        name=name,
        size_bytes=size,
        digest=digest if isinstance(digest, str) else "",
        parameter_size=_text(details.get("parameter_size")),
        quantization=_text(details.get("quantization_level")),
        family=_text(details.get("family")),
        modified_at=modified if isinstance(modified, str) else "",
    )


def _text(value):
    return value if isinstance(value, str) else ""


def _windows_ram_bytes():
    """Installed RAM via GlobalMemoryStatusEx. Windows only."""
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = (
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        )

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
    kernel.GlobalMemoryStatusEx.restype = ctypes.c_int
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OllamaError(
            "Windows didn't report how much memory this PC has.")
    total = int(status.ullTotalPhys)
    if total <= 0:
        raise OllamaError("Windows reported no installed memory.")
    return total


def _posix_ram_bytes():
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, AttributeError):
        pages = size = -1
    if not isinstance(pages, int) or not isinstance(size, int):
        pages = size = -1
    if pages <= 0 or size <= 0:
        raise OllamaError("This PC's memory size could not be read.")
    return pages * size
