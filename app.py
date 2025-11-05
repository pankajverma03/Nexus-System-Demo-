# app.py
import os
import json
import random
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify

from db import init_db, get_db_session
from ai_router import get_ai_suggestion

# Config
DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
PORT = int(os.getenv("PORT", 5000))
SECRET_KEY = os.getenv("SECRET_KEY", "change_me_in_prod")

# App init
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config.update(SECRET_KEY=SECRET_KEY)

# Logging
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("nexus")

# Init DB (creates tables if not exists)
init_db()

# Simulated metrics (pluggable)
def get_system_metrics():
    return {
        "cpu_load": round(random.uniform(10.0, 75.0), 2),
        "memory_utilization": round(random.uniform(30.0, 90.0), 2),
        "network_latency_ms": random.randint(5, 150),
        "total_users": 8764,
        "active_sessions": random.randint(200, 2000),
        "disk_capacity_gb": 1024,
        "disk_used_gb": round(random.uniform(100, 950), 2),
        "status_icon": "🟢",
        "health_status": "Operational",
        "alerts": [
            {"id": 101, "message": "High CPU on Node 3", "level": "Warning", "time": "2m ago"},
            {"id": 102, "message": "Firmware deploy success", "level": "Info", "time": "1h ago"}
        ]
    }

def now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def calculate_disk_usage(used, total):
    try:
        return round((used / total) * 100, 2) if total else 0
    except Exception:
        return 0

# Web UI
@app.route("/")
def dashboard():
    metrics = get_system_metrics()
    disk_percent = calculate_disk_usage(metrics["disk_used_gb"], metrics["disk_capacity_gb"])
    ctx = {
        "title": "Nexus System Dashboard",
        "metrics": metrics,
        "disk_usage_percent": disk_percent,
        "current_time": now_str()
    }
    return render_template("dashboard.html", **ctx)

# Ingest API (demo)
@app.route("/v1/ingest/event", methods=["POST"])
def ingest_event():
    try:
        body = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400
    if not body or "tenantId" not in body or "service" not in body:
        return jsonify({"ok": False, "error": "tenantId & service required"}), 400

    # persist to DB (demo: write to events table)
    session = get_db_session()
    from models import Event
    ev = Event(tenant_id=body.get("tenantId"), service=body.get("service"),
               type=body.get("type", "ERROR"), trace_id=body.get("traceId"),
               metadata=body.get("metadata"), payload=body.get("payload"))
    session.add(ev)
    session.commit()
    session.refresh(ev)
    event_id = ev.id
    logger.info("Ingested event %s tenant=%s service=%s", event_id, ev.tenant_id, ev.service)
    session.close()
    return jsonify({"ok": True, "id": event_id}), 202

# AI Debug endpoint
@app.route("/v1/ai/debug", methods=["POST"])
def ai_debug():
    data = request.get_json(force=True, silent=True) or {}
    event = data.get("event")
    event_id = data.get("eventId")
    if event_id and not event:
        # load from DB
        session = get_db_session()
        from models import Event
        ev = session.query(Event).filter(Event.id == event_id).first()
        session.close()
        if not ev:
            return jsonify({"ok": False, "error": "event_not_found"}), 404
        event = {
            "id": ev.id, "tenantId": ev.tenant_id, "service": ev.service,
            "metadata": ev.metadata, "payload": ev.payload
        }
    if not event:
        return jsonify({"ok": False, "error": "event or eventId required"}), 400

    trace_frames = data.get("traceFrames")
    suggestion = get_ai_suggestion(event, trace_frames)
    return jsonify({"ok": True, "suggestion": suggestion}), 200

# Health & Status
@app.route("/v1/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "version": "0.1.0", "time": now_str()}), 200

@app.route("/v1/status", methods=["GET"])
def status():
    deps = {"db": "ok", "ai_provider": "configured" if os.getenv("OPENAI_API_KEY") else "not-configured"}
    return jsonify({"ok": True, "deps": deps, "version": "0.1.0", "time": now_str()}), 200

if __name__ == "__main__":
    logger.info("Starting Nexus app (debug=%s) on port %s", DEBUG, PORT)
    app.run(host="0.0.0.0", port=PORT, debug=DEBUG)
