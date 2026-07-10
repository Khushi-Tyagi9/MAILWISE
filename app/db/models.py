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