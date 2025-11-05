# ------- app.py (TOP section) - paste exactly this block at file top -------
from flask import Flask, render_template, request, jsonify
from sqlalchemy.orm import sessionmaker
from db import engine
from models import Event, AISuggestion
from datetime import datetime

# Create Flask app FIRST (must be before any @app.route usage)
app = Flask(__name__)
SessionLocal = sessionmaker(bind=engine)

# Delay heavy imports (ai_router) until runtime to avoid import-time crashes
# If ai_router import fails during startup it can break the whole process.
try:
    from ai_router import analyze_event_ai
except Exception as e:
    analyze_event_ai = None
    app.logger.warning(f"ai_router import failed at startup: {e}")
# ---------------------------------------------------------------------------
# --- Dashboard (simple demo UI, uses templates/dashboard.html) ---
@app.route('/')
def dashboard():
    # simulated snapshot + alerts (keep lightweight for demo)
    snapshot = {
        "time": datetime.utcnow().isoformat(),
        "ok": False,   # DB check below may flip to True
        "db": False
    }

    # check DB connectivity quickly (non-blocking, best-effort)
    try:
        with SessionLocal() as db:
            # quick read to ensure engine works
            _ = db.execute("SELECT 1").fetchone()
            snapshot["db"] = True
            snapshot["ok"] = True
    except Exception:
        # leave snapshot db=False
        pass

    alerts = [
        {"level": "Warning", "msg": "High CPU on Node 3", "age": "2m"},
        {"level": "Info", "msg": "Firmware deploy success", "age": "1h"}
    ]

    return render_template('dashboard.html', title='Nexus System Dashboard',
                           snapshot=snapshot, alerts=alerts)

# --- Health endpoints ---
@app.route('/health')
def health():
    # simple liveness
    return jsonify(ok=True, version="1.0.0", uptimeSec=0), 200

@app.route('/status')
def status():
    deps = {"db": "unknown"}
    try:
        with SessionLocal() as db:
            _ = db.execute("SELECT 1").fetchone()
            deps["db"] = "ok"
    except Exception:
        deps["db"] = "down"

    return jsonify(ok=(deps["db"] == "ok"), deps=deps, build="1.0.0"), 200

# --- AI Suggest endpoint (core) ---
@app.route('/api/ai/suggest', methods=['POST'])
def api_ai_suggest():
    body = request.get_json(force=True) or {}
    event_id = body.get("event_id") or body.get("eventId") or body.get("id")
    if not event_id:
        return jsonify(ok=False, error="missing event_id"), 400

    # Fetch event payload from DB if available; else pass None (heuristic will work)
    event_payload = None
    event_meta = None
    try:
        with SessionLocal() as db:
            ev = db.query(Event).filter_by(id=event_id).first()
            if ev:
                event_payload = getattr(ev, "payload", None)
                # use meta_info (models.py renamed earlier)
                event_meta = getattr(ev, "meta_info", None)
    except Exception:
        # DB read failure: continue with None (fallback heuristic)
        pass

    # Call the AI router (OpenAI / local fallback). Should return dict with keys: analysis, suggestion, provider
    try:
        res = analyze_event_ai(event_id=event_id, event_payload=event_payload, event_meta=event_meta)
    except Exception as e:
        # if ai_router import/call fails, return graceful error for demo
        return jsonify(ok=False, error="ai_router failure", detail=str(e)), 500

    # persist suggestion if you want (best-effort, ignore failures)
    try:
        with SessionLocal() as db:
            sug = AISuggestion(
                event_id=event_id,
                analysis=res.get("analysis"),
                suggestion=res.get("suggestion"),
                provider=res.get("provider")
            )
            db.add(sug)
            db.commit()
            db.refresh(sug)
            res["suggestion_id"] = sug.id
    except Exception:
        pass

    return jsonify(ok=True, **res), 200

# --- Error handlers ---
@app.errorhandler(404)
def page_not_found(e):
    return render_template('error.html', title='Not Found', error_code=404), 404

@app.errorhandler(500)
def server_error(e):
    # keep internal error text out of UI in production; show minimal info for demo
    return render_template('error.html', title='Server Error', error_code=500), 500

# --- Run (only when executed locally) ---
if __name__ == '__main__':
    # debug False in production; using default Flask dev server only for local testing
    app.run(host='0.0.0.0', port=int(__import__('os').environ.get('PORT', 8080)), debug=True)
