import base64
from bs4 import BeautifulSoup

def _decode(data):
    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

def _looks_like_html(text):
    stripped = text.strip().lower()
    return stripped.startswith('<!doctype') or stripped.startswith('<html') or '<body' in stripped[:2000]

def html_to_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style']):
        tag.decompose()
    text = soup.get_text(separator='\n')
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return '\n'.join(lines)

def get_plain_text_body(message):
    payload = message['payload']
    plain_text = None
    html_text = None

    if 'parts' in payload:
        for part in payload['parts']:
            data = part['body'].get('data')
            if not data:
                continue
            decoded = _decode(data)
            if part['mimeType'] == 'text/plain':
                plain_text = decoded
            elif part['mimeType'] == 'text/html':
                html_text = decoded
    else:
        data = payload['body'].get('data')
        if data:
            decoded = _decode(data)
            if payload['mimeType'] == 'text/plain':
                plain_text = decoded
            elif payload['mimeType'] == 'text/html':
                html_text = decoded

    # Defend against senders mislabeling HTML as text/plain
    if plain_text and _looks_like_html(plain_text):
        return html_to_text(plain_text)
    if plain_text:
        return plain_text
    if html_text:
        return html_to_text(html_text)
    return ""