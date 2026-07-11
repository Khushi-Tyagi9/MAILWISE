from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from app.db.session import Base

class Email(Base):
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True)
    gmail_id = Column(String, unique=True, nullable=False)
    subject = Column(String)
    sender = Column(String, nullable=True)          # <- new line
    body = Column(Text)
    folder = Column(String)
    urgency = Column(String, nullable=True)
    tasks = Column(Text, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)
class SyncState(Base):
    __tablename__ = "sync_state"
    key = Column(String, primary_key=True)
    value = Column(String)
class RequestLog(Base):
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True)
    email_id = Column(Integer, nullable=True)
    latency_ms = Column(Integer)
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)