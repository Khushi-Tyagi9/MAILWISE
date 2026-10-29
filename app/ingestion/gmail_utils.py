from datetime import datetime, timezone


def internal_date_to_utc(internal_date):
    """Gmail internalDate (ms since epoch, usually a string) -> timezone-aware UTC datetime, or None."""
    if internal_date is None or internal_date == "":
        return None
    try:
        return datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def folder_from_labels(label_ids):
    """'inbox' if INBOX is present, 'sent' if SENT is present without INBOX, otherwise None."""
    labels = set(label_ids or [])
    if "INBOX" in labels:
        return "inbox"
    if "SENT" in labels:
        return "sent"
    return None
