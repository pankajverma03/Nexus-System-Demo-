# app.py - Nexus System (startup-safe, demo-friendly)
from flask import Flask, render_template, request, jsonify
from datetime import datetime
import os
import logging

# Create Flask app FIRST (must exist before routes)
app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# DB / SQLAlchemy lazy initialization to avoid import-time crash
SessionLocal = None
engine = None

def init_db_engine():
    global engine, SessionLocal
    if engine is not None and SessionLocal is not None:
        return

    try:
        # Try to import engine from db.py (production path)
        from db import engine as imported_engine
        from sqlalchemy.orm import sessionmaker as _sessionmaker
        engine = imported_engine
        SessionLocal = _sessionmaker(bind=engine)
        app.logger.info("DB engine loaded from db.py")
        return
    except Exception as e:
        app.logger.warning(f"db import failed at startup: {e}")

    # Fallback: lightweight in-memory SQLite for demo (no persistence)
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker as _sessionmaker
        engine = create_engine("sqlite:///:memory:", echo=False, future=True)
        SessionLocal = _sessionmaker(bind=engine)
        app.logger.info("Using fallback in-memory SQLite engine (demo mode)")
    except Exception as e:
        app.logger.error(f"Failed to create fallback DB engine: {e}")
        engine = None
        SessionLocal = None

# Delay heavy imports (ai_router) until runtime to avoid startup crash
analyze_event_ai = None
try:
    # try import but tolerate failure
    from ai_router import analyze_event_ai as _analyze
    analyze_event_ai = _analyze
    app.logger.info("ai_router imported successfully")
except Exception as e:
    analyze_event_ai = None
    app.logger.warning(f"ai_router import failed at startup: {e}")

# --- Dashboard (simple demo UI, templates/dashboard.html) ---
@app.route('/')
def dashboard():
    # ensure DB engine available (non-blocking)
    init_db_engine()

    # simulated snapshot + alerts for demo
    snapshot = {
        "time": datetime.utcnow().isoformat(),
        "ok": False,
        "db": False,
    }

    # quick readability DB check (best-effort)
    try:
        if SessionLocal:
            with SessionLocal() as db:
                # quick lightweight query to validate connection (SQLite or Postgres)
                _ = db.execute("SELECT 1").fetchone()
                snapshot["db"] = True
                snapshot["ok"] = True
    except Exception as e:
        app.logger.warning(f"DB quick-check failed: {e}")
        snapshot["db"] = False
        snapshot["ok"] = False

    alerts = [
        {"level": "Warning", "msg": "High CPU on Node 3", "age": "2m"},
        {"level": "Info", "msg": "Firmware deploy success", "age": "1h"},
    ]

    return render_template('dashboard.html', title='Nexus System Dashboard', snapshot=snapshot, alerts=alerts)

# --- Health endpoint ---
@app.route('/health')
def health():
    init_db_engine()
    ok = False
    try:
        if SessionLocal:
            with SessionLocal() as db:
                _ = db.execute("SELECT 1").fetchone()
                ok = True
    except Exception:
        ok = False
    return jsonify(status='ok' if ok else 'degraded', db=bool(SessionLocal and ok)), 200

# --- Sample create event endpoint for demo (UI button) ---
@app.route('/api/create_sample', methods=['POST'])
def create_sample():
    # lightweight sample event payload (no persistence if DB not ready)
    init_db_engine()
    sample = {
        "id": "ev_demo_1",
        "payload": {"message": "simulated error: connection reset", "code": 502},
        "meta_info": {"service": "demo-service", "tenant": "demo"}
    }
    try:
        if SessionLocal:
            from models import Event  # local import to avoid startup issues
            with SessionLocal() as db:
                ev = Event(id=sample["id"], payload=sample["payload"], meta_info=sample["meta_info"])
                db.add(ev)
                db.commit()
    except Exception as e:
        app.logger.warning(f"Create-sample persistence failed: {e}")
    return jsonify(ok=True, event=sample), 200

# --- AI suggest endpoint (uses analyze_event_ai if available, else simple heuristic) ---
@app.route('/api/ai/suggest', methods=['POST'])
def api_ai_suggest():
    init_db_engine()
    body = request.get_json(force=True) or {}
    event_id = body.get("event_id") or body.get("eventId") or body.get("id")
    if not event_id:
        return jsonify(ok=False, error="missing event_id"), 400

    event_payload = None
    event_meta = None
    try:
        if SessionLocal:
            from models import Event
            with SessionLocal() as db:
                ev = db.query(Event).filter_by(id=event_id).first()
                if ev:
                    event_payload = ev.payload
                    event_meta = getattr(ev, "meta_info", None)
    except Exception as e:
        app.logger.warning(f"Failed to read event from DB: {e}")

    # Use ai_router if available
    if analyze_event_ai:
        try:
            res = analyze_event_ai(event_id=event_id, event_payload=event_payload, event_meta=event_meta)
        except Exception as e:
            app.logger.warning(f"analyze_event_ai failed at runtime: {e}")
            analyze_local = None
            res = {"analysis": "ai runtime error", "suggestion": "AI unavailable", "provider": "none"}
    else:
        # Simple local heuristic fallback (demo)
        summary = f"Event {event_id}: local-heuristic analysis"
        suggestion = "Check network connectivity and restart the affected node."
        res = {"analysis": summary, "suggestion": suggestion, "provider": "local-heuristic"}

    # optional persist suggestion
    try:
        if SessionLocal:
            from models import AISuggestion
            with SessionLocal() as db:
                sug = AISuggestion(event_id=event_id, analysis=res.get("analysis"), suggestion=res.get("suggestion"), provider=res.get("provider"))
                db.add(sug)
                db.commit()
                db.refresh(sug)
                res["suggestion_id"] = sug.id
    except Exception as e:
        app.logger.warning(f"Failed to persist AISuggestion: {e}")

    return jsonify(ok=True, **res), 200

# standard run for local debug (ignored by gunicorn)
if __name__ == '__main__':
    init_db_engine()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)), debug=True)
