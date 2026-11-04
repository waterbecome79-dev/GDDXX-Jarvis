"""Pure checks: no microphone, no speech models, no window.

    python tests/test_units.py

Covers screenshot number stripping, the nightly review's one retry after a
failed model call, and the add-on server claiming a free local port.
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

for _k in ("JARVIS_CONFIG", "JARVIS_MEMORY", "JARVIS_LLM_BASE_URL", "JARVIS_LLM_API_KEY", "JARVIS_LLM_MODEL"):
    os.environ.pop(_k, None)
os.environ["JARVIS_HOME"] = tempfile.mkdtemp()
os.environ["JARVIS_APP_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def screen_and_reply():
    from jarvis import screen
    from jarvis.brain import split_reply
    from jarvis.plugins import creator
    from jarvis.wake import greet_wake, split_wake

    assert split_wake("Hey Jarvis, open the light") == (True, "open the light")
    assert split_wake("贾维斯，打开灯") == (True, "打开灯")
    assert split_wake("Tonight the television said jarvis is a movie character") == (False, "")
    assert greet_wake("Hi everyone, welcome to the show") == (False, "")
    assert greet_wake("Hi Travis, open the light") == (True, "open the light")

    assert split_reply("Done, sir.\n【中文】好了。") == ("Done, sir.", "好了。")
    en, zh = split_reply("灯已经打开了, sir")
    assert "灯" not in en and zh.startswith("灯"), (en, zh)

    screen.UI = None
    assert screen.set_screen("awake") == {"ok": False, "error": "no window connected"}
    sent = []
    screen.UI = sent.append
    assert screen.set_screen("awake")["mode"] == "awake"
    assert screen.set_screen("sleep")["mode"] == "standby"
    assert [m["mode"] for m in sent] == ["awake", "standby"]

    assert creator.to_number("12.5万", "count") == 125000
    assert creator.to_number("1.2亿", "count") == 120000000
    assert creator.to_number("9.51%", "pct") == 9.51
    boxes = [
        {"t": "播放量", "x": 0.10, "y": 0.30, "w": 0.08, "h": 0.02},
        {"t": "12.5", "x": 0.10, "y": 0.34, "w": 0.05, "h": 0.02},
        {"t": "万", "x": 0.16, "y": 0.34, "w": 0.02, "h": 0.02},
    ]
    got = creator.parse(boxes)
    assert got["metrics"]["plays"]["value"] == 125000, got
    assert got["metrics"]["plays"]["text"] == "12.5万"


class _Night(BaseHTTPRequestHandler):
    n = 0

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        _Night.n += 1
        if _Night.n == 1:
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        payload = {
            "summary_en": "Yesterday had one miss, sir.",
            "summary_zh": "昨天有一次没对上。",
            "proposals": [
                {"kind": "nope", "title": "skip me"},
                {"kind": "fix", "title": "回声", "why": "听成了自己", "evidence": "sir", "plan": "忽略回声"},
            ],
        }
        body = json.dumps({"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def night_llm():
    """A failed nightly model call is not saved, so the next pass tries again."""
    from jarvis import memory, review

    conv = [{"who": "you", "en": "不对，不是这个", "t": 1.0}, {"who": "jarvis", "en": "ok", "t": 2.0}]
    work = [{"tool": "set_screen", "t": 3.0, "result": {"ok": False, "error": "no window"}}]
    sig = review._signals(conv, work)
    assert any(s.startswith("tool set_screen failed") for s in sig), sig
    assert any(s.startswith("user correction") for s in sig), sig

    srv = HTTPServer(("127.0.0.1", 0), _Night)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["JARVIS_LLM_BASE_URL"] = f"http://127.0.0.1:{srv.server_port}/v1"
    os.environ["JARVIS_LLM_API_KEY"] = "good"
    os.environ["JARVIS_LLM_MODEL"] = "fake-1"

    empty = review.run("2000-01-01")
    assert empty.get("empty") and empty["proposals"] == [] and _Night.n == 0, empty

    day = review._day(1)
    folder = memory.CONV
    folder.mkdir(parents=True, exist_ok=True)
    rows = [
        {"t": time.time() - 86400, "who": "you", "en": "turn the light on"},
        {"t": time.time() - 86400, "who": "jarvis", "en": "Done"},
    ]
    (folder / f"{day}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    failed = review.run(day)
    assert "error" in failed and review.load(day) is None and _Night.n == 1, failed
    ok = review.run(day)
    assert not ok.get("error") and ok["proposals"][0]["kind"] == "fix", ok
    assert ok["proposals"][0]["id"].endswith("-2"), ok["proposals"]
    assert review.load(day)["summary_en"].startswith("Yesterday")
    again = review.run(day)
    assert again["proposals"] == ok["proposals"] and _Night.n == 2, _Night.n
    srv.shutdown()


def claim_port():
    """The film server binds 127.0.0.1 on a free port once, and only after install."""
    from jarvis.plugins import earth_migration as em

    assert em.url() == ""
    em.DEST.mkdir(parents=True, exist_ok=True)
    (em.DEST / "index.html").write_text("ok", encoding="utf-8")
    em.STAMP.write_text(em.MAN["commit"], encoding="utf-8")
    u = em.url()
    assert u.startswith("http://127.0.0.1:") and u.endswith("/"), u
    assert em.url() == u
    last = None
    for _ in range(20):
        try:
            with urllib.request.urlopen(u + "index.html", timeout=1) as r:
                assert r.read() == b"ok"
            break
        except Exception as e:
            last = e
            time.sleep(0.05)
    else:
        raise AssertionError(last)


def main():
    screen_and_reply()
    night_llm()
    claim_port()
    from jarvis.plugins.earth import selftest
    selftest()
    print("pure checks: all passed")


if __name__ == "__main__":
    main()
