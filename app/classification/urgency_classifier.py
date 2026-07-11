import os
import json
from groq import Groq
from dotenv import load_dotenv
from app.classification.prompts import URGENCY_CLASSIFICATION_PROMPT
from app.db.session import SessionLocal
from app.db.models import Email
from app.classification.rules import rule_based_classify

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def classify_urgency(subject, body, sender=None):
    rule_result = rule_based_classify(subject, sender)
    if rule_result:
        return rule_result

    prompt = URGENCY_CLASSIFICATION_PROMPT.format(subject=subject, body=body[:1000])
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )
    raw_output = response.choices[0].message.content
    try:
        result = json.loads(raw_output)
        return result["urgency"]
    except (json.JSONDecodeError, KeyError):
        return "routine"


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