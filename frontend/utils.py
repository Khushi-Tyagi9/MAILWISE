"""Pure helpers for the dashboard. No Streamlit import, so these are testable offline."""
import json
import re
import urllib.parse
from datetime import datetime, timezone

FOLDERS = ("inbox", "sent")
LABEL_FILTERS = ["All", "Urgent", "Routine", "Notification", "Newsletter"]
LABEL_COLORS = {
    "urgent": "red",
    "routine": "blue",
    "newsletter": "yellow",
    "notification": "gray",
    "pending": "orange",
}
# Hex versions for the avatar circle
AVATAR_COLORS = {
    "urgent": "#ef4444",
    "routine": "#3b82f6",
    "newsletter": "#eab308",
    "notification": "#6b7280",
    "pending": "#f59e0b",
}
DEFAULT_AVATAR_COLOR = "#6366f1"

QUOTE_MARKERS = [r"\nOn .+ wrote:", r"\n>", r"\n-+ ?Original Message ?-+"]


def split_quoted(text):
    """Split a body into (main, quoted) at the earliest quote marker."""
    text = text or ""
    starts = [m.start() for m in (re.search(p, text) for p in QUOTE_MARKERS) if m]
    if not starts:
        return text, ""
    cut = min(starts)
    return text[:cut], text[cut:].lstrip("\n")


def strip_quoted(text):
    return split_quoted(text)[0]


def sender_name(sender):
    if not sender or not sender.strip():
        return "Unknown"
    sender = sender.strip()
    name = sender.split("<")[0].strip().strip('"').strip()
    if name:
        return name
    m = re.search(r"<(.+?)>", sender)
    return m.group(1) if m else sender


def avatar_initial(name):
    name = (name or "").strip()
    return name[0].upper() if name else "?"


def snippet(body, n=90):
    """First non-empty line of the cleaned body, whitespace collapsed, truncated."""
    for line in strip_quoted(body).splitlines():
        line = " ".join(line.split())
        if line:
            return line if len(line) <= n else line[: n - 1].rstrip() + "…"
    return ""


def parse_tasks(raw):
    if not raw:
        return []
    try:
        tasks = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(tasks, list):
        return []
    return [str(t) for t in tasks if str(t).strip()]


def label_key(email, folder):
    """Label for a row: the urgency for inbox mail ('pending' if unprocessed), None for sent."""
    if folder != "inbox":
        return None
    return email.get("urgency") or "pending"


def to_local(received_at, tz=None):
    """Parse a received_at value (naive means UTC) and convert it to tz, or the machine's zone."""
    if not received_at:
        return None
    if isinstance(received_at, datetime):
        dt = received_at
    else:
        try:
            dt = datetime.fromisoformat(str(received_at).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def short_date(received_at, now=None, tz=None):
    local = to_local(received_at, tz)
    if local is None:
        return ""
    now = (now or datetime.now(timezone.utc)).astimezone(local.tzinfo)
    if local.date() == now.date():
        return local.strftime("%H:%M")
    if local.year == now.year:
        return f"{local:%b} {local.day}"
    return f"{local:%b} {local.day}, {local.year}"


def full_date(received_at, tz=None):
    local = to_local(received_at, tz)
    if local is None:
        return ""
    return f"{local:%a}, {local:%b} {local.day}, {local.year}, {local:%H:%M}"


def filter_emails(emails, query="", label="All"):
    query = (query or "").strip().lower()
    out = []
    for e in emails:
        if label and label != "All" and (e.get("urgency") or "pending") != label.lower():
            continue
        if query and query not in f"{e.get('subject') or ''}\n{e.get('sender') or ''}".lower():
            continue
        out.append(e)
    return out


def label_counts(emails):
    counts = {k: 0 for k in ("urgent", "routine", "newsletter", "notification")}
    for e in emails:
        if e.get("urgency") in counts:
            counts[e["urgency"]] += 1
    return counts


def gmail_compose_link(to, subject, body):
    to_clean = re.sub(r'^.*<(.+)>$', r'\1', to or "")
    params = {"view": "cm", "fs": "1", "to": to_clean, "su": f"Re: {subject}", "body": body or ""}
    return "https://mail.google.com/mail/?" + urllib.parse.urlencode(params)


# ---------- links ----------

SAFE_LINK_SCHEMES = ("http", "https", "mailto")
LINK_LABEL_MAX = 60
LINKS_SHOWN = 8
UNSUBSCRIBE_KIND = "unsubscribe"
# Any ASCII punctuation may be backslash-escaped in Markdown; this also covers
# Streamlit's :directive[...] and :material/icon: syntax.
_MARKDOWN_SPECIAL = re.compile(r"([!-/:-@\[-`{-~])")
_BARE_DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}(?:[/?#]\S*)?$", re.IGNORECASE)


def is_safe_url(url):
    """True only for an absolute http/https URL with a host, or a mailto with an address."""
    if not isinstance(url, str) or not url or url != url.strip() or re.search(r"[\x00-\x1f\x7f\s]", url):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    scheme = parts.scheme.lower()
    if scheme == "mailto":
        return bool(parts.path)
    return scheme in SAFE_LINK_SCHEMES and bool(host)


def url_domain(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() == "mailto":
        domain = urllib.parse.unquote(parts.path).split(",")[0].rpartition("@")[2]
    else:
        domain = parts.hostname or ""
    domain = domain.strip().lower()
    return domain[4:] if domain.startswith("www.") else domain


def parse_links(raw):
    """Stored links JSON -> list of {text, url, domain, kind}, keeping only safe URLs. Bad JSON gives []."""
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    links = []
    for item in value:
        if not isinstance(item, dict) or not is_safe_url(item.get("url")):
            continue
        text = item.get("text")
        links.append({
            "text": text if isinstance(text, str) else "",
            "url": item["url"],
            "domain": url_domain(item["url"]),  # recomputed, never trusted from storage
            "kind": UNSUBSCRIBE_KIND if item.get("kind") == UNSUBSCRIBE_KIND else "link",
        })
    return links


def cut_label(text, n=LINK_LABEL_MAX):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def escape_markdown(text):
    """Makes text render literally in a Streamlit label (which supports Markdown links and images)."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text or "")


def _label_host(label):
    """The host a label claims to point at, if it looks like a URL, domain or email address."""
    label = (label or "").strip().rstrip(".,;:!?").lower()
    if not label or " " in label:
        return None
    if re.match(r"^[a-z][a-z0-9+.-]*://", label):
        try:
            host = urllib.parse.urlsplit(label).hostname
        except ValueError:
            return None
    elif label.startswith("mailto:") or re.match(r"^[^@\s]+@[^@\s]+$", label):
        host = label.rpartition("@")[2]
    elif _BARE_DOMAIN.match(label):
        host = re.split(r"[/?#]", label, maxsplit=1)[0]
    else:
        return None
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


def label_mismatch(label, url):
    """True when the label looks like a URL/domain for a different site than the link really opens."""
    claimed = _label_host(label)
    if claimed is None:
        return False
    actual = url_domain(url)
    same_site = (claimed == actual or actual.endswith("." + claimed) or claimed.endswith("." + actual))
    return not same_site


def link_button_label(link):
    """(Markdown-safe button label, mismatch). On a mismatch only the real domain is shown."""
    domain = link["domain"] or "link"
    if label_mismatch(link["text"], link["url"]):
        return escape_markdown(domain), True
    text = cut_label(link["text"]) or domain
    return f"{escape_markdown(text)} · {escape_markdown(domain)}", False


def split_links(links):
    """(regular links, unsubscribe/preferences links), each keeping its index in links for widget keys."""
    regular = [(i, link) for i, link in enumerate(links) if link["kind"] != UNSUBSCRIBE_KIND]
    unsubscribe = [(i, link) for i, link in enumerate(links) if link["kind"] == UNSUBSCRIBE_KIND]
    return regular, unsubscribe
