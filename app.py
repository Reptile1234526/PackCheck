#!/usr/bin/env python3
"""
Backpack RFID Checker — Web App.
Run on the Pi and open from your phone's browser.
"""

import json
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string, Response
from reader import J4210Reader

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
HISTORY_FILE = BASE_DIR / "history.json"
lock = threading.Lock()

MAX_HISTORY = 100


def load_config():
    with open(CONFIG_FILE) as f:
        config = json.load(f)
    if "profiles" not in config:
        config["profiles"] = {"Everyday": list(config.get("items", {}).keys())}
        config["active_profile"] = "Everyday"
        save_config(config)
    return config


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {"scans": []}


def save_history(history):
    history["scans"] = history["scans"][-MAX_HISTORY:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def do_scan(config):
    with J4210Reader(port=config["port"], baudrate=config["baudrate"]) as reader:
        tags = reader.scan(
            duration_sec=config["scan_duration"],
            power_dbm=config["power_dbm"],
        )
    return tags


def get_scheduled_profile(config):
    """Return the profile for today based on the day schedule, or None."""
    schedule = config.get("day_schedule", {})
    if not schedule:
        return None
    day = datetime.now().strftime("%A")  # e.g. "Monday"
    return schedule.get(day)


def perform_check(config=None):
    """Run a check and return results with RSSI data. Shared by API and auto-scan."""
    if config is None:
        config = load_config()
    all_items = config["items"]
    scheduled = get_scheduled_profile(config)
    profile_name = scheduled if scheduled and scheduled in config.get("profiles", {}) else config.get("active_profile", "Everyday")
    profile_items = config.get("profiles", {}).get(profile_name, [])

    with lock:
        tags = do_scan(config)

    epc_to_tag = {tag.epc: tag for tag in tags}
    results = []
    for name in profile_items:
        if name in all_items:
            epc = all_items[name]
            tag = epc_to_tag.get(epc)
            results.append({
                "name": name,
                "epc": epc,
                "found": epc in epc_to_tag,
                "rssi": tag.rssi if tag else None,
                "count": tag.count if tag else 0,
            })

    total = len(results)
    found = sum(1 for r in results if r["found"])

    # Log to history
    history = load_history()
    history["scans"].append({
        "timestamp": datetime.now().isoformat(),
        "profile": profile_name,
        "found": found,
        "total": total,
        "items": [{"name": r["name"], "found": r["found"], "rssi": r["rssi"]} for r in results],
    })
    save_history(history)

    return {"items": results, "found": found, "total": total, "profile": profile_name}


# --- Notification via ntfy.sh ---

def send_notification(title, message, config):
    topic = config.get("ntfy_topic", "")
    if not topic:
        return
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=message.encode(),
            headers={
                "Title": f"PackCheck: {title}",
                "Priority": "high",
                "Tags": "school_satchel",
                "Icon": "https://cdn-icons-png.flaticon.com/512/3750/3750777.png",
            },
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


# --- Auto-scan scheduler ---

class AutoScanner(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.last_triggered = {}

    def run(self):
        while True:
            try:
                config = load_config()
                times = config.get("auto_scan_times", [])
                now = datetime.now()
                current_time = now.strftime("%H:%M")
                today = now.strftime("%Y-%m-%d")

                for t in times:
                    key = f"{today}-{t}"
                    if current_time == t and key not in self.last_triggered:
                        self.last_triggered[key] = True
                        result = perform_check(config)
                        if result["found"] < result["total"]:
                            missing = [i["name"] for i in result["items"] if not i["found"]]
                            send_notification(
                                "Missing Items!",
                                f"Missing: {', '.join(missing)} ({result['found']}/{result['total']})",
                                config,
                            )
                        else:
                            send_notification(
                                "All Clear",
                                f"All {result['total']} items found in your bag.",
                                config,
                            )
                # Clean up old triggers
                self.last_triggered = {k: v for k, v in self.last_triggered.items() if k.startswith(today)}
            except Exception:
                pass
            time.sleep(30)


auto_scanner = AutoScanner()
auto_scanner.start()


# --- API routes ---

@app.route("/api/check")
def api_check():
    return jsonify(perform_check())


@app.route("/api/quickcheck")
def api_quickcheck():
    """Plain text endpoint for iOS Shortcuts."""
    result = perform_check()
    if result["total"] == 0:
        text = "No items in active profile."
    elif result["found"] == result["total"]:
        text = f"All {result['total']} items found."
    else:
        missing = [i["name"] for i in result["items"] if not i["found"]]
        text = f"MISSING: {', '.join(missing)} ({result['found']}/{result['total']} found)"
    return Response(text, mimetype="text/plain")


@app.route("/quickcheck")
def quickcheck_page():
    """Styled quick-check page — auto-scans on load."""
    return render_template_string(QUICKCHECK_TEMPLATE)


QUICKCHECK_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#050a08">
<title>PackCheck</title>
<link rel="icon" href="/icon.svg">
<link rel="apple-touch-icon" href="/icon.svg">
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');
  :root {
    --green: #00ff88; --green-dim: #00ff8833; --green-mid: #00ff8866;
    --red: #ff3366; --red-dim: #ff336633;
    --bg: #050a08; --surface: #0a1410; --border: #0f2a1f;
    --text: #c0e8d0; --text-dim: #4a7a60;
    --mono: 'JetBrains Mono', 'SF Mono', monospace;
    --sans: 'Space Grotesk', -apple-system, sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: var(--sans); background: var(--bg); color: var(--text);
    min-height: 100vh; display: flex; flex-direction: column;
    align-items: center; justify-content: center; padding: 24px;
    padding-top: max(24px, env(safe-area-inset-top));
  }
  body::after {
    content: ''; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: repeating-linear-gradient(0deg, transparent, transparent 2px,
      rgba(0,255,136,0.015) 2px, rgba(0,255,136,0.015) 4px);
    pointer-events: none; z-index: 1000;
  }
  .logo {
    font-family: var(--mono); font-size: 10px; color: var(--text-dim);
    letter-spacing: 3px; text-transform: uppercase; margin-bottom: 24px;
  }

  /* Scanning state */
  .scan-ring {
    width: 160px; height: 160px; position: relative; margin-bottom: 24px;
  }
  .ring {
    position: absolute; border-radius: 50%;
    border: 2px solid var(--green-dim);
    animation: ring-pulse 2s ease-out infinite;
  }
  .ring:nth-child(1) { width: 160px; height: 160px; top: 0; left: 0; }
  .ring:nth-child(2) { width: 120px; height: 120px; top: 20px; left: 20px; animation-delay: 0.3s; }
  .ring:nth-child(3) { width: 80px; height: 80px; top: 40px; left: 40px; animation-delay: 0.6s; }
  .ring-center {
    width: 40px; height: 40px; position: absolute; top: 60px; left: 60px;
    border-radius: 50%; background: var(--green); opacity: 0.8;
    box-shadow: 0 0 30px var(--green), 0 0 60px var(--green-dim);
    animation: center-pulse 1s ease-in-out infinite;
  }
  @keyframes ring-pulse {
    0% { transform: scale(0.85); opacity: 0.8; border-color: var(--green-mid); }
    100% { transform: scale(1.15); opacity: 0; }
  }
  @keyframes center-pulse {
    0%, 100% { opacity: 0.8; transform: scale(1); }
    50% { opacity: 0.4; transform: scale(0.9); }
  }
  .scan-text {
    font-family: var(--mono); font-size: 12px; letter-spacing: 2px;
    color: var(--text-dim); text-transform: uppercase; margin-bottom: 8px;
  }
  #scanPhase { display: none; text-align: center; }
  #resultPhase { display: none; text-align: center; width: 100%; max-width: 380px; }

  /* Result */
  .result-count {
    font-family: var(--mono); font-size: 72px; font-weight: 700;
    line-height: 1; margin-bottom: 8px;
  }
  .result-count.good { color: var(--green); text-shadow: 0 0 40px var(--green-dim); }
  .result-count.bad { color: var(--red); text-shadow: 0 0 40px var(--red-dim); }
  .result-msg {
    font-family: var(--mono); font-size: 14px; font-weight: 600;
    letter-spacing: 1px; margin-bottom: 24px;
  }
  .result-msg.good { color: var(--green); }
  .result-msg.bad { color: var(--red); }
  .result-profile {
    font-family: var(--mono); font-size: 10px; color: var(--text-dim);
    letter-spacing: 2px; text-transform: uppercase; margin-bottom: 20px;
  }

  .result-item {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 16px; margin-bottom: 8px;
    display: flex; align-items: center; gap: 12px;
    position: relative; overflow: hidden;
  }
  .result-item.found { border-color: rgba(0,255,136,0.2); }
  .result-item.found::before {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0;
    width: 3px; background: var(--green);
  }
  .result-item.missing { border-color: rgba(255,51,102,0.2); }
  .result-item.missing::before {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0;
    width: 3px; background: var(--red);
  }
  .result-item-icon {
    width: 32px; height: 32px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-family: var(--mono); font-size: 14px; font-weight: 700; flex-shrink: 0;
  }
  .result-item.found .result-item-icon { background: rgba(0,255,136,0.1); color: var(--green); }
  .result-item.missing .result-item-icon { background: rgba(255,51,102,0.1); color: var(--red); }
  .result-item-name {
    font-family: var(--sans); font-weight: 600; font-size: 15px; color: var(--text);
  }
  .rssi-bar { display: flex; gap: 2px; align-items: flex-end; height: 12px; margin-left: auto; }
  .rssi-bar .bar { width: 3px; border-radius: 1px; background: var(--border); }
  .rssi-bar .bar.active { background: var(--green); }
  .rssi-bar .bar.weak { background: #ffcc00; }
  .rssi-bar .bar:nth-child(1) { height: 4px; }
  .rssi-bar .bar:nth-child(2) { height: 6px; }
  .rssi-bar .bar:nth-child(3) { height: 8px; }
  .rssi-bar .bar:nth-child(4) { height: 10px; }
  .rssi-bar .bar:nth-child(5) { height: 12px; }

  .btn-rescan {
    margin-top: 16px; padding: 14px 24px; width: 100%;
    border: 1px solid var(--green-mid); border-radius: 10px;
    background: linear-gradient(135deg, rgba(0,255,136,0.12), rgba(0,255,136,0.05));
    color: var(--green); font-family: var(--mono); font-size: 12px;
    font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
    cursor: pointer;
  }
  .btn-rescan:active { transform: scale(0.97); }
  .time-stamp {
    font-family: var(--mono); font-size: 10px; color: var(--text-dim);
    margin-top: 12px;
  }
</style>
</head>
<body>
<div class="logo">rfid // packcheck</div>

<div id="scanPhase" style="display:flex;flex-direction:column;align-items:center">
  <div class="scan-ring">
    <div class="ring"></div><div class="ring"></div><div class="ring"></div>
    <div class="ring-center"></div>
  </div>
  <div class="scan-text">Scanning bag...</div>
</div>

<div id="resultPhase">
  <div class="result-count" id="rCount"></div>
  <div class="result-msg" id="rMsg"></div>
  <div class="result-profile" id="rProfile"></div>
  <div id="rItems"></div>
  <button class="btn-rescan" onclick="runScan()">[ SCAN AGAIN ]</button>
  <div class="time-stamp" id="rTime"></div>
</div>

<script>
const AudioCtx = window.AudioContext || window.webkitAudioContext;
let audioCtx;
function initAudio() { if (!audioCtx) audioCtx = new AudioCtx(); }
function playSuccess() {
  initAudio(); const now = audioCtx.currentTime;
  [440,660].forEach((f,i) => {
    const o=audioCtx.createOscillator(),g=audioCtx.createGain();
    o.type='sine';o.frequency.value=f;
    g.gain.setValueAtTime(0.15,now+i*0.12);
    g.gain.exponentialRampToValueAtTime(0.001,now+i*0.12+0.15);
    o.connect(g).connect(audioCtx.destination);
    o.start(now+i*0.12);o.stop(now+i*0.12+0.15);
  });
}
function playAlert() {
  initAudio(); const now = audioCtx.currentTime;
  [880,660,440].forEach((f,i) => {
    const o=audioCtx.createOscillator(),g=audioCtx.createGain();
    o.type='square';o.frequency.value=f;
    g.gain.setValueAtTime(0.12,now+i*0.18);
    g.gain.exponentialRampToValueAtTime(0.001,now+i*0.18+0.2);
    o.connect(g).connect(audioCtx.destination);
    o.start(now+i*0.18);o.stop(now+i*0.18+0.2);
  });
}

function rssiBar(rssi) {
  if (rssi === null) return '';
  const strength = Math.max(0, Math.min(5, Math.round((rssi + 80) / 12)));
  let bars = '';
  for (let i = 0; i < 5; i++) {
    const active = i < strength;
    bars += `<div class="bar ${active ? (strength<=2?'weak':'active') : ''}"></div>`;
  }
  return `<div class="rssi-bar">${bars}</div>`;
}

async function runScan() {
  initAudio();
  document.getElementById('scanPhase').style.display = 'flex';
  document.getElementById('resultPhase').style.display = 'none';
  try {
    const res = await fetch('/api/check');
    const data = await res.json();
    document.getElementById('scanPhase').style.display = 'none';
    document.getElementById('resultPhase').style.display = 'block';

    const rc = document.getElementById('rCount');
    const rm = document.getElementById('rMsg');
    rc.textContent = data.found + '/' + data.total;

    if (data.total === 0) {
      rc.className = 'result-count'; rm.className = 'result-msg';
      rm.textContent = 'No items in profile';
    } else if (data.found === data.total) {
      rc.className = 'result-count good'; rm.className = 'result-msg good';
      rm.textContent = 'ALL CLEAR';
      playSuccess();
    } else {
      rc.className = 'result-count bad'; rm.className = 'result-msg bad';
      const missing = data.items.filter(i => !i.found).map(i => i.name);
      rm.textContent = 'MISSING: ' + missing.join(', ');
      playAlert();
    }

    document.getElementById('rProfile').textContent = data.profile;
    document.getElementById('rTime').textContent = new Date().toLocaleTimeString('en-US', {hour12:false});

    // Sort: missing first
    data.items.sort((a,b) => a.found - b.found);
    document.getElementById('rItems').innerHTML = data.items.map(item => {
      const cls = item.found ? 'found' : 'missing';
      const icon = item.found ? '&#x2713;' : '!';
      return `
      <div class="result-item ${cls}">
        <div class="result-item-icon">${icon}</div>
        <div class="result-item-name">${item.name}</div>
        ${item.rssi !== null ? rssiBar(item.rssi) : ''}
      </div>`;
    }).join('');

  } catch(e) {
    document.getElementById('scanPhase').style.display = 'none';
    document.getElementById('resultPhase').style.display = 'block';
    document.getElementById('rCount').textContent = 'ERR';
    document.getElementById('rCount').className = 'result-count bad';
    document.getElementById('rMsg').textContent = 'Connection failed';
    document.getElementById('rMsg').className = 'result-msg bad';
    document.getElementById('rItems').innerHTML = '';
  }
}

runScan();
</script>
</body>
</html>
"""


@app.route("/api/scan")
def api_scan():
    config = load_config()
    with lock:
        tags = do_scan(config)
    known = {v: k for k, v in config["items"].items()}
    results = []
    for tag in tags:
        results.append({
            "epc": tag.epc,
            "rssi": tag.rssi,
            "count": tag.count,
            "name": known.get(tag.epc),
        })
    return jsonify({"tags": results})


@app.route("/api/items")
def api_items():
    config = load_config()
    return jsonify(config["items"])


@app.route("/api/items/add", methods=["POST"])
def api_add_item():
    data = request.json
    name = data.get("name", "").strip()
    epc = data.get("epc", "").strip().upper()
    if not name or not epc:
        return jsonify({"error": "name and epc required"}), 400
    config = load_config()
    if name in config["items"]:
        return jsonify({"error": f"'{name}' already exists"}), 400
    config["items"][name] = epc
    profile = config.get("active_profile", "Everyday")
    if profile in config.get("profiles", {}):
        if name not in config["profiles"][profile]:
            config["profiles"][profile].append(name)
    save_config(config)
    return jsonify({"ok": True})


@app.route("/api/items/remove", methods=["POST"])
def api_remove_item():
    data = request.json
    name = data.get("name", "").strip()
    config = load_config()
    if name not in config["items"]:
        return jsonify({"error": f"'{name}' not found"}), 404
    del config["items"][name]
    for pname in config.get("profiles", {}):
        if name in config["profiles"][pname]:
            config["profiles"][pname].remove(name)
    save_config(config)
    return jsonify({"ok": True})


# --- Profile API ---

@app.route("/api/profiles")
def api_profiles():
    config = load_config()
    scheduled = get_scheduled_profile(config)
    return jsonify({
        "profiles": config.get("profiles", {}),
        "active": config.get("active_profile", "Everyday"),
        "scheduled": scheduled,
        "all_items": list(config["items"].keys()),
    })


@app.route("/api/profiles/active", methods=["POST"])
def api_set_active_profile():
    data = request.json
    name = data.get("name", "").strip()
    config = load_config()
    if name not in config.get("profiles", {}):
        return jsonify({"error": "Profile not found"}), 404
    config["active_profile"] = name
    save_config(config)
    return jsonify({"ok": True})


@app.route("/api/profiles/create", methods=["POST"])
def api_create_profile():
    data = request.json
    name = data.get("name", "").strip()
    items = data.get("items", [])
    if not name:
        return jsonify({"error": "name required"}), 400
    config = load_config()
    config.setdefault("profiles", {})[name] = items
    save_config(config)
    return jsonify({"ok": True})


@app.route("/api/profiles/update", methods=["POST"])
def api_update_profile():
    data = request.json
    name = data.get("name", "").strip()
    items = data.get("items", [])
    config = load_config()
    if name not in config.get("profiles", {}):
        return jsonify({"error": "Profile not found"}), 404
    config["profiles"][name] = items
    save_config(config)
    return jsonify({"ok": True})


@app.route("/api/profiles/delete", methods=["POST"])
def api_delete_profile():
    data = request.json
    name = data.get("name", "").strip()
    config = load_config()
    if name not in config.get("profiles", {}):
        return jsonify({"error": "Profile not found"}), 404
    del config["profiles"][name]
    if config.get("active_profile") == name:
        remaining = list(config.get("profiles", {}).keys())
        config["active_profile"] = remaining[0] if remaining else "Everyday"
    save_config(config)
    return jsonify({"ok": True})


@app.route("/api/profiles/reorder", methods=["POST"])
def api_reorder_profiles():
    data = request.json
    order = data.get("order", [])
    config = load_config()
    old_profiles = config.get("profiles", {})
    new_profiles = {}
    for name in order:
        if name in old_profiles:
            new_profiles[name] = old_profiles[name]
    # Add any profiles not in the order list (shouldn't happen, but safety)
    for name in old_profiles:
        if name not in new_profiles:
            new_profiles[name] = old_profiles[name]
    config["profiles"] = new_profiles
    save_config(config)
    return jsonify({"ok": True})


@app.route("/api/profiles/export")
def api_export_profile():
    """Export a profile as JSON for QR code sharing."""
    name = request.args.get("name", "")
    config = load_config()
    if name not in config.get("profiles", {}):
        return jsonify({"error": "Profile not found"}), 404
    items_in_profile = config["profiles"][name]
    export = {
        "type": "packcheck_profile",
        "name": name,
        "items": {n: config["items"][n] for n in items_in_profile if n in config["items"]},
    }
    return jsonify(export)


@app.route("/api/profiles/import", methods=["POST"])
def api_import_profile():
    """Import a profile from shared data."""
    data = request.json
    if data.get("type") != "packcheck_profile":
        return jsonify({"error": "Invalid profile data"}), 400
    name = data.get("name", "").strip()
    items = data.get("items", {})
    if not name:
        return jsonify({"error": "name required"}), 400
    config = load_config()
    for item_name, epc in items.items():
        if item_name not in config["items"]:
            config["items"][item_name] = epc
    config.setdefault("profiles", {})[name] = list(items.keys())
    save_config(config)
    return jsonify({"ok": True})


# --- History API ---

@app.route("/api/history")
def api_history():
    history = load_history()
    return jsonify(history)


@app.route("/api/history/item/<name>")
def api_item_history(name):
    """Get history for a specific item — when it was last seen, miss rate, etc."""
    history = load_history()
    appearances = []
    for scan in history["scans"]:
        for item in scan["items"]:
            if item["name"] == name:
                appearances.append({
                    "timestamp": scan["timestamp"],
                    "found": item["found"],
                    "rssi": item["rssi"],
                })
    total = len(appearances)
    missed = sum(1 for a in appearances if not a["found"])
    last_seen = None
    for a in reversed(appearances):
        if a["found"]:
            last_seen = a["timestamp"]
            break
    return jsonify({
        "name": name,
        "total_scans": total,
        "times_missed": missed,
        "miss_rate": round(missed / total * 100, 1) if total > 0 else 0,
        "last_seen": last_seen,
        "history": appearances[-20:],
    })


# --- Settings API ---

@app.route("/api/settings")
def api_settings():
    config = load_config()
    return jsonify({
        "ntfy_topic": config.get("ntfy_topic", ""),
        "auto_scan_times": config.get("auto_scan_times", []),
        "theme": config.get("theme", "dark"),
        "power_dbm": config.get("power_dbm", 20),
        "scan_duration": config.get("scan_duration", 2.0),
        "day_schedule": config.get("day_schedule", {}),
    })


@app.route("/api/settings", methods=["POST"])
def api_update_settings():
    data = request.json
    config = load_config()
    for key in ("ntfy_topic", "auto_scan_times", "theme", "power_dbm", "scan_duration", "day_schedule"):
        if key in data:
            config[key] = data[key]
    save_config(config)
    return jsonify({"ok": True})


# --- PWA ---

@app.route("/manifest.json")
def pwa_manifest():
    return jsonify({
        "name": "RFID PackCheck",
        "short_name": "PackCheck",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#050a08",
        "theme_color": "#050a08",
        "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}],
    })


ICON_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>
<rect width='100' height='100' rx='20' fill='#050a08'/>
<text x='50' y='62' text-anchor='middle' font-size='50' font-family='monospace' fill='#00ff88'>R</text>
<circle cx='78' cy='22' r='8' fill='#00ff88' opacity='0.8'/>
<circle cx='78' cy='22' r='14' fill='none' stroke='#00ff88' stroke-width='2' opacity='0.4'/>
<circle cx='78' cy='22' r='20' fill='none' stroke='#00ff88' stroke-width='1.5' opacity='0.2'/>
</svg>"""


@app.route("/icon.svg")
def icon():
    return ICON_SVG, 200, {"Content-Type": "image/svg+xml"}


@app.route("/sw.js")
def service_worker():
    return """
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(clients.claim()));
self.addEventListener('fetch', e => e.respondWith(fetch(e.request).catch(() => new Response('Offline'))));
""", 200, {"Content-Type": "application/javascript"}


# --- Web UI ---

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#050a08">
<link rel="manifest" href="/manifest.json">
<title>RFID // PACKCHECK</title>
<link rel="icon" href="/icon.svg">
<link rel="apple-touch-icon" href="/icon.svg">
<script src="https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');

  :root {
    --green: #00ff88;
    --green-dim: #00ff8833;
    --green-mid: #00ff8866;
    --red: #ff3366;
    --red-dim: #ff336633;
    --cyan: #00e5ff;
    --cyan-dim: #00e5ff22;
    --yellow: #ffcc00;
    --yellow-dim: #ffcc0033;
    --bg: #050a08;
    --surface: #0a1410;
    --surface2: #0f1f18;
    --border: #0f2a1f;
    --text: #c0e8d0;
    --text-dim: #4a7a60;
    --mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;
    --sans: 'Space Grotesk', -apple-system, sans-serif;
  }

  /* Light theme */
  .light {
    --bg: #f5f5f0;
    --surface: #ffffff;
    --surface2: #eeeee8;
    --border: #d0d0c8;
    --text: #1a1a18;
    --text-dim: #888880;
    --green: #00994d;
    --green-dim: #00994d22;
    --green-mid: #00994d44;
    --red: #cc2244;
    --red-dim: #cc224422;
    --cyan: #0088bb;
    --cyan-dim: #0088bb22;
  }
  .light body::after { display: none; }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: var(--sans);
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 16px;
    padding-top: max(16px, env(safe-area-inset-top));
    padding-bottom: max(24px, env(safe-area-inset-bottom));
    overflow-x: hidden;
    transition: background 0.3s, color 0.3s;
  }

  body::after {
    content: '';
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: repeating-linear-gradient(
      0deg, transparent, transparent 2px,
      rgba(0, 255, 136, 0.015) 2px, rgba(0, 255, 136, 0.015) 4px
    );
    pointer-events: none;
    z-index: 1000;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 16px;
  }
  .logo {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-dim);
    letter-spacing: 3px;
    text-transform: uppercase;
  }
  .title {
    font-family: var(--mono);
    font-size: 22px;
    font-weight: 700;
    color: var(--green);
    text-shadow: 0 0 20px var(--green-dim), 0 0 40px rgba(0,255,136,0.1);
    margin-top: 2px;
  }
  .light .title { text-shadow: none; }
  .header-right {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .theme-toggle {
    background: none;
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-dim);
    font-size: 16px;
    padding: 4px 8px;
    cursor: pointer;
  }
  .status-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 8px var(--green);
    animation: pulse-dot 2s ease-in-out infinite;
  }
  .light .status-dot { box-shadow: none; }
  .status-dot.offline { background: var(--red); box-shadow: 0 0 8px var(--red); }
  @keyframes pulse-dot {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  /* Tabs */
  .tabs {
    display: flex;
    gap: 0;
    margin-bottom: 16px;
    border-bottom: 1px solid var(--border);
  }
  .tab {
    padding: 10px 16px;
    font-family: var(--mono);
    font-size: 11px;
    letter-spacing: 1px;
    color: var(--text-dim);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: all 0.2s;
  }
  .tab.active {
    color: var(--green);
    border-bottom-color: var(--green);
  }

  /* Profile bar */
  .profile-bar {
    display: flex;
    gap: 8px;
    margin-bottom: 16px;
    overflow-x: auto;
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
  }
  .profile-bar::-webkit-scrollbar { display: none; }
  .profile-chip {
    flex-shrink: 0;
    padding: 8px 14px;
    border: 1px solid var(--border);
    border-radius: 20px;
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-dim);
    background: var(--surface);
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
  }
  .profile-chip:active { transform: scale(0.95); }
  .profile-chip[draggable="true"] { cursor: grab; touch-action: none; }
  .profile-chip.dragging { opacity: 0.5; transform: scale(1.05); }
  .profile-chip.active {
    border-color: var(--green-mid);
    color: var(--green);
    background: rgba(0,255,136,0.06);
  }
  .profile-chip.edit-chip {
    border-color: var(--cyan-dim);
    color: var(--cyan);
    border-style: dashed;
  }

  .scan-hud {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    position: relative;
    overflow: hidden;
  }
  .scan-hud::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--green-mid), transparent);
  }
  .hud-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
  }
  .hud-label {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 2px;
    color: var(--text-dim);
    text-transform: uppercase;
  }
  .hud-time {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--text-dim);
  }
  .hud-count {
    font-family: var(--mono);
    font-size: 56px;
    font-weight: 700;
    text-align: center;
    line-height: 1;
    transition: color 0.3s;
  }
  .hud-count.good { color: var(--green); text-shadow: 0 0 30px var(--green-dim); }
  .hud-count.bad { color: var(--red); text-shadow: 0 0 30px var(--red-dim); }
  .hud-count.idle { color: var(--text-dim); }
  .light .hud-count { text-shadow: none; }
  .hud-msg {
    font-family: var(--mono);
    font-size: 12px;
    text-align: center;
    margin-top: 8px;
    color: var(--text-dim);
    min-height: 18px;
  }
  .hud-msg.good { color: var(--green); }
  .hud-msg.bad { color: var(--red); }

  .scan-line {
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--green), transparent);
    box-shadow: 0 0 15px var(--green), 0 0 30px var(--green-dim);
    opacity: 0;
    z-index: 2;
  }
  .scanning .scan-line {
    opacity: 1;
    animation: sweep 1.5s ease-in-out infinite;
  }
  @keyframes sweep { 0% { top: 0; } 100% { top: 100%; } }

  .actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-bottom: 20px;
  }
  .btn {
    padding: 14px 16px;
    border: 1px solid var(--border);
    border-radius: 10px;
    font-family: var(--mono);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    cursor: pointer;
    transition: all 0.15s;
  }
  .btn:active { transform: scale(0.97); }
  .btn-scan {
    grid-column: 1 / -1;
    background: linear-gradient(135deg, rgba(0,255,136,0.12), rgba(0,255,136,0.05));
    border-color: var(--green-mid);
    color: var(--green);
  }
  .btn-scan:disabled { opacity: 0.4; border-color: var(--border); }
  .btn-add { background: var(--surface); color: var(--cyan); border-color: var(--cyan-dim); }
  .btn-raw { background: var(--surface); color: var(--text-dim); }

  .section-label {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 2px;
    color: var(--text-dim);
    text-transform: uppercase;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .section-label::after { content: ''; flex: 1; height: 1px; background: var(--border); }

  .item {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 12px;
    transition: all 0.3s;
    position: relative;
    overflow: hidden;
  }
  .item.found { border-color: rgba(0,255,136,0.2); }
  .item.found::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--green); }
  .item.missing { border-color: rgba(255,51,102,0.2); }
  .item.missing::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--red); }
  .item-icon {
    width: 36px; height: 36px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-family: var(--mono); font-size: 14px; font-weight: 700; flex-shrink: 0;
  }
  .item.found .item-icon { background: rgba(0,255,136,0.1); color: var(--green); }
  .item.missing .item-icon { background: rgba(255,51,102,0.1); color: var(--red); }
  .item.neutral .item-icon { background: var(--surface2); color: var(--text-dim); }
  .item-info { flex: 1; min-width: 0; }
  .item-name { font-family: var(--sans); font-weight: 600; font-size: 15px; color: var(--text); }
  .item-meta {
    font-family: var(--mono); font-size: 10px; color: var(--text-dim);
    margin-top: 2px; display: flex; align-items: center; gap: 8px;
  }
  .item-epc {
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 140px;
  }

  /* RSSI bar */
  .rssi-bar {
    display: flex; gap: 2px; align-items: flex-end; height: 12px;
  }
  .rssi-bar .bar {
    width: 3px; border-radius: 1px;
    background: var(--border);
    transition: background 0.3s;
  }
  .rssi-bar .bar.active { background: var(--green); }
  .rssi-bar .bar.weak { background: var(--yellow); }
  .rssi-bar .bar:nth-child(1) { height: 4px; }
  .rssi-bar .bar:nth-child(2) { height: 6px; }
  .rssi-bar .bar:nth-child(3) { height: 8px; }
  .rssi-bar .bar:nth-child(4) { height: 10px; }
  .rssi-bar .bar:nth-child(5) { height: 12px; }

  .item-remove {
    background: none; border: none; color: var(--text-dim);
    font-size: 18px; cursor: pointer; padding: 4px 8px; opacity: 0.4;
  }
  .item-remove:active { opacity: 1; color: var(--red); }

  .empty-state {
    text-align: center; padding: 40px 20px;
    font-family: var(--mono); font-size: 12px;
    color: var(--text-dim); line-height: 1.8;
  }
  .blink { display: inline-block; animation: blink 1s step-end infinite; }
  @keyframes blink { 50% { opacity: 0; } }

  /* Page sections */
  .page { display: none; }
  .page.active { display: block; }

  /* Modal */
  .modal-overlay {
    display: none; position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(5,10,8,0.92); z-index: 100;
    padding: 16px; justify-content: center; align-items: center;
    backdrop-filter: blur(8px);
  }
  .light .modal-overlay { background: rgba(200,200,195,0.92); }
  .modal-overlay.active { display: flex; }
  .modal {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 24px; width: 100%; max-width: 380px;
    max-height: 80vh; overflow-y: auto; position: relative;
  }
  .modal::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, var(--cyan-dim), transparent);
  }
  .modal-title {
    font-family: var(--mono); font-size: 13px; letter-spacing: 2px;
    color: var(--cyan); text-transform: uppercase; margin-bottom: 20px;
  }
  .modal input[type="text"], .modal input[type="search"], .modal select {
    width: 100%; padding: 12px 14px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--bg);
    color: var(--text); font-family: var(--sans); font-size: 16px;
    margin-bottom: 12px; outline: none; -webkit-appearance: none;
  }
  .modal input[type="text"]:focus { border-color: var(--cyan-dim); }
  .modal input[type="text"]::placeholder { color: var(--text-dim); }
  .modal .btn { width: 100%; margin-bottom: 8px; text-align: center; }
  .modal .btn-modal-scan {
    background: linear-gradient(135deg, rgba(0,229,255,0.12), rgba(0,229,255,0.05));
    border-color: rgba(0,229,255,0.3); color: var(--cyan);
  }
  .modal .btn-cancel { background: transparent; border-color: var(--border); color: var(--text-dim); }
  .modal .btn-save {
    background: linear-gradient(135deg, rgba(0,255,136,0.12), rgba(0,255,136,0.05));
    border-color: var(--green-mid); color: var(--green);
  }
  .modal .btn-danger { background: transparent; border-color: rgba(255,51,102,0.2); color: var(--red); }

  .radar { width: 60px; height: 60px; margin: 20px auto; position: relative; }
  .radar-circle {
    position: absolute; border: 1px solid var(--green-dim); border-radius: 50%;
    animation: radar-ping 2s ease-out infinite;
  }
  .radar-circle:nth-child(1) { width: 60px; height: 60px; top: 0; left: 0; }
  .radar-circle:nth-child(2) { width: 40px; height: 40px; top: 10px; left: 10px; animation-delay: 0.3s; }
  .radar-circle:nth-child(3) { width: 20px; height: 20px; top: 20px; left: 20px; animation-delay: 0.6s; }
  .radar-dot {
    width: 6px; height: 6px; background: var(--green);
    box-shadow: 0 0 10px var(--green); border-radius: 50%;
    position: absolute; top: 27px; left: 27px;
  }
  @keyframes radar-ping {
    0% { transform: scale(0.8); opacity: 1; border-color: var(--green-mid); }
    100% { transform: scale(1.3); opacity: 0; }
  }

  .scan-msg { font-family: var(--mono); font-size: 11px; color: var(--text-dim); text-align: center; letter-spacing: 1px; }
  .tag-option { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin: 8px 0; cursor: pointer; }
  .tag-option:active { border-color: var(--green-mid); }
  .tag-option-epc { font-family: var(--mono); font-size: 11px; color: var(--text); word-break: break-all; }
  .tag-option-meta { font-family: var(--mono); font-size: 10px; color: var(--text-dim); margin-top: 4px; }

  .checklist-item {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 0; border-bottom: 1px solid var(--border);
    font-family: var(--sans); font-size: 14px; color: var(--text);
  }
  .checklist-item:last-child { border-bottom: none; }
  .checklist-item input[type="checkbox"] {
    width: 20px; height: 20px; accent-color: var(--green); margin: 0; flex-shrink: 0;
  }

  /* History */
  .history-entry {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 16px; margin-bottom: 8px;
  }
  .history-top {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 6px;
  }
  .history-time { font-family: var(--mono); font-size: 11px; color: var(--text-dim); }
  .history-result { font-family: var(--mono); font-size: 13px; font-weight: 600; }
  .history-result.good { color: var(--green); }
  .history-result.bad { color: var(--red); }
  .history-detail { font-family: var(--mono); font-size: 10px; color: var(--text-dim); }

  /* Settings */
  .setting-group {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px; margin-bottom: 12px;
  }
  .setting-group-title {
    font-family: var(--mono); font-size: 11px; letter-spacing: 2px;
    color: var(--cyan); text-transform: uppercase; margin-bottom: 12px;
  }
  .setting-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 0; border-bottom: 1px solid var(--border);
  }
  .setting-row:last-child { border-bottom: none; }
  .setting-label { font-family: var(--sans); font-size: 14px; color: var(--text); }
  .setting-hint { font-family: var(--mono); font-size: 10px; color: var(--text-dim); margin-top: 2px; }
  .setting-input {
    padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); font-family: var(--mono);
    font-size: 13px; width: 140px; text-align: right; outline: none;
  }
  .setting-input:focus { border-color: var(--cyan-dim); }

  /* QR */
  .qr-container { text-align: center; padding: 16px; }
  .qr-container canvas, .qr-container img { border-radius: 8px; }
</style>
</head>
<body>

<div class="header">
  <div>
    <div class="logo">rfid // packcheck</div>
    <div class="title">BACKPACK SCANNER</div>
  </div>
  <div class="header-right">
    <button class="theme-toggle" onclick="toggleTheme()" id="themeBtn">&#9789;</button>
    <div class="status-dot" id="statusDot"></div>
  </div>
</div>

<!-- Tabs -->
<div class="tabs">
  <div class="tab active" onclick="showPage('scan')">SCAN</div>
  <div class="tab" onclick="showPage('history')">HISTORY</div>
  <div class="tab" onclick="showPage('settings')">SETTINGS</div>
</div>

<!-- === SCAN PAGE === -->
<div class="page active" id="page-scan">
  <div class="profile-bar" id="profileBar"></div>

  <div class="scan-hud" id="scanHud">
    <div class="scan-line"></div>
    <div class="hud-top">
      <span class="hud-label">Inventory Status</span>
      <span class="hud-time" id="hudTime">--:--:--</span>
    </div>
    <div class="hud-count idle" id="hudCount">- / -</div>
    <div class="hud-msg" id="hudMsg">Awaiting scan<span class="blink">_</span></div>
  </div>

  <div class="actions">
    <button class="btn btn-scan" id="checkBtn" onclick="doCheck()">[ SCAN BAG ]</button>
    <button class="btn btn-add" onclick="startAdd()">+ ADD ITEM</button>
    <button class="btn btn-raw" onclick="doRawScan()">RAW SCAN</button>
  </div>

  <div id="itemsSection">
    <div class="section-label">Tracked Items</div>
    <div id="itemsList"></div>
  </div>
</div>

<!-- === HISTORY PAGE === -->
<div class="page" id="page-history">
  <div class="section-label">Recent Scans</div>
  <div id="historyList"></div>
</div>

<!-- === SETTINGS PAGE === -->
<div class="page" id="page-settings">
  <div class="setting-group">
    <div class="setting-group-title">Push Notifications</div>
    <div style="font-family:var(--sans);font-size:13px;color:var(--text);line-height:1.7;padding:4px 0;">
      <div style="margin-bottom:12px;color:var(--text-dim);font-family:var(--mono);font-size:11px;">
        Get alerts on your phone when items are missing — even when you're not looking at the app.
        Uses ntfy.sh, a free open-source notification service.
      </div>
      <div style="margin-bottom:10px">
        <span style="color:var(--cyan);font-family:var(--mono);font-weight:700">1.</span>
        Install the <b>ntfy</b> app on your iPhone (free on the App Store — search "ntfy")
      </div>
      <div style="margin-bottom:10px">
        <span style="color:var(--cyan);font-family:var(--mono);font-weight:700">2.</span>
        Open the ntfy app, tap <b>+</b>, and subscribe to a topic name you make up
        (e.g. <span style="font-family:var(--mono);color:var(--cyan)">my-backpack-123</span>)
      </div>
      <div style="margin-bottom:10px">
        <span style="color:var(--cyan);font-family:var(--mono);font-weight:700">3.</span>
        Enter that <b>same topic name</b> below
      </div>
      <div style="margin-bottom:10px">
        <span style="color:var(--cyan);font-family:var(--mono);font-weight:700">4.</span>
        Add a scan time under <b>Auto Scan Schedule</b> (e.g. 07:30)
      </div>
      <div style="margin-bottom:12px">
        <span style="color:var(--cyan);font-family:var(--mono);font-weight:700">5.</span>
        Tap <b>Save Settings</b> — the Pi will auto-scan at those times and notify you if anything's missing
      </div>
    </div>
    <div class="setting-row">
      <div>
        <div class="setting-label">ntfy Topic</div>
        <div class="setting-hint">Must match what you subscribed to in the ntfy app</div>
      </div>
      <input class="setting-input" id="settingNtfy" placeholder="topic name">
    </div>
  </div>

  <div class="setting-group">
    <div class="setting-group-title">Auto Scan Schedule</div>
    <div style="font-family:var(--sans);font-size:13px;color:var(--text-dim);line-height:1.6;margin-bottom:12px;">
      The Pi scans your bag at these times every day. If items are missing, you get a push notification.
      If everything's there, you get an "All Clear".
    </div>
    <div id="autoScanTimes"></div>
    <button class="btn btn-add" onclick="addAutoTime()" style="margin-top:8px;width:100%">+ ADD TIME</button>
  </div>

  <div class="setting-group">
    <div class="setting-group-title">Day Schedule</div>
    <div style="font-family:var(--sans);font-size:13px;color:var(--text-dim);line-height:1.6;margin-bottom:12px;">
      Automatically switch profiles based on the day of the week.
      Leave a day blank to use whatever profile is currently active.
    </div>
    <div id="daySchedule"></div>
  </div>

  <div class="setting-group">
    <div class="setting-group-title">Reader</div>
    <div class="setting-row">
      <div class="setting-label">Power (dBm)</div>
      <input class="setting-input" id="settingPower" type="text" inputmode="numeric">
    </div>
    <div class="setting-row">
      <div class="setting-label">Scan Duration (s)</div>
      <input class="setting-input" id="settingScanDur" type="text" inputmode="decimal">
    </div>
  </div>

  <div class="setting-group">
    <div class="setting-group-title">iOS Shortcut Setup</div>
    <div style="font-family:var(--sans);font-size:13px;color:var(--text);line-height:1.7;padding:4px 0;">
      <div style="margin-bottom:12px;color:var(--text-dim);font-family:var(--mono);font-size:11px;">
        One-tap bag check from your home screen — no browser needed.
      </div>
      <div style="margin-bottom:10px">
        <span style="color:var(--cyan);font-family:var(--mono);font-weight:700">1.</span>
        Open the <b>Shortcuts</b> app on your iPhone
      </div>
      <div style="margin-bottom:10px">
        <span style="color:var(--cyan);font-family:var(--mono);font-weight:700">2.</span>
        Tap the <b>+</b> in the top right to create a new shortcut
      </div>
      <div style="margin-bottom:10px">
        <span style="color:var(--cyan);font-family:var(--mono);font-weight:700">3.</span>
        Tap <b>Add Action</b>, search for <b>"Open URLs"</b> and add it
      </div>
      <div style="margin-bottom:6px">
        <span style="color:var(--cyan);font-family:var(--mono);font-weight:700">4.</span>
        Tap the URL field and paste this:
      </div>
      <div style="font-family:var(--mono);font-size:11px;color:var(--cyan);word-break:break-all;padding:10px;background:var(--bg);border-radius:6px;margin:0 0 10px;cursor:pointer;border:1px solid var(--border);" id="shortcutUrl" onclick="copyUrl()"></div>
      <div style="font-size:11px;color:var(--text-dim);margin-bottom:10px;font-family:var(--mono)" id="copyHint">Tap to copy</div>
      <div style="margin-bottom:10px">
        <span style="color:var(--cyan);font-family:var(--mono);font-weight:700">5.</span>
        Tap the name at the top, rename it to <b>"Check Backpack"</b>
      </div>
      <div style="margin-bottom:10px">
        <span style="color:var(--cyan);font-family:var(--mono);font-weight:700">6.</span>
        Tap the dropdown arrow next to the name > <b>Add to Home Screen</b>
      </div>
      <div style="margin-bottom:4px">
        <span style="color:var(--cyan);font-family:var(--mono);font-weight:700">7.</span>
        Done! Tap the icon — it opens a styled scan page that auto-checks your bag.
      </div>
      <div style="margin-top:12px;padding:10px;background:var(--surface2);border-radius:8px;font-family:var(--mono);font-size:11px;color:var(--text-dim);">
        Tip: You can also say "Hey Siri, Check Backpack" to trigger it hands-free.
      </div>
    </div>
  </div>

  <button class="btn btn-save" onclick="saveSettings()" style="width:100%;margin-top:8px">SAVE SETTINGS</button>
</div>

<!-- Add Item Modal -->
<div class="modal-overlay" id="addModal">
  <div class="modal">
    <div id="modalStep1">
      <div class="modal-title">Register New Tag</div>
      <input type="text" id="itemName" placeholder="Item name..." autocomplete="off">
      <button class="btn btn-modal-scan" onclick="scanForTag()">SCAN TAG</button>
      <button class="btn btn-cancel" onclick="closeModal('addModal')">CANCEL</button>
    </div>
    <div id="modalStep2" style="display:none">
      <div class="modal-title">Scanning...</div>
      <div class="radar">
        <div class="radar-circle"></div><div class="radar-circle"></div><div class="radar-circle"></div>
        <div class="radar-dot"></div>
      </div>
      <div class="scan-msg">PLACE TAG NEAR READER</div><br>
      <button class="btn btn-cancel" onclick="closeModal('addModal')">CANCEL</button>
    </div>
    <div id="modalStep3" style="display:none">
      <div class="modal-title">Select Tag</div>
      <div id="tagList"></div>
      <button class="btn btn-cancel" onclick="closeModal('addModal')">CANCEL</button>
    </div>
  </div>
</div>

<!-- Profile Editor Modal -->
<div class="modal-overlay" id="profileModal">
  <div class="modal">
    <div class="modal-title" id="profileModalTitle">Edit Profile</div>
    <input type="text" id="profileName" placeholder="Profile name...">
    <div class="section-label" style="margin-top:8px">Items in this profile</div>
    <div id="profileItems"></div>
    <button class="btn btn-save" onclick="saveProfile()" style="margin-top:16px">SAVE PROFILE</button>
    <button class="btn btn-modal-scan" id="shareProfileBtn" onclick="shareProfile()">SHARE (QR CODE)</button>
    <button class="btn btn-danger" id="deleteProfileBtn" onclick="deleteProfile()">DELETE PROFILE</button>
    <button class="btn btn-cancel" onclick="closeModal('profileModal')">CANCEL</button>
  </div>
</div>

<!-- QR Modal -->
<div class="modal-overlay" id="qrModal">
  <div class="modal">
    <div class="modal-title">Share Profile</div>
    <div class="qr-container" id="qrContainer"></div>
    <div class="scan-msg" style="margin:12px 0">Scan this QR code to import the profile</div>
    <button class="btn btn-cancel" onclick="closeModal('qrModal')">CLOSE</button>
  </div>
</div>

<!-- Import Modal -->
<div class="modal-overlay" id="importModal">
  <div class="modal">
    <div class="modal-title">Import Profile</div>
    <textarea id="importData" placeholder="Paste profile JSON here..." style="
      width:100%;height:120px;padding:12px;border-radius:8px;border:1px solid var(--border);
      background:var(--bg);color:var(--text);font-family:var(--mono);font-size:11px;
      resize:vertical;outline:none;margin-bottom:12px;
    "></textarea>
    <button class="btn btn-save" onclick="doImport()">IMPORT</button>
    <button class="btn btn-cancel" onclick="closeModal('importModal')">CANCEL</button>
  </div>
</div>

<script>
// --- Audio ---
const AudioCtx = window.AudioContext || window.webkitAudioContext;
let audioCtx;
function initAudio() { if (!audioCtx) audioCtx = new AudioCtx(); }

function playSuccess() {
  initAudio();
  const now = audioCtx.currentTime;
  [440, 660].forEach((freq, i) => {
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.type = 'sine'; o.frequency.value = freq;
    g.gain.setValueAtTime(0.15, now + i*0.12);
    g.gain.exponentialRampToValueAtTime(0.001, now + i*0.12 + 0.15);
    o.connect(g).connect(audioCtx.destination);
    o.start(now + i*0.12); o.stop(now + i*0.12 + 0.15);
  });
}
function playAlert() {
  initAudio();
  const now = audioCtx.currentTime;
  [880, 660, 440].forEach((freq, i) => {
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.type = 'square'; o.frequency.value = freq;
    g.gain.setValueAtTime(0.12, now + i*0.18);
    g.gain.exponentialRampToValueAtTime(0.001, now + i*0.18 + 0.2);
    o.connect(g).connect(audioCtx.destination);
    o.start(now + i*0.18); o.stop(now + i*0.18 + 0.2);
  });
}

// --- Theme ---
function getTheme() { return localStorage.getItem('theme') || 'dark'; }
function applyTheme(t) {
  document.documentElement.className = t === 'light' ? 'light' : '';
  document.getElementById('themeBtn').innerHTML = t === 'light' ? '&#9788;' : '&#9789;';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = t === 'light' ? '#f5f5f0' : '#050a08';
}
function toggleTheme() {
  const t = getTheme() === 'dark' ? 'light' : 'dark';
  localStorage.setItem('theme', t);
  applyTheme(t);
  fetch('/api/settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({theme: t})
  });
}
applyTheme(getTheme());

// --- Tabs / Pages ---
function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  document.querySelectorAll('.tab')[['scan','history','settings'].indexOf(name)].classList.add('active');
  if (name === 'history') loadHistory();
  if (name === 'settings') loadSettings();
}

// --- RSSI helper ---
function rssiBar(rssi) {
  if (rssi === null || rssi === undefined) return '';
  // RSSI typically -20 (strong) to -80 (weak)
  const strength = Math.max(0, Math.min(5, Math.round((rssi + 80) / 12)));
  let bars = '';
  for (let i = 0; i < 5; i++) {
    const active = i < strength;
    const cls = active ? (strength <= 2 ? 'bar weak' : 'bar active') : 'bar';
    bars += `<div class="${cls}"></div>`;
  }
  return `<div class="rssi-bar" title="RSSI: ${rssi} dBm">${bars}</div>`;
}

// --- Profiles ---
let profileData = { profiles: {}, active: 'Everyday', all_items: [], scheduled: null };
let editingProfile = null;
let initialLoad = true;

async function loadProfiles() {
  try {
    const res = await fetch('/api/profiles');
    profileData = await res.json();
    // On first load, auto-select today's scheduled profile if one exists
    if (initialLoad && profileData.scheduled && profileData.profiles[profileData.scheduled]) {
      profileData.active = profileData.scheduled;
      // Set it on the server too so scans use it
      fetch('/api/profiles/active', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: profileData.scheduled})
      });
      initialLoad = false;
    }
    renderProfileBar();
  } catch(e) {}
}

function renderProfileBar() {
  const bar = document.getElementById('profileBar');
  const names = Object.keys(profileData.profiles);
  bar.innerHTML = names.map(name => `
    <div class="profile-chip ${name === profileData.active ? 'active' : ''}"
         draggable="true" data-profile="${esc(name)}"
         onclick="setProfile('${esc(name)}')">
      ${esc(name)}
    </div>
  `).join('') + `<div class="profile-chip edit-chip" onclick="editProfile(null)">+</div>`;

  // Long press to edit
  bar.querySelectorAll('.profile-chip:not(.edit-chip)').forEach(chip => {
    let timer;
    let didLongPress = false;
    const name = chip.dataset.profile;
    chip.addEventListener('contextmenu', e => { e.preventDefault(); editProfile(name); });

    // Touch drag-and-drop
    let dragChip = null;
    let startX = 0;
    let isDragging = false;

    chip.addEventListener('touchstart', e => {
      didLongPress = false;
      startX = e.touches[0].clientX;
      timer = setTimeout(() => {
        didLongPress = true;
        isDragging = true;
        dragChip = chip;
        chip.style.opacity = '0.5';
        chip.style.zIndex = '10';
        navigator.vibrate && navigator.vibrate(30);
      }, 400);
    }, {passive: true});

    chip.addEventListener('touchmove', e => {
      const dx = Math.abs(e.touches[0].clientX - startX);
      if (!isDragging && dx > 10) clearTimeout(timer);
      if (!isDragging) return;
      e.preventDefault();
      const touch = e.touches[0];
      const els = document.elementsFromPoint(touch.clientX, touch.clientY);
      const target = els.find(el => el.classList.contains('profile-chip') && !el.classList.contains('edit-chip') && el !== chip);
      if (target) {
        const chipRect = chip.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        if (chipRect.left < targetRect.left) {
          target.after(chip);
        } else {
          target.before(chip);
        }
      }
    });

    chip.addEventListener('touchend', e => {
      clearTimeout(timer);
      if (isDragging) {
        chip.style.opacity = '';
        chip.style.zIndex = '';
        isDragging = false;
        saveProfileOrder();
        e.preventDefault();
      } else if (didLongPress) {
        editProfile(name);
        e.preventDefault();
      }
    });
  });

  // Desktop drag-and-drop
  let draggedEl = null;
  bar.querySelectorAll('.profile-chip:not(.edit-chip)').forEach(chip => {
    chip.addEventListener('dragstart', e => {
      draggedEl = chip;
      chip.style.opacity = '0.5';
      e.dataTransfer.effectAllowed = 'move';
    });
    chip.addEventListener('dragend', () => {
      chip.style.opacity = '';
      draggedEl = null;
    });
    chip.addEventListener('dragover', e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
    });
    chip.addEventListener('drop', e => {
      e.preventDefault();
      if (!draggedEl || draggedEl === chip) return;
      const allChips = [...bar.querySelectorAll('.profile-chip:not(.edit-chip)')];
      const dragIdx = allChips.indexOf(draggedEl);
      const dropIdx = allChips.indexOf(chip);
      if (dragIdx < dropIdx) {
        chip.after(draggedEl);
      } else {
        chip.before(draggedEl);
      }
      saveProfileOrder();
    });
  });
}

async function saveProfileOrder() {
  const bar = document.getElementById('profileBar');
  const chips = bar.querySelectorAll('.profile-chip:not(.edit-chip)');
  const order = Array.from(chips).map(c => c.dataset.profile);
  // Update local data
  const newProfiles = {};
  order.forEach(name => { if (profileData.profiles[name]) newProfiles[name] = profileData.profiles[name]; });
  profileData.profiles = newProfiles;
  // Save to server
  await fetch('/api/profiles/reorder', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({order})
  });
}

async function setProfile(name) {
  await fetch('/api/profiles/active', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name})
  });
  profileData.active = name;
  renderProfileBar();
}

function editProfile(name) {
  editingProfile = name;
  document.getElementById('profileName').value = name || '';
  document.getElementById('profileModalTitle').textContent = name ? 'Edit Profile' : 'New Profile';
  document.getElementById('deleteProfileBtn').style.display = name ? 'block' : 'none';
  document.getElementById('shareProfileBtn').style.display = name ? 'block' : 'none';
  const currentItems = name ? (profileData.profiles[name] || []) : [];
  document.getElementById('profileItems').innerHTML = profileData.all_items.map(item => `
    <label class="checklist-item">
      <input type="checkbox" value="${esc(item)}" ${currentItems.includes(item) ? 'checked' : ''}>
      ${esc(item)}
    </label>
  `).join('') || '<div style="color:var(--text-dim);font-size:12px;padding:8px 0;">No items registered yet</div>';
  document.getElementById('profileModal').classList.add('active');
}

async function saveProfile() {
  const name = document.getElementById('profileName').value.trim();
  if (!name) { alert('Enter a profile name'); return; }
  const items = Array.from(document.querySelectorAll('#profileItems input[type="checkbox"]'))
    .filter(c => c.checked).map(c => c.value);
  if (editingProfile && editingProfile !== name) {
    await fetch('/api/profiles/delete', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: editingProfile})
    });
  }
  await fetch(editingProfile && editingProfile === name ? '/api/profiles/update' : '/api/profiles/create', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name, items})
  });
  closeModal('profileModal');
  await loadProfiles();
}

async function deleteProfile() {
  if (!editingProfile || !confirm('Delete "' + editingProfile + '"?')) return;
  await fetch('/api/profiles/delete', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: editingProfile})
  });
  closeModal('profileModal');
  await loadProfiles();
}

async function shareProfile() {
  if (!editingProfile) return;
  const res = await fetch('/api/profiles/export?name=' + encodeURIComponent(editingProfile));
  const data = await res.json();
  const jsonStr = JSON.stringify(data);
  closeModal('profileModal');

  const container = document.getElementById('qrContainer');
  container.innerHTML = '';
  try {
    const qr = qrcode(0, 'L');
    qr.addData(jsonStr);
    qr.make();
    container.innerHTML = qr.createSvgTag(6, 0);
    const svg = container.querySelector('svg');
    if (svg) { svg.style.borderRadius = '8px'; }
  } catch(e) {
    container.innerHTML = '<div style="font-family:var(--mono);font-size:10px;color:var(--text-dim);word-break:break-all;padding:12px;background:var(--bg);border-radius:8px;">' + esc(jsonStr) + '</div>';
  }
  document.getElementById('qrModal').classList.add('active');
}

// --- Check / Scan ---
async function doCheck() {
  initAudio();
  const btn = document.getElementById('checkBtn');
  const hud = document.getElementById('scanHud');
  btn.disabled = true;
  btn.textContent = '[ SCANNING... ]';
  hud.classList.add('scanning');
  try {
    const res = await fetch('/api/check');
    const data = await res.json();
    const count = document.getElementById('hudCount');
    const msg = document.getElementById('hudMsg');
    document.getElementById('hudTime').textContent = new Date().toLocaleTimeString('en-US', {hour12: false});
    count.textContent = data.found + ' / ' + data.total;
    if (data.total === 0) {
      count.className = 'hud-count idle'; msg.className = 'hud-msg';
      msg.textContent = 'No items in profile';
    } else if (data.found === data.total) {
      count.className = 'hud-count good'; msg.className = 'hud-msg good';
      msg.innerHTML = 'ALL ITEMS FOUND &#x2713;';
      playSuccess();
    } else {
      count.className = 'hud-count bad'; msg.className = 'hud-msg bad';
      const missing = data.items.filter(i => !i.found).map(i => i.name);
      msg.textContent = 'MISSING: ' + missing.join(', ');
      playAlert();
    }
    renderCheckResults(data.items);
  } catch(e) {
    document.getElementById('hudMsg').textContent = 'SCAN FAILED: ' + e.message;
    document.getElementById('hudMsg').className = 'hud-msg bad';
  }
  hud.classList.remove('scanning');
  btn.disabled = false;
  btn.textContent = '[ SCAN BAG ]';
}

async function doRawScan() {
  const btn = document.querySelector('.btn-raw');
  btn.textContent = 'SCANNING...'; btn.disabled = true;
  try {
    const res = await fetch('/api/scan');
    const data = await res.json();
    if (data.tags.length === 0) { alert('No tags in range'); }
    else {
      const lines = data.tags.map(t =>
        (t.name || '???') + '\n' + t.epc + '\nRSSI: ' + t.rssi + ' dBm | Reads: ' + t.count
      );
      alert('Found ' + data.tags.length + ' tag(s):\n\n' + lines.join('\n\n'));
    }
  } catch(e) { alert('Error: ' + e.message); }
  btn.textContent = 'RAW SCAN'; btn.disabled = false;
}

function renderCheckResults(items) {
  const el = document.getElementById('itemsList');
  if (items.length === 0) {
    el.innerHTML = '<div class="empty-state">No items in this profile.<br>Long-press a profile to edit.<span class="blink">_</span></div>';
    return;
  }
  items.sort((a,b) => a.found - b.found);
  el.innerHTML = items.map(item => {
    const cls = item.found ? 'found' : 'missing';
    const icon = item.found ? '&#x2713;' : '!';
    return `
    <div class="item ${cls}">
      <div class="item-icon">${icon}</div>
      <div class="item-info">
        <div class="item-name">${esc(item.name)}</div>
        <div class="item-meta">
          <span class="item-epc">${item.epc}</span>
          ${item.rssi !== null ? rssiBar(item.rssi) : ''}
          ${item.rssi !== null ? '<span>' + item.rssi + ' dBm</span>' : ''}
        </div>
      </div>
      <button class="item-remove" onclick="removeItem('${esc(item.name)}')">&times;</button>
    </div>`;
  }).join('');
}

async function loadItems() {
  try {
    const res = await fetch('/api/items');
    const items = await res.json();
    const el = document.getElementById('itemsList');
    const entries = Object.entries(items);
    if (entries.length === 0) {
      el.innerHTML = '<div class="empty-state">No items tracked yet.<br>Tap + ADD ITEM to register a tag.<span class="blink">_</span></div>';
      return;
    }
    el.innerHTML = entries.map(([name, epc]) => `
      <div class="item neutral">
        <div class="item-icon">#</div>
        <div class="item-info">
          <div class="item-name">${esc(name)}</div>
          <div class="item-meta"><span class="item-epc">${epc}</span></div>
        </div>
        <button class="item-remove" onclick="removeItem('${esc(name)}')">&times;</button>
      </div>
    `).join('');
  } catch(e) { document.getElementById('statusDot').classList.add('offline'); }
}

// --- Add Item ---
function startAdd() {
  document.getElementById('addModal').classList.add('active');
  document.getElementById('modalStep1').style.display = 'block';
  document.getElementById('modalStep2').style.display = 'none';
  document.getElementById('modalStep3').style.display = 'none';
  document.getElementById('itemName').value = '';
  setTimeout(() => document.getElementById('itemName').focus(), 100);
}
function closeModal(id) { document.getElementById(id).classList.remove('active'); }

async function scanForTag() {
  const name = document.getElementById('itemName').value.trim();
  if (!name) { alert('Enter a name first'); return; }
  document.getElementById('modalStep1').style.display = 'none';
  document.getElementById('modalStep2').style.display = 'block';
  try {
    const res = await fetch('/api/scan');
    const data = await res.json();
    if (data.tags.length === 0) {
      alert('No tags found. Move closer and try again.');
      document.getElementById('modalStep2').style.display = 'none';
      document.getElementById('modalStep1').style.display = 'block';
      return;
    }
    const itemsRes = await fetch('/api/items');
    const items = await itemsRes.json();
    const registered = new Set(Object.values(items));
    const available = data.tags.filter(t => !registered.has(t.epc));
    if (available.length === 0) { alert('All detected tags are already registered.'); closeModal('addModal'); return; }
    if (available.length === 1) { await registerTag(name, available[0].epc); return; }
    document.getElementById('modalStep2').style.display = 'none';
    document.getElementById('modalStep3').style.display = 'block';
    document.getElementById('tagList').innerHTML = available.map(t => `
      <div class="tag-option" onclick="registerTag('${esc(name)}', '${t.epc}')">
        <div class="tag-option-epc">${t.epc}</div>
        <div class="tag-option-meta">RSSI ${t.rssi} dBm // ${t.count} reads</div>
      </div>
    `).join('');
  } catch(e) { alert('Scan failed: ' + e.message); closeModal('addModal'); }
}

async function registerTag(name, epc) {
  const res = await fetch('/api/items/add', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name, epc})
  });
  const data = await res.json();
  if (data.error) alert(data.error);
  closeModal('addModal');
  loadItems(); loadProfiles();
}

async function removeItem(name) {
  if (!confirm('Remove "' + name + '"?')) return;
  await fetch('/api/items/remove', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name})
  });
  loadItems(); loadProfiles();
}

// --- History ---
async function loadHistory() {
  const res = await fetch('/api/history');
  const data = await res.json();
  const el = document.getElementById('historyList');
  const scans = data.scans.slice().reverse().slice(0, 30);
  if (scans.length === 0) {
    el.innerHTML = '<div class="empty-state">No scan history yet.<span class="blink">_</span></div>';
    return;
  }
  el.innerHTML = scans.map(scan => {
    const d = new Date(scan.timestamp);
    const time = d.toLocaleString('en-US', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', hour12:false});
    const allGood = scan.found === scan.total;
    const missing = scan.items.filter(i => !i.found).map(i => i.name);
    return `
    <div class="history-entry">
      <div class="history-top">
        <span class="history-time">${time} // ${esc(scan.profile)}</span>
        <span class="history-result ${allGood ? 'good' : 'bad'}">${scan.found}/${scan.total}</span>
      </div>
      ${missing.length > 0 ? '<div class="history-detail">Missing: ' + missing.map(esc).join(', ') + '</div>' : '<div class="history-detail" style="color:var(--green)">All clear</div>'}
    </div>`;
  }).join('');
}

// --- Settings ---
let autoScanTimes = [];
let daySchedule = {};
const DAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];

async function loadSettings() {
  const res = await fetch('/api/settings');
  const s = await res.json();
  document.getElementById('settingNtfy').value = s.ntfy_topic || '';
  document.getElementById('settingPower').value = s.power_dbm;
  document.getElementById('settingScanDur').value = s.scan_duration;
  autoScanTimes = s.auto_scan_times || [];
  daySchedule = s.day_schedule || {};
  renderAutoTimes();
  renderDaySchedule();
  document.getElementById('shortcutUrl').textContent = location.origin + '/quickcheck';
  if (s.theme && s.theme !== getTheme()) {
    localStorage.setItem('theme', s.theme);
    applyTheme(s.theme);
  }
}

function renderDaySchedule() {
  const el = document.getElementById('daySchedule');
  const profileNames = Object.keys(profileData.profiles);
  const today = new Date().toLocaleDateString('en-US', {weekday: 'long'});
  el.innerHTML = DAYS.map(day => {
    const selected = daySchedule[day] || '';
    const isToday = day === today;
    return `
    <div class="setting-row" ${isToday ? 'style="background:var(--green-dim);margin:0 -16px;padding:8px 16px;border-radius:6px"' : ''}>
      <div>
        <div class="setting-label">${day}${isToday ? ' <span style="font-family:var(--mono);font-size:10px;color:var(--green)">(today)</span>' : ''}</div>
      </div>
      <select class="setting-input" style="width:150px;text-align:right"
              onchange="daySchedule['${day}']=this.value||undefined;if(!this.value)delete daySchedule['${day}']">
        <option value="" ${!selected ? 'selected' : ''}>—</option>
        ${profileNames.map(p => `<option value="${esc(p)}" ${selected === p ? 'selected' : ''}>${esc(p)}</option>`).join('')}
      </select>
    </div>`;
  }).join('');
}

function renderAutoTimes() {
  const el = document.getElementById('autoScanTimes');
  el.innerHTML = autoScanTimes.map((t, i) => `
    <div class="setting-row">
      <input class="setting-input" value="${t}" style="width:100px;text-align:center"
             onchange="autoScanTimes[${i}]=this.value" placeholder="HH:MM">
      <button class="btn btn-danger" style="width:auto;padding:6px 12px;margin:0"
              onclick="autoScanTimes.splice(${i},1);renderAutoTimes()">X</button>
    </div>
  `).join('');
  if (autoScanTimes.length === 0) {
    el.innerHTML = '<div style="color:var(--text-dim);font-size:12px;padding:8px 0">No scheduled scans</div>';
  }
}

function addAutoTime() {
  autoScanTimes.push('07:30');
  renderAutoTimes();
}

async function saveSettings() {
  await fetch('/api/settings', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      ntfy_topic: document.getElementById('settingNtfy').value.trim(),
      auto_scan_times: autoScanTimes,
      power_dbm: parseInt(document.getElementById('settingPower').value) || 20,
      scan_duration: parseFloat(document.getElementById('settingScanDur').value) || 2.0,
      theme: getTheme(),
      day_schedule: daySchedule,
    })
  });
  alert('Settings saved!');
}

async function doImport() {
  try {
    const data = JSON.parse(document.getElementById('importData').value);
    const res = await fetch('/api/profiles/import', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    const result = await res.json();
    if (result.error) { alert(result.error); return; }
    closeModal('importModal');
    loadItems(); loadProfiles();
    alert('Profile imported!');
  } catch(e) { alert('Invalid data: ' + e.message); }
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function copyUrl() {
  const url = document.getElementById('shortcutUrl').textContent;
  navigator.clipboard.writeText(url).then(() => {
    document.getElementById('copyHint').textContent = 'Copied!';
    setTimeout(() => { document.getElementById('copyHint').textContent = 'Tap to copy'; }, 2000);
  }).catch(() => {
    // Fallback for older browsers
    const ta = document.createElement('textarea');
    ta.value = url;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    document.getElementById('copyHint').textContent = 'Copied!';
    setTimeout(() => { document.getElementById('copyHint').textContent = 'Tap to copy'; }, 2000);
  });
}

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');
loadItems();
loadProfiles();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
