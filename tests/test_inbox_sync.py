import base64
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.db.models import Email
from app.db import crud
from app.api import routes
from app.ingestion import fetch_emails
from app.ingestion.gmail_utils import internal_date_to_utc, folder_from_labels
from scripts import backfill_email_metadata as backfill_script


# ---------- fakes ----------

class _Call:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeGmail:
    """Minimal stand-in for the googleapiclient Gmail service.

    list_pages / history_pages are consumed in order, one per list() call.
    messages maps id -> full message dict returned by get().
    """

    def __init__(self, list_pages=None, history_pages=None, messages=None, history_id="999"):
        self.list_pages = list(list_pages or [])
        self.history_pages = list(history_pages or [])
        self.messages_by_id = dict(messages or {})
        self.history_id = history_id
        self.list_calls = []
        self.history_calls = []
        self.get_calls = []

    def users(self):
        return self

    def messages(self):
        return _Namespace(list=self._list, get=self._get)

    def history(self):
        return _Namespace(list=self._history_list)

    def getProfile(self, userId):
        return _Call(lambda: {"historyId": self.history_id})

    def _list(self, **kwargs):
        self.list_calls.append(kwargs)
        return _Call(lambda: self.list_pages.pop(0) if self.list_pages else {})

    def _history_list(self, **kwargs):
        self.history_calls.append(kwargs)
        return _Call(lambda: self.history_pages.pop(0) if self.history_pages else {})

    def _get(self, userId, id, format, **kwargs):
        self.get_calls.append({"id": id, "format": format, **kwargs})
        return _Call(lambda: self.messages_by_id[id])


class _Namespace:
    def __init__(self, **fns):
        self.__dict__.update(fns)


def make_message(msg_id, labels, internal_date="1700000000000", subject="Hi", sender="a@example.com"):
    return {
        "id": msg_id,
        "labelIds": labels,
        "internalDate": internal_date,
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "Subject", "value": subject}, {"name": "From", "value": sender}],
            "body": {"data": base64.urlsafe_b64encode(b"body").decode()},
        },
    }


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(crud, "SessionLocal", Session)
    monkeypatch.setattr(routes, "SessionLocal", Session)
    return Session


# ---------- date / label helpers ----------

def test_internal_date_to_utc_converts_milliseconds():
    assert internal_date_to_utc("1700000000000") == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    assert internal_date_to_utc(1700000000123).microsecond == 123000


def test_internal_date_to_utc_is_timezone_aware_utc():
    assert internal_date_to_utc("0").tzinfo == timezone.utc


@pytest.mark.parametrize("value", [None, "", "not-a-number"])
def test_internal_date_to_utc_bad_input_returns_none(value):
    assert internal_date_to_utc(value) is None


@pytest.mark.parametrize("labels, expected", [
    (["INBOX", "UNREAD"], "inbox"),
    (["SENT"], "sent"),
    (["SENT", "INBOX"], "inbox"),
    (["CATEGORY_UPDATES"], None),
    ([], None),
    (None, None),
])
def test_folder_from_labels(labels, expected):
    assert folder_from_labels(labels) == expected


# ---------- save_email ----------

def test_save_email_stores_received_at_as_naive_utc(db):
    aware = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    crud.save_email(gmail_id="g1", subject="s", body="b", folder="inbox", received_at=aware)
    row = db().query(Email).filter_by(gmail_id="g1").one()
    assert row.received_at == datetime(2024, 1, 2, 3, 4, 5)


# ---------- GET /emails ordering ----------

def test_get_emails_orders_by_received_at_desc_nulls_last_then_id_desc(db):
    s = db()
    s.add_all([
        Email(id=1, gmail_id="a", subject="old", folder="inbox", received_at=datetime(2024, 1, 1)),
        Email(id=2, gmail_id="b", subject="null-low-id", folder="inbox", received_at=None),
        Email(id=3, gmail_id="c", subject="new", folder="inbox", received_at=datetime(2024, 6, 1)),
        Email(id=4, gmail_id="d", subject="null-high-id", folder="inbox", received_at=None),
        Email(id=5, gmail_id="e", subject="tie-high-id", folder="inbox", received_at=datetime(2024, 1, 1)),
        Email(id=6, gmail_id="f", subject="sent", folder="sent", received_at=datetime(2025, 1, 1)),
    ])
    s.commit()

    result = routes.get_emails(folder="inbox")

    assert [e.id for e in result] == [3, 5, 1, 4, 2]


def test_email_out_includes_received_at(db):
    from app.api.schemas import EmailOut
    email = Email(id=1, gmail_id="a", subject="s", folder="inbox", received_at=datetime(2024, 1, 1))
    assert EmailOut.model_validate(email).received_at == datetime(2024, 1, 1)


# ---------- inbox sync label filters ----------

def test_initial_sync_lists_inbox_only_and_follows_pages(db):
    service = FakeGmail(list_pages=[
        {"messages": [{"id": f"m{i}"} for i in range(30)], "nextPageToken": "p2"},
        {"messages": [{"id": f"m{i}"} for i in range(30, 60)], "nextPageToken": "p3"},
    ])

    messages = fetch_emails.incremental_sync(service)

    assert len(messages) == 50
    assert all(call["labelIds"] == ["INBOX"] for call in service.list_calls)
    assert len(service.list_calls) == 2
    assert "pageToken" not in service.list_calls[0]
    assert service.list_calls[1]["pageToken"] == "p2"
    assert crud.get_sync_state("gmail_history_id") == "999"


def test_initial_sync_stops_when_no_next_page(db):
    service = FakeGmail(list_pages=[{"messages": [{"id": "m1"}]}])
    assert [m["id"] for m in fetch_emails.incremental_sync(service)] == ["m1"]
    assert len(service.list_calls) == 1


def test_history_sync_filters_by_inbox_label(db):
    crud.set_sync_state("gmail_history_id", "100")
    service = FakeGmail(history_pages=[{"history": []}])

    fetch_emails.incremental_sync(service)

    call = service.history_calls[0]
    assert call["labelId"] == "INBOX"
    assert call["startHistoryId"] == "100"
    assert call["historyTypes"] == ["messageAdded"]


def test_history_sync_skips_non_inbox_and_duplicate_messages(db):
    crud.set_sync_state("gmail_history_id", "100")
    service = FakeGmail(history_pages=[{"history": [
        {"messagesAdded": [{"message": {"id": "in1", "labelIds": ["INBOX", "UNREAD"]}}]},
        {"messagesAdded": [{"message": {"id": "sent1", "labelIds": ["SENT"]}}]},
        {"messagesAdded": [{"message": {"id": "nolabels"}}]},
        {"messagesAdded": [{"message": {"id": "in1", "labelIds": ["INBOX"]}}]},
    ]}])

    messages = fetch_emails.incremental_sync(service)

    assert [m["id"] for m in messages] == ["in1"]


def test_history_paging_stops_at_ten_pages(db):
    crud.set_sync_state("gmail_history_id", "100")
    pages = [{"history": [{"messagesAdded": [{"message": {"id": f"m{i}", "labelIds": ["INBOX"]}}]}],
              "nextPageToken": f"t{i + 1}"} for i in range(15)]
    service = FakeGmail(history_pages=pages)

    messages = fetch_emails.incremental_sync(service)

    assert len(service.history_calls) == 10
    assert len(messages) == 10
    assert service.history_calls[3]["pageToken"] == "t3"


def test_sync_inbox_sets_folder_and_received_at_from_message(db):
    service = FakeGmail(
        list_pages=[{"messages": [{"id": "in1"}, {"id": "gone"}]}],
        messages={
            "in1": make_message("in1", ["INBOX"], internal_date="1700000000000"),
            # Archived between list and get: must not be saved as inbox
            "gone": make_message("gone", ["CATEGORY_UPDATES"]),
        },
    )

    assert fetch_emails.sync_inbox(service) == 1

    rows = db().query(Email).all()
    assert [(r.gmail_id, r.folder) for r in rows] == [("in1", "inbox")]
    assert rows[0].received_at == datetime(2023, 11, 14, 22, 13, 20)
    assert rows[0].sender == "a@example.com"


# ---------- backfill ----------

def _seed_backfill_rows(Session):
    s = Session()
    s.add_all([
        Email(id=1, gmail_id="inbox_msg", subject="a", folder="inbox"),
        Email(id=2, gmail_id="mislabeled_sent", subject="b", folder="inbox"),
        Email(id=3, gmail_id="archived", subject="c", folder="inbox"),
        Email(id=4, gmail_id="deleted", subject="d", folder="inbox"),
        Email(id=5, gmail_id="already_done", subject="e", folder="inbox", received_at=datetime(2020, 1, 1)),
    ])
    s.commit()


GMAIL_METADATA = {
    "inbox_msg": {"labelIds": ["INBOX"], "internalDate": "1700000000000"},
    "mislabeled_sent": {"labelIds": ["SENT"], "internalDate": "1700000100000"},
    "archived": {"labelIds": ["CATEGORY_PERSONAL"], "internalDate": "1700000200000"},
    "deleted": None,
    "already_done": {"labelIds": ["SENT"], "internalDate": "1700000300000"},
}


class FakeFetch:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def __call__(self, gmail_id):
        self.calls.append(gmail_id)
        value = self.data[gmail_id]
        if isinstance(value, Exception):
            raise value
        return value


def _run_backfill(Session, fetch, **kwargs):
    sleeps = []
    summary = backfill_script.backfill(Session, fetch, sleep=sleeps.append, log=lambda *_: None, **kwargs)
    return summary, sleeps


def _rows(Session):
    return {r.gmail_id: (r.folder, r.received_at) for r in Session().query(Email).all()}


def test_backfill_updates_null_rows_and_keeps_folder_when_labels_unknown(db):
    _seed_backfill_rows(db)
    fetch = FakeFetch(GMAIL_METADATA)

    summary, sleeps = _run_backfill(db, fetch)

    rows = _rows(db)
    assert rows["inbox_msg"] == ("inbox", datetime(2023, 11, 14, 22, 13, 20))
    assert rows["mislabeled_sent"] == ("sent", datetime(2023, 11, 14, 22, 15))
    assert rows["archived"] == ("inbox", datetime(2023, 11, 14, 22, 16, 40))
    assert rows["deleted"] == ("inbox", None)
    # Default scope skips rows that already have received_at
    assert rows["already_done"] == ("inbox", datetime(2020, 1, 1))
    assert "already_done" not in fetch.calls

    assert summary["scanned"] == 4
    assert summary["updated"] == 3
    assert summary["missing"] == 1
    assert summary["folder_changes"] == {("inbox", "sent"): 1}
    assert sleeps == [0.2, 0.2, 0.2]


def test_backfill_is_safe_to_rerun(db):
    _seed_backfill_rows(db)
    _run_backfill(db, FakeFetch(GMAIL_METADATA))
    after_first = _rows(db)

    summary, _ = _run_backfill(db, FakeFetch(GMAIL_METADATA), include_all=True)
    summary, _ = _run_backfill(db, FakeFetch(GMAIL_METADATA), include_all=True)

    assert summary["updated"] == 0
    assert summary["unchanged"] == 4
    rows = _rows(db)
    for gmail_id in ("inbox_msg", "mislabeled_sent", "archived", "deleted"):
        assert rows[gmail_id] == after_first[gmail_id]


def test_backfill_all_rechecks_rows_with_received_at(db):
    _seed_backfill_rows(db)
    summary, _ = _run_backfill(db, FakeFetch(GMAIL_METADATA), include_all=True)

    assert summary["scanned"] == 5
    assert _rows(db)["already_done"] == ("sent", datetime(2023, 11, 14, 22, 18, 20))


def test_backfill_dry_run_writes_nothing_but_reports_changes(db):
    _seed_backfill_rows(db)
    before = _rows(db)
    lines = []
    fetch = FakeFetch(GMAIL_METADATA)

    summary = backfill_script.backfill(db, fetch, sleep=lambda s: None, dry_run=True, log=lines.append)

    assert _rows(db) == before
    assert len(fetch.calls) == 4
    assert summary["updated"] == 3
    assert summary["folder_changes"] == {("inbox", "sent"): 1}
    assert any("would update id=2" in l and "folder inbox -> sent" in l for l in lines)


def test_backfill_counts_errors_and_continues(db):
    _seed_backfill_rows(db)
    data = dict(GMAIL_METADATA, inbox_msg=RuntimeError("boom"))

    summary, _ = _run_backfill(db, FakeFetch(data))

    assert summary["errors"] == 1
    assert summary["updated"] == 2
    assert _rows(db)["inbox_msg"] == ("inbox", None)


def test_metadata_fetcher_uses_metadata_format_and_maps_404_to_none():
    from googleapiclient.errors import HttpError
    from types import SimpleNamespace

    class Service(FakeGmail):
        def _get(self, userId, id, format, **kwargs):
            self.get_calls.append({"id": id, "format": format})
            if id == "missing":
                def raise_404():
                    raise HttpError(SimpleNamespace(status=404, reason="Not Found"), b"")
                return _Call(raise_404)
            return _Call(lambda: {"labelIds": ["INBOX"]})

    service = Service()
    fetch = backfill_script.make_metadata_fetcher(service)

    assert fetch("present") == {"labelIds": ["INBOX"]}
    assert fetch("missing") is None
    assert {c["format"] for c in service.get_calls} == {"metadata"}


# ---------- reparse bodies ----------

def _html_message(html):
    return {"payload": {"mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(html.encode()).decode()}}}


def _nested_message(text):
    inner = {"mimeType": "text/plain", "filename": "", "headers": [],
             "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}
    alt = {"mimeType": "multipart/alternative", "filename": "", "parts": [inner], "body": {"size": 0}}
    return {"payload": {"mimeType": "multipart/mixed", "filename": "", "parts": [alt], "body": {"size": 0}}}


def _seed_reparse_rows(Session):
    s = Session()
    s.add_all([
        Email(id=1, gmail_id="broken", subject="a", folder="inbox", sender="x@example.com",
              body="invite you to the\nAgentic AI Hackathon\n, a 1-day hands-on", tasks='["t"]', draft="d"),
        Email(id=2, gmail_id="was_empty", subject="b", folder="inbox", body=""),
        Email(id=3, gmail_id="same", subject="c", folder="sent", body="already fine"),
        Email(id=4, gmail_id="would_blank", subject="d", folder="inbox", body="keep me"),
        Email(id=5, gmail_id="gone", subject="e", folder="inbox", body="old"),
    ])
    s.commit()


REPARSE_MESSAGES = {
    "broken": _html_message('<p>invite you to the <a href="u">Agentic AI Hackathon</a>, a 1-day hands-on</p>'),
    "was_empty": _nested_message("nested body"),
    "same": _html_message("<p>already fine</p>"),
    "would_blank": {"payload": {"mimeType": "text/plain", "body": {"size": 0}}},
    "gone": None,
}


def _bodies(Session):
    return {r.gmail_id: r.body for r in Session().query(Email).all()}


def test_reparse_updates_only_changed_bodies(db):
    _seed_reparse_rows(db)
    sleeps = []

    summary = backfill_script.reparse_bodies(db, FakeFetch(REPARSE_MESSAGES), sleep=sleeps.append, log=lambda *_: None)

    bodies = _bodies(db)
    assert bodies["broken"] == "invite you to the Agentic AI Hackathon, a 1-day hands-on"
    assert bodies["was_empty"] == "nested body"
    assert bodies["same"] == "already fine"
    assert bodies["would_blank"] == "keep me"  # never overwritten with an empty body
    assert bodies["gone"] == "old"
    assert summary["scanned"] == 5
    assert summary["updated"] == 2
    assert summary["empty_to_filled"] == 1
    assert summary["unchanged"] == 1
    assert summary["kept_nonempty"] == 1
    assert summary["missing"] == 1
    assert sleeps == [0.2] * 4


def test_reparse_touches_no_other_column(db):
    _seed_reparse_rows(db)
    before = db().get(Email, 1)
    snapshot = {c: getattr(before, c) for c in ("subject", "sender", "folder", "tasks", "draft", "received_at", "urgency")}

    backfill_script.reparse_bodies(db, FakeFetch(REPARSE_MESSAGES), sleep=lambda s: None, log=lambda *_: None)

    after = db().get(Email, 1)
    assert {c: getattr(after, c) for c in snapshot} == snapshot


def test_reparse_is_safe_to_rerun(db):
    _seed_reparse_rows(db)
    backfill_script.reparse_bodies(db, FakeFetch(REPARSE_MESSAGES), sleep=lambda s: None, log=lambda *_: None)
    after_first = _bodies(db)

    summary = backfill_script.reparse_bodies(db, FakeFetch(REPARSE_MESSAGES), sleep=lambda s: None, log=lambda *_: None)

    assert summary["updated"] == 0
    assert summary["unchanged"] == 3
    assert _bodies(db) == after_first


def test_reparse_dry_run_writes_nothing_and_reports_sample(db, capsys):
    _seed_reparse_rows(db)
    before = _bodies(db)
    lines = []

    summary = backfill_script.reparse_bodies(db, FakeFetch(REPARSE_MESSAGES), sleep=lambda s: None,
                                             dry_run=True, log=lines.append)

    assert _bodies(db) == before
    assert summary["updated"] == 2
    assert summary["empty_to_filled"] == 1
    assert summary["sample"][0] == 1
    assert any("would update id=1" in l for l in lines)

    backfill_script.print_reparse_summary(summary, dry_run=True)
    out = capsys.readouterr().out
    assert "Dry run, nothing written" in out
    assert "of which empty before, non-empty after:" in out
    assert "--- before ---" in out and "--- after ---" in out
    assert "Agentic AI Hackathon, a 1-day" in out


def test_reparse_sample_is_truncated(db, capsys):
    s = db()
    s.add(Email(id=1, gmail_id="long", subject="a", folder="inbox", body="x" * 500))
    s.commit()

    summary = backfill_script.reparse_bodies(db, FakeFetch({"long": _html_message("<p>" + "y" * 500 + "</p>")}),
                                             sleep=lambda s: None, dry_run=True, log=lambda *_: None)
    backfill_script.print_reparse_summary(summary, dry_run=True)

    out = capsys.readouterr().out
    assert "x" * 200 + "..." in out and "x" * 201 not in out
    assert "y" * 200 + "..." in out and "y" * 201 not in out


def test_reparse_counts_errors_and_continues(db):
    _seed_reparse_rows(db)
    data = dict(REPARSE_MESSAGES, broken=RuntimeError("boom"))

    summary = backfill_script.reparse_bodies(db, FakeFetch(data), sleep=lambda s: None, log=lambda *_: None)

    assert summary["errors"] == 1
    assert summary["updated"] == 1
    assert _bodies(db)["broken"].startswith("invite you to the\n")


def test_full_fetcher_uses_full_format_and_maps_404_to_none():
    from googleapiclient.errors import HttpError
    from types import SimpleNamespace

    class Service(FakeGmail):
        def _get(self, userId, id, format, **kwargs):
            self.get_calls.append({"id": id, "format": format})
            if id == "missing":
                def raise_404():
                    raise HttpError(SimpleNamespace(status=404, reason="Not Found"), b"")
                return _Call(raise_404)
            return _Call(lambda: {"payload": {}})

    service = Service()
    fetch = backfill_script.make_full_fetcher(service)

    assert fetch("present") == {"payload": {}}
    assert fetch("missing") is None
    assert {c["format"] for c in service.get_calls} == {"full"}


def test_reparse_rejects_all_flag():
    with pytest.raises(SystemExit):
        backfill_script.main(["--reparse-bodies", "--all"])


def test_subject_contains_requires_reparse_bodies():
    with pytest.raises(SystemExit):
        backfill_script.main(["--subject-contains", "x"])


def test_reparse_subject_filter_fetches_only_matching_rows(db):
    s = db()
    s.add_all([
        Email(id=1, gmail_id="match", subject="Festive POCKET Money is live", folder="inbox", body="old"),
        Email(id=2, gmail_id="other", subject="Weekly digest", folder="inbox", body="old"),
        Email(id=3, gmail_id="wild", subject="100% off_today", folder="inbox", body="old"),
    ])
    s.commit()
    fetch = FakeFetch({"match": _html_message("<p>new</p>"), "other": _html_message("<p>new</p>"),
                       "wild": _html_message("<p>new</p>")})

    summary = backfill_script.reparse_bodies(db, fetch, sleep=lambda s: None, log=lambda *_: None,
                                             subject_contains="pocket money")

    assert fetch.calls == ["match"]
    assert summary["scanned"] == 1
    assert _bodies(db) == {"match": "new", "other": "old", "wild": "old"}

    fetch.calls.clear()
    backfill_script.reparse_bodies(db, fetch, sleep=lambda s: None, log=lambda *_: None, subject_contains="0%")
    assert fetch.calls == ["wild"]  # % is matched literally, not as a wildcard
    fetch.calls.clear()
    backfill_script.reparse_bodies(db, fetch, sleep=lambda s: None, log=lambda *_: None, subject_contains="f_t")
    assert fetch.calls == ["wild"]  # _ is matched literally too


def _alt_message(plain, html):
    def part(mime, text):
        return {"mimeType": mime, "filename": "", "headers": [],
                "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}
    return {"payload": {"mimeType": "multipart/alternative", "filename": "", "body": {"size": 0},
                        "parts": [part("text/plain", plain), part("text/html", html)]}}


FRAGMENTED = "Festive Pocket Money\nis\nLIVE\nwith\n10,000+ internships,\nstipends up to\nand more\nApply\nnow"
FRAGMENTED_HTML = "<p>Festive Pocket Money is LIVE with 10,000+ internships, stipends up to and more</p><p>Apply now</p>"


def test_reparse_counts_body_sources_and_lists_fragmented_samples(db, capsys):
    s = db()
    rows, data = [], {}
    for i in range(1, 5):
        rows.append(Email(id=i, gmail_id=f"frag{i}", subject="s", folder="inbox", body="old"))
        data[f"frag{i}"] = _alt_message(FRAGMENTED, FRAGMENTED_HTML)
    rows += [
        Email(id=5, gmail_id="plain", subject="s", folder="inbox", body="hello"),
        Email(id=6, gmail_id="html_only", subject="s", folder="inbox", body="old"),
        Email(id=7, gmail_id="mislabelled", subject="s", folder="inbox", body="old"),
    ]
    data.update({
        "plain": _alt_message("hello", "<p>hello</p>"),
        "html_only": _html_message("<p>html</p>"),
        "mislabelled": _nested_message("<html><body><p>was html</p></body></html>"),
    })
    s.add_all(rows)
    s.commit()

    summary = backfill_script.reparse_bodies(db, FakeFetch(data), sleep=lambda s: None,
                                             dry_run=True, log=lambda *_: None)

    assert summary["source_html_fragmented_plain"] == 4
    assert summary["source_plain"] == 1  # counted even though the body is unchanged
    assert summary["source_html_no_plain"] == 1
    assert summary["source_html_mislabelled_plain"] == 1
    assert [email_id for email_id, _ in summary["fragmented_samples"]] == [1, 2, 3]
    assert summary["fragmented_samples"][0][1]["plain_lines"] == 9

    backfill_script.print_reparse_summary(summary, dry_run=True)
    out = capsys.readouterr().out
    assert "Body source chosen" in out
    assert "HTML, plain text was fragmented:" in out
    assert "Fragmented rule fired on (first 3):" in out
    assert "id=1: plain 9 lines" in out
    assert "id=4:" not in out
