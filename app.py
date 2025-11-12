# app.py - Nexus System (startup-safe, demo-friendly)
from flask import Flask, render_template, request, jsonify
from datetime import datetime
from sqlalchemy import text
from sqlalchemy import text as _text
import os
import logging
import traceback
import time
import random

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
                "id TEXT PRIMARY KEY, event_id TEXT, title TEXT, body TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
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

# --- helper: insert AI suggestion in a dialect-resilient way ---
def insert_ai_suggestion(db, event_id, title, body):
    """
    Try to insert into ai_suggestions safely.
    We try an INSERT with a generated id (string) first (Postgres that requires id),
    then fallback to insert without id (if DB has autogenerate).
    Returns (ok: bool, error: str|None)
    """
    try:
        # detect postgres vs sqlite
        is_postgres = False
        try:
            is_postgres = getattr(engine, "dialect").name in ("postgresql", "postgres")
        except Exception:
            try:
                is_postgres = str(getattr(engine, "url", "")).startswith("postgres")
            except Exception:
                is_postgres = False

        # prepare params
        # use a string id (safe for Postgres SERIAL or string PKs)
        suggestion_id = f"sugg_{int(time.time()*1000)}_{random.randint(100,999)}"
        params_with_id = {"id": suggestion_id, "eid": event_id, "t": title, "b": body}
        params_no_id = {"eid": event_id, "t": title, "b": body}

        # If Postgres, attempt insert with id first (avoid NOT NULL PK failure).
        if is_postgres:
            try:
                db.execute(text("INSERT INTO ai_suggestions (id, event_id, title, body) VALUES (:id, :eid, :t, :b)"), params_with_id)
                db.commit()
                return True, None
            except Exception as e:
                db.rollback()
                app.logger.warning(f"insert_ai_suggestion (with id) failed: {e}")
                # fallback: try without id (maybe column defaults exist)
                try:
                    db.execute(text("INSERT INTO ai_suggestions (event_id, title, body) VALUES (:eid, :t, :b)"), params_no_id)
                    db.commit()
                    return True, None
                except Exception as e2:
                    db.rollback()
                    app.logger.error(f"insert_ai_suggestion fallback failed: {e2}")
                    return False, str(e2)
        else:
            # SQLite/general: try without id (autoincrement)
            try:
                db.execute(text("INSERT INTO ai_suggestions (event_id, title, body) VALUES (:eid, :t, :b)"), params_no_id)
                db.commit()
                return True, None
            except Exception as e:
                db.rollback()
                app.logger.warning(f"insert_ai_suggestion (sqlite) failed: {e}")
                # as last resort, insert with a generated id into id column (if it's text primary key in non-sqlite)
                try:
                    db.execute(text("INSERT INTO ai_suggestions (id, event_id, title, body) VALUES (:id, :eid, :t, :b)"), params_with_id)
                    db.commit()
                    return True, None
                except Exception as e2:
                    db.rollback()
                    app.logger.error(f"insert_ai_suggestion final fallback failed: {e2}")
                    return False, str(e2)
    except Exception as e_outer:
        app.logger.exception(f"insert_ai_suggestion outer exception: {e_outer}")
        return False, str(e_outer)

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
            # add a simple ai suggestion row for one event - use helper
            ok, err = insert_ai_suggestion(db, "ev_demo_1", "Investigate DB timeout", "Check DB connections; restart DB pool if necessary.")
            if not ok:
                app.logger.warning(f"seed_demo_events: failed to insert demo suggestion: {err}")
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
            ok, err = insert_ai_suggestion(db, event_id, sim_title, sim_body)
            if not ok:
                app.logger.warning(f"api_ingest: failed to persist suggestion: {err}")
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
        suggestion = "No clear pattern from payload. Inspect logs with correlationId for RCA."
        res = {"analysis": summary, "suggestion": suggestion, "provider": "local-heuristic"}

    # optional persist suggestion (best-effort)
    try:
        if SessionLocal:
            with SessionLocal() as db:
                ensure_demo_tables(db)
                ok, err = insert_ai_suggestion(db, event_id, f"{res.get('provider')} suggestion", res.get("suggestion"))
                if not ok:
                    app.logger.warning(f"api_ai_suggest: failed to persist suggestion: {err}")
                db.commit()
    except Exception as e:
        app.logger.warning(f"Failed to persist AISuggestion: {e}")

    return jsonify(ok=True, **res), 200

# ----------------- TEMP: DB migration helper (events table) -----------------
@app.route('/admin/fix_events_table', methods=['POST'])
def admin_fix_events_table():
    """
    Temporary migration route — run once to ensure events.message column exists
    and copy data from 'msg' into 'message' when appropriate.

    Protect this route with MIGRATE_SECRET env var or use the ?secret= query param.
    """
    secret = os.environ.get("MIGRATE_SECRET", "")
    q = request.args.get("secret") or request.form.get("secret")
    if not secret or q != secret:
        return jsonify(ok=False, error="missing/invalid secret"), 401

    init_db_engine()
    if SessionLocal is None:
        return jsonify(ok=False, error="DB not available"), 500

    results = []
    try:
        with SessionLocal() as db:
            # 1) Try add the message column (SQLite/Postgres safe-ish)
            try:
                # dialect-aware alter: attempt SQLite-friendly, fallback to generic
                db.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS message TEXT"))
                results.append({"stmt": "ALTER TABLE events ADD COLUMN IF NOT EXISTS message TEXT"})
            except Exception as e_add:
                # Some dialects (older SQLite) may error on IF NOT EXISTS; ignore if column exists
                results.append({"stmt": "ALTER TABLE (add) failed, will continue", "error": str(e_add)})

            # 2) If column 'msg' exists, copy into 'message' (Postgres: DO $$ ... END $$; else best-effort)
            is_postgres = False
            try:
                is_postgres = getattr(db.bind.dialect, "name", "") == "postgresql"
            except Exception:
                is_postgres = False

            if is_postgres:
                copy_sql = """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='events' AND column_name='msg'
  ) THEN
    UPDATE events SET message = msg WHERE message IS NULL AND msg IS NOT NULL;
  END IF;
END$$;
"""
                try:
                    db.execute(text(copy_sql))
                    results.append({"stmt": "Postgres copy executed"})
                except Exception as e:
                    results.append({"stmt": "P
