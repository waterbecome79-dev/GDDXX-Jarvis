"""A local HTTP API so other programs can ask Jarvis something without a window or a microphone.

  GET  /health                 -> {"ok": true, "service": true, "model": "deepseek-chat"}
  POST /ask   {"text": "..."}  -> {"reply_en": "...", "reply_zh": "..."}
  GET  /ask?text=...           -> the same, for curl

The question travels to the running voice service over ws://127.0.0.1:8765 ({"type": "ask"}), so the
answer comes from the same brain, memory and tools the voice uses -- it is simply never read aloud.
Only 127.0.0.1 is served. JARVIS_API_PORT (default 8770) picks another port; run with `python -m jarvis.api`.
"""
import asyncio
import json
import os
import socket
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, paths

HOST = "127.0.0.1"
PORT = int(os.environ.get("JARVIS_API_PORT", 8770))
VOICE = int(os.environ.get("JARVIS_VOICE_PORT", 8765))
TIMEOUT = float(os.environ.get("JARVIS_API_TIMEOUT", 150))
LOG = paths.DATA / "api.log"


def log(line: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def service_up() -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex((HOST, VOICE)) == 0


async def ask(text: str) -> dict:
    import websockets

    req = uuid.uuid4().hex
    loop = asyncio.get_running_loop()
    deadline = loop.time() + TIMEOUT
    async with websockets.connect(f"ws://{HOST}:{VOICE}", open_timeout=8, max_size=None) as ws:
        await ws.send(json.dumps({"type": "ask", "req": req, "text": text}, ensure_ascii=False))
        while True:
            left = deadline - loop.time()
            if left <= 0:
                raise TimeoutError("the voice service did not answer in time")
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=left))
            if m.get("type") == "answer":
                if m.get("error"):
                    raise RuntimeError(m["error"])
                return {"reply_en": m.get("en", ""), "reply_zh": m.get("zh", "")}


class Handler(BaseHTTPRequestHandler):
    server_version = "JarvisAPI/1.0"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - http.server naming
        # Under pythonw.exe sys.stderr is None, and the base class writes the access log to it;
        # that AttributeError would kill the request before a single byte reaches the client.
        log("%s %s" % (self.address_string(), fmt % args))

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _answer(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return self._send(400, {"error": "empty text"})
        if not service_up():
            return self._send(503, {"error": "the voice service is not running (start it with: pythonw -m jarvis)"})
        try:
            out = asyncio.run(ask(text))
        except Exception as e:                       # noqa: BLE001 - the caller gets the reason as JSON
            log(f"{text[:80]} -> {type(e).__name__}: {e}")
            return self._send(502, {"error": f"{type(e).__name__}: {e}"})
        log(f"{text[:80]} -> {out['reply_en'][:120]}")
        self._send(200, {"ok": True, **out, "text": text})

    def do_GET(self) -> None:                        # noqa: N802 - http.server naming
        u = urlparse(self.path)
        if u.path == "/health":
            self._send(200, {"ok": True, "service": service_up(), "model": config.llm()[2] or "",
                             "reply_lang": config.get("reply_lang") or "en", "api_port": PORT, "voice_port": VOICE})
        elif u.path == "/ask":
            self._answer(parse_qs(u.query).get("text", [""])[0])
        else:
            self._send(404, {"error": "use GET /health or POST /ask"})

    def do_POST(self) -> None:                       # noqa: N802 - http.server naming
        if urlparse(self.path).path != "/ask":
            return self._send(404, {"error": "use POST /ask"})
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8", "replace") if n else ""
        text = raw
        if raw.lstrip().startswith("{"):
            try:
                text = json.loads(raw).get("text", "")
            except json.JSONDecodeError:
                return self._send(400, {"error": "body is not valid JSON"})
        self._answer(text)


def main() -> None:
    paths.DATA.mkdir(parents=True, exist_ok=True)
    log(f"listening on http://{HOST}:{PORT} -> voice ws://{HOST}:{VOICE}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
