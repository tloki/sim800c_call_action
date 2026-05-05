#!/usr/bin/env python3

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import logging
from flask import Flask, jsonify, render_template_string, request

from action import do_action
from bonbon_utils import BonbonMoneyTransfer
from sim800 import SIM800CHandler
from utils import standardize_number_international

NUMBERS_DB_FILE_NAME = "allowed_numbers.json"
BONBON_CONFIG_FILE_NAME = "bonbon_config.json"
USB_CONFIG_FILE_NAME = "usb_config.json"
WEB_CONFIG_FILE_NAME = "web_config.json"

logging.basicConfig(level=logging.DEBUG)

# ─── Web Config ────────────────────────────────────────────────────────────────
_WEB_CONFIG_FILE = Path(__file__).parent / WEB_CONFIG_FILE_NAME


def _load_web_config() -> dict:
    if not _WEB_CONFIG_FILE.exists():
        return {"host": "0.0.0.0", "port": 5001, "debug": False, "enabled": False}
    with _WEB_CONFIG_FILE.open(mode="r") as f:
        return json.load(fp=f)


_web_cfg = _load_web_config()
WEB_ENABLED: bool = _web_cfg.get("enabled", False)
WEB_HOST: str = _web_cfg.get("host", "0.0.0.0")
WEB_PORT: int = _web_cfg.get("port", 5001)
WEB_DEBUG: bool = _web_cfg.get("debug", False)
# ───────────────────────────────────────────────────────────────────────────────


def load_usb_config() -> tuple[str, int, int]:
    cfg_pth = Path(__file__).parent / USB_CONFIG_FILE_NAME
    if not cfg_pth.exists():
        raise RuntimeError(f"Unable to find '{USB_CONFIG_FILE_NAME}' in path {Path(__file__).parent}")
    with cfg_pth.open(mode="r") as f:
        cfg: dict[str, str | int] = json.load(fp=f)
    return str(cfg["com_port"]), int(cfg["baud"]), int(cfg["timeout_money_transfer"])


def load_bonbon_config() -> tuple[str, str]:
    cfg_pth = Path(__file__).parent / BONBON_CONFIG_FILE_NAME
    if not cfg_pth.exists():
        raise RuntimeError(f"Unable to find '{BONBON_CONFIG_FILE_NAME}' in path {Path(__file__).parent}")
    with cfg_pth.open(mode="r") as f:
        cfg: dict[str, str] = json.load(fp=f)
    return cfg["cellular_number"], cfg["master"]


def load_allowed_number_db() -> set[str]:
    numbers_list_path = Path(__file__).parent / NUMBERS_DB_FILE_NAME
    if not numbers_list_path.exists():
        raise RuntimeError(f"Unable to find '{NUMBERS_DB_FILE_NAME}' in path {Path(__file__).parent}")
    with numbers_list_path.open(mode="r") as f:
        numbers_list: list[str] = json.load(fp=f)
    standardized: list[str] = [standardize_number_international(n) for n in numbers_list]
    return set(standardized)


# ─── Shared State ──────────────────────────────────────────────────────────────
_lock = threading.Lock()
_call_log: list[dict] = []
_sms_log: list[dict] = []
_cellular: Optional[SIM800CHandler] = None
_money_transfer: Optional[BonbonMoneyTransfer] = None


def _add_call_entry(number: str) -> None:
    with _lock:
        _call_log.insert(0, {"number": number, "time": datetime.now(timezone.utc).isoformat()})
        if len(_call_log) > 200:
            del _call_log[200:]


def _add_sms_entry(number: str, text: str) -> None:
    with _lock:
        _sms_log.insert(0, {"number": number, "text": text, "time": datetime.now(timezone.utc).isoformat()})
        if len(_sms_log) > 200:
            del _sms_log[200:]


# ─── Callbacks ─────────────────────────────────────────────────────────────────
def call_handle(number: str, decline_call_handle: Callable) -> None:
    print(f"got call from {number}")
    _add_call_entry(number)
    if number in load_allowed_number_db():
        print("call in db! running action...")
        decline_call_handle()
        do_action()
    else:
        print("number not in db, ignoring...")


def sms_handle(number: str, text: str) -> None:
    print(f"got SMS from {number}: '{text}'")
    _add_sms_entry(number, text)
    if number in load_allowed_number_db():
        print("SMS in db! running action...")
        do_action()
    else:
        print("number not in db, ignoring...")


# ─── Allowed Numbers API ───────────────────────────────────────────────────────
def _save_allowed_numbers(numbers: list[str]) -> None:
    path = Path(__file__).parent / NUMBERS_DB_FILE_NAME
    with path.open(mode="w") as f:
        json.dump(numbers, f, indent=2)


# ─── Flask App ─────────────────────────────────────────────────────────────────
app = Flask(__name__)

HTML = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard</title>
<style>
:root,[data-theme="light"]{
  --bg:#f7f6f2;--surface:#f9f8f5;--border:#d4d1ca;
  --text:#28251d;--text-muted:#7a7974;
  --primary:#01696f;--primary-hover:#0c4e54;
  --danger:#a13544;--danger-hover:#782b33;
  --success:#2d8a5e;--success-hover:#1f6b45;
  --radius:1.25rem;--shadow:0 8px 32px oklch(0.2 0.01 80/0.12);
}
[data-theme="dark"]{
  --bg:#171614;--surface:#1c1b19;--border:#393836;
  --text:#cdccca;--text-muted:#797876;
  --primary:#4f98a3;--primary-hover:#227f8b;
  --danger:#dd6974;--danger-hover:#c24a59;
  --success:#4caf7d;--success-hover:#3a8f60;
  --shadow:0 8px 32px oklch(0 0 0/0.4);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{-webkit-font-smoothing:antialiased}
body{
  min-height:100dvh;display:flex;flex-direction:column;
  background:var(--bg);color:var(--text);
  font-family:'Inter',system-ui,sans-serif;
  transition:background .25s,color .25s;
}
.toggle{
  position:fixed;top:1.25rem;right:1.25rem;z-index:100;
  background:var(--surface);border:1px solid var(--border);
  border-radius:9999px;padding:.5rem;cursor:pointer;
  color:var(--text-muted);display:flex;align-items:center;
  transition:all .18s;
}
.toggle:hover{color:var(--text);border-color:var(--primary)}
.container{width:100%;max-width:600px;margin:0 auto;padding:1rem;flex:1;display:flex;flex-direction:column;gap:1rem}
.header{text-align:center;padding:2rem 0 1rem}
.header h1{font-size:1.5rem;font-weight:700}
.header .subtitle{font-size:.85rem;color:var(--text-muted);margin-top:.25rem}
.card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:1.25rem;
  box-shadow:var(--shadow);
}
.status-grid{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
.status-item{text-align:center;padding:.75rem}
.status-item .label{font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted);margin-bottom:.25rem}
.status-item .value{font-size:1.1rem;font-weight:600}
.status-item .value.ok{color:var(--success)}
.status-item .value.warn{color:var(--danger)}
.tabs{display:flex;gap:.25rem;background:var(--bg);border-radius:.75rem;padding:.25rem;margin-bottom:.5rem}
.tab{
  flex:1;padding:.5rem;text-align:center;border-radius:.5rem;
  cursor:pointer;font-size:.8rem;font-weight:600;color:var(--text-muted);
  transition:all .18s;border:none;background:transparent;
}
.tab:hover{color:var(--text)}
.tab.active{background:var(--surface);color:var(--text);box-shadow:0 1px 3px rgba(0,0,0,.1)}
.tab-content{display:none}
.tab-content.active{display:block}
.log-list{display:flex;flex-direction:column;gap:.5rem;max-height:60vh;overflow-y:auto}
.log-entry{
  display:flex;justify-content:space-between;align-items:center;
  padding:.75rem;background:var(--bg);border-radius:.5rem;
  font-size:.85rem;gap:.5rem;flex-wrap:wrap;
}
.log-entry .sender{font-weight:600;color:var(--primary);word-break:break-all}
.log-entry .text{color:var(--text-muted);font-size:.8rem;flex:1;min-width:100px;margin-top:.25rem}
.log-entry .time{font-size:.75rem;color:var(--text-muted);white-space:nowrap}
.numbers-list{display:flex;flex-direction:column;gap:.5rem}
.number-item{
  display:flex;justify-content:space-between;align-items:center;
  padding:.75rem;background:var(--bg);border-radius:.5rem;font-size:.9rem;
}
.btn-remove{
  background:var(--danger);color:#fff;border:none;border-radius:.5rem;
  padding:.35rem .75rem;cursor:pointer;font-size:.75rem;font-weight:600;
  transition:background .18s;
}
.btn-remove:hover{background:var(--danger-hover)}
.add-form{display:flex;gap:.5rem;margin-top:1rem}
.add-form input{
  flex:1;padding:.75rem;border:1px solid var(--border);border-radius:.5rem;
  background:var(--bg);color:var(--text);font-size:.9rem;outline:none;
}
.add-form input:focus{border-color:var(--primary)}
.add-form button{
  padding:.75rem 1.25rem;background:var(--primary);color:#fff;border:none;
  border-radius:.5rem;cursor:pointer;font-weight:600;font-size:.85rem;
  transition:background .18s;white-space:nowrap;
}
.add-form button:hover{background:var(--primary-hover)}
.empty{text-align:center;padding:2rem;color:var(--text-muted);font-size:.9rem}
.refresh-hint{text-align:center;font-size:.75rem;color:var(--text-muted);padding:.5rem 0}
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

<div class="container">
  <div class="header">
    <h1>Dashboard</h1>
    <div class="subtitle">SIM800C Status</div>
  </div>

  <div class="card">
    <div class="status-grid">
      <div class="status-item">
        <div class="label">SIM Number</div>
        <div class="value" id="sim-number">--</div>
      </div>
      <div class="status-item">
        <div class="label">Status</div>
        <div class="value" id="status">--</div>
      </div>
      <div class="status-item">
        <div class="label">Expires</div>
        <div class="value" id="expiration">--</div>
      </div>
      <div class="status-item">
        <div class="label">Allowed #</div>
        <div class="value" id="allowed-count">--</div>
      </div>
    </div>
  </div>

  <div class="tabs">
    <button class="tab active" data-tab="calls">Calls</button>
    <button class="tab" data-tab="sms">SMS</button>
    <button class="tab" data-tab="numbers">Numbers</button>
  </div>

  <div class="card">
    <div id="tab-calls" class="tab-content active">
      <div class="log-list" id="calls-list"></div>
    </div>
    <div id="tab-sms" class="tab-content">
      <div class="log-list" id="sms-list"></div>
    </div>
    <div id="tab-numbers" class="tab-content">
      <div class="numbers-list" id="numbers-list"></div>
      <div class="add-form">
        <input type="text" id="new-number" placeholder="Add number (e.g. +3859...)" />
        <button onclick="addNumber()">Add</button>
      </div>
    </div>
  </div>

  <div class="refresh-hint">Auto-refresh every 5s</div>
</div>

<script>
const API = '';

async function refresh() {
  try {
    const res = await fetch(API + '/api/dashboard');
    const data = await res.json();
    document.getElementById('sim-number').textContent = data.sim_number || '--';
    const statusEl = document.getElementById('status');
    statusEl.textContent = data.status || '--';
    statusEl.className = 'value ' + (data.status === 'OK' ? 'ok' : 'warn');
    const expEl = document.getElementById('expiration');
    expEl.textContent = data.expiration || '--';
    expEl.className = 'value' + (data.expiration && data.expiration !== 'unknown' ? '' : ' warn');
    document.getElementById('allowed-count').textContent = (data.allowed_numbers || []).length;
    const callsList = document.getElementById('calls-list');
    if (data.calls && data.calls.length) {
      callsList.innerHTML = data.calls.map(c =>
        `<div class="log-entry"><span class="sender">${esc(c.number)}</span><span class="time">${formatTime(c.time)}</span></div>`
      ).join('');
    } else {
      callsList.innerHTML = '<div class="empty">No calls yet</div>';
    }
    const smsList = document.getElementById('sms-list');
    if (data.sms && data.sms.length) {
      smsList.innerHTML = data.sms.map(s =>
        `<div class="log-entry"><span class="sender">${esc(s.number)}</span><span class="text">${esc(s.text)}</span><span class="time">${formatTime(s.time)}</span></div>`
      ).join('');
    } else {
      smsList.innerHTML = '<div class="empty">No SMS yet</div>';
    }
    const numbersList = document.getElementById('numbers-list');
    const nums = data.allowed_numbers || [];
    numbersList.innerHTML = nums.map(n =>
      `<div class="number-item"><span>${esc(n)}</span><button class="btn-remove" onclick="removeNumber('${n}')">Remove</button></div>`
    ).join('');
  } catch(e) {}
}

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function formatTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {dateStyle:'medium',timeStyle:'short'});
}

async function addNumber() {
  const input = document.getElementById('new-number');
  const num = input.value.trim();
  if (!num) return;
  try {
    await fetch(API + '/api/allowed-numbers', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({number: num})
    });
    input.value = '';
    refresh();
  } catch(e) {}
}

async function removeNumber(num) {
  try {
    await fetch(API + '/api/allowed-numbers', {
      method: 'DELETE',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({number: num})
    });
    refresh();
  } catch(e) {}
}

document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
  });
});

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

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/dashboard")
def api_dashboard():
    with _lock:
        calls = list(_call_log)
        sms = list(_sms_log)
    allowed = load_allowed_number_db()
    exp = "unknown"
    if _money_transfer:
        exp = _money_transfer.expiration_date
    return jsonify({
        "sim_number": _cellular.my_number if _cellular else None,
        "status": "OK" if _cellular else "OFFLINE",
        "expiration": exp,
        "allowed_numbers": sorted(allowed),
        "calls": calls,
        "sms": sms,
    })


@app.route("/api/allowed-numbers", methods=["GET"])
def api_get_numbers():
    allowed = load_allowed_number_db()
    return jsonify({"numbers": sorted(allowed)})


@app.route("/api/allowed-numbers", methods=["POST"])
def api_add_number():
    data = request.get_json()
    number = data.get("number", "").strip()
    if not number:
        return jsonify({"error": "number required"}), 400
    standardized = standardize_number_international(number)
    path = Path(__file__).parent / NUMBERS_DB_FILE_NAME
    with path.open(mode="r") as f:
        nums: list[str] = json.load(fp=f)
    if standardized not in nums:
        nums.append(standardized)
        with path.open(mode="w") as f:
            json.dump(nums, f, indent=2)
    return jsonify({"ok": True})


@app.route("/api/allowed-numbers", methods=["DELETE"])
def api_remove_number():
    data = request.get_json()
    number = data.get("number", "").strip()
    if not number:
        return jsonify({"error": "number required"}), 400
    standardized = standardize_number_international(number)
    path = Path(__file__).parent / NUMBERS_DB_FILE_NAME
    with path.open(mode="r") as f:
        nums: list[str] = json.load(fp=f)
    nums = [n for n in nums if n != standardized]
    with path.open(mode="w") as f:
        json.dump(nums, f, indent=2)
    return jsonify({"ok": True})


# ─── Main ──────────────────────────────────────────────────────────────────────
garage_phone_number, master_phone_number = load_bonbon_config()
garage_phone_number = standardize_number_international(number=garage_phone_number)

cellular = SIM800CHandler(port=load_usb_config()[0], baudrate=load_usb_config()[1],
                          call_handle=call_handle, sms_handle=sms_handle)
cellular.run()

time.sleep(5)

print(f"my number is: '{cellular.my_number}'")
assert cellular.my_number == garage_phone_number, (f"garage phone - got '{cellular.my_number}', "
                                                   f"expected '{garage_phone_number}'")

t = time.time()
money_transfer_handler = BonbonMoneyTransfer(master_number=master_phone_number, cellular=cellular)
money_transfer_handler.run_automatic()

# Store globals for API access
_cellular = cellular
_money_transfer = money_transfer_handler

if WEB_ENABLED:
    import threading
    threading.Thread(target=lambda: app.run(host=WEB_HOST, port=WEB_PORT, debug=WEB_DEBUG), daemon=True).start()
    print(f"[web] Dashboard started on http://{WEB_HOST}:{WEB_PORT}")

while True:
    try:
        time.sleep(2.5)
        if time.time() - t > load_usb_config()[2]:
            money_transfer_handler.run_automatic()
            t = time.time()
    except KeyboardInterrupt:
        cellular.kill()
        break

print("done")
