import json
from app import llm
from app.classification.prompts import URGENCY_CLASSIFICATION_PROMPT
from app.db.session import SessionLocal
from app.db.models import Email
from app.classification.rules import rule_based_classify

VALID_LABELS = {"urgent", "routine", "notification", "newsletter"}

def classify_urgency(subject, body, sender=None):
    rule_result = rule_based_classify(subject, sender)
    if rule_result:
        return rule_result

    prompt = URGENCY_CLASSIFICATION_PROMPT.format(subject=subject, body=body[:1000])
    raw_output = llm.chat(prompt)
    try:
        label = str(json.loads(raw_output)["urgency"]).strip().lower()
    except (json.JSONDecodeError, KeyError, TypeError):
        return "routine"
    return label if label in VALID_LABELS else "routine"


def classify_all_pending():
    session = SessionLocal()
    try:
        emails = session.query(Email).filter(Email.urgency.is_(None)).all()
        print(f"Classifying {len(emails)} emails...")

        for email in emails:
            urgency = classify_urgency(email.subject, email.body or "", email.sender or "")
            email.urgency = urgency
            print(f"{email.subject[:50]} -> {urgency}")

        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    classify_all_pending()