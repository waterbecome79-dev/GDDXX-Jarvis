"""Jarvis's abilities as folders, so it can grow new ones without touching its own program.

  ~/.jarvis/skills/<name>/          installed: the voice layer loads these at every reply
  ~/.jarvis/lab/skills-trial/<name>/ built by the brain, waiting for the user's approval
  ~/.jarvis/skills-archive/          every replaced or removed version, for rollback

Each folder holds SKILL.md (name, description), and optionally tool.py (TOOLS + run(name, args)) and test.json.
Installed skills also appear in the brain's own skill catalogue (see brainlink.PROFILE_PATCH).

The learning list (~/.jarvis/memory/learning.json) is what Jarvis could not do yet: it adds to it when it has to say
"I can't do that yet", and the user approves, rejects or forgets entries."""
import importlib.util, json, re, shutil, sys, time, traceback
from pathlib import Path

from .paths import SKILLS as LIVE, SKILLS_TRIAL as TRIAL, SKILLS_ARCHIVE as ARCHIVE, MEMORY
LEARN = MEMORY / "learning.json"
RESERVED = {"set_screen", "control_home_device", "get_system_status", "manage_schedule", "read_creator_stats",
            "show_machine_hologram", "show_launch_sequence", "search_memory", "remember_fact", "forget_fact", "ask_harness", "harness_jobs",
            "note_cannot_do", "open_brain", "manage_abilities", "show_roadster_hover", "show_optimus_walk", "voiceprint",
            "get_weather", "plan_route", "save_place",
            "show_earth_now", "earth_migration"}         # built-in names a learned skill may not take over
_loaded = {}       # path -> (mtime, module)


def _front(text):
    m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith(" "):
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip().strip('"\'')
    return out


def _folders(root):
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").exists() and not p.name.startswith("."))


def info(folder):
    meta = _front((folder / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
    stat = folder.stat()
    return {"name": meta.get("name") or folder.name, "folder": folder.name, "description": meta.get("description", "")[:300],
            "code": (folder / "tool.py").exists(), "tests": (folder / "test.json").exists(),
            "changed": time.strftime("%Y-%m-%d %H:%M", time.localtime(max(stat.st_mtime, *(f.stat().st_mtime for f in folder.iterdir()))))}


def listing():
    return {"installed": [info(f) for f in _folders(LIVE)], "trial": [info(f) for f in _folders(TRIAL)]}


def _module(folder):
    path = folder / "tool.py"
    if not path.exists():
        return None
    mt = path.stat().st_mtime
    hit = _loaded.get(str(path))
    if hit and hit[0] == mt:
        return hit[1]
    name = f"jarvis_skill_{folder.parent.name}_{folder.name}".replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _loaded[str(path)] = (mt, mod)
    return mod


def tools():
    """(tool definitions, {name: callable}) from every installed skill that has code. A broken skill is skipped."""
    defs, run = [], {}
    for folder in _folders(LIVE):
        try:
            mod = _module(folder)
            if not mod:
                continue
            for t in getattr(mod, "TOOLS", []):
                n = t.get("function", {}).get("name")
                if not n or n in RESERVED or n in run:
                    continue
                defs.append(t)
                run[n] = (lambda m, nm: lambda **a: m.run(nm, a))(mod, n)
        except Exception as e:
            print(f"skill {folder.name} skipped: {type(e).__name__}: {e}", flush=True)
    return defs, run


def guides():
    """Installed skills without code are recipes: their descriptions go into the voice layer's prompt."""
    out = []
    for folder in _folders(LIVE):
        if not (folder / "tool.py").exists():
            i = info(folder)
            out.append(f"- {i['name']}: {i['description']}")
    return "\n".join(out[:20])


def test(name, where="trial"):
    root = TRIAL if where == "trial" else LIVE
    folder = root / name
    if not (folder / "SKILL.md").exists():
        return {"ok": False, "error": f"no skill '{name}' in {where}", "available": [f.name for f in _folders(root)]}
    if not (folder / "tool.py").exists():
        return {"ok": True, "note": "a recipe skill with no code: nothing to run", "skill": info(folder)}
    try:
        _loaded.pop(str(folder / "tool.py"), None)
        mod = _module(folder)
    except Exception:
        return {"ok": False, "error": "tool.py does not load", "trace": traceback.format_exc()[-1500:]}
    names = {t.get("function", {}).get("name") for t in getattr(mod, "TOOLS", [])}
    clash = sorted(n for n in names if n in RESERVED)
    if clash:
        return {"ok": False, "error": f"tool names taken by Jarvis's core: {clash}"}
    try:
        cases = json.loads((folder / "test.json").read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"test.json missing or invalid: {e}"}
    results, passed = [], 0
    for c in cases[:40]:
        t0 = time.time()
        try:
            got = mod.run(c["tool"], c.get("args", {}))
            want = c.get("expect", {})
            ok = isinstance(got, dict) and all(got.get(k) == v for k, v in want.items())
            ms = round((time.time() - t0) * 1000)
            ok = ok and ms < 5000
            results.append({"tool": c["tool"], "ok": ok, "ms": ms, "got": json.dumps(got, ensure_ascii=False)[:300]})
        except Exception as e:
            results.append({"tool": c.get("tool"), "ok": False, "error": f"{type(e).__name__}: {e}"[:300]})
            ok = False
        passed += ok
    return {"ok": passed == len(results) and results != [], "passed": passed, "total": len(results), "results": results}


import threading as _th
_PROMOTE_LOCK = _th.Lock()     # claude-safe-promote


def promote(name):
    with _PROMOTE_LOCK:
        if (LIVE / name).exists() and not (TRIAL / name).exists():
            return {"ok": True, "installed": name, "note": "already installed"}
        return _promote(name)


def _promote(name):
    """The user approved a trial skill: archive any old version, move the new one in, keep the trial copy out."""
    src = TRIAL / name
    if not (src / "SKILL.md").exists():
        return {"ok": False, "error": f"no trial skill '{name}'"}
    t = test(name, "trial")
    if not t.get("ok"):
        return {"ok": False, "error": "its tests do not pass", "test": t}
    dst = LIVE / name
    stamp = time.strftime("%Y%m%d-%H%M%S")
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.move(str(dst), str(ARCHIVE / f"{name}@{stamp}"))
    LIVE.mkdir(parents=True, exist_ok=True)
    tmp = LIVE / f".{name}.installing"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    tmp.rename(dst)
    shutil.move(str(src), str(ARCHIVE / f"{name}@{stamp}-trial"))
    _done_learning(name)
    return {"ok": True, "installed": name}


def remove(name):
    src = LIVE / name
    if not src.exists():
        return {"ok": False, "error": f"no installed skill '{name}'"}
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(ARCHIVE / f"{name}@{time.strftime('%Y%m%d-%H%M%S')}-removed"))
    return {"ok": True, "removed": name}


def rollback(name):
    """Put back the version that was installed before the current one."""
    olds = sorted(p for p in ARCHIVE.glob(f"{name}@*") if not p.name.endswith("-trial"))
    if not olds:
        return {"ok": False, "error": f"no earlier version of '{name}'"}
    prev = olds[-1]
    if (LIVE / name).exists():
        shutil.move(str(LIVE / name), str(ARCHIVE / f"{name}@{time.strftime('%Y%m%d-%H%M%S')}-rolled-back"))
    shutil.move(str(prev), str(LIVE / name))
    return {"ok": True, "restored": prev.name}


# -- the learning list --------------------------------------------------------------------------------------------
def _learn_load():
    try:
        return json.loads(LEARN.read_text(encoding="utf-8"))
    except Exception:
        return []


def _learn_save(items):
    LEARN.parent.mkdir(parents=True, exist_ok=True)
    LEARN.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def note_cannot_do(what="", asked="", **_):
    what = (what or "").strip()
    if not what:
        return {"ok": False, "error": "say what could not be done"}
    items = _learn_load()
    for it in items:
        if it["what"].lower() == what.lower() and it["state"] in ("new", "approved"):
            it["times"] = it.get("times", 1) + 1
            it["last"] = time.strftime("%Y-%m-%d %H:%M")
            _learn_save(items)
            return {"ok": True, "note": f"already on the learning list ({it['times']} times asked)"}
    items.append({"id": f"L{int(time.time())}", "what": what, "asked": asked[:300], "state": "new", "times": 1,
                  "first": time.strftime("%Y-%m-%d %H:%M"), "last": time.strftime("%Y-%m-%d %H:%M")})
    _learn_save(items)
    return {"ok": True, "note": "added to the learning list; tonight's review will propose how to learn it"}


def learning(state=None):
    items = _learn_load()
    return [i for i in items if state is None or i["state"] == state]


def set_learning(ident, state):
    items = _learn_load()
    for it in items:
        if it["id"] == ident or it["what"] == ident:
            it["state"] = state
            it["changed"] = time.strftime("%Y-%m-%d %H:%M")
            _learn_save(items)
            return {"ok": True, "item": it}
    return {"ok": False, "error": "no such item"}


def _done_learning(skill):
    items = _learn_load()
    for it in items:
        if it.get("skill") == skill and it["state"] in ("approved", "building"):
            it["state"] = "learned"
    _learn_save(items)


# -- the voice layer's own tools for this -------------------------------------------------------------------------
def voice_tools():
    return [
        {"type": "function", "function": {
            "name": "note_cannot_do",
            "description": "When the user asks for something none of your tools can do, call this before you answer, so it "
                           "goes on your learning list; then tell the user plainly you can't do it yet and that you've noted it to learn.",
            "parameters": {"type": "object", "properties": {
                "what": {"type": "string", "description": "the missing ability in a few words, in Chinese, e.g. '设置倒计时提醒'"},
                "asked": {"type": "string", "description": "what the user said"}}, "required": ["what"]}}},
        {"type": "function", "function": {
            "name": "manage_abilities",
            "description": "Your learned abilities and learning list: 'list' them, 'install' a trial ability the user approves "
                           "(装上, 批准), 'remove' or 'rollback' an installed one, 'approve_learning' or 'reject_learning' an item "
                           "on the learning list, 'approve_proposal' / 'reject_proposal' for an idea from your nightly review, 'review_now' "
                           "to review a day (name = YYYY-MM-DD, default yesterday), 'learn_now' to have your brain learn an "
                           "approved item right away instead of tonight.",
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["list", "install", "remove", "rollback", "approve_learning", "reject_learning",
                                                      "approve_proposal", "reject_proposal", "review_now", "learn_now"]},
                "name": {"type": "string", "description": "the ability's folder name, or the learning item's id or text"}},
                "required": ["action"]}}},
    ]


def manage(action="list", name="", **_):
    if action == "list":
        from . import review
        return {"ok": True, **listing(), "learning": [i for i in _learn_load() if i["state"] in ("new", "approved", "building", "trial", "stuck")],
                "review_ideas": review.all_open()}
    if action == "install":
        return promote(name)
    if action == "remove":
        return remove(name)
    if action == "rollback":
        return rollback(name)
    if action in ("approve_learning", "reject_learning"):
        return set_learning(name, "approved" if action == "approve_learning" else "rejected")
    if action in ("approve_proposal", "reject_proposal", "review_now", "learn_now"):
        from . import review
        if action == "review_now":
            r = review.run(name or None, force=True)
            return {"ok": not r.get("error"), "summary": r.get("summary_zh"), "proposals": r.get("proposals"), "error": r.get("error")}
        if action == "learn_now":
            item = next((i for i in _learn_load() if name and (i["id"] == name or i["what"] == name)), None)
            if item and item["state"] == "new":
                set_learning(item["id"], "approved"); item["state"] = "approved"
            return review.start_learning(item)
        return review.decide(name, action == "approve_proposal")
    return {"ok": False, "error": "unknown action"}


HINT = (" Your abilities can grow. When the user asks for something no tool of yours can do, call note_cannot_do first, "
        "then say in one sentence that you can't yet and have noted it to learn. Never pretend to do it. Use manage_abilities "
        "to list, install (only when the user approves), remove or roll back learned abilities. Bigger jobs that need "
        "planning and building go to your brain: call open_brain with the task.")


def provide():
    learned, learned_run = tools()
    pairs = [(t, {"note_cannot_do": note_cannot_do, "manage_abilities": manage}[t["function"]["name"]]) for t in voice_tools()]
    pairs += [(t, learned_run[t["function"]["name"]]) for t in learned]
    g = guides()
    return pairs, HINT + ((" Learned recipes you can follow:\n" + g) if g else "")
