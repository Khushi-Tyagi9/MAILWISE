from app.db.session import SessionLocal
from app.db.models import Email
from app.db.models import SyncState

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
        
def get_sync_state(key):
    session = SessionLocal()
    try:
        row = session.query(SyncState).filter_by(key=key).first()
        return row.value if row else None
    finally:
        session.close()

def set_sync_state(key, value):
    session = SessionLocal()
    try:
        row = session.query(SyncState).filter_by(key=key).first()
        if row:
            row.value = value
        else:
            row = SyncState(key=key, value=value)
            session.add(row)
        session.commit()
    finally:
        session.close()