# db.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from models import Base
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./nexus_demo.db")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

def init_db():
    # create tables (simple, for demo). For prod use Alembic migrations.
    Base.metadata.create_all(bind=engine)

def get_db_session():
    db = SessionLocal()
    return db
