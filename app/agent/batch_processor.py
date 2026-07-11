from app.db.session import SessionLocal
from app.db.models import Email
from app.classification.urgency_classifier import classify_urgency
from app.classification.task_extractor import extract_tasks
from app.retrieval.vector_store import find_similar
from app.agent.draft_generator import generate_draft
from app.agent.confidence import score_confidence, should_auto_save
import json

def process_all_pending():
    session = SessionLocal()
    try:
        emails = session.query(Email).filter(
            Email.folder == "inbox", Email.draft_status.is_(None)
        ).all()
        print(f"Processing {len(emails)} emails...")

        for email in emails:
            urgency = classify_urgency(email.subject or "", email.body or "", email.sender or "")
            email.urgency = urgency

            if urgency in ("newsletter", "notification"):
                email.draft_status = "auto_archived"
                session.commit()
                continue

            tasks = extract_tasks(email.subject or "", email.body or "")
            email.tasks = json.dumps(tasks)

            similar = find_similar(f"{email.subject}\n{email.body}", top_k=3)
            confidence = score_confidence(similar)
            draft = generate_draft(email.subject or "", email.body or "", email.sender or "")

            email.confidence = str(confidence)
            email.draft = draft
            email.draft_status = "draft_ready" if should_auto_save(confidence) else "needs_review"

            session.commit()
            print(f"{email.subject[:50]} -> {email.draft_status}")
    finally:
        session.close()


if __name__ == "__main__":
    process_all_pending()