# app.py
import os
import json
import time
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from models import Base, Event, Incident, AISuggestion
from ai_router import analyze_event_ai

DATABASE_URL = os.environ.get("DATABASE_URL")
PORT = int(os.environ.get("PORT", "8080"))
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")

# DB setup
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))

# Create tables (MVP simplicity)
Base.metadata.create_all(bind=engine)

app = Flask(__name__, template_folder="templates")
app.config["SECRET_KEY"] = SECRET_KEY

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/v1/health", methods=["GET"])
def health():
    # Basic health check
    try:
        with SessionLocal() as db:
            # simple DB ping
            db.execute("SELECT 1")
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

    return jsonify(ok=True, version="1.0.0", time=datetime.utcnow().isoformat()), 200

@app.route("/v1/status", methods=["GET"])
def status():
    # Lightweight status: DB and minimal metrics
    try:
        with SessionLocal() as db:
            db.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify(ok=db_ok, db=db_ok, time=datetime.utcnow().isoformat())

@app.route("/v1/ingest/event", methods=["POST"])
def ingest_event():
    data = request.get_json(force=True)
    if not data:
        return jsonify(ok=False, error="invalid json"), 400

    tenant = data.get("tenantId", "demo")
    service = data.get("service", "nexus-demo")
    ev_type = data.get("type", "EVENT")
    payload = data.get("payload") or {}

    ev = Event(tenant_id=tenant, service=service, type=ev_type, payload=payload)
    with SessionLocal() as db:
        db.add(ev)
        db.commit()
        db.refresh(ev)

    return jsonify(ok=True, id=ev.id), 202

@app.route("/v1/ai/debug", methods=["POST"])
def ai_debug():
    body = request.get_json(force=True)
    if not body:
        return jsonify(ok=False, error="invalid json"), 400

    event_id = body.get("eventId") or body.get("id")
    if not event_id:
        return jsonify(ok=False, error="missing eventId"), 400

    # fetch event
    with SessionLocal() as db:
        ev = db.query(Event).filter_by(id=event_id).first()
        if not ev:
            return jsonify(ok=False, error="event not found"), 404

    # Run AI analysis (this returns dict with analysis + suggestion)
    analysis = analyze_event_ai(event_id=ev.id, event_payload=ev.payload, event_meta=getattr(ev, "meta_info", None))

    # store suggestion
    suggestion = AISuggestion(event_id=ev.id, analysis=analysis.get("analysis"), suggestion=analysis.get("suggestion"))
    with SessionLocal() as db:
        db.add(suggestion)
        db.commit()
        db.refresh(suggestion)

    return jsonify(ok=True, suggestion_id=suggestion.id, analysis=analysis), 200

if __name__ == "__main__":
    # local dev
    app.run(host="0.0.0.0", port=PORT, debug=False)
