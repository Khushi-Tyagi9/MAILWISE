from app.auth.gmail_auth import get_gmail_service
from app.ingestion.parser import get_plain_text_body
from app.db.session import init_db
from app.db.crud import save_email

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

if __name__ == "__main__":
    init_db()  # creates the table if it doesn't exist yet
    
    service = get_gmail_service()
    messages = list_recent_messages(service, max_results=10)
    print(f"Found {len(messages)} messages\n")

    for m in messages:
        detail = get_message_detail(service, m['id'])
        subject = extract_subject(detail)
        body = get_plain_text_body(detail)
        save_email(gmail_id=m['id'], subject=subject, body=body, folder="inbox")
        print(f"Saved: {subject}")