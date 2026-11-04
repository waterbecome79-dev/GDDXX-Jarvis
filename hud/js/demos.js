'use strict';
/* Demos stay unbuilt until a command or hotkey opens one. install() is the heavy
   part: the particle holograms, and for Earth a second WebGL context plus the
   day/night textures. */
let SHIP = null, SHIPYAW = 0, RD = null, OP = null, EW = null, frameOdd = false;

function demoDim(p) {
  if (p > 0.001) {
    U.uGain.value = Math.min(U.uGain.value, 1 - Math.min(1, p * 1.6));
    rainM.opacity *= 1 - p * 0.85; rpM.opacity *= 1 - p * 0.85;
    if (p > 0.3) orbits.visible = false; if (p > 0.05) labelBox.style.opacity = '0';
  }
}
/* While the module is still loading, a second open replaces the first.
   Returns true when the caller should not run the command yet. Callers drop
   hide/pause themselves so those never construct a demo that is not up. */
function deferUntil(built, ensure, slot, m) {
  if (built()) return false;
  slot.m = m || {};
  ensure().then(obj => {
    const pending = slot.m; slot.m = null;
    if (pending && obj) slot.go(pending);
  });
  return true;
}
function demoOpens(m) { const a = (m && m.action) || 'play'; return a !== 'hide' && a !== 'pause'; }

/* <<starship: Starship V3 launch-to-recovery hologram (hud/demos/starship.js) */
let shipP = null;
function ensureShip() {
  if (SHIP) return Promise.resolve(SHIP);
  if (!shipP) shipP = import('../demos/starship.js?v=20261022h').then(m => {
    SHIP = window.SHIP = m.install({ THREE, scene, camera, pixel: DPR, spin: () => SHIPYAW, dim: demoDim });
    return SHIP;
  }).catch(e => { shipP = null; console.warn('starship hologram:', e); return null; });
  return shipP;
}
const shipSlot = { m: null, go: m => shipCommand(m) };
function shipCommand(m) {
  if (!SHIP && !demoOpens(m)) { if ((m && m.action) === 'hide') shipSlot.m = null; return; }
  if (deferUntil(() => SHIP, ensureShip, shipSlot, m)) return;
  if ((m.action || 'play') !== 'hide') { try { dormHold = false; wakeUI(); machineHide(); holoHide(); if (OP && OP.state.on) OP.hide(); } catch (_) {} }
  SHIP.command(m);
}
/* keyboard: Ctrl+Shift+S start/stop, Ctrl+Shift+← → previous/next stage, Ctrl+Shift+P pause */
addEventListener('keydown', e => {
  if (!e.ctrlKey || !e.shiftKey) return;
  if (!SHIP) { if (e.code === 'KeyS') { e.preventDefault(); shipCommand({ action: shipSlot.m ? 'hide' : 'play' }); } return; }
  const st = SHIP.state, cur = Math.max(0, SHIP.stages.findIndex(s => st.t < s.at + s.dur));
  if (e.code === 'KeyS') { e.preventDefault(); st.on && !st.ending ? SHIP.hide() : shipCommand({ action: 'play' }); }
  else if (e.code === 'KeyP' && st.on) { e.preventDefault(); st.paused = !st.paused; }
  else if (e.code === 'ArrowRight' && st.on && !st.ending) { e.preventDefault(); SHIP.seek(Math.min(SHIP.stages.length - 1, cur + 1)); }
  else if (e.code === 'ArrowLeft' && st.on && !st.ending) { e.preventDefault(); SHIP.seek(Math.max(0, cur - 1)); }
});
/* starship>> */

/* <<roadster: Tesla Roadster cold-gas thrusters + suicide burn hologram (hud/demos/roadster.js), added 2026-10-23 for the 特斯拉悬停 video */
let rdP = null;
function ensureRoadster() {
  if (RD) return Promise.resolve(RD);
  if (!rdP) rdP = import('../demos/roadster.js?v=20261023a').then(m => {
    RD = window.RD = m.install({ THREE, scene, camera, pixel: DPR, spin: () => SHIPYAW, dim: demoDim });
    return RD;
  }).catch(e => { rdP = null; console.warn('roadster hologram:', e); return null; });
  return rdP;
}
const rdSlot = { m: null, go: m => roadsterCommand(m) };
function roadsterCommand(m) {
  if (!RD && !demoOpens(m)) { if ((m && m.action) === 'hide') rdSlot.m = null; return; }
  if (deferUntil(() => RD, ensureRoadster, rdSlot, m)) return;
  if ((m.action || 'play') !== 'hide') { try { dormHold = false; wakeUI(); machineHide(); holoHide(); if (SHIP && SHIP.state.on) SHIP.hide(); if (OP && OP.state.on) OP.hide(); } catch (_) {} }
  RD.command(m);
}
/* keyboard: Ctrl+Shift+R start/stop, Ctrl+Shift+← → previous/next scene, Ctrl+Shift+P pause (while it plays) */
addEventListener('keydown', e => {
  if (!e.ctrlKey || !e.shiftKey) return;
  if (!RD) { if (e.code === 'KeyR') { e.preventDefault(); roadsterCommand({ action: rdSlot.m ? 'hide' : 'play' }); } return; }
  const st = RD.state, cur = Math.max(0, RD.stages.findIndex(s => st.t < s.at + s.dur));
  if (e.code === 'KeyR') { e.preventDefault(); st.on && !st.ending ? RD.hide() : roadsterCommand({ action: 'play' }); }
  else if (!st.on || st.ending) return;
  else if (OP && OP.state.on && !OP.state.ending) return;
  else if (e.code === 'KeyP') { e.preventDefault(); e.stopImmediatePropagation(); st.paused = !st.paused; }
  else if (e.code === 'ArrowRight') { e.preventDefault(); e.stopImmediatePropagation(); RD.seek(Math.min(RD.stages.length - 1, cur + 1)); }
  else if (e.code === 'ArrowLeft') { e.preventDefault(); e.stopImmediatePropagation(); RD.seek(Math.max(0, cur - 1)); }
}, true);
/* roadster>> */

/* <<optimus: Optimus walking hologram (hud/demos/optimus.js), added 2026-10-23 */
let opP = null;
function ensureOptimus() {
  if (OP) return Promise.resolve(OP);
  if (!opP) opP = import('../demos/optimus.js?v=20261023c').then(m => {
    OP = window.OP = m.install({ THREE, scene, camera, pixel: DPR, spin: () => SHIPYAW, dim: demoDim });
    return OP;
  }).catch(e => { opP = null; console.warn('optimus hologram:', e); return null; });
  return opP;
}
const opSlot = { m: null, go: m => optimusCommand(m) };
function optimusCommand(m) {
  if (!OP && !demoOpens(m)) { if ((m && m.action) === 'hide') opSlot.m = null; return; }
  if (deferUntil(() => OP, ensureOptimus, opSlot, m)) return;
  if ((m.action || 'play') !== 'hide') { try { dormHold = false; wakeUI(); machineHide(); holoHide(); if (SHIP && SHIP.state.on) SHIP.hide(); if (RD && RD.state.on) RD.hide(); } catch (_) {} }
  OP.command(m);
}
/* keyboard: Ctrl+Shift+O start/stop, Ctrl+Shift+← → previous/next scene, Ctrl+Shift+P pause (while it plays) */
addEventListener('keydown', e => {
  if (!e.ctrlKey || !e.shiftKey) return;
  if (!OP) { if (e.code === 'KeyO') { e.preventDefault(); optimusCommand({ action: opSlot.m ? 'hide' : 'play' }); } return; }
  const st = OP.state, cur = Math.max(0, OP.stages.findIndex(s => st.t < s.at + s.dur));
  if (e.code === 'KeyO') { e.preventDefault(); st.on && !st.ending ? OP.hide() : optimusCommand({ action: 'play' }); }
  else if (!st.on || st.ending) return;
  else if (e.code === 'KeyP') { e.preventDefault(); e.stopImmediatePropagation(); st.paused = !st.paused; }
  else if (e.code === 'ArrowRight') { e.preventDefault(); e.stopImmediatePropagation(); OP.seek(Math.min(OP.stages.length - 1, cur + 1)); }
  else if (e.code === 'ArrowLeft') { e.preventDefault(); e.stopImmediatePropagation(); OP.seek(Math.max(0, cur - 1)); }
}, true);
/* optimus>> */

/* <<earth: 地球此刻 · Earth-now card wall (hud/demos/earthwatch.js) */
let earthP = null;
const earthQ = [];
function ensureEarth() {
  if (EW) return Promise.resolve(EW);
  if (!earthP) earthP = import('../demos/earthwatch.js?v=20261031a').then(m => {
    EW = window.EW = m.install({ THREE, send: (o) => liveSend(o), dim: demoDim });
    const q = earthQ.splice(0); for (const d of q) EW.data(d);
    return EW;
  }).catch(e => { earthP = null; earthQ.length = 0; console.warn('earth wall:', e); return null; });
  return earthP;
}
function earthData(m) { if (EW) EW.data(m); else if (earthP && earthSlot.m) earthQ.push(m); }
const earthSlot = { m: null, go: m => earthCommand(m) };
function earthOpens(m) { const a = (m && m.action) || 'show'; return a === 'show' || a === 'open' || a === 'play'; }
function earthCommand(m) {
  const a = (m && m.action) || 'show';
  if (!EW && !earthOpens(m)) { if (a === 'hide' || a === 'close' || a === 'back') { earthSlot.m = null; earthQ.length = 0; } return; }
  if (deferUntil(() => EW, ensureEarth, earthSlot, m)) return;
  if (a === 'show' || a === 'open') { try { dormHold = false; wakeUI(); machineHide(); holoHide(); if (SHIP && SHIP.state.on) SHIP.hide(); if (RD && RD.state.on) RD.hide(); if (OP && OP.state.on) OP.hide(); } catch (_) {} }
  EW.command(m);
}
/* keyboard: Ctrl+Shift+E show/hide the wall; while it is up, 1-6 open a card and Esc goes back */
addEventListener('keydown', e => {
  if (!e.ctrlKey || !e.shiftKey || e.code !== 'KeyE') return;
  e.preventDefault();
  if (!EW) { earthCommand({ action: earthSlot.m ? 'hide' : 'show' }); return; }
  EW.live() ? EW.hide() : earthCommand({ action: 'show' });
}, true);
/* earth>> */
