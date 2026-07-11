from app.classification.urgency_classifier import classify_urgency

def test_urgent_email():
    result = classify_urgency("URGENT: server down", "Production is down, respond ASAP.")
    assert result == "urgent"

def test_newsletter_email():
    result = classify_urgency("Weekly Newsletter", "Top 10 AI trends this week.")
    assert result == "newsletter"

def test_notification_email():
    result = classify_urgency("Submission reminder", "Reminder! Your submission is pending. No reply needed.")
    assert result == "notification"