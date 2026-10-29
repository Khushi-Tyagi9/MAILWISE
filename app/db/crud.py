import json
from datetime import timezone
from app.db.session import SessionLocal
from app.db.models import Email
from app.db.models import SyncState

def _to_naive_utc(dt):
    # Stored naive in UTC, matching fetched_at
    if dt is not None and dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

def dump_links(links):
    """JSON for the links column; None when there are no links."""
    return json.dumps(links) if links else None

def save_email(gmail_id, subject, body, folder, sender=None, received_at=None, links=None):
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
            sender=sender,
            received_at=_to_naive_utc(received_at),
            links=dump_links(links),
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
