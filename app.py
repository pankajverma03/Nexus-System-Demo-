# app.py - Nexus System (startup-safe, demo-friendly)
from flask import Flask, render_template, request, jsonify
from datetime import datetime
from sqlalchemy import text
from sqlalchemy import text as _text
import os
import logging
import traceback

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# DB / SQLAlchemy lazy initialization to avoid import-time crash
SessionLocal = None
engine = None

def init_db_engine():
    """
    Try to import engine from db.py (production).
    If that fails, create an in-memory SQLite fallback (demo mode).
    This function is idempotent.
    """
    global engine, SessionLocal
    if engine is not None and SessionLocal is not None:
        return

    # Try production engine import
    try:
        from db import engine as imported_engine
        from sqlalchemy.orm import sessionmaker as _sessionmaker
        engine = imported_engine
        SessionLocal = _sessionmaker(bind=engine)
        app.logger.info("DB engine loaded from db.py")
        return
    except Exception as e:
        app.logger.warning(f"db import failed at startup: {e}")

    # Fallback: in-memory SQLite (demo-only)
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

# --- helper: create demo tables in a dialect-aware way ---
def ensure_demo_tables(db):
    """
    Create 'events' and 'ai_suggestions' tables using SQL that matches the DB dialect.
    Call with an open SessionLocal() context: `with SessionLocal() as db: ensure_demo_tables(db)`
    """
    try:
        is_postgres = False
        try:
            is_postgres = getattr(engine, "dialect").name in ("postgresql", "postgres")
        except Exception:
            # fallback: inspect engine.url string
            try:
                is_postgres = str(getattr(engine, "url", "")).startswith("postgres")
            except Exception:
                is_postgres = False

        if is_postgres:
            # PostgreSQL-friendly DDL
            db.execute(_text(
                "CREATE TABLE IF NOT EXISTS events ("
                "id TEXT PRIMARY KEY, event_type TEXT, message TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            ))
            db.execute(_text(
                "CREATE TABLE IF NOT EXISTS ai_suggestions ("
                "id SERIAL PRIMARY KEY, event_id TEXT, title TEXT, body TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            ))
        else:
            # SQLite / generic fallback
            db.execute(_text(
                "CREATE TABLE IF NOT EXISTS events ("
                "id TEXT PRIMARY KEY, event_type TEXT, message TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
            ))
            db.execute(_text(
                "CREATE TABLE IF NOT EXISTS ai_suggestions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT, title TEXT, body TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
            ))
    except Exception as e:
        app.logger.exception(f"ensure_demo_tables failed: {e}")

def seed_demo_events():
    """
    Seed a few demo events and suggestions when using the in-memory fallback.
    Safe to call multiple times.
    """
    try:
        if SessionLocal is None:
            app.logger.warning("SessionLocal is None — skipping seed_demo_events")
            return

        with SessionLocal() as db:
            # dialect-aware table creation
            ensure_demo_tables(db)

            # Check if already seeded (avoid duplicates)
            row = db.execute(text("SELECT COUNT(1) as c FROM events")).fetchone()
            count = row[0] if row else 0
            if count > 0:
                app.logger.info("Demo DB already seeded (events exist).")
                return

            demo_rows = [
                ("ev_demo_1", "ERROR", "DB connection timeout on /api/metrics"),
                ("ev_demo_2", "WARN", "Memory usage spike detected (85%)"),
                ("ev_demo_3", "INFO", "Service restart completed: svc-auth"),
                ("ev_demo_4", "ERROR", "Failed write to disk /var/log"),
                ("ev_demo_5", "INFO", "Synthetic event for demo: TraceID demo-1234")
            ]
            for _id, et, msg in demo_rows:
                db.execute(text("INSERT INTO events (id, event_type, message) VALUES (:id, :et, :msg)"),
                           {"id": _id, "et": et, "msg": msg})
            # add a simple ai suggestion row for one event
            db.execute(text("INSERT INTO ai_suggestions (event_id, title, body) VALUES (:eid, :t, :b)"),
                       {"eid": "ev_demo_1", "t": "Investigate DB timeout", "b": "Check DB connections; restart DB pool if necessary."})
            db.commit()
            app.logger.info("Seeded demo events and ai_suggestions (5 events + 1 suggestion)")
    except Exception as e:
        app.logger.exception(f"seed_demo_events failed: {e}")

# Lazy AI loader: keep analyze_event_ai None until first use
analyze_event_ai = None
def ensure_ai_router_loaded():
    """
    Lazy import ai_router and set analyze_event_ai callable.
    Returns callable or None.
    """
    global analyze_event_ai
    if analyze_event_ai is not None:
        return analyze_event_ai
    try:
        from ai_router import analyze_event_ai as _analyze
        analyze_event_ai = _analyze
        app.logger.info("ai_router imported successfully at runtime")
    except Exception as e:
        analyze_event_ai = None
        app.logger.warning(f"ai_router import failed at runtime: {e}")
    return analyze_event_ai

# --- Dashboard (simple demo UI, templates/dashboard.html) ---
@app.route('/')
def dashboard():
    init_db_engine()
    # seed demo only for fallback sqlite or when env DEMO_SEED is true (default True for demo)
    try:
        demo_seed_flag = os.environ.get("DEMO_SEED", "true").lower() in ("1", "true", "yes")
        if engine is not None and str(getattr(engine, "url", "")).startswith("sqlite") and demo_seed_flag:
            seed_demo_events()
    except Exception:
        app.logger.debug("seed_demo check failed: " + traceback.format_exc())

    snapshot = {
        "time": datetime.utcnow().isoformat(),
        "ok": False,
        "db": False,
    }

    # best-effort DB quick-check (non-blocking)
    try:
        if SessionLocal:
            with SessionLocal() as db:
                _ = db.execute(text("SELECT 1")).fetchone()
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
                _ = db.execute(text("SELECT 1")).fetchone()
                ok = True
    except Exception:
        ok = False
    return jsonify(status='ok' if ok else 'degraded', db=bool(SessionLocal and ok)), 200

# --- create / persist a sample event for demo (GET/POST) ---
@app.route('/api/create_sample', methods=['GET', 'POST'])
def create_sample():
    """
    Create a demo sample event. Try to persist if DB is ready,
    but always return the sample JSON to the client (non-blocking).
    """
    init_db_engine()
    import random, time
    sample = {
        "id": f"ev_demo_{int(time.time())}_{random.randint(100,999)}",
        "payload": {"message": "simulated error: connection reset", "code": 502},
        "meta_info": {"service": "demo-service", "tenant": "demo"}
    }
    try:
        if SessionLocal:
            with SessionLocal() as db:
                # ensure tables exist and then insert
                ensure_demo_tables(db)
                db.execute(text("INSERT OR REPLACE INTO events (id, event_type, message) VALUES (:id, :et, :msg)"),
                           {"id": sample["id"], "et": "ERROR", "msg": str(sample["payload"] )})
                db.commit()
    except Exception as e:
        app.logger.warning(f"Create-sample persistence failed: {e}")

    return jsonify(ok=True, event=sample), 200

# --- Minimal ingest endpoint to populate the demo dashboard ---
@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    """
    Minimal ingest endpoint for demo:
    - Inserts event into events table
    - Returns a simulated AI suggestion (so UI shows Recent AI Suggestions)
    """
    init_db_engine()
    payload = request.get_json(silent=True) or {}
    event_type = payload.get("event_type", "INFO")
    message = payload.get("message", "Synthetic ingest event from demo UI")
    event_id = payload.get("id") or f"ev_manual_{int(datetime.utcnow().timestamp())}"

    try:
        if SessionLocal is None:
            return jsonify({"ok": False, "error": "DB not available"}), 500

        with SessionLocal() as db:
            ensure_demo_tables(db)
            db.execute(text("INSERT OR REPLACE INTO events (id, event_type, message) VALUES (:id, :et, :msg)"),
                       {"id": event_id, "et": event_type, "msg": message})
            db.commit()

            # create a simple AI suggestion row (simulated)
            sim_title = f"{event_type} - Demo Suggestion"
            sim_body = f"Simulated: check logs for recent {event_type} events. TraceID: demo-{int(datetime.utcnow().timestamp())}"
            db.execute(text("INSERT INTO ai_suggestions (event_id, title, body) VALUES (:eid, :t, :b)"),
                       {"eid": event_id, "t": sim_title, "b": sim_body})
            db.commit()

        suggestion = {"suggestion": sim_body, "action": "Check application logs and restart service if persistent."}
        return jsonify({"ok": True, "event_id": event_id, "suggestion": suggestion}), 201
    except Exception as e:
        app.logger.exception(f"api_ingest failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# -------------------------
# Add this GET endpoint to expose stored AI suggestions to the frontend
# -------------------------
@app.route("/api/ai/suggestions", methods=["GET"])
def api_ai_suggestions():
    """
    Return recent AI suggestions (best-effort).
    """
    init_db_engine()
    try:
        if SessionLocal is None:
            return jsonify(ok=False, error="DB not available"), 500

        with SessionLocal() as db:
            ensure_demo_tables(db)
            rows = db.execute(text("SELECT id, event_id, title, body, created_at FROM ai_suggestions ORDER BY created_at DESC LIMIT 20")).fetchall()
            suggestions = []
            for r in rows:
                suggestions.append({
                    "id": r[0],
                    "event_id": r[1],
                    "title": r[2],
                    "body": r[3],
                    "created_at": str(r[4])
                })
        return jsonify(ok=True, suggestions=suggestions), 200
    except Exception as e:
        app.logger.exception(f"api_ai_suggestions failed: {e}")
        return jsonify(ok=False, error=str(e)), 500

# --- route: metrics (GET) ---
@app.route('/api/metrics', methods=['GET'])
def api_metrics():
    import random, time
    now = int(time.time())
    labels = []
    cpu = []
    mem = []
    for i in range(10):
        labels.append(now - (9 - i) * 5)
        cpu.append(round(random.uniform(10, 50), 2))
        mem.append(round(random.uniform(20, 70), 2))
    return jsonify({
        "ok": True,
        "time": datetime.utcnow().isoformat(),
        "series": {"labels": labels, "cpu": cpu, "mem": mem},
        "db": True if SessionLocal else False
    })

# --- AI suggest endpoint (uses analyze_event_ai if available, else local heuristic) ---
@app.route('/api/ai/suggest', methods=['POST'])
def api_ai_suggest():
    init_db_engine()
    body = request.get_json(force=True) or {}
    event_id = body.get("event_id") or body.get("eventId") or body.get("id")
    if not event_id:
        return jsonify(ok=False, error="missing event_id"), 400

    event_payload = None
    event_meta = None
    # Try to fetch event from DB (best-effort)
    try:
        if SessionLocal:
            with SessionLocal() as db:
                # Try fetch event row
                row = db.execute(text("SELECT message FROM events WHERE id = :id"), {"id": event_id}).fetchone()
                if row:
                    event_payload = row[0]
    except Exception as e:
        app.logger.warning(f"Failed to read event from DB: {e}")

    # Try lazy load ai_router
    ai_callable = ensure_ai_router_loaded()
    if ai_callable:
        try:
            res = ai_callable(event_id=event_id, event_payload=event_payload, event_meta=event_meta)
            # Expect res to be dict-like; if string, wrap it
            if isinstance(res, str):
                res = {"analysis": res, "suggestion": res, "provider": "ai_router"}
        except Exception as e:
            app.logger.warning(f"analyze_event_ai failed at runtime: {e}")
            res = {"analysis": "ai runtime error", "suggestion": "AI unavailable", "provider": "none"}
    else:
        # Local heuristic fallback
        summary = f"Event {event_id}: local-heuristic analysis"
        suggestion = "Check network connectivity and restart the affected node."
        res = {"analysis": summary, "suggestion": suggestion, "provider": "local-heuristic"}

    # optional persist suggestion (best-effort)
    try:
        if SessionLocal:
            with SessionLocal() as db:
                ensure_demo_tables(db)
                db.execute(text("INSERT INTO ai_suggestions (event_id, title, body) VALUES (:eid, :t, :b)"),
                           {"eid": event_id, "t": f"{res.get('provider')} suggestion", "b": res.get("suggestion")})
                db.commit()
    except Exception as e:
        app.logger.warning(f"Failed to persist AISuggestion: {e}")

    return jsonify(ok=True, **res), 200
    # ----------------- TEMP: DB migration helper (run once) -----------------
@app.route('/admin/fix_ai_table', methods=['POST', 'GET'])
def admin_fix_ai_table():
    """
    TEMP route - run once to add missing columns to ai_suggestions in Postgres.
    Protect with MIGRATE_SECRET env var. Remove this route after success.
    """
    secret = os.environ.get("MIGRATE_SECRET", "")
    q = request.args.get("secret") or request.form.get("secret") or ""
    if not secret or q != secret:
        return jsonify(ok=False, error="missing/invalid secret"), 403

    init_db_engine()
    if SessionLocal is None:
        return jsonify(ok=False, error="DB not available"), 500

    statements = [
        # add title/body/created_at if missing
        "ALTER TABLE ai_suggestions ADD COLUMN IF NOT EXISTS title TEXT;",
        "ALTER TABLE ai_suggestions ADD COLUMN IF NOT EXISTS body TEXT;",
        "ALTER TABLE ai_suggestions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        # ensure id exists (if created earlier differently), try to avoid breaking existing PK
        # no-op if column already exists
    ]
    results = []
    try:
        with SessionLocal() as db:
            for s in statements:
                try:
                    db.execute(text(s))
                    results.append({"stmt": s, "ok": True})
                except Exception as e:
                    results.append({"stmt": s, "ok": False, "error": str(e)})
            db.commit()
        return jsonify(ok=True, results=results), 200
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500
# -----------------------------------------------------------------------

# standard run for local debug (ignored by gunicorn)
if __name__ == '__main__':
    init_db_engine()
    # seed immediately for local dev if configured
    try:
        if engine is not None and str(getattr(engine, "url", "")).startswith("sqlite"):
            seed_demo_events()
    except Exception:
        app.logger.debug("initial seed attempt failed: " + traceback.format_exc())

    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)), debug=True)
