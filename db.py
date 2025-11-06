# db.py - Database initialization (safe, startup-friendly)
import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Logger setup
logger = logging.getLogger("db")
logger.setLevel(logging.INFO)

# SQLAlchemy Base (for models.py)
Base = declarative_base()

# Try to read DATABASE_URL from environment (Render / .env)
DATABASE_URL = os.getenv("DATABASE_URL")

# Fallback: use local SQLite in-memory (for demo or dev)
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///:memory:"
    logger.warning("DATABASE_URL not set, using in-memory SQLite engine (demo mode)")

try:
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        future=True,
    )
    SessionLocal = sessionmaker(bind=engine)
    logger.info(f"Database engine initialized successfully: {DATABASE_URL}")
except Exception as e:
    logger.error(f"Failed to initialize database engine: {e}")
    engine = None
    SessionLocal = None
