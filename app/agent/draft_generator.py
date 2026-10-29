import json
from app import llm
from app.classification.prompts import DRAFT_REPLY_PROMPT
from app.retrieval.vector_store import find_similar

def generate_draft(subject, body, sender="unknown sender"):
    similar = find_similar(f"{subject}\n{body}", top_k=3)
    examples_text = "\n---\n".join(similar['documents'][0]) if similar['documents'] else "No past examples available."

    prompt = DRAFT_REPLY_PROMPT.format(examples=examples_text, subject=subject, body=body[:1000], sender=sender)

    raw_output = llm.chat(prompt)

    try:
        result = json.loads(raw_output)
        return result["draft"]
    except (json.JSONDecodeError, KeyError):
        return None


if __name__ == "__main__":
    draft = generate_draft(
        subject="Order return status",
        body="Hi, I returned my order last week but haven't heard back. Can you update me?",
        sender="support@kalyaretail.com"
    )
    print(draft)