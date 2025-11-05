# --- add these imports at top of app.py ---
from flask import Flask, jsonify, request
import random, time, datetime

# ---------- demo in-memory store (for quick demo) ----------
_demo_events = []
def _now_iso(): return datetime.datetime.utcnow().isoformat()

# ---------- route: create sample ---------- (POST)
@app.route('/api/create_sample', methods=['POST'])
def create_sample():
    ev_id = f"ev_{int(time.time())}_{random.randint(100,999)}"
    ev = {
      "id": ev_id,
      "title": "Selector missing on page",
      "level": random.choice(["Info","Warning","Critical"]),
      "time": "2m ago",
      "payload": {"selector":"#objective","errorCode":"META-SEL-001"}
    }
    _demo_events.insert(0, ev)
    return jsonify({"ok":True, "event_id": ev_id})

# ---------- route: metrics (GET) ----------
@app.route('/api/metrics', methods=['GET'])
def api_metrics():
    # If you have DB connectivity, return real data; else demo values:
    # build demo time-series arrays (10 points)
    labels = []
    cpu = []; mem = []; disk = []
    now = int(time.time())
    for i in range(10):
        labels.append((now - (9-i)*5))  # timestamp placeholders
        cpu.append(round(random.uniform(20,80),2))
        mem.append(round(random.uniform(50,88),2))
        disk.append(round(random.uniform(22,60),2))
    resp = {
      "ok": True,
      "db": False,  # if your DB is connected, set True
      "time": _now_iso(),
      "active_sessions": random.randint(200,1200),
      "latency_ms": random.randint(10,120),
      "disk_percent": round(disk[-1],2),
      "disk_used": round(random.uniform(200,900),2),
      "series": {"labels": labels, "cpu": cpu, "mem": mem, "disk": disk},
      "alerts": _demo_events[:6]
    }
    return jsonify(resp)

# ---------- route: AI suggestion (POST) ----------
@app.route('/api/ai/suggest', methods=['POST'])
def api_ai_suggest():
    body = request.get_json() or {}
    event_id = body.get('event_id')
    # Minimal: call local heuristic first; if OPENAI_API_KEY present, call ai_router
    try:
        # quick heuristic
        if event_id and "META-SEL" in (event_id or ""):
            sug = "Heuristic: Check selector mapping for Meta adset_edit. Likely selector changed. Patch: update selector map and re-deploy version."
            return jsonify({"ok":True, "summary":"Selector mapping hint", "suggestion":sug})
        # otherwise fallback - simple canned response for demo
        sug = f"Demo suggestion for {event_id or 'unknown'}: Inspect last 24h logs for correlationId; check 3rd-party API rate-limits."
        return jsonify({"ok":True, "summary":"Demo AI suggestion", "suggestion":sug})
    except Exception as e:
        return jsonify({"ok":False, "error": str(e)}), 500
