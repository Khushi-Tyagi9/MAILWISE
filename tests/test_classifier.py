import json
import pytest

from app.classification.urgency_classifier import classify_urgency
from app.classification.task_extractor import extract_tasks
from app.agent import draft_generator


@pytest.mark.parametrize("label", ["urgent", "routine", "notification", "newsletter"])
def test_valid_labels_pass_through(fake_groq, label):
    fake_groq.reply(json.dumps({"urgency": label}))
    assert classify_urgency("Some subject", "Some body that no rule matches") == label


def test_label_is_normalised(fake_groq):
    fake_groq.reply(json.dumps({"urgency": " Urgent "}))
    assert classify_urgency("Some subject", "Some body") == "urgent"


def test_unknown_label_falls_back_to_routine(fake_groq):
    fake_groq.reply(json.dumps({"urgency": "spam"}))
    assert classify_urgency("Some subject", "Some body") == "routine"


@pytest.mark.parametrize("raw", ["not json", "{}", "[]", "null", '{"urgency": null}'])
def test_malformed_output_falls_back_to_routine(fake_groq, raw):
    fake_groq.reply(raw)
    assert classify_urgency("Some subject", "Some body") == "routine"


def test_rule_match_skips_the_llm(fake_groq):
    result = classify_urgency("Weekly digest", "body", sender="noreply@example.com")
    assert result in {"newsletter", "notification"}
    assert fake_groq.calls == []


def test_extract_tasks_parses_json(fake_groq):
    fake_groq.reply(json.dumps({"tasks": ["send report"]}))
    assert extract_tasks("Report", "Please send the report") == ["send report"]


def test_extract_tasks_bad_output_gives_empty_list(fake_groq):
    fake_groq.reply("nonsense")
    assert extract_tasks("Report", "body") == []


def test_generate_draft_parses_json(fake_groq, monkeypatch):
    monkeypatch.setattr(draft_generator, "find_similar", lambda *a, **k: {"documents": [["past reply"]]})
    fake_groq.reply(json.dumps({"draft": "Thanks, will do."}))
    assert draft_generator.generate_draft("Hi", "Can you help?", "a@b.com") == "Thanks, will do."
    assert "past reply" in fake_groq.calls[0]["messages"][0]["content"]


def test_generate_draft_bad_output_gives_none(fake_groq, monkeypatch):
    monkeypatch.setattr(draft_generator, "find_similar", lambda *a, **k: {"documents": []})
    fake_groq.reply("nonsense")
    assert draft_generator.generate_draft("Hi", "Can you help?") is None
