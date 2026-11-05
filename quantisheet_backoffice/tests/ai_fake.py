"""A fake local model server for the AI tests (no real model anywhere):
listens on 127.0.0.1, answers the Ollama API (/api/tags, /api/chat) and the
OpenAI-compatible one (/v1/models, /v1/chat/completions), and records every
request so tests can check exactly what was sent. `redirect_to` makes every
answer a 302 to that address (the redirect test)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

DIGEST = "0123456789abcdef0123456789abcdef"     # made up


class FakeOllama:
    def __init__(self, models=("llama3.2:latest",)):
        self.models = list(models)
        self.requests = []
        self.reply = lambda body: json.dumps({})
        self.redirect_to = None
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj):
                data = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _redirected(self):
                if not fake.redirect_to:
                    return False
                self.send_response(302)
                self.send_header("Location", fake.redirect_to + self.path)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return True

            def do_GET(self):
                fake.requests.append(("GET", self.path, None))
                if self._redirected():
                    return
                if self.path == "/api/tags":
                    self._send({"models": [
                        {"name": m, "digest": DIGEST,
                         "details": {"parameter_size": "3.2B",
                                     "quantization_level": "Q4_K_M"}}
                        for m in fake.models]})
                elif self.path == "/v1/models":
                    self._send({"data": [{"id": m} for m in fake.models]})
                else:
                    self.send_error(404)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                fake.requests.append(("POST", self.path, body))
                if self._redirected():
                    return
                if self.path not in ("/api/chat", "/v1/chat/completions"):
                    self.send_error(404)
                    return
                content = fake.reply(body)
                if not isinstance(content, str):
                    content = json.dumps(content)
                if self.path == "/api/chat":
                    self._send({"model": body.get("model"), "done": True,
                                "message": {"role": "assistant",
                                            "content": content}})
                else:
                    self._send({"model": body.get("model"), "choices": [
                        {"message": {"role": "assistant",
                                     "content": content}}]})

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def chats(self):
        return [b for m, p, b in self.requests
                if p in ("/api/chat", "/v1/chat/completions")]

    def sent_text(self):
        return "\n".join(m["content"] for b in self.chats()
                         for m in b["messages"])

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def router(by_phrase):
    """A reply function for assistant tests: the first phrase (lower case)
    found in the user's question picks the route dict."""
    def reply(body):
        q = body["messages"][-1]["content"].lower()
        for phrase, route in by_phrase.items():
            if phrase in q:
                return route
        return {"tool": ""}
    return reply
