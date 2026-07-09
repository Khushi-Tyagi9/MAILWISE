"""
Builds eval/labeled_set.jsonl by pulling emails from the database
and pairing them with hand-assigned labels.
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.db.models import Email

LABELS = {
    1: "newsletter",
    2: "newsletter",
    5: "routine",
    7: "routine",
    9: "newsletter",
    14: "urgent",
    16: "urgent",
    17: "newsletter",
    18: "newsletter",
    19: "routine",
    20: "newsletter",
    21: "routine",
    22: "newsletter",
    23: "newsletter",
    24: "routine",
    28: "newsletter",
    29: "newsletter",
    31: "routine",
    32: "routine",
    33: "newsletter",
    34: "newsletter",
    35: "routine",
    36: "newsletter",
    37: "newsletter",
    38: "newsletter",
    39: "newsletter",
    41: "newsletter",
    42: "newsletter",
    43: "routine",
    44: "routine",
    45: "newsletter",
    46: "routine",
    47: "routine",
    48: "urgent",
    49: "routine",
    50: "urgent",
}

def build():
    session = SessionLocal()
    try:
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "labeled_set.jsonl"
        )
        written = 0
        skipped = []

        with open(output_path, "w", encoding="utf-8") as f:
            for email_id, label in LABELS.items():
                email = session.query(Email).filter(Email.id == email_id).first()
                if not email:
                    skipped.append(email_id)
                    continue

                record = {
                    "subject": email.subject or "",
                    "body": (email.body or "")[:1000],
                    "true_urgency": label,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1

        print(f"Wrote {written} labeled examples to {output_path}")
        if skipped:
            print(f"Skipped IDs not found in DB: {skipped}")
    finally:
        session.close()


if __name__ == "__main__":
    build()