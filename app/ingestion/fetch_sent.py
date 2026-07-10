from app.auth.gmail_auth import get_gmail_service
from app.ingestion.fetch_emails import get_message_detail, extract_subject
from app.ingestion.parser import get_plain_text_body
from app.db.session import init_db
from app.db.crud import save_email

def list_sent_messages(service, max_results=20):
    response = service.users().messages().list(
        userId='me',
        maxResults=max_results,
        q='in:sent'
    ).execute()
    return response.get('messages', [])

if __name__ == "__main__":
    init_db()

    service = get_gmail_service()
    messages = list_sent_messages(service, max_results=30)
    print(f"Found {len(messages)} sent messages\n")

    for m in messages:
        detail = get_message_detail(service, m['id'])
        subject = extract_subject(detail)
        body = get_plain_text_body(detail)
        save_email(gmail_id=m['id'], subject=subject, body=body, folder="sent")
        print(f"Saved: {subject}")