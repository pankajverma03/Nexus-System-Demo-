# models.py - Nexus System DB models (clean, explicit names)
import uuid
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, DateTime, Boolean, JSON, func, Text

Base = declarative_base()

def gen_id(prefix="ev"):
    """Generate short readable id: prefix_hex12"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=lambda: gen_id("ev"))
    tenant_id = Column(String, index=True, nullable=True)   # optional for demo
    service = Column(String, index=True, nullable=True)     # optional for demo
    ts = Column(DateTime(timezone=True), server_default=func.now())
    type = Column(String, nullable=True)
    trace_id = Column(String, index=True, nullable=True)
    meta_info = Column(JSON, nullable=True)   # NOTE: app.py expects `meta_info`
    payload = Column(JSON, nullable=True)
    processed = Column(Boolean, default=False)

    def __repr__(self):
        return f"<Event id={self.id} service={self.service} ts={self.ts}>"

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, default=lambda: gen_id("inc"))
    tenant_id = Column(String, index=True, nullable=True)
    summary = Column(String, nullable=True)
    severity = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved = Column(Boolean, default=False)
    details = Column(JSON, nullable=True)

    def __repr__(self):
        return f"<Incident id={self.id} severity={self.severity}>"

class AISuggestion(Base):
    __tablename__ = "ai_suggestions"

    id = Column(String, primary_key=True, default=lambda: gen_id("as"))
    event_id = Column(String, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    analysis = Column(Text, nullable=True)       # AI analysis summary
    suggestion = Column(Text, nullable=True)     # AI suggestion / action items
    provider = Column(String, default="openai", nullable=True)

    def __repr__(self):
        return f"<AISuggestion id={self.id} event_id={self.event_id} provider={self.provider}>"

# helper: create tables if you have an engine (useful for demo fallback)
def create_tables(engine):
    """
    Create DB tables from models. Use only for dev/demo.
    Example:
        from models import create_tables
        create_tables(engine)
    """
    Base.metadata.create_all(bind=engine)
