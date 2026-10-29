import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from frontend import utils

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=IST)


# ---------- quoted text ----------

def test_split_quoted_on_wrote():
    body = "Thanks, see you then.\nOn Mon, Oct 26, 2026 at 9:00 AM Bob <b@x.com> wrote:\n> earlier"
    main, quoted = utils.split_quoted(body)
    assert main == "Thanks, see you then."
    assert quoted.startswith("On Mon")


def test_split_quoted_angle_lines():
    main, quoted = utils.split_quoted("Sounds good\n> old line\n> older")
    assert main == "Sounds good"
    assert quoted == "> old line\n> older"


def test_split_quoted_original_message():
    main, quoted = utils.split_quoted("Reply\n-----Original Message-----\nFrom: someone")
    assert main == "Reply"
    assert "Original Message" in quoted


def test_split_quoted_uses_earliest_marker():
    main, _ = utils.split_quoted("A\n> q\nOn Mon Bob wrote:\nB")
    assert main == "A"


def test_split_quoted_no_marker_and_none():
    assert utils.split_quoted("plain body") == ("plain body", "")
    assert utils.split_quoted(None) == ("", "")
    assert utils.strip_quoted(None) == ""


# ---------- sender / avatar / snippet ----------

def test_sender_name_variants():
    assert utils.sender_name('"Jane Doe" <jane@x.com>') == "Jane Doe"
    assert utils.sender_name("Jane Doe <jane@x.com>") == "Jane Doe"
    assert utils.sender_name("<jane@x.com>") == "jane@x.com"
    assert utils.sender_name("jane@x.com") == "jane@x.com"
    assert utils.sender_name(None) == "Unknown"
    assert utils.sender_name("   ") == "Unknown"


def test_avatar_initial():
    assert utils.avatar_initial("jane") == "J"
    assert utils.avatar_initial("") == "?"
    assert utils.avatar_initial(None) == "?"


def test_snippet_first_line_collapsed_and_truncated():
    assert utils.snippet("\n\n  Hello   there \nsecond line") == "Hello there"
    long = "word " * 50
    s = utils.snippet(long, n=20)
    assert len(s) <= 20 and s.endswith("…")
    assert utils.snippet("Hi\n> quoted") == "Hi"
    assert utils.snippet(None) == ""


# ---------- tasks ----------

def test_parse_tasks():
    assert utils.parse_tasks('["Reply to Bob", "Book room"]') == ["Reply to Bob", "Book room"]
    assert utils.parse_tasks("[]") == []
    assert utils.parse_tasks(None) == []
    assert utils.parse_tasks("not json") == []
    assert utils.parse_tasks('{"tasks": ["x"]}') == []


# ---------- dates ----------

def test_to_local_treats_naive_as_utc():
    local = utils.to_local("2026-10-28T08:05:00", tz=IST)
    assert local.hour == 13 and local.minute == 35
    assert local.utcoffset() == timedelta(hours=5, minutes=30)


def test_to_local_accepts_aware_and_datetime():
    assert utils.to_local("2026-10-28T08:05:00Z", tz=IST).hour == 13
    assert utils.to_local(datetime(2026, 10, 28, 8, 5), tz=IST).hour == 13
    assert utils.to_local(None) is None
    assert utils.to_local("garbage") is None


def test_to_local_default_is_machine_zone():
    local = utils.to_local("2026-10-28T08:05:00")
    assert local.tzinfo is not None


def test_short_date_today_shows_time():
    assert utils.short_date("2026-10-28T05:00:00", now=NOW, tz=IST) == "10:30"


def test_short_date_utc_rollover_counts_as_local_today():
    # 20:00 UTC on the 27th is 01:30 on the 28th in IST
    assert utils.short_date("2026-10-27T20:00:00", now=NOW, tz=IST) == "01:30"


def test_short_date_older_same_year():
    assert utils.short_date("2026-10-03T05:00:00", now=NOW, tz=IST) == "Oct 3"


def test_short_date_other_year():
    assert utils.short_date("2024-10-03T05:00:00", now=NOW, tz=IST) == "Oct 3, 2024"


def test_short_date_missing():
    assert utils.short_date(None, now=NOW, tz=IST) == ""


def test_full_date():
    assert utils.full_date("2026-10-28T08:05:00", tz=IST) == "Wed, Oct 28, 2026, 13:35"
    assert utils.full_date(None) == ""


# ---------- filtering / counts ----------

EMAILS = [
    {"id": 1, "subject": "Invoice due", "sender": "Billing <b@x.com>", "urgency": "urgent"},
    {"id": 2, "subject": "Weekly digest", "sender": "News <n@x.com>", "urgency": "newsletter"},
    {"id": 3, "subject": "Lunch?", "sender": "Sam <sam@x.com>", "urgency": "routine"},
    {"id": 4, "subject": "New login", "sender": None, "urgency": None},
]


def test_filter_emails_search_subject_and_sender():
    assert [e["id"] for e in utils.filter_emails(EMAILS, "invoice")] == [1]
    assert [e["id"] for e in utils.filter_emails(EMAILS, "SAM@")] == [3]
    assert len(utils.filter_emails(EMAILS, "")) == 4


def test_filter_emails_label():
    assert [e["id"] for e in utils.filter_emails(EMAILS, label="Newsletter")] == [2]
    assert [e["id"] for e in utils.filter_emails(EMAILS, "digest", "Urgent")] == []
    assert len(utils.filter_emails(EMAILS, label="All")) == 4


def test_label_counts():
    assert utils.label_counts(EMAILS) == {"urgent": 1, "routine": 1, "newsletter": 1, "notification": 0}


def test_label_key_inbox_only():
    assert utils.label_key(EMAILS[0], "inbox") == "urgent"
    assert utils.label_key(EMAILS[3], "inbox") == "pending"
    assert utils.label_key(EMAILS[0], "sent") is None


# ---------- compose link ----------

def test_gmail_compose_link():
    url = utils.gmail_compose_link('"Jane" <jane@x.com>', "Hello", "Draft body")
    parsed = urlparse(url)
    assert url.startswith("https://mail.google.com/mail/?")
    q = parse_qs(parsed.query)
    assert q["view"] == ["cm"]
    assert q["to"] == ["jane@x.com"]
    assert q["su"] == ["Re: Hello"]
    assert q["body"] == ["Draft body"]


# ---------- links ----------

@pytest.mark.parametrize("url, safe", [
    ("https://internshala.com/a", True),
    ("http://x.com", True),
    ("HTTPS://X.COM/a", True),
    ("mailto:a@b.com", True),
    ("javascript:alert(1)", False),
    ("JAVASCRIPT:alert(1)", False),
    ("data:text/html,hi", False),
    ("tel:+911234", False),
    ("/relative", False),
    ("//cdn.x.com/a", False),
    ("https://", False),
    ("mailto:", False),
    (" https://x.com", False),
    ("https://x.com/a b", False),
    ("https://x.com/\nb", False),
    ("ftp://x.com", False),
    ("", False),
    (None, False),
    (42, False),
])
def test_is_safe_url(url, safe):
    assert utils.is_safe_url(url) is safe


def test_parse_links_keeps_only_safe_well_formed_entries():
    raw = json.dumps([
        {"text": "Apply", "url": "https://www.internshala.com/a", "domain": "evil.com", "kind": "link"},
        {"text": "Bad", "url": "javascript:alert(1)", "domain": "x", "kind": "link"},
        {"text": "No url"},
        "just a string",
        {"text": 5, "url": "mailto:hi@Example.com", "kind": "unsubscribe"},
        {"text": "Weird kind", "url": "https://x.com", "kind": "<script>"},
    ])
    assert utils.parse_links(raw) == [
        {"text": "Apply", "url": "https://www.internshala.com/a", "domain": "internshala.com", "kind": "link"},
        {"text": "", "url": "mailto:hi@Example.com", "domain": "example.com", "kind": "unsubscribe"},
        {"text": "Weird kind", "url": "https://x.com", "domain": "x.com", "kind": "link"},
    ]


@pytest.mark.parametrize("raw", [None, "", "not json", "{}", '"string"', "42", "[1, 2]"])
def test_parse_links_bad_input_gives_empty_list(raw):
    assert utils.parse_links(raw) == []


def test_cut_label():
    assert utils.cut_label("Apply   Now\n") == "Apply Now"
    assert utils.cut_label("x" * 60) == "x" * 60
    cut = utils.cut_label("word " * 20)
    assert len(cut) <= 60 and cut.endswith("…")
    assert utils.cut_label(None) == ""


def test_escape_markdown_neutralises_links_images_and_directives():
    escaped = utils.escape_markdown("![x](https://t.co/p.png) [a](javascript:1) **b** :red[c] :material/home:")
    for raw in ("![", "](", "**", ":red[", ":material/"):
        assert raw not in escaped
    assert escaped.replace("\\", "") == "![x](https://t.co/p.png) [a](javascript:1) **b** :red[c] :material/home:"


def _link(text, url, kind="link"):
    return {"text": text, "url": url, "domain": utils.url_domain(url), "kind": kind}


def test_link_button_label_shows_label_and_domain():
    label, mismatch = utils.link_button_label(_link("Apply Now", "https://internshala.com/a"))
    assert (label, mismatch) == ("Apply Now · internshala\\.com", False)


def test_link_button_label_cuts_long_labels_and_falls_back_to_domain():
    label, _ = utils.link_button_label(_link("a" * 100, "https://x.com"))
    assert label.startswith("a" * 59 + "…")
    assert utils.link_button_label(_link("", "https://x.com"))[0] == "x\\.com · x\\.com"


@pytest.mark.parametrize("text, url, mismatch", [
    ("https://paypal.com/login", "https://evil.example.net/x", True),
    ("www.paypal.com", "https://paypal.com.evil.io/", True),
    ("paypal.com", "https://evil.io/paypal.com", True),
    ("support@bank.com", "mailto:help@phish.io", True),
    ("https://example.com/a", "https://www.example.com/b", False),
    ("example.com", "https://news.example.com/a", False),
    ("news.example.com", "https://example.com", False),
    ("https://ci.example.com/run/7.", "https://ci.example.com/run/7", False),
    ("Apply Now", "https://elsewhere.com", False),
    ("Read more at our site", "https://elsewhere.com", False),
    ("", "https://elsewhere.com", False),
])
def test_label_mismatch(text, url, mismatch):
    assert utils.label_mismatch(text, url) is mismatch


def test_link_button_label_on_mismatch_shows_only_real_domain():
    label, mismatch = utils.link_button_label(_link("https://paypal.com", "https://evil.example.net/x"))
    assert mismatch is True
    assert label == "evil\\.example\\.net"
    assert "paypal" not in label


def test_split_links_keeps_original_indexes():
    links = [_link("a", "https://a.com"), _link("Unsubscribe", "https://a.com/u", "unsubscribe"),
             _link("b", "https://b.com")]
    regular, unsubscribe = utils.split_links(links)
    assert [i for i, _ in regular] == [0, 2]
    assert [i for i, _ in unsubscribe] == [1]
