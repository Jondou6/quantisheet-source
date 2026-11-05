"""The only way Back Office talks to an AI model (P3-01, P3-05, P3-06;
decision 14 = A): a model server on this PC - Ollama by default, or another
localhost runtime with an OpenAI-compatible API - with the model the user
picked in Settings > AI. No cloud AI, no other address.

Transport rules:
* the address must be localhost / loopback (check_local);
* no proxies (ProxyHandler({})) and NO redirects: a 30x answer raises
  instead of being followed, so a local server can't bounce a request to
  another host (_NoRedirect);
* short timeouts (TIMEOUT for a reply, TAGS_TIMEOUT for 'is it there').

Everything here is optional. With no server, no model chosen or the server
stopped, available() is False and callers say so (decision 6.3 = A, Jon,
Oct 22, 2026: 'AI is unavailable', plus the plain search). Nothing a model
returns is posted, approved or moved by this module.

Every prompt goes through aiguard.prepare() first, so personal data never
reaches the model.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import aiguard, settings

DEFAULT_URL = "http://localhost:11434"     # same default QuantiSheet uses
APIS = {"ollama": "Ollama", "openai": "OpenAI-compatible (localhost)"}
TIMEOUT = 30
TAGS_TIMEOUT = 3
LOCAL_NAMES = {"localhost"}


class AIUnavailable(RuntimeError):
    """No local model is set up or it did not answer; callers degrade."""


class NotLocalError(ValueError):
    """An address that is not this PC was given for the AI server."""


class Cancelled(RuntimeError):
    """The user pressed Cancel."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code, f"redirect to {newurl!r} refused (the AI "
            f"server must answer itself)", headers, fp)


def check_local(url: str) -> str:
    """Return `url` when it points at this PC (localhost / loopback);
    raise NotLocalError otherwise."""
    p = urllib.parse.urlparse(url or "")
    if p.scheme not in ("http", "https") or not p.hostname:
        raise NotLocalError(f"not a local AI address: {url!r}")
    host = p.hostname.lower()
    if host in LOCAL_NAMES:
        return url.rstrip("/")
    try:
        if ipaddress.ip_address(host).is_loopback:
            return url.rstrip("/")
    except ValueError:
        pass
    raise NotLocalError("The AI server must run on this PC (localhost). "
                        f"{host} is not allowed: Back Office never sends "
                        "data to an outside AI.")


def config() -> dict:
    return {"url": settings.get("ai_url") or DEFAULT_URL,
            "model": settings.get("ai_model") or "",
            "api": settings.get("ai_api") or "ollama",
            "threshold": str(settings.get("ai_threshold") or "0.80")}


def configure(url=None, model=None, threshold=None, api=None) -> dict:
    """Settings > AI: the local address, the model the user chose, the
    runtime type and the confidence threshold for bulk accept."""
    if url is not None:
        settings.set("ai_url", check_local(url) if url else "")
    if model is not None:
        settings.set("ai_model", str(model).strip())
    if api is not None:
        if api not in APIS:
            raise ValueError(f"api is one of {', '.join(APIS)}")
        settings.set("ai_api", api)
    if threshold is not None:
        from decimal import Decimal, InvalidOperation
        try:
            t = Decimal(str(threshold))
        except InvalidOperation:
            raise ValueError("threshold is a number between 0 and 1")
        if not 0 <= t <= 1:
            raise ValueError("threshold is between 0 and 1")
        settings.set("ai_threshold", str(t))
    return config()


def input_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class Client:
    """A minimal client for a local model server (stdlib only)."""

    def __init__(self, url=None, model=None, timeout=TIMEOUT, api=None):
        cfg = config()
        self.url = check_local(url or cfg["url"])
        self.model = model if model is not None else cfg["model"]
        self.api = api or cfg["api"]
        self.timeout = timeout
        self.cancel = threading.Event()
        self.calls = 0                      # chat calls made (tests, log)
        self._info = None
        # The UI sets runner to run each HTTP call off the UI thread (the
        # database work stays on the UI thread); None = call directly.
        self.runner = None
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect())

    # ---- transport ---------------------------------------------------------
    def _request(self, path, body=None, timeout=None):
        if self.cancel.is_set():
            raise Cancelled("Cancelled.")
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.url + path, data=data, method="POST" if data else "GET",
            headers={"Content-Type": "application/json"})
        def call():
            with self._opener.open(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        try:
            out = self.runner(call) if self.runner else call()
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise AIUnavailable(f"The local AI model did not answer ({e}).") \
                from e
        if self.cancel.is_set():
            raise Cancelled("Cancelled.")
        return out

    def _models_raw(self) -> list[dict]:
        if self.api == "openai":
            return [{"name": m.get("id", ""), "digest": "", "details": {}}
                    for m in self._request("/v1/models", timeout=TAGS_TIMEOUT
                                           ).get("data", [])]
        return self._request("/api/tags", timeout=TAGS_TIMEOUT).get(
            "models", [])

    def models(self) -> list[str]:
        return sorted(m.get("name", "") for m in self._models_raw())

    def model_info(self) -> dict:
        """{'name', 'version'}: the installed model's own name and digest /
        size as the server reports them (for the audit trail)."""
        if self._info is None:
            info = {"name": self.model, "version": ""}
            try:
                for m in self._models_raw():
                    n = m.get("name", "")
                    if n == self.model or n.split(":")[0] == \
                            self.model.split(":")[0]:
                        d = m.get("details") or {}
                        parts = [x for x in (
                            (m.get("digest") or "")[:12],
                            d.get("parameter_size", ""),
                            d.get("quantization_level", "")) if x]
                        info = {"name": n, "version": " ".join(parts)}
                        break
            except AIUnavailable:
                pass
            self._info = info
        return self._info

    def available(self) -> bool:
        if not self.model:
            return False
        try:
            names = self.models()
        except AIUnavailable:
            return False
        base = {n.split(":")[0] for n in names}
        return self.model in names or self.model.split(":")[0] in base

    def test_connection(self) -> str:
        """Settings > AI 'Test connection'."""
        if not self.model:
            return "Choose a model first."
        try:
            names = self.models()
        except AIUnavailable as e:
            return f"Not reachable: {e}"
        if not self.available():
            return (f"Connected, but {self.model} is not installed "
                    f"(installed: {', '.join(names) or 'none'}).")
        i = self.model_info()
        return f"Connected: {i['name']} {i['version']}".strip()

    def chat(self, office, system: str, user: str, json_reply=True) -> dict:
        """Send one prompt; returns {'text', 'model', 'model_version',
        'input_hash', 'prompt'}. The prompt is scrubbed and checked for
        personal data first (aiguard); one that still holds any is not
        sent."""
        if not self.model:
            raise AIUnavailable("No local model is chosen (Settings > AI).")
        system = aiguard.prepare(office, system)
        user = aiguard.prepare(office, user)
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
        self.calls += 1
        if self.api == "openai":
            body = {"model": self.model, "temperature": 0, "messages": msgs}
            if json_reply:
                body["response_format"] = {"type": "json_object"}
            r = self._request("/v1/chat/completions", body)
            ch = (r.get("choices") or [{}])[0]
            text = (ch.get("message") or {}).get("content", "")
        else:
            body = {"model": self.model, "stream": False,
                    "options": {"temperature": 0}, "messages": msgs}
            if json_reply:
                body["format"] = "json"
            r = self._request("/api/chat", body)
            text = (r.get("message") or {}).get("content", "")
        info = self.model_info()
        return {"text": text, "model": r.get("model") or info["name"],
                "model_version": info["version"],
                "input_hash": input_hash(system + "\n" + user),
                "prompt": user}


def client() -> Client | None:
    """A client for the chosen model, or None when none is set up."""
    try:
        c = Client()
    except NotLocalError:
        return None
    return c if c.model else None


def ready_client() -> Client | None:
    """A client whose server answers and has the model; else None."""
    c = client()
    return c if c is not None and c.available() else None


def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply ({} if none)."""
    text = (text or "").strip()
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else {}
    except ValueError:
        pass
    a, b = text.find("{"), text.rfind("}")
    if a >= 0 and b > a:
        try:
            v = json.loads(text[a:b + 1])
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}
    return {}
