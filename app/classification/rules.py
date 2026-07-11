NEWSLETTER_SENDER_PATTERNS = [
    "no-reply@", "noreply@", "newsletter@", "notifications@",
    "updates@", "jobalerts-noreply@", "notify@",
]

NOTIFICATION_KEYWORDS = [
    "verify your", "verify your email", "account deletion",
    "sign in to", "review this sign in", "verify your device",
]

def rule_based_classify(subject, sender):
    subject_lower = (subject or "").lower()
    sender_lower = (sender or "").lower()

    for pattern in NOTIFICATION_KEYWORDS:
        if pattern in subject_lower:
            return "notification"

    for pattern in NEWSLETTER_SENDER_PATTERNS:
        if pattern in sender_lower:
            return "newsletter"

    return None  # not confident, fall through to LLM