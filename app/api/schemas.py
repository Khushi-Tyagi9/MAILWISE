from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class EmailOut(BaseModel):
    id: int
    subject: str
    sender: Optional[str]
    body: Optional[str]
    urgency: Optional[str]
    draft: Optional[str]
    confidence: Optional[str]
    draft_status: Optional[str]
    received_at: Optional[datetime] = None
    tasks: Optional[str] = None  # JSON-encoded list, as stored
    links: Optional[str] = None  # JSON-encoded list, as stored

    class Config:
        from_attributes = True

class DraftOut(BaseModel):
    email_id: int
    draft: Optional[str]
    confidence: Optional[float]
    status: str

class FeedbackIn(BaseModel):
    liked: bool