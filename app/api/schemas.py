from pydantic import BaseModel
from typing import Optional, List

class EmailOut(BaseModel):
    id: int
    subject: str
    sender: Optional[str]
    body: Optional[str]
    urgency: Optional[str]
    draft: Optional[str]
    confidence: Optional[str]
    draft_status: Optional[str]

    class Config:
        from_attributes = True

class DraftOut(BaseModel):
    email_id: int
    draft: Optional[str]
    confidence: Optional[float]
    status: str

class FeedbackIn(BaseModel):
    liked: bool