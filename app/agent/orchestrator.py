import json
from app.classification.urgency_classifier import classify_urgency
from app.classification.task_extractor import extract_tasks
from app.retrieval.vector_store import find_similar
from app.agent.draft_generator import generate_draft
from app.agent.confidence import score_confidence, should_auto_save

def process_email(subject, body):
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

    if urgency == "newsletter":
        result["status"] = "auto_archived"
        return result

    similar = find_similar(f"{subject}\n{body}", top_k=3)
    confidence = score_confidence(similar)
    draft = generate_draft(subject, body)

    result["confidence"] = confidence
    result["draft"] = draft

    if should_auto_save(confidence):
        result["status"] = "draft_ready"
    else:
        result["status"] = "needs_review"

    return result


if __name__ == "__main__":
    result = process_email(
        subject="Order return status",
        body="Hi, I returned my order last week but haven't heard back. Can you update me?"
    )
    print(json.dumps(result, indent=2))