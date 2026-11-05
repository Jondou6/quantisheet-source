"""Model inventory: Ollama on this PC only, made-up models, no downloads.

The fake server listens on 127.0.0.1. Sizes, names, and digests are made up.
"""
import json
import os
import shutil
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.ai import models


# Made-up model list. Sizes are not real Ollama blobs.
BIG = 2_019_393_189          # over 1 GB
SMALL = 400_000_000          # under 1 GB
DIGEST_A = "sha256:" + "ab" * 32
DIGEST_B = "sha256:" + "cd" * 32
FAKE_MODELS = [
    {"name": "llama3.2:latest", "model": "llama3.2:latest",
     "modified_at": "2026-01-15T12:00:00Z", "size": BIG,
     "digest": DIGEST_A,
     "details": {"family": "llama", "parameter_size": "3.2B",
                 "quantization_level": "Q4_K_M"}},
    {"name": "tiny-test:latest", "size": SMALL, "digest": DIGEST_B,
     "details": {"family": "test", "parameter_size": "0.5B",
                 "quantization_level": "Q4_0"}},
]


class FakeOllama:
    """A local-only stand-in for Ollama's model list."""

    def __init__(self, payload=None, status=200, redirect=None, delay=0,
                 raw=None, host="127.0.0.1"):
        self.payload = {"models": [dict(m) for m in FAKE_MODELS]} \
            if payload is None else payload
        self.status = status
        self.redirect = redirect
        self.delay = delay
        self.raw = raw
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _record(self):
                fake.requests.append((self.command, self.path,
                                      self.headers.get("Host")))

            def do_GET(self):
                self._record()
                if fake.delay:
                    import time
                    time.sleep(fake.delay)
                if fake.redirect:
                    self.send_response(302)
                    self.send_header("Location", fake.redirect)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path != "/api/tags":
                    self.send_error(404)
                    return
                if fake.raw is not None:
                    body = fake.raw
                else:
                    body = json.dumps(fake.payload).encode()
                self.send_response(fake.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self._record()
                self.send_error(500)

        self.server = HTTPServer((host, 0), Handler)
        port = self.server.server_address[1]
        self.url = f"http://{host}:{port}"
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def ollama():
    fake = FakeOllama()
    yield fake
    fake.close()


def test_default_host_is_this_pc():
    assert models.check_local(models.DEFAULT_HOST) == models.DEFAULT_HOST
    assert models.DEFAULT_HOST.startswith("http://127.0.0.1")


@pytest.mark.parametrize("host", [
    "http://203.0.113.9:11434",
    "http://192.168.0.5:11434",
    "http://10.1.2.3",
    "http://8.8.8.8",
    "http://ollama.com",
    "http://localhost.evil.test",
    "http://127.0.0.1.nip.io",
    "localhost:11434",
    "http://user:pw@127.0.0.1:11434",
    "http://127.0.0.1:11434/api/pull",
    "http://127.0.0.1:11434?x=1",
    "http://127.0.0.1:11434#frag",
    "file:///tmp/x",
    "ftp://127.0.0.1",
    "http://0.0.0.0:11434",
    "http://[::]:11434",
    "http://[::ffff:8.8.8.8]/",
    "http://169.254.1.1/",
    "",
    "http://localhost./",
])
def test_other_hosts_are_refused(host):
    with pytest.raises(models.NotLocalError):
        models.check_local(host)


def test_non_strings_are_refused():
    for bad in (None, 11434, b"http://127.0.0.1"):
        with pytest.raises(models.NotLocalError):
            models.check_local(bad)


@pytest.mark.parametrize("host", [
    "http://127.0.0.1:11434",
    "http://127.0.0.1:11434/",
    "http://127.0.0.2:9",
    "HTTP://LOCALHOST:11434",
    "http://[::1]:11434",
    "http://[::ffff:127.0.0.1]:11434",
    "https://127.0.0.1:11434",
])
def test_loopback_hosts_are_accepted(host):
    got = models.check_local(host)
    assert got.startswith(("http://", "https://"))
    assert "://" in got
    rest = got.split("://", 1)[1]
    assert rest.startswith(("127.", "localhost", "[::1]", "[::ffff:"))


def test_localhost_that_resolves_elsewhere_is_refused(monkeypatch):
    def elsewhere(hostname, port, *args, **kwargs):
        assert hostname == "localhost"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 ("203.0.113.9", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", elsewhere)
    with pytest.raises(models.NotLocalError):
        models.check_local("http://localhost:11434")


def test_outside_host_never_opens_a_connection(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("a connection was opened")

    monkeypatch.setattr(models.urllib.request.OpenerDirector, "open", boom)
    with pytest.raises(models.NotLocalError):
        models.list_installed("http://203.0.113.50:11434")


def test_list_installed_reads_the_fake_server(ollama):
    found = models.list_installed(ollama.url)
    assert [m.name for m in found] == ["llama3.2:latest", "tiny-test:latest"]
    assert found[0].size_bytes == BIG
    assert found[0].size_label == models.format_bytes(BIG)
    assert found[0].parameter_size == "3.2B"
    assert found[0].quantization == "Q4_K_M"
    assert found[0].family == "llama"
    assert found[0].digest == DIGEST_A
    assert found[0].modified_at == "2026-01-15T12:00:00Z"
    assert found[1].size_bytes == SMALL
    assert ollama.requests == [("GET", "/api/tags",
                                ollama.requests[0][2])]
    assert ollama.requests[0][2].startswith("127.0.0.1:")
    assert all(method == "GET" for method, path, host in ollama.requests)
    assert all(path == "/api/tags" for method, path, host in ollama.requests)


def test_localhost_name_reaches_the_ipv4_server(ollama):
    found = models.list_installed("http://localhost:" + ollama.url.rsplit(":", 1)[1])
    assert [m.name for m in found] == ["llama3.2:latest", "tiny-test:latest"]


def test_disk_use_is_the_sum_of_reported_sizes(ollama):
    found = models.list_installed(ollama.url)
    assert models.disk_use(found) == BIG + SMALL
    assert models.disk_use([]) == 0


def test_disk_use_rejects_raw_dicts():
    with pytest.raises(TypeError):
        models.disk_use(FAKE_MODELS)


def test_redirect_is_not_followed(monkeypatch):
    fake = FakeOllama(redirect="http://203.0.113.9/api/tags")
    try:
        with pytest.raises(models.OllamaError, match="another address"):
            models.list_installed(fake.url)
        assert fake.requests == [("GET", "/api/tags", fake.requests[0][2])]
    finally:
        fake.close()


def test_http_error_is_reported():
    fake = FakeOllama(status=500, payload={"models": []})
    try:
        with pytest.raises(models.OllamaError, match="500"):
            models.list_installed(fake.url)
    finally:
        fake.close()


def test_bad_json_is_refused():
    fake = FakeOllama(raw=b"not-json")
    try:
        with pytest.raises(models.OllamaError, match="not a model list"):
            models.list_installed(fake.url)
    finally:
        fake.close()


def test_missing_size_is_refused():
    payload = {"models": [{"name": "no-size:latest", "digest": DIGEST_A}]}
    fake = FakeOllama(payload=payload)
    try:
        with pytest.raises(models.OllamaError, match="how big"):
            models.list_installed(fake.url)
    finally:
        fake.close()


def test_huge_reply_is_refused():
    fake = FakeOllama(raw=b" " * (models.MAX_BODY + 1))
    try:
        with pytest.raises(models.OllamaError, match="too large"):
            models.list_installed(fake.url)
    finally:
        fake.close()


def test_unreachable_port_is_an_error():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with pytest.raises(models.OllamaError, match="Can't reach Ollama"):
        models.list_installed(f"http://127.0.0.1:{port}", timeout=2)


def test_slow_server_times_out():
    fake = FakeOllama(delay=2)
    try:
        with pytest.raises(models.OllamaError, match="Can't reach Ollama"):
            models.list_installed(fake.url, timeout=0.2)
    finally:
        fake.close()


def test_proxy_environment_is_ignored(ollama, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://203.0.113.9:8080")
    monkeypatch.setenv("HTTP_PROXY", "http://203.0.113.9:8080")
    monkeypatch.setenv("https_proxy", "http://203.0.113.9:8080")
    found = models.list_installed(ollama.url)
    assert len(found) == 2
    assert [path for method, path, host in ollama.requests] == ["/api/tags"]


def test_module_does_not_download():
    text = open(models.__file__, encoding="utf-8").read().lower()
    assert "/api/pull" not in text
    assert "ollama pull" not in text
    assert "proxyhandler({})" in text
    assert "api/tags" in text


def test_free_disk_matches_the_drive(tmp_path):
    got = models.free_disk(tmp_path)
    usage = shutil.disk_usage(tmp_path)
    assert got.free_bytes == usage.free
    assert got.total_bytes == usage.total
    assert os.path.samefile(got.path, tmp_path)


def test_free_disk_missing_path(tmp_path):
    missing = tmp_path / "no-such-folder"
    with pytest.raises(models.OllamaError, match="not there"):
        models.free_disk(missing)


def test_recommend_size_follows_the_ram_bands():
    cases = (
        (64 * models.GB, 20 * models.GB, "32 billion"),
        (32 * models.GB, 12 * models.GB, "14 billion"),
        (16 * models.GB, 5 * models.GB, "7 to 8"),
        (8 * models.GB, 2 * models.GB, "3 billion"),
        (8 * models.GB - 1, 1 * models.GB, "very small"),
        (4 * models.GB, 1 * models.GB, "very small"),
        (1 * models.GB, models.GB // 2, "very small"),
        (0, 0, "no installed memory"),
    )
    for ram, cap, words in cases:
        advice = models.recommend_size(ram)
        assert advice.ram_bytes == ram
        assert advice.max_bytes == cap
        assert words in advice.reason
        assert advice.max_bytes <= max(ram // 2, 0)


def test_recommend_size_rejects_a_bool_or_a_negative():
    with pytest.raises(ValueError):
        models.recommend_size(True)
    with pytest.raises(ValueError):
        models.recommend_size(-1)
    # 8 means 8 bytes, not 8 GB. Half of that is the cap.
    tiny = models.recommend_size(8)
    assert tiny.max_bytes == 4
    assert "4 bytes" in tiny.reason
    one = models.recommend_size(1)
    assert one.max_bytes == 0
    assert "too little" in one.reason


def test_machine_ram_is_a_positive_count():
    n = models.machine_ram_bytes()
    assert isinstance(n, int) and n > 0


def test_download_warning_only_over_one_gb():
    assert models.download_warning(models.GB) == ""
    assert models.download_warning(SMALL) == ""
    assert models.download_warning(0) == ""
    text = models.download_warning(BIG)
    assert f"{models.format_bytes(BIG)}, which is over 1 GB" in text
    assert "Nothing has been downloaded yet." in text
    just = models.download_warning(models.GB + 1)
    assert just.startswith("This download is just over 1 GB.")
    assert "Nothing has been downloaded yet." in just


def test_download_warning_mentions_free_space():
    tight = models.download_warning(2 * models.GB, free_bytes=models.GB)
    assert "not enough" in tight
    assert "Nothing has been downloaded yet." in tight
    roomy = models.download_warning(2 * models.GB, free_bytes=10 * models.GB)
    assert "10.0 GB free" in roomy
    assert "not enough" not in roomy
    exact = models.download_warning(2 * models.GB, free_bytes=2 * models.GB)
    assert "not enough" not in exact


def test_download_warning_rejects_bad_numbers():
    with pytest.raises(ValueError):
        models.download_warning(-1)
    with pytest.raises(ValueError):
        models.download_warning(True)
    with pytest.raises(ValueError):
        models.download_warning(2 * models.GB, free_bytes=-5)
    # A small download still validates free_bytes, and stays quiet.
    assert models.download_warning(100, free_bytes=0) == ""


def test_inventory_bundles_the_snapshot(ollama, tmp_path):
    inv = models.inventory(ollama.url, disk_path=tmp_path,
                           ram_bytes=16 * models.GB)
    assert [m.name for m in inv.models] == ["llama3.2:latest",
                                            "tiny-test:latest"]
    assert inv.used_bytes == BIG + SMALL
    assert inv.used_label == models.format_bytes(BIG + SMALL)
    assert inv.advice.max_bytes == 5 * models.GB
    assert inv.disk.free_bytes == shutil.disk_usage(tmp_path).free
    assert [path for method, path, host in ollama.requests] == ["/api/tags"]


def test_format_bytes_labels():
    assert models.format_bytes(0) == "0 bytes"
    assert models.format_bytes(1) == "1 byte"
    assert models.format_bytes(models.GB) == "1.0 GB"
    assert models.format_bytes(512 * 1024 * 1024) == "512.0 MB"
