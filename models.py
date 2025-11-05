# models.py
import uuid
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, DateTime, Boolean, JSON, func, Integer, Text

Base = declarative_base()

def gen_id(prefix="ev"):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

class Event(Base):
    __tablename__ = "events"
    id = Column(String, primary_key=True, default=lambda: gen_id("ev"))
    tenant_id = Column(String, index=True, nullable=False)
    service = Column(String, index=True, nullable=False)
    ts = Column(DateTime(timezone=True), server_default=func.now())
    type = Column(String, nullable=False)
    trace_id = Column(String, index=True)
    meta_info = Column(JSON)
    payload = Column(JSON)
    processed = Column(Boolean, default=False)

class Incident(Base):
    __tablename__ = "incidents"
    id = Column(String, primary_key=True, default=lambda: gen_id("inc"))
    tenant_id = Column(String, index=True, nullable=False)
    summary = Column(String)
    severity = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved = Column(Boolean, default=False)
    details = Column(JSON)

class AISuggestion(Base):
    __tablename__ = "ai_suggestions"
    id = Column(String, primary_key=True, default=lambda: gen_id("as"))
    event_id = Column(String, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    analysis = Column(Text)       # AI analysis summary
    suggestion = Column(Text)     # AI suggestion / action items
    provider = Column(String, default="openai")  # record source
