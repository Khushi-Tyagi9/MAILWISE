from app.auth.gmail_auth import get_gmail_service
from app.ingestion.parser import get_plain_text_body
from app.db.session import init_db
from app.db.crud import save_email
from app.db.crud import save_email, get_sync_state, set_sync_state

def list_recent_messages(service, max_results=10):
    response = service.users().messages().list(userId='me', maxResults=max_results).execute()
    return response.get('messages', [])

def get_message_detail(service, msg_id):
    return service.users().messages().get(userId='me', id=msg_id, format='full').execute()

def extract_subject(message):
    headers = message['payload']['headers']
    for header in headers:
        if header['name'] == 'Subject':
            return header['value']
    return "(no subject)"

def extract_sender(message):
    headers = message['payload']['headers']
    for header in headers:
        if header['name'] == 'From':
            return header['value']
    return "(unknown sender)"

def incremental_sync(service):
    last_history_id = get_sync_state("gmail_history_id")

    if not last_history_id:
        messages = list_recent_messages(service, max_results=10)
        profile = service.users().getProfile(userId='me').execute()
        set_sync_state("gmail_history_id", str(profile['historyId']))
        return messages

    try:
        history = service.users().history().list(
            userId='me', startHistoryId=last_history_id, historyTypes=['messageAdded']
        ).execute()

        messages = []
        for record in history.get('history', []):
            for added in record.get('messagesAdded', []):
                messages.append(added['message'])

        profile = service.users().getProfile(userId='me').execute()
        set_sync_state("gmail_history_id", str(profile['historyId']))
        return messages
    except Exception:
        # historyId too old/invalid - fall back to regular fetch
        messages = list_recent_messages(service, max_results=10)
        profile = service.users().getProfile(userId='me').execute()
        set_sync_state("gmail_history_id", str(profile['historyId']))
        return messages

if __name__ == "__main__":
    init_db()

    service = get_gmail_service()
    messages = incremental_sync(service)
    print(f"Found {len(messages)} messages\n")

    for m in messages:
        detail = get_message_detail(service, m['id'])
        subject = extract_subject(detail)
        sender = extract_sender(detail)
        body = get_plain_text_body(detail)
        save_email(gmail_id=m['id'], subject=subject, body=body, folder="inbox", sender=sender)
        print(f"Saved: {subject}")