from app.auth.gmail_auth import get_gmail_service
from app.ingestion.parser import parse_body
from app.ingestion.gmail_utils import internal_date_to_utc, folder_from_labels
from app.db.session import init_db
from app.db.crud import save_email, get_sync_state, set_sync_state

INITIAL_SYNC_MAX = 50
LIST_PAGE_SIZE = 50
MAX_HISTORY_PAGES = 10

def list_recent_messages(service, max_results=INITIAL_SYNC_MAX, max_pages=MAX_HISTORY_PAGES):
    messages = []
    page_token = None
    for _ in range(max_pages):
        kwargs = dict(userId='me', labelIds=['INBOX'], maxResults=min(LIST_PAGE_SIZE, max_results - len(messages)))
        if page_token:
            kwargs['pageToken'] = page_token
        response = service.users().messages().list(**kwargs).execute()
        messages.extend(response.get('messages', []))
        page_token = response.get('nextPageToken')
        if not page_token or len(messages) >= max_results:
            break
    return messages[:max_results]

def list_inbox_history(service, start_history_id, max_pages=MAX_HISTORY_PAGES):
    messages = []
    seen = set()
    page_token = None
    for _ in range(max_pages):
        kwargs = dict(userId='me', startHistoryId=start_history_id,
                      historyTypes=['messageAdded'], labelId='INBOX')
        if page_token:
            kwargs['pageToken'] = page_token
        history = service.users().history().list(**kwargs).execute()
        for record in history.get('history', []):
            for added in record.get('messagesAdded', []):
                message = added['message']
                if 'INBOX' not in message.get('labelIds', []):
                    continue
                if message['id'] in seen:
                    continue
                seen.add(message['id'])
                messages.append(message)
        page_token = history.get('nextPageToken')
        if not page_token:
            break
    return messages

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

def _save_profile_history_id(service):
    profile = service.users().getProfile(userId='me').execute()
    set_sync_state("gmail_history_id", str(profile['historyId']))

def incremental_sync(service):
    last_history_id = get_sync_state("gmail_history_id")

    if not last_history_id:
        messages = list_recent_messages(service)
        _save_profile_history_id(service)
        return messages

    try:
        messages = list_inbox_history(service, last_history_id)
        _save_profile_history_id(service)
        return messages
    except Exception:
        # historyId too old/invalid - fall back to regular fetch
        messages = list_recent_messages(service)
        _save_profile_history_id(service)
        return messages

def sync_inbox(service):
    """Fetch new inbox messages and save them. Returns the number of messages saved or already stored."""
    messages = incremental_sync(service)
    count = 0
    for m in messages:
        detail = get_message_detail(service, m['id'])
        folder = folder_from_labels(detail.get('labelIds'))
        if folder != "inbox":
            # Left the inbox between listing and fetching
            continue
        choice = parse_body(detail)
        save_email(
            gmail_id=m['id'],
            subject=extract_subject(detail),
            body=choice.text,
            folder=folder,
            sender=extract_sender(detail),
            received_at=internal_date_to_utc(detail.get('internalDate')),
            links=choice.links,
        )
        count += 1
    return count

if __name__ == "__main__":
    init_db()

    service = get_gmail_service()
    count = sync_inbox(service)
    print(f"Saved {count} inbox messages")
