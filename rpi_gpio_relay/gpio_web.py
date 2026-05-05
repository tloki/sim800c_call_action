#!/usr/bin/env python3
"""
GPIO Web Controller
Exposes a single GPIO pin via a web UI and REST API.
"""

import json
import threading
import time
from pathlib import Path
from flask import Flask, jsonify, render_template_string

# ─── CONFIG ────────────────────────────────────────────────────────────────────
_CONFIG_FILE = Path(__file__).parent / "gpio_web_config.json"


def _load_config() -> dict:
    if not _CONFIG_FILE.exists():
        raise RuntimeError(f"Unable to find 'gpio_web_config.json' in {Path(__file__).parent}")
    with _CONFIG_FILE.open(mode="r") as f:
        return json.load(fp=f)


_cfg = _load_config()
GPIO_PIN: int = _cfg["gpio_pin"]
PULSE_SECS: float = _cfg["pulse_secs"]
HOST: str = _cfg["host"]
PORT: int = _cfg["port"]
DEBUG: bool = _cfg["debug"]
# ───────────────────────────────────────────────────────────────────────────────

try:
    import RPi.GPIO as GPIO

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(GPIO_PIN, GPIO.OUT)
    GPIO.output(GPIO_PIN, 0)
    RPI_AVAILABLE = True
except (ImportError, RuntimeError):
    RPI_AVAILABLE = False
    print("[warn] RPi.GPIO not available – running in simulation mode")

app = Flask(__name__)

_busy = False
_lock = threading.Lock()


def _pulse():
    global _busy
    if RPI_AVAILABLE:
        GPIO.output(GPIO_PIN, 1)
    time.sleep(PULSE_SECS)
    if RPI_AVAILABLE:
        GPIO.output(GPIO_PIN, 0)
    with _lock:
        _busy = False


def trigger():
    global _busy
    with _lock:
        if _busy:
            return False
        _busy = True
    t = threading.Thread(target=_pulse, daemon=True)
    t.start()
    return True


HTML = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GPIO {{ pin }}</title>
<style>
:root,[data-theme="light"]{
  --bg:#f7f6f2;--surface:#f9f8f5;--border:#d4d1ca;
  --text:#28251d;--text-muted:#7a7974;
  --primary:#01696f;--primary-hover:#0c4e54;
  --busy:#a13544;--busy-hover:#782b33;
  --radius:1.25rem;
  --shadow:0 8px 32px oklch(0.2 0.01 80/0.12);
}
[data-theme="dark"]{
  --bg:#171614;--surface:#1c1b19;--border:#393836;
  --text:#cdccca;--text-muted:#797876;
  --primary:#4f98a3;--primary-hover:#227f8b;
  --busy:#dd6974;--busy-hover:#c24a59;
  --shadow:0 8px 32px oklch(0 0 0/0.4);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{-webkit-font-smoothing:antialiased}
body{
  min-height:100dvh;display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  background:var(--bg);color:var(--text);
  font-family:'Inter',system-ui,sans-serif;
  transition:background .25s,color .25s;
}
.toggle{
  position:fixed;top:1.25rem;right:1.25rem;
  background:var(--surface);border:1px solid var(--border);
  border-radius:9999px;padding:.5rem;cursor:pointer;
  color:var(--text-muted);display:flex;align-items:center;
  transition:all .18s;
}
.toggle:hover{color:var(--text);border-color:var(--primary)}
.card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:clamp(2rem,6vw,4rem);
  width:min(92vw,420px);text-align:center;
  box-shadow:var(--shadow);
  display:flex;flex-direction:column;align-items:center;gap:1.5rem;
}
.pin-label{font-size:.75rem;letter-spacing:.12em;text-transform:uppercase;color:var(--text-muted)}
.pin-num{font-size:clamp(1.1rem,4vw,1.4rem);font-weight:600}
.status-row{display:flex;align-items:center;gap:.5rem}
.dot{width:10px;height:10px;border-radius:50%;background:var(--border);transition:background .2s}
.dot.busy-dot{background:var(--busy);box-shadow:0 0 8px var(--busy)}
.status-text{font-size:.85rem;color:var(--text-muted)}
.btn{
  width:100%;max-width:320px;
  padding:clamp(1.1rem,4vw,1.6rem) 2rem;
  font-size:clamp(1.1rem,4vw,1.4rem);font-weight:700;letter-spacing:.02em;
  border:none;border-radius:calc(var(--radius) - .25rem);
  background:var(--primary);color:#fff;cursor:pointer;
  transition:background .18s,transform .12s,box-shadow .18s;
  touch-action:manipulation;user-select:none;
  -webkit-tap-highlight-color:transparent;
}
.btn:hover:not(:disabled){background:var(--primary-hover)}
.btn:active:not(:disabled){transform:scale(.97)}
.btn:disabled{cursor:default;opacity:.85}
.btn.state-busy{background:var(--busy)}
.btn.state-busy:hover:not(:disabled){background:var(--busy-hover)}
.bar-wrap{width:100%;height:6px;border-radius:9999px;background:var(--border);overflow:hidden;opacity:0;transition:opacity .2s}
.bar-wrap.visible{opacity:1}
.bar{height:100%;border-radius:9999px;background:var(--busy);width:100%;transform-origin:left}
.api-hint{font-size:.78rem;color:var(--text-muted);line-height:1.6;background:var(--bg);
  border:1px solid var(--border);border-radius:.5rem;padding:.6rem .9rem;width:100%;text-align:left}
.api-hint code{font-family:monospace;color:var(--primary)}
</style>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
</head>
<body>

<button class="toggle" data-theme-toggle aria-label="Toggle theme">
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
  </svg>
</button>

<div class="card">
  <div>
    <div class="pin-label">GPIO Pin (BCM)</div>
    <div class="pin-num">{{ pin }}</div>
  </div>
  <div class="status-row">
    <span class="dot" id="dot"></span>
    <span class="status-text" id="status-text">Ready</span>
  </div>
  <button class="btn" id="main-btn" onclick="doTrigger()">Trigger</button>
  <div class="bar-wrap" id="bar-wrap"><div class="bar" id="bar"></div></div>
  <div class="api-hint">
    <b>REST API</b><br>
    <code>GET /api/trigger</code> — fire pulse<br>
    <code>GET /api/status</code> — check state<br>
    Response: <code>200 ok</code> or <code>200 busy</code>
  </div>
</div>

<script>
const PULSE = {{ pulse }};
let isBusy = false;
let timer = null;

function setState(busy) {
  isBusy = busy;
  const btn  = document.getElementById('main-btn');
  const dot  = document.getElementById('dot');
  const txt  = document.getElementById('status-text');
  const wrap = document.getElementById('bar-wrap');
  const bar  = document.getElementById('bar');
  if (busy) {
    btn.textContent = 'Busy\u2026';
    btn.classList.add('state-busy');
    btn.disabled = true;
    dot.className = 'dot busy-dot';
    txt.textContent = 'GPIO HIGH';
    wrap.classList.add('visible');
    bar.style.transition = 'none';
    bar.style.transform = 'scaleX(1)';
    bar.getBoundingClientRect();
    bar.style.transition = 'transform ' + PULSE + 's linear';
    bar.style.transform = 'scaleX(0)';
    clearTimeout(timer);
    timer = setTimeout(() => setState(false), PULSE * 1000);
  } else {
    btn.textContent = 'Trigger';
    btn.classList.remove('state-busy');
    btn.disabled = false;
    dot.className = 'dot';
    txt.textContent = 'Ready';
    wrap.classList.remove('visible');
    bar.style.transition = 'none';
    bar.style.transform = 'scaleX(1)';
  }
}

async function doTrigger() {
  if (isBusy) return;
  setState(true);
  try {
    await fetch('/api/trigger');
  } catch(e) {}
}

(function(){
  const html = document.documentElement;
  const btn = document.querySelector('[data-theme-toggle]');
  const sun = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>';
  const moon = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
  let dark = html.getAttribute('data-theme') === 'dark';
  btn.innerHTML = dark ? sun : moon;
  btn.addEventListener('click', () => {
    dark = !dark;
    html.setAttribute('data-theme', dark ? 'dark' : 'light');
    btn.innerHTML = dark ? sun : moon;
  });
})();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML, pin=GPIO_PIN, pulse=PULSE_SECS)


@app.route("/api/trigger", methods=["GET", "POST"])
def api_trigger():
    ok = trigger()
    return ("ok" if ok else "busy"), 200


@app.route("/api/status")
def api_status():
    with _lock:
        state = "busy" if _busy else "idle"
    return jsonify({"state": state, "pin": GPIO_PIN, "pulse_secs": PULSE_SECS})


if __name__ == "__main__":
    try:
        app.run(host=HOST, port=PORT, debug=DEBUG)
    finally:
        if RPI_AVAILABLE:
            GPIO.cleanup()
