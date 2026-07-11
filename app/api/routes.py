from fastapi import APIRouter, HTTPException
from app.db.session import SessionLocal, init_db
from app.db.models import Email
from app.agent.orchestrator import process_email
from app.api.schemas import EmailOut, DraftOut, FeedbackIn
import json

router = APIRouter()

@router.post("/sync")
@router.post("/sync")
def sync_emails():
    from app.ingestion.fetch_emails import get_gmail_service, incremental_sync, get_message_detail, extract_subject, extract_sender
    from app.ingestion.parser import get_plain_text_body
    from app.db.crud import save_email

    init_db()
    service = get_gmail_service()
    messages = incremental_sync(service)

    count = 0
    for m in messages:
        detail = get_message_detail(service, m['id'])
        subject = extract_subject(detail)
        sender = extract_sender(detail)
        body = get_plain_text_body(detail)
        save_email(gmail_id=m['id'], subject=subject, body=body, folder="inbox", sender=sender)
        count += 1

    return {"synced": count}


@router.get("/emails", response_model=list[EmailOut])
def get_emails(folder: str = "inbox"):
    session = SessionLocal()
    try:
        emails = session.query(Email).filter(Email.folder == folder).all()
        return emails
    finally:
        session.close()


@router.get("/emails/{email_id}/draft", response_model=DraftOut)
def get_draft(email_id: int):
    session = SessionLocal()
    try:
        email = session.query(Email).filter(Email.id == email_id).first()
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")

        result = process_email(email.subject or "", email.body or "")

        return DraftOut(
            email_id=email.id,
            draft=result["draft"],
            confidence=result["confidence"],
            status=result["status"]
        )
    finally:
        session.close()


@router.post("/emails/{email_id}/feedback")
def submit_feedback(email_id: int, feedback: FeedbackIn):
    return {"email_id": email_id, "recorded": feedback.liked}