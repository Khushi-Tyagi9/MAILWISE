import base64
import re
from collections import namedtuple
from urllib.parse import urlsplit, unquote_plus
from bs4 import BeautifulSoup
from bs4.element import NavigableString, PreformattedString

_MAX_PART_DEPTH = 10

# Removed with their contents
_DROP_TAGS = {'script', 'style', 'head', 'title', 'meta', 'noscript', 'template'}
# Start and end on their own line
_BLOCK_TAGS = {
    'div', 'tr', 'li', 'table', 'ul', 'ol', 'tbody', 'thead', 'tfoot',
    'section', 'article', 'header', 'footer', 'center', 'hr', 'dl', 'dt', 'dd', 'pre',
}
# Separated from neighbours by a blank line
_PARAGRAPH_TAGS = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote'}
# Table cells sit side by side on one line
_CELL_TAGS = {'td', 'th'}

# Matched against the inline style lowercased with all whitespace removed
_HIDDEN_STYLE = re.compile(
    r'(?:^|;)(?:display:none|visibility:hidden|mso-hide:all'
    r'|(?:font-size|max-height):0(?:\.0+)?(?:px|em|rem|pt|%)?)'
    r'(?:!important)?(?:;|$)'
)
# Zero-width / invisible characters used as preheader padding
_INVISIBLE = re.compile('[­͏​-‍⁠﻿]')
# Any whitespace, including nbsp and other Unicode spaces, collapses to one space
_HTML_WHITESPACE = re.compile(r'\s+')

# A text/plain alternative counts as fragmented (auto-generated, one phrase per line)
# only when all of these hold; then the converted HTML part is used instead.
FRAGMENT_MIN_LINES = 6           # never judge short emails
FRAGMENT_LINE_RATIO = 0.5        # plain avg line length < half the converted HTML's
FRAGMENT_SHORT_LINE_CHARS = 30   # a "short" line is under this many chars...
FRAGMENT_SHORT_SHARE = 0.6       # ...and at least this share of plain lines are short and unpunctuated
HTML_MIN_LENGTH_RATIO = 0.6      # converted HTML must be at least this share of the plain text's length
_END_PUNCTUATION = ('.', '!', '?', ':', ';')

# Why select_body picked its source
REASON_PLAIN = 'plain'
REASON_FRAGMENTED = 'html_fragmented_plain'
REASON_NO_PLAIN = 'html_no_plain'
REASON_MISLABELLED = 'html_mislabelled_plain'
REASON_EMPTY = 'empty'
REASON_DESCRIPTIONS = {
    REASON_PLAIN: 'text/plain kept',
    REASON_FRAGMENTED: 'HTML, plain text was fragmented',
    REASON_NO_PLAIN: 'HTML, no usable plain text',
    REASON_MISLABELLED: 'HTML, plain part was mislabelled HTML',
    REASON_EMPTY: 'no body found',
}

# links is filled in by parse_body; select_body alone leaves it None
BodyChoice = namedtuple('BodyChoice', 'text reason stats links', defaults=(None,))

MAX_LINKS = 30
MAX_LINK_URL = 2000
LINK_UNSUBSCRIBE = 'unsubscribe'
LINK_PLAIN = 'link'
_LINK_SCHEMES = ('http', 'https', 'mailto')
_UNSUBSCRIBE = re.compile(r'unsubscribe|opt-?out|manage[\s_-]*preferences', re.IGNORECASE)
_TEXT_URL = re.compile(r'https?://[^\s<>"\'`{}|\\^\[\]]+', re.IGNORECASE)
_TRAILING_PUNCTUATION = '.,;:!?\'"'
# Browsers drop these from hrefs before parsing them
_URL_NOISE = re.compile(r'[\t\r\n]')


def _decode(data):
    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

def _looks_like_html(text):
    stripped = text.strip().lower()
    return stripped.startswith('<!doctype') or stripped.startswith('<html') or '<body' in stripped[:2000]

def _strip_invisible(text):
    return _INVISIBLE.sub('', text)

def _is_hidden(tag):
    style = tag.get('style')
    if not style:
        return False
    return bool(_HIDDEN_STYLE.search(re.sub(r'\s+', '', style.lower())))

def html_to_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    out = []
    pending = 0  # newlines owed before the next visible text

    # Iterative walk; ('break', n) entries mark the end of a block element
    stack = [soup]
    while stack:
        node = stack.pop()
        if isinstance(node, tuple):
            pending = max(pending, node[1])
            continue
        if isinstance(node, PreformattedString):  # comments, doctype, CDATA
            continue
        if isinstance(node, NavigableString):
            text = _HTML_WHITESPACE.sub(' ', _strip_invisible(str(node)))
            if not text.strip():
                if text and not pending:
                    out.append(' ')
                continue
            if pending and out:
                out.append('\n' * min(pending, 2))
            pending = 0
            out.append(text)
            continue

        name = node.name
        if name in _DROP_TAGS:
            continue
        if _is_hidden(node):
            # Keep the word break its whitespace stood for: "upGrad,<span hidden> </span>Marks"
            if out and not pending and _HTML_WHITESPACE.search(_strip_invisible(node.get_text())):
                out.append(' ')
            continue
        if name == 'br':
            pending += 1
            continue
        if name in _PARAGRAPH_TAGS:
            gap = 2
        elif name in _BLOCK_TAGS:
            gap = 1
        else:
            gap = 0
        if gap:
            pending = max(pending, gap)
            stack.append(('break', gap))
        elif name in _CELL_TAGS and not pending:
            out.append(' ')
        stack.extend(reversed(node.contents))

    lines = [re.sub(r' {2,}', ' ', line).strip() for line in ''.join(out).split('\n')]
    text = '\n'.join(lines)
    return re.sub(r'\n{3,}', '\n\n', text).strip()

def _link_url(raw):
    """Returns raw as an absolute http, https or mailto URL, or None if it is anything else."""
    url = _URL_NOISE.sub('', raw or '').strip()
    if not url or len(url) > MAX_LINK_URL:
        return None
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in _LINK_SCHEMES:
        return None
    if scheme == 'mailto':
        return url if parts.path.strip() else None
    return url if host else None

def link_domain(url):
    parts = urlsplit(url)
    if parts.scheme.lower() == 'mailto':
        address = unquote_plus(parts.path).split(',')[0].strip()
        domain = address.rpartition('@')[2]
    else:
        domain = parts.hostname or ''
    domain = domain.lower()
    return domain[4:] if domain.startswith('www.') else domain

def _link(url, label):
    domain = link_domain(url)
    label = label or domain
    unsubscribe = _UNSUBSCRIBE.search(label) or _UNSUBSCRIBE.search(unquote_plus(url))
    return {'text': label, 'url': url, 'domain': domain,
            'kind': LINK_UNSUBSCRIBE if unsubscribe else LINK_PLAIN}

def _skipped(tag):
    """Same visibility rules as html_to_text: dropped tags and hidden subtrees."""
    return tag.name in _DROP_TAGS or _is_hidden(tag)

def _visible_tags(root):
    """Yields every tag under root, in document order, that html_to_text would not skip."""
    stack = list(reversed(root.contents))
    while stack:
        node = stack.pop()
        if isinstance(node, NavigableString) or _skipped(node):
            continue
        yield node
        stack.extend(reversed(node.contents))

def _collapse(text):
    return _HTML_WHITESPACE.sub(' ', _strip_invisible(text)).strip()

def _anchor_label(anchor):
    """Visible anchor text, else the alt text of a visible image inside it, else ''."""
    texts, alts = [], []
    stack = list(reversed(anchor.contents))
    while stack:
        node = stack.pop()
        if isinstance(node, PreformattedString):
            continue
        if isinstance(node, NavigableString):
            texts.append(str(node))
            continue
        if _skipped(node):
            continue
        if node.name == 'img':
            alts.append(node.get('alt') or '')
        stack.extend(reversed(node.contents))
    label = _collapse(''.join(texts))
    if label:
        return label
    return next((alt for alt in map(_collapse, alts) if alt), '')

def _html_links(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tag in _visible_tags(soup):
        if tag.name == 'a':
            url = _link_url(tag.get('href'))
            if url:
                yield _link(url, _anchor_label(tag))

def _strip_trailing(url):
    while url:
        if url[-1] in _TRAILING_PUNCTUATION:
            url = url[:-1]
        elif url[-1] == ')' and url.count(')') > url.count('('):
            url = url[:-1]
        else:
            break
    return url

def _text_links(text):
    for match in _TEXT_URL.finditer(_strip_invisible(text)):
        url = _link_url(_strip_trailing(match.group()))
        if url:
            yield _link(url, '')

def extract_links(html_or_text, html=None):
    """Links as {text, url, domain, kind} dicts, de-duplicated by URL, in order, at most MAX_LINKS.

    html says whether the input is HTML; when None it is guessed. Never part of the body text.
    """
    if not html_or_text:
        return []
    if html is None:
        html = _looks_like_html(html_or_text) or bool(re.search(r'<a\s', html_or_text, re.IGNORECASE))
    links, seen = [], set()
    for link in (_html_links if html else _text_links)(html_or_text):
        if link['url'] in seen:
            continue
        seen.add(link['url'])
        links.append(link)
        if len(links) >= MAX_LINKS:
            break
    return links

def _is_attachment(part):
    if part.get('filename'):
        return True
    for header in part.get('headers') or []:
        if header.get('name', '').lower() == 'content-disposition':
            return header.get('value', '').strip().lower().startswith('attachment')
    return False

def _collect_text_parts(part, found, depth=0):
    """Fills found with the first text/plain and text/html body, searching nested multiparts."""
    if depth > _MAX_PART_DEPTH or _is_attachment(part):
        return
    children = part.get('parts')
    if children:
        for child in children:
            _collect_text_parts(child, found, depth + 1)
        return
    mime = (part.get('mimeType') or '').lower()
    if mime in ('text/plain', 'text/html') and mime not in found:
        data = (part.get('body') or {}).get('data')
        if data:
            found[mime] = _decode(data)

def find_text_parts(payload):
    """Returns {'text/plain': str, 'text/html': str} with whichever body parts exist."""
    found = {}
    _collect_text_parts(payload, found)
    return found

def _nonempty_lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]

def _avg_len(lines):
    return sum(len(line) for line in lines) / len(lines) if lines else 0.0

def fragment_stats(plain_text, converted_html):
    """Line statistics used to decide whether plain_text is a fragmented alternative."""
    plain_lines = _nonempty_lines(plain_text)
    short = sum(1 for line in plain_lines
                if len(line) < FRAGMENT_SHORT_LINE_CHARS and not line.endswith(_END_PUNCTUATION))
    plain_len = len(' '.join(plain_text.split()))
    html_len = len(' '.join(converted_html.split()))
    return {
        'plain_lines': len(plain_lines),
        'plain_avg': _avg_len(plain_lines),
        'html_avg': _avg_len(_nonempty_lines(converted_html)),
        'short_share': short / len(plain_lines) if plain_lines else 0.0,
        'html_len_ratio': html_len / plain_len if plain_len else 0.0,
    }

def is_fragmented(stats):
    return (stats['plain_lines'] >= FRAGMENT_MIN_LINES
            and stats['plain_avg'] < FRAGMENT_LINE_RATIO * stats['html_avg']
            and stats['short_share'] >= FRAGMENT_SHORT_SHARE
            and stats['html_len_ratio'] >= HTML_MIN_LENGTH_RATIO)

def format_fragment_stats(stats):
    return (f"plain {stats['plain_lines']} lines, avg {stats['plain_avg']:.1f} chars, "
            f"{stats['short_share']:.0%} short; HTML avg {stats['html_avg']:.1f} chars; "
            f"HTML/plain length {stats['html_len_ratio']:.2f}")

def select_body(plain_text, html_text):
    """Picks the body text from the raw text/plain and text/html parts (either may be None)."""
    # Defend against senders mislabeling HTML as text/plain
    if plain_text and _looks_like_html(plain_text):
        return BodyChoice(html_to_text(plain_text), REASON_MISLABELLED, None)
    plain = _strip_invisible(plain_text) if plain_text else ''
    if plain.strip():
        converted = html_to_text(html_text) if html_text else ''
        if not converted:
            return BodyChoice(plain, REASON_PLAIN, None)
        stats = fragment_stats(plain, converted)
        if is_fragmented(stats):
            return BodyChoice(converted, REASON_FRAGMENTED, stats)
        return BodyChoice(plain, REASON_PLAIN, stats)
    if html_text:
        return BodyChoice(html_to_text(html_text), REASON_NO_PLAIN, None)
    return BodyChoice('', REASON_EMPTY, None)

def _body_links(choice, plain_text, html_text):
    """Links from the part the body came from, or from the other part if that one has none."""
    if choice.reason == REASON_MISLABELLED:
        sources = [(plain_text, True), (html_text, True)]
    elif choice.reason == REASON_PLAIN:
        sources = [(plain_text, False), (html_text, True)]
    else:
        sources = [(html_text, True), (plain_text, None)]
    for content, is_html in sources:
        links = extract_links(content, html=is_html)
        if links:
            return links
    return []

def parse_body(message):
    found = find_text_parts(message['payload'])
    plain_text, html_text = found.get('text/plain'), found.get('text/html')
    choice = select_body(plain_text, html_text)
    try:
        links = _body_links(choice, plain_text, html_text)
    except Exception:
        # A bad link must never cost us the body
        links = []
    return choice._replace(links=links)

def get_plain_text_body(message):
    return parse_body(message).text
