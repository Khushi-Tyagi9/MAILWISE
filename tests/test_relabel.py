import json
import re
import sqlite3

import pytest

from eval import relabel

FORBIDDEN = ["urgency", "tasks", "draft", "confidence", "draft_status"]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "mail.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE emails (id INTEGER PRIMARY KEY, gmail_id TEXT, subject TEXT, sender TEXT, body TEXT, "
        "folder TEXT, urgency TEXT, tasks TEXT, draft TEXT, confidence TEXT, draft_status TEXT, "
        "received_at DATETIME, fetched_at DATETIME)"
    )
    rows = [
        (f"g{i}", f"Subject {i}", f"Person {i} <p{i}@x.com>",
         f"Body {i}\n\nOn Mon someone wrote:\n> QUOTEDHISTORY", "inbox",
         "SECRETURGENCY", "SECRETTASKS", "SECRETDRAFT", "SECRETCONF", "SECRETSTATUS",
         f"2026-10-{i + 1:02d} 08:00:00.000000")
        for i in range(5)
    ]
    rows.append(("sent1", "Sent one", None, "sent body", "sent", None, None, None, None, None, None))
    conn.executemany(
        "INSERT INTO emails (gmail_id, subject, sender, body, folder, urgency, tasks, draft, confidence, "
        "draft_status, received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return path


def session(db, tmp_path, keys, seed=42):
    inputs = iter(keys)
    lines = []

    def input_fn(prompt):
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError

    labels = relabel.run(
        db_path=db, labels_path=tmp_path / "labels.jsonl", skipped_path=tmp_path / "skipped.jsonl",
        seed=seed, input_fn=input_fn, out=lines.append,
    )
    return labels, "\n".join(lines)


def shown_subjects(output):
    return re.findall(r"Subject: (.+)", output)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_query_never_reads_pipeline_decisions():
    query = relabel.QUERY.lower()
    assert "*" not in query
    for column in FORBIDDEN:
        assert not re.search(rf"\b{column}\b", query), column
    assert "gmail_id, subject, sender, body, received_at" in query


def test_load_inbox_is_read_only_and_inbox_only(db, tmp_path):
    emails = relabel.load_inbox(db)
    assert {e["gmail_id"] for e in emails} == {f"g{i}" for i in range(5)}
    assert set(emails[0]) == {"gmail_id", "subject", "sender", "body", "received_at"}
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        relabel.load_inbox(missing)
    assert not missing.exists()


def test_display_hides_decisions_and_quoted_history(db, tmp_path):
    _, output = session(db, tmp_path, ["q"])
    assert "SECRET" not in output
    assert "QUOTEDHISTORY" not in output
    assert "Inbox emails: 5  labeled: 0  skipped: 0  remaining: 5" in output


def test_label_is_saved_with_expected_fields(db, tmp_path):
    labels, output = session(db, tmp_path, ["u", "q"])
    records = read_jsonl(tmp_path / "labels.jsonl")
    assert len(records) == 1
    rec = records[0]
    assert set(rec) == {"gmail_id", "subject", "sender", "body", "received_at", "true_label", "labeled_at"}
    assert rec["true_label"] == "urgent"
    assert "SECRET" not in json.dumps(rec)
    assert shown_subjects(output)[0] == rec["subject"]


def test_order_is_seeded_and_resume_skips_labeled(db, tmp_path):
    _, first = session(db, tmp_path, ["u", "r", "q"])
    order = shown_subjects(first)
    _, second = session(db, tmp_path, ["n", "q"])
    assert "Inbox emails: 5  labeled: 2  skipped: 0  remaining: 3" in second
    assert shown_subjects(second)[0] == order[2]
    assert [r["true_label"] for r in read_jsonl(tmp_path / "labels.jsonl")] == ["urgent", "routine", "notification"]

    other = tmp_path / "other"
    other.mkdir()
    _, again = session(db, other, ["u", "u", "u", "q"])
    # The same seed gives the same order in a fresh labeling file.
    assert shown_subjects(again)[:3] == order[:3]


def test_undo_in_same_session(db, tmp_path):
    # The next email is already on screen when b is pressed, so the undone one is shown third.
    _, output = session(db, tmp_path, ["u", "b", "w", "q"])
    subjects = shown_subjects(output)
    assert subjects[0] == subjects[2] != subjects[1]
    records = read_jsonl(tmp_path / "labels.jsonl")
    assert [r["true_label"] for r in records] == ["newsletter"]
    assert records[0]["subject"] == subjects[0]


def test_undo_across_sessions(db, tmp_path):
    session(db, tmp_path, ["u", "r", "q"])
    before = read_jsonl(tmp_path / "labels.jsonl")
    _, output = session(db, tmp_path, ["b", "n", "q"])
    assert f"Undid {before[1]['gmail_id']}" in output
    after = read_jsonl(tmp_path / "labels.jsonl")
    assert [(r["gmail_id"], r["true_label"]) for r in after] == [
        (before[0]["gmail_id"], "urgent"), (before[1]["gmail_id"], "notification")]


def test_skip_persists_and_can_be_undone(db, tmp_path):
    _, first = session(db, tmp_path, ["s", "q"])
    skipped_subject = shown_subjects(first)[0]
    _, second = session(db, tmp_path, ["q"])
    assert "skipped: 1  remaining: 4" in second
    assert shown_subjects(second)[0] != skipped_subject

    _, third = session(db, tmp_path, ["b", "q"])
    assert shown_subjects(third)[1] == skipped_subject
    assert read_jsonl(tmp_path / "skipped.jsonl") == []


def test_unknown_key_and_nothing_to_undo(db, tmp_path):
    labels, output = session(db, tmp_path, ["b", "x", "q"])
    assert "Nothing to undo." in output and "Unknown key." in output
    assert labels == {}


def test_progress_and_counts_shown(db, tmp_path):
    _, output = session(db, tmp_path, ["u", "w", "q"])
    assert "[1/5]  urgent=0" in output
    assert "[3/5]  urgent=1  routine=0  notification=0  newsletter=1" in output
