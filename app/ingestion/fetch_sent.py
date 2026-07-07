from app.auth.gmail_auth import get_gmail_service

def list_sent_messages(service, max_results=20):
    response = service.users().messages().list(
        userId='me',
        maxResults=max_results,
        q='in:sent'
    ).execute()
    return response.get('messages', [])

if __name__ == "__main__":
    service = get_gmail_service()
    messages = list_sent_messages(service, max_results=20)
    print(f"Found {len(messages)} sent messages")