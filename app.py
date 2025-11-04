import os
import json
from flask import Flask, request, jsonify
from sqlalchemy import create_engine, Column, String, Integer, JSON, DateTime, Boolean, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
import uuid
import datetime
import logging

# Optional OpenAI import (sirf tab use hoga jab OPENAI_API_KEY ho)
try:
    import openai
except Exception:
    openai = None

# --- Configuration (Environment Variables) ---
# DATABASE_URL: Railway/Cloud se aayega; local demo ke liye SQLite fallback.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./debug_connector_demo.db")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", None)
PORT = int(os.getenv("PORT", 5000))

# OpenAI SDK setup
if OPENAI_API_KEY and openai:
    openai.api_key = OPENAI_API_KEY

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debug-connector")

# --- Database Setup (SQLAlchemy) ---
Base = declarative_base()
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

def gen_id(prefix='ev'):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

class Event(Base):
    # Events table: logs, errors, metrics yahan store honge
    __tablename__ = 'events'
    id = Column(String, primary_key=True, default=lambda: gen_id('ev'))
    tenant_id = Column(String, index=True, nullable=False)
    service = Column(String, index=True, nullable=False)
    ts = Column(DateTime(timezone=True), server_default=func.now())
    type = Column(String, nullable=False)
    trace_id = Column(String, index=True)
    metadata = Column(JSON)
    payload = Column(JSON)
    processed = Column(Boolean, default=False)

# Tables create karo (demo ke liye auto create, production mein Alembic use hota hai)
def init_db():
    Base.metadata.create_all(bind=engine)

# --- Utility Functions ---
REDACT_FIELDS = ['email','card','token','account_id','ssn']

def redact_payload(obj, fields=REDACT_FIELDS):
    # PII (Personal Identifiable Information) ko mask karta hai
    try:
        s = json.dumps(obj)
    except Exception:
        return obj
    for f in fields:
        s = s.replace(f, '***')
    try:
        return json.loads(s)
    except Exception:
        return obj

def validate_event(obj):
    return isinstance(obj, dict) and 'tenantId' in obj and 'service' in obj

# --- AI Router (Failover Logic) ---
def call_openai_chat(prompt):
    # LLM (Large Language Model) call karta hai
    if not openai:
        raise RuntimeError("openai package not installed")
    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini", # Cost saving ke liye mini model use kiya hai
        messages=[{"role":"system","content":"You are an SRE assistant. Provide only the suggested fix and hypothesis."},
                  {"role":"user","content":prompt}],
        max_tokens=400,
        temperature=0.0
    )
    return resp.choices[0].message.content

def local_heuristic_suggestion(event):
    # Agar AI key na ho to yeh simple, rule-based suggestion deta hai (Fallback)
    payload_msg = (event.get('payload') or {}).get('message','').lower()
    if 'nullpointer' in payload_msg:
        return ("Hypothesis: Null reference (NPE).", "Fix: Add null-check before use.","Example: if (obj == null) { handle }")
    if 'timeout' in payload_msg:
        return ("Hypothesis: Downstream service timeout.", "Fix: Increase timeout value or check network connectivity.","Example: requests.get(url, timeout=10)")
    if 'outofmemory' in payload_msg or 'oom' in payload_msg:
        return ("Hypothesis: Out of memory.", "Fix: Increase memory allocation or profile for memory leaks.","Example: profile heap and GC.")
    return ("No quick heuristic match.", "Fix: Collect diagnostics bundle and perform manual review.","")

def get_ai_suggestion(event, trace_frames=None):
    prompt = f"Event: {json.dumps(event, default=str)}\nTrace frames: {trace_frames}"
    # 1. Try OpenAI
    if OPENAI_API_KEY and openai:
        try:
            text = call_openai_chat(prompt)
            return {"source":"openai","text": text}
        except Exception as e:
            logger.warning("OpenAI call failed, falling back to heuristic: %s", str(e))
            # 2. Fallback to local heuristics
    # 3. Direct Fallback
    hypo, steps, snippet = local_heuristic_suggestion(event)
    return {"source":"heuristic","text": f"Hypothesis: {hypo}\n\nSteps:\n{steps}\n\nSnippet:\n{snippet}"}

# --- Flask App Routes ---
app = Flask(__name__)
init_db() # DB tables banane ke liye

@app.route('/v1/ingest/event', methods=['POST'])
def ingest_event():
    # Events collect karta hai aur DB mein save karta hai
    body = request.get_json(force=True, silent=True)
    if not body or not validate_event(body):
        return jsonify({"ok":False,"error":"invalid event - tenantId & service required"}), 400
    safe = redact_payload(body)
    db = SessionLocal()
    try:
        ev = Event(tenant_id=safe.get('tenantId'), service=safe.get('service'), type=safe.get('type','ERROR'),
            trace_id=safe.get('traceId'), metadata=safe.get('metadata'), payload=safe.get('payload'))
        db.add(ev)
        db.commit()
        db.refresh(ev)
        return jsonify({"ok":True,"id":ev.id}), 202
    except Exception as e:
        logger.exception("db write error: %s", str(e))
        db.rollback()
        return jsonify({"ok":False,"error":"internal"}), 500
    finally:
        db.close()

@app.route('/v1/ai/debug', methods=['POST'])
def ai_debug():
    # AI se debug suggestion maangta hai
    data = request.get_json(force=True, silent=True) or {}
    event_payload = None
    if data.get('eventId'): # Agar event ID se search karna ho
        db = SessionLocal()
        ev = db.query(Event).filter(Event.id==data['eventId']).first()
        db.close()
        if not ev: return jsonify({"ok":False,"error":"event not found"}), 404
        event_payload = {"id": ev.id, "tenantId": ev.tenant_id, "service": ev.service, "metadata": ev.metadata, "payload": ev.payload}
    elif data.get('event'): # Ya agar poora event JSON mein diya ho
        event_payload = data.get('event')
    else: return jsonify({"ok":False,"error":"event or eventId required"}), 400

    suggestion = get_ai_suggestion(event_payload, data.get('traceFrames'))
    return jsonify({"ok":True,"suggestion": suggestion}), 200

@app.route('/v1/health', methods=['GET'])
def health():
    # Health check
    return jsonify({"ok":True, "version":"0.1.0", "uptimeSec": int((datetime.datetime.utcnow()-datetime.datetime(1970,1,1)).total_seconds())})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
