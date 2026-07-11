import json
from app.classification.urgency_classifier import classify_urgency
from app.classification.task_extractor import extract_tasks
from app.retrieval.vector_store import find_similar
from app.agent.draft_generator import generate_draft
from app.agent.confidence import score_confidence, should_auto_save
import time
from app.db.session import SessionLocal
from app.db.models import RequestLog

def process_email(subject, body, email_id=None):
    start = time.time()

    urgency = classify_urgency(subject, body)
    tasks = extract_tasks(subject, body)

    result = {
        "subject": subject,
        "urgency": urgency,
        "tasks": tasks,
        "draft": None,
        "confidence": None,
        "status": None,
    }

    if urgency in ("newsletter", "notification"):
        result["status"] = "auto_archived"
        _log_request(email_id, start, result["status"])
        return result

    similar = find_similar(f"{subject}\n{body}", top_k=3)
    confidence = score_confidence(similar)
    draft = generate_draft(subject, body)

    result["confidence"] = confidence
    result["draft"] = draft
    result["status"] = "draft_ready" if should_auto_save(confidence) else "needs_review"

    _log_request(email_id, start, result["status"])
    return result


def _log_request(email_id, start_time, status):
    latency_ms = int((time.time() - start_time) * 1000)
    session = SessionLocal()
    try:
        log = RequestLog(email_id=email_id, latency_ms=latency_ms, status=status)
        session.add(log)
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    result = process_email(
        subject="Order return status",
        body="Hi, I returned my order last week but haven't heard back. Can you update me?"
    )
    print(json.dumps(result, indent=2))