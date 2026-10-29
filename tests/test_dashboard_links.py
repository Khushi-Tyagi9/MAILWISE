"""Renders the real dashboard headlessly with the API stubbed out. No network, database or LLM."""
import json
import os

import pytest
import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

DASHBOARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dashboard.py")


def _link(text, url, kind="link"):
    return {"text": text, "url": url, "domain": "ignored", "kind": kind}


LINKS = ([_link(f"Story {i}", f"https://news.example.com/{i}") for i in range(10)]
         + [_link("Unsubscribe", "https://news.example.com/unsub", "unsubscribe"),
            _link("Bad", "javascript:alert(1)"),
            _link("https://paypal.com/login", "https://evil.example.net/x"),
            _link("![pixel](https://t.example.com/p.png)", "https://img.example.com/")])

EMAIL = {"id": 7, "subject": "Weekly news", "sender": "News <n@news.example.com>", "body": "Hello",
         "urgency": "newsletter", "draft": None, "confidence": None, "draft_status": None,
         "received_at": "2026-10-28T10:00:00", "tasks": None, "links": json.dumps(LINKS)}


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


@pytest.fixture
def app(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return FakeResponse([EMAIL] if (params or {}).get("folder") == "inbox" else [])

    def no_post(*args, **kwargs):
        raise AssertionError("dashboard must not POST while rendering")

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", no_post)
    st.cache_data.clear()
    at = AppTest.from_file(DASHBOARD, default_timeout=30)
    at.run()
    assert not at.exception
    yield at
    st.cache_data.clear()


def _link_buttons(at):
    return [(el.proto.label, el.proto.url) for el in at.get("link_button") if el.proto.url != ""]


def _show_all(at):
    next(t for t in at.toggle if t.label.startswith("Show all")).set_value(True).run()
    assert not at.exception
    return at


def _story_buttons(at):
    return [b for b in _link_buttons(at) if "news.example.com/" in b[1] and "unsub" not in b[1]]


def test_reading_pane_shows_first_eight_links_then_toggle(app):
    assert len(_story_buttons(app)) == 8
    toggle = next(t for t in app.toggle if t.label.startswith("Show all"))
    assert toggle.label == "Show all 12 links"

    toggle.set_value(True).run()
    assert len(_story_buttons(app)) == 10


def test_unsafe_links_are_never_rendered_and_labels_are_escaped(app):
    buttons = _link_buttons(_show_all(app))
    assert len(buttons) == 13  # 12 regular + 1 unsubscribe; the javascript: link is dropped
    assert not any(url.startswith("javascript:") for _, url in buttons)
    assert all(url.startswith(("https://", "mailto:")) for _, url in buttons)
    # Markdown image in a label is escaped, so it can't load a remote image
    pixel = next(label for label, url in buttons if url == "https://img.example.com/")
    assert "![" not in pixel and "](" not in pixel


def test_mismatched_label_shows_real_domain_and_caption(app):
    label = next(label for label, url in _link_buttons(_show_all(app)) if url == "https://evil.example.net/x")
    assert "paypal" not in label
    assert "evil" in label
    assert any(c.value == "label does not match destination" for c in app.caption)


def test_unsubscribe_links_sit_in_collapsed_expander_with_warning(app):
    expander = next(e for e in app.expander if e.label == "Unsubscribe and preferences")
    assert expander.proto.expanded is False
    assert any("confirm to the sender" in c.value for c in expander.caption)
    assert [b.proto.url for b in expander.get("link_button")] == ["https://news.example.com/unsub"]


def test_link_keys_include_folder_email_id_and_index(app):
    keys = {el.proto.id for el in app.get("link_button")}
    assert any("link_inbox_7_0" in k for k in keys)
    assert any("link_inbox_7_10" in k for k in keys)
