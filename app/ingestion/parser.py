import base64
from bs4 import BeautifulSoup

def _decode(data):
    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

def html_to_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    # remove script/style tags entirely - their text content isn't real content
    for tag in soup(['script', 'style']):
        tag.decompose()
    text = soup.get_text(separator='\n')
    # collapse multiple blank lines left behind after stripping tags
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
            if part['mimeType'] == 'text/plain':
                plain_text = _decode(data)
            elif part['mimeType'] == 'text/html':
                html_text = _decode(data)
    else:
        data = payload['body'].get('data')
        if data:
            if payload['mimeType'] == 'text/plain':
                plain_text = _decode(data)
            elif payload['mimeType'] == 'text/html':
                html_text = _decode(data)

    if plain_text:
        return plain_text
    if html_text:
        return html_to_text(html_text)
    return ""