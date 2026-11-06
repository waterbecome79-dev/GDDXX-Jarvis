"""Voice state machine: always standing by, wake on "嗨，贾维斯", barge-in while speaking.

Feed 16 kHz mono float32 audio in any chunk size with feed(). The engine never keeps
audio or text from speech that did not start with the wake phrase.

Events (on_event(name, data)):
  wake      KWS heard the wake phrase; UI should light up right away
  ack       woke with no command yet ("嗨，贾维斯" alone); say "我在" and wait
  command   {'text': ...} the words after the wake phrase; run it
  rejected  KWS fired but ASR found no wake phrase (TV, similar words)
  barge_in  user started talking over Jarvis; stop TTS now
  stop      the barge-in was just "停/别说了"; stay quiet
  timeout   woke but nothing followed
"""
import os, re
import time
import numpy as np
from . import models
from .wake import split_wake, greet_wake

WAKE_REMNANT = re.compile(r"^(?:(?:[嗨嘿海开哎诶]?[贾加嘉甲假佳哎诶]?[维为威卫伟][斯思丝司死])|(?:(?:hey|hi|okay|ok|a)[\s,]+)?(?:jarvis|javis|jarvas|jervis|jarves|travis|harvis|service)\b)[，,。.!\s]*", re.I)
NAME_LIKE = re.compile(r"(?:jar|jer|ja|tra|dja|cha|har|gar)\s?v[aei]?[sz]\b", re.I)
FILLER = re.compile(r"^(?:[嗯啊哦呃额唉哎嗷噢 ]{1,3}|(?:um+|uh+|hmm+|mm+|ah+|oh)(?:[ ,]+(?:um+|uh+|hmm+|mm+|ah+|oh))*)[。.!！?？]*$", re.I)
STOP_WORDS = re.compile(r"^(?:停|停一下|停下|别说了|不用说了|闭嘴|好了|可以了|行了|算了|(?:okay|ok|alright)?[ ,]*(?:stop|wait|hold on|enough|that's enough|never mind|nevermind|cancel|shut up|be quiet|quiet|thanks|thank you|got it|okay|ok)(?:[ ,]+(?:jarvis|please|now|thanks|that's fine|it))*)[。.!！?？]*$", re.I)


def _debug_heard():
    return os.environ.get("JARVIS_DEBUG_HEARD", "0") == "1"


class VoiceEngine:
    def __init__(self, on_event, *, follow_window=8.0, barge_ms=350, echo_ratio=0.6,
                 asr_fallback=True, max_segment=15.0, wake_trust=0.6, vad_tail=0.45, preroll=0.6, pad=0.25, wake=None, vad=None, asr=None):
        self.emit = on_event
        self.follow_window = follow_window
        self.barge_ms = barge_ms
        self.echo_ratio = echo_ratio
        self.asr_fallback = asr_fallback
        self.max_segment = max_segment
        self.preroll = preroll
        self.pad = pad
        self.wake = wake or models.wake()
        self.vad = vad or models.vad()
        self.asr = asr or models.Transcriber()
        self.state = "standby"      # standby | awake | thinking | speaking
        self.n = 0                  # samples consumed
        self.buf = np.zeros(0, np.float32)
        self.woke_at = None         # time KWS fired
        self.wait_until = None      # awake: deadline for the follow-up command
        self.follow = False         # next segment is a command without wake phrase
        self.speech_run = 0.0       # seconds of continuous speech while speaking
        self.ref_rms = 0.0          # playback level reported by the player
        self.cut_from = None
        self.kw_strong = False
        self.wake_peak = 0.0
        self.vad_tail = vad_tail       # = the VAD's min_silence
        self.wake_trust = wake_trust   # acoustic score that wakes even if the transcript missed "Jarvis"
        self.verify_at = None
        self.held = None
        self.busy_since = 0.0
        self.barged = False
        self.said = ""              # what Jarvis just said, to drop its own echo
        self.drop_before = None
        self.pending_ack = False    # wake confirmed while the user was still talking
        self.ring = np.zeros(int(30 * models.SR), np.float32)   # last 30 s, for onset padding
        self.voice = None           # voiceprint.Voiceprint, set by the service: only the user's voice counts

    # -- app hooks -------------------------------------------------------
    def now(self):
        return self.n / models.SR

    def set_speaking(self, on: bool, said: str = ""):
        """Jarvis started (on) or finished (off) talking. When it finishes on its own, the
        conversation stays open: the next thing the user says is heard without the wake word."""
        if on:
            if self.state in ("standby", "awake", "thinking"):
                self.state = "speaking"
                self.follow = False         # let the user's voice barge in
                self.wait_until = None
                self.speech_run = 0.0
                self.busy_since = self.now()
        elif self.state == "speaking":
            t = self.now()
            self.state, self.follow, self.barged = "awake", True, False
            self.woke_at = self.verify_at = None
            self.cut_from = None
            self.drop_before = t            # segments that ended while it talked were its own voice
            self.said = said
            self.wait_until = t + self.follow_window

    def set_playback_level(self, rms: float):
        self.ref_rms = rms

    # -- audio -----------------------------------------------------------
    def feed(self, chunk):
        chunk = np.asarray(chunk, dtype=np.float32)
        self.buf = np.concatenate([self.buf, chunk])
        while len(self.buf) >= 512:
            frame, self.buf = self.buf[:512], self.buf[512:]
            self._frame(frame)

    def _frame(self, frame):
        self.ring = np.roll(self.ring, -len(frame)); self.ring[-len(frame):] = frame
        self.n += len(frame)
        t = self.now()
        # 1) fast acoustic wake check
        hit = self.wake.process(frame)
        # 2) voice activity
        self.vad.accept_waveform(frame)
        speaking_now = self.vad.is_speech_detected()
        rms = float(np.sqrt(np.mean(frame ** 2)) + 1e-9)

        if hit:
            self._on_kws(hit, t)

        if self.state in ("speaking", "thinking") and not self.follow:
            loud = rms > self.echo_ratio * self.ref_rms + 0.004
            self.speech_run = self.speech_run + len(frame) / models.SR if (speaking_now and loud) else 0.0
            if self.speech_run * 1000 >= self.barge_ms:
                self._barge(t, "voice")

        while not self.vad.empty():
            seg = self.vad.front
            core = np.asarray(seg.samples, dtype=np.float32)
            self.vad.pop()
            # Use the VAD's own samples and place them in time from "now": a segment is emitted
            # once min_silence of quiet follows it. (seg.start is not reliable across sherpa versions.)
            end = t - self.vad_tail
            start = end - len(core) / models.SR
            pre = self._span(max(0.0, start - self.pad), start)   # silero tends to clip the first syllable
            if _debug_heard():
                print(f"vad seg {len(core) / models.SR:.2f}s (vad start {seg.start / models.SR:.2f}, est {start:.2f})", flush=True)
            self._on_segment(np.concatenate([pre, core]), start - len(pre) / models.SR, t)

        if self.state == "awake" and self.verify_at is not None:
            self.wake_peak = max(self.wake_peak, getattr(self.wake, "score", 0.0))
            if t >= self.verify_at:
                self._verify(t)

        if self.state == "awake" and self.wait_until and t > self.wait_until and not speaking_now:
            self._event("timeout", {})
            self._reset()

    # -- transitions -----------------------------------------------------
    def _event(self, name, data):
        self.emit(name, data)

    def _reset(self):
        self.state = "standby"
        self.woke_at = self.wait_until = self.cut_from = self.verify_at = None
        self.follow = self.barged = self.pending_ack = False
        self.said = ""
        self.drop_before = None

    def _on_kws(self, keyword, t):
        if self.state in ("speaking", "thinking"):
            self._barge(t, "wake")
            return
        if self.state == "standby":
            self.state = "awake"
            self.woke_at = t
            self.kw_strong = keyword.startswith(("嗨", "嘿", "hey"))
            self.wake_peak = getattr(self.wake, "score", 0.0)
            self.wait_until = None
            self._event("wake", {"keyword": keyword})
            # Decide from the audio around the hit itself, not from VAD segments: a noisy room can
            # keep the VAD from ever closing a segment, which used to leave the wake hanging.
            self.verify_at = t + 0.4
            self.held = None

    def _verify(self, t):
        self.verify_at = None
        a = max(0.0, self.woke_at - 2.0)
        text = self._text(self._span(a, t))
        woke, _ = split_wake(text, trusted=True)
        # the acoustic detector already fired, so near-misses of the name count too ("Hi, Travis")
        woke = woke or bool(NAME_LIKE.search(text)) or greet_wake(text)[0]   # claude-greet-wake
        ok = woke or self.kw_strong or self.wake_peak >= self.wake_trust
        if _debug_heard():
            print(f"wake check: score {self.wake_peak:.2f}, heard {text!r} -> {'yes' if ok else 'no'}", flush=True)
        if ok and self._vp(self._span(max(0.0, self.woke_at - 1.6), t), "wake") is False:
            self._not_you("wake")
            ok = False
        if not ok:
            self._event("rejected", {"heard": "(discarded)"})
            self._reset()
            return
        # answer right away; whatever is said next (or is still being said) is the command
        self.follow, self.barged, self.cut_from = True, False, None
        self.wait_until = t + self.follow_window
        held, self.held = self.held, None
        if held:
            self._on_segment(held[0], held[1], t)   # "Hey Jarvis, turn on the light" in one breath
        if self.state == "awake":
            if self.vad.is_speech_detected():
                self.pending_ack = True     # still talking: maybe the request follows in the same breath
            else:
                self._event("ack", {})

    def _barge(self, t, why):
        self.state = "awake"
        self.follow = True              # the words being spoken are the new command
        self.wait_until = t + self.follow_window
        self.cut_from = t - self.speech_run - self.preroll   # drop any echo before the user spoke
        self.barged = True
        self.speech_run = 0.0
        self._event("barge_in", {"by": why})

    def _span(self, start, end):
        a = int((self.now() - start) * models.SR)
        b = int((self.now() - end) * models.SR)
        a = min(a, len(self.ring))
        return self.ring[len(self.ring) - a: len(self.ring) - b if b > 0 else None].copy()

    def _text(self, samples, mixed=False):
        return self.asr.text(samples, mixed=mixed) if mixed else self.asr.text(samples)

    def _vp(self, samples, why):
        """Is this the user's voice? True / False / None (no voiceprint, or too short to tell)."""
        if self.voice is None or not self.voice.ready():
            return None
        try:
            return self.voice.verify(samples[: int(6.0 * models.SR)], why)
        except Exception as ex:
            print(f"voiceprint failed: {ex}", flush=True)
            return None

    def _not_you(self, why):
        print(f"ignored (not your voice): {why}", flush=True)
        self.emit("not_you", {"why": why})

    def _on_segment(self, samples, start, t):
        dur = len(samples) / models.SR
        end = start + dur
        if self.voice is not None and self.voice.enrolling and self.state not in ("speaking", "thinking"):
            r = self.voice.add(samples)                 # enrolment: every line read goes to the voiceprint
            self._event("enroll", r)
            if r.get("done") or r.get("error"):
                self._reset()
            return
        if _debug_heard():
            print(f"segment {dur:.1f}s while {self.state}", flush=True)
        if self.state == "standby":
            # speech that never contained the wake phrase is dropped unheard,
            # unless the cheap acoustic check missed and the local text check catches it
            if not self.asr_fallback or dur > 8.0:
                return
            # the wake phrase has to open the utterance, so the first few seconds are enough to check
            heard = self._text(samples[: int(3.0 * models.SR)])
            woke, cmd = split_wake(heard)
            if woke and dur > 3.0:
                cmd = ""            # the command runs past what was transcribed; ask for it instead
            if _debug_heard():
                print("heard (standby):", heard, flush=True)
                self.emit("heard", {"text": heard})
            if not woke:
                return
            if self._vp(samples[: int(3.0 * models.SR)], "wake (heard)") is False:
                self._not_you("wake (heard)")
                return
            self.state, self.woke_at = "awake", start
            self._event("wake", {"keyword": "asr"})
            self._deliver(cmd, t)
            return

        if self.state == "awake" and self.verify_at is not None:
            self.held = (samples, start)          # may hold the command said in the same breath
            return

        if self.state == "awake":
            if self.follow:
                if self.drop_before is not None and end < self.drop_before:
                    return
                if self.cut_from is not None:
                    if end < self.cut_from:
                        return
                    samples = samples[max(0, int((self.cut_from - start) * models.SR)):]
                    start = max(start, self.cut_from)
                    self.cut_from = None
                holds_wake = self.woke_at is not None and start < self.woke_at
                if holds_wake:
                    # the wake phrase is inside this segment: cut earlier TV/chatter, take what follows it
                    off = int(max(0.0, self.woke_at - 1.8 - start) * models.SR)
                    samples, start = samples[off:], start + off / models.SR
                if self._vp(samples, "command") is False:
                    self._not_you("command")
                    return
                text = self._text(samples[: int(self.max_segment * models.SR)], mixed=True)
                woke_in, after = split_wake(text, trusted=holds_wake)
                # "Hey Jarvis." alone leaves nothing after the wake word: that is not a command
                cmd = WAKE_REMNANT.sub("", after if woke_in else text).strip(" ,.!?，。！？")
                if holds_wake and re.search(r"[\u4e00-\u9fff]", cmd):
                    # Chinese after an English wake word ("嘿E JARIS 把台灯打开"): transcribe only what
                    # came after the detector fired, so the garbled wake is not part of the request
                    rest = samples[int(max(0.0, self.woke_at - start) * models.SR):]
                    again = self._text(rest, mixed=True) if len(rest) > 0.4 * models.SR else ""
                    if re.search(r"[\u4e00-\u9fff]", again):
                        cmd = WAKE_REMNANT.sub("", split_wake(again, trusted=True)[1] or again).strip(" ,.!?，。！？")
                if holds_wake and dur < 1.8 and cmd.isascii() and len(cmd.split()) <= 3:
                    cmd = ""        # just the wake phrase, misheard ("Hey Joeis", "Friend Travis")
                if not cmd:
                    if self.pending_ack:
                        self.pending_ack = False
                        self._event("ack", {})
                    return
                if not holds_wake and not self.barged and self._is_echo(cmd):
                    print("ignored (own echo):", cmd, flush=True)
                    return
                # a short word thrown in while Jarvis talks means "stop"; real requests are longer
                short = self.barged and (len(cmd.split()) < 3 if cmd.isascii() else len(cmd) < 4)
                if short or STOP_WORDS.match(cmd) or FILLER.match(cmd) or (len(cmd) <= 4 and "停" in cmd) or (len(cmd) <= 12 and re.search(r"\bstop\b", cmd, re.I)):
                    self._event("stop", {"text": cmd})
                    self._reset()
                    return
                self._command(cmd)
                return
            # only the segment that actually contains the wake phrase counts
            if self.woke_at is not None and start <= self.woke_at + 0.3 and end >= self.woke_at - 0.2:
                # start shortly before the wake phrase so earlier TV/chatter in the same stretch is cut off
                off = int(max(0.0, self.woke_at - 1.8 - start) * models.SR)
                samples, start = samples[off:], start + off / models.SR
                if self._vp(samples, "wake+command") is False:
                    self._not_you("wake+command")
                    self._event("rejected", {"heard": "(not your voice)"})
                    self._reset()
                    return
                text = self._text(samples[: int(self.max_segment * models.SR)], mixed=True)
                woke, cmd = split_wake(text, trusted=self.kw_strong)
                if not woke and self.kw_strong:
                    # KWS heard the full "嗨贾维斯"; trust it and transcribe only what came after
                    rest = samples[int(max(0.0, self.woke_at - start) * models.SR):]
                    cmd = self._text(rest, mixed=True) if len(rest) > 0.3 * models.SR else ""
                    woke = True
                if not woke:
                    dbg = (round(start,2), round(end,2), self.woke_at, text) if _debug_heard() else None
                    if dbg is not None:
                        print("heard (wake rejected):", text, flush=True)
                        self.emit("heard", {"text": text})
                    self._event("rejected", {"heard": "(discarded)", "dbg": dbg})
                    self._reset()
                    return
                self._deliver(cmd, t)

        if self.state in ("speaking", "thinking") and not self.follow and dur >= 0.35 and start >= self.busy_since:
            # short words like "停" can finish before the live check fires; catch them here
            if float(np.sqrt(np.mean(samples ** 2))) > max(0.012, 1.5 * self.echo_ratio * self.ref_rms):
                self._barge(t, "voice")
                self.cut_from = None
                self._on_segment(samples, start, t)
        # other segments while thinking/speaking are echo or noise: ignore

    def _is_echo(self, cmd):
        """The open mic after a reply can pick up the end of Jarvis's own sentence (late echo)."""
        if not self.said:
            return False
        w = re.findall(r"[a-z']+", cmd.lower())
        said = set(re.findall(r"[a-z']+", self.said.lower()))
        return bool(w) and sum(x in said for x in w) >= 0.7 * len(w)

    def _deliver(self, cmd, t):
        if cmd:
            self._command(cmd)
        else:
            self.follow = True
            self.barged = False
            self.wait_until = t + self.follow_window
            self._event("ack", {})

    def _command(self, cmd):
        self.follow = self.barged = self.pending_ack = False
        self.wait_until = None
        self.state = "thinking"
        self.busy_since = self.now()
        self._event("command", {"text": cmd})
