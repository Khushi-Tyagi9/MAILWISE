import os
import json
from groq import Groq
from dotenv import load_dotenv
from app.classification.prompts import TASK_EXTRACTION_PROMPT

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def extract_tasks(subject, body):
    prompt = TASK_EXTRACTION_PROMPT.format(subject=subject, body=body[:1000])

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    raw_output = response.choices[0].message.content

    try:
        result = json.loads(raw_output)
        return result["tasks"]
    except (json.JSONDecodeError, KeyError):
        return []

import json
from app.db.session import SessionLocal
from app.db.models import Email

def extract_all_pending_tasks():
    session = SessionLocal()
    try:
        emails = session.query(Email).filter(Email.tasks.is_(None)).all()
        print(f"Extracting tasks for {len(emails)} emails...")

        for email in emails:
            tasks = extract_tasks(email.subject, email.body or "")
            email.tasks = json.dumps(tasks)
            if tasks:
                print(f"{email.subject[:50]} -> {tasks}")

        session.commit()
    finally:
        session.close()
        
if __name__ == "__main__":
    extract_all_pending_tasks()