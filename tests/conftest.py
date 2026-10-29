import os
import sys

# Set before anything imports app.config / app.llm, so the real .env is never used in tests.
os.environ["GROQ_API_KEY"] = "test-key"
os.environ["GROQ_MODEL"] = "test-model"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import pytest
from types import SimpleNamespace

from app import llm


class FakeGroq:
    """Stands in for the shared Groq client. `responses` is consumed in order;
    an Exception instance is raised, anything else is returned as the message content."""

    def __init__(self):
        self.responses = []
        self.default = "{}"
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0) if self.responses else self.default
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=item))])

    def reply(self, *items, default=None):
        self.responses = list(items)
        if default is not None:
            self.default = default


@pytest.fixture(autouse=True)
def fake_groq(monkeypatch):
    def no_network(*args, **kwargs):
        raise RuntimeError("Tests must not make real HTTP calls")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    fake = FakeGroq()
    monkeypatch.setattr(llm, "client", fake)
    monkeypatch.setattr(llm, "_sleep", lambda seconds: None)
    return fake
