from app.db.session import SessionLocal
from app.db.models import Email

def save_email(gmail_id, subject, body, folder, sender=None):
    session = SessionLocal()
    try:
        existing = session.query(Email).filter_by(gmail_id=gmail_id).first()
        if existing:
            return existing

        email = Email(
            gmail_id=gmail_id,
            subject=subject,
            body=body,
            folder=folder,
            sender=sender
        )
        session.add(email)
        session.commit()
        return email
    finally:
        session.close()