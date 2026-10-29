import base64
import json

import pytest
from sqlalchemy import create_engine, text

from app.db import crud, session as db_session
from app.db.models import Email
from app.db.session import Base, ensure_schema
from app.api.schemas import EmailOut
from app.ingestion import fetch_emails
from scripts import backfill_email_metadata as backfill_script
from tests.test_inbox_sync import FakeFetch, FakeGmail, db  # noqa: F401  (db is a fixture)


def _html_message(html, plain=None):
    def part(mime, content):
        return {"mimeType": mime, "filename": "", "headers": [],
                "body": {"data": base64.urlsafe_b64encode(content.encode()).decode()}}
    parts = ([part("text/plain", plain)] if plain is not None else []) + [part("text/html", html)]
    return {"payload": {"mimeType": "multipart/alternative", "filename": "", "headers": [],
                        "body": {"size": 0}, "parts": parts}}


def _columns(engine):
    with engine.connect() as conn:
        return [row[1] for row in conn.execute(text("PRAGMA table_info(emails)"))]


def _links(Session, gmail_id):
    raw = Session().query(Email).filter_by(gmail_id=gmail_id).one().links
    return json.loads(raw) if raw else None


# ---------- ensure_schema ----------

@pytest.fixture
def temp_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    yield engine
    engine.dispose()


def test_ensure_schema_adds_missing_links_column_once(temp_engine):
    with temp_engine.begin() as conn:
        conn.execute(text("CREATE TABLE emails (id INTEGER PRIMARY KEY, gmail_id VARCHAR, body TEXT)"))
        conn.execute(text("INSERT INTO emails (id, gmail_id, body) VALUES (1, 'g1', 'kept body')"))

    ensure_schema(temp_engine)
    ensure_schema(temp_engine)

    assert _columns(temp_engine) == ["id", "gmail_id", "body", "links"]
    with temp_engine.connect() as conn:
        assert conn.execute(text("SELECT id, gmail_id, body, links FROM emails")).all() == [(1, "g1", "kept body", None)]


def test_ensure_schema_leaves_current_table_alone(temp_engine):
    Base.metadata.create_all(bind=temp_engine)
    before = _columns(temp_engine)
    assert "links" in before

    ensure_schema(temp_engine)
    ensure_schema(temp_engine)

    assert _columns(temp_engine) == before


def test_ensure_schema_without_table_creates_nothing(temp_engine):
    ensure_schema(temp_engine)
    with temp_engine.connect() as conn:
        assert conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all() == []


def test_init_db_upgrades_old_table(temp_engine, monkeypatch):
    with temp_engine.begin() as conn:
        conn.execute(text("CREATE TABLE emails (id INTEGER PRIMARY KEY, gmail_id VARCHAR NOT NULL UNIQUE)"))
    monkeypatch.setattr(db_session, "engine", temp_engine)

    db_session.init_db()

    assert "links" in _columns(temp_engine)


def test_backfill_main_checks_schema_only_after_argument_checks(monkeypatch):
    from app.auth import gmail_auth
    calls = []
    monkeypatch.setattr(db_session, "ensure_schema", lambda *a: calls.append("ensure_schema"))

    with pytest.raises(SystemExit):
        backfill_script.main(["--reparse-bodies", "--all"])
    assert calls == []

    def no_gmail():
        calls.append("gmail")
        raise RuntimeError("stop before Gmail")

    monkeypatch.setattr(gmail_auth, "get_gmail_service", no_gmail)
    with pytest.raises(RuntimeError, match="stop before Gmail"):
        backfill_script.main(["--reparse-bodies", "--dry-run"])
    assert calls == ["ensure_schema", "gmail"]


# ---------- save path ----------

LINKS = [{"text": "Apply Now", "url": "https://internshala.com/a", "domain": "internshala.com", "kind": "link"}]


def test_save_email_stores_links_and_reads_them_back(db):
    crud.save_email(gmail_id="g1", subject="s", body="b", folder="inbox", links=LINKS)
    crud.save_email(gmail_id="g2", subject="s", body="b", folder="inbox", links=[])
    crud.save_email(gmail_id="g3", subject="s", body="b", folder="inbox")

    assert _links(db, "g1") == LINKS
    assert _links(db, "g2") is None
    assert _links(db, "g3") is None
    row = db().query(Email).filter_by(gmail_id="g1").one()
    assert json.loads(EmailOut.model_validate(row).links) == LINKS


def test_sync_inbox_stores_body_and_links_from_one_parse(db):
    html = '<p>Apply via <a href="https://internshala.com/a">Apply Now</a></p>'
    message = dict(_html_message(html), id="in1", labelIds=["INBOX"], internalDate="1700000000000")
    message["payload"]["headers"] = [{"name": "Subject", "value": "Hi"}, {"name": "From", "value": "a@x.com"}]
    service = FakeGmail(list_pages=[{"messages": [{"id": "in1"}]}], messages={"in1": message})

    assert fetch_emails.sync_inbox(service) == 1

    row = db().query(Email).one()
    assert row.body == "Apply via Apply Now"
    assert "internshala.com" not in row.body
    assert json.loads(row.links) == LINKS


# ---------- backfill: --reparse-bodies with links ----------

NEWSLETTER = ('<p>Big sale this week at https://shop.example.com/sale.</p>'
              '<p><a href="https://shop.example.com/sale?utm=1">Shop now</a> '
              '<a href="https://shop.example.com/unsubscribe">Unsubscribe</a></p>')
NEWSLETTER_BODY = "Big sale this week at https://shop.example.com/sale.\n\nShop now Unsubscribe"
OLD_LINK = [{"text": "Old", "url": "https://old.example.com/x", "domain": "old.example.com", "kind": "link"}]


def _seed(Session):
    s = Session()
    s.add_all([
        # body already right, links missing: changes only because of links
        Email(id=1, gmail_id="links_only", subject="a", folder="inbox", body=NEWSLETTER_BODY),
        # new parse finds no links: stored links must survive
        Email(id=2, gmail_id="keep_links", subject="b", folder="inbox", body="plain words",
              links=json.dumps(OLD_LINK)),
        # empty-body guard blocks the body, but links are still filled in
        Email(id=3, gmail_id="blank_body", subject="c", folder="inbox", body="stored body"),
        # nothing to do
        Email(id=4, gmail_id="same", subject="d", folder="inbox", body="Hello"),
    ])
    s.commit()


MESSAGES = {
    "links_only": _html_message(NEWSLETTER),
    "keep_links": _html_message("<p>plain words</p>"),
    "blank_body": _html_message('<a href="https://img.example.com/x"><img alt=""></a>'),
    "same": _html_message("<p>Hello</p>"),
}


def _run(Session, **kwargs):
    return backfill_script.reparse_bodies(Session, FakeFetch(MESSAGES), sleep=lambda s: None,
                                          log=kwargs.pop("log", lambda *_: None), **kwargs)


def test_reparse_updates_links_and_counts_link_only_changes(db):
    _seed(db)

    summary = _run(db)

    rows = {r.gmail_id: r for r in db().query(Email).all()}
    assert rows["links_only"].body == NEWSLETTER_BODY
    assert [l["url"] for l in json.loads(rows["links_only"].links)] == [
        "https://shop.example.com/sale?utm=1", "https://shop.example.com/unsubscribe"]
    assert json.loads(rows["keep_links"].links) == OLD_LINK
    assert rows["blank_body"].body == "stored body"
    assert json.loads(rows["blank_body"].links)[0]["url"] == "https://img.example.com/x"
    assert summary["updated"] == 2
    assert summary["body_changed"] == 0
    assert summary["links_changed"] == 2
    assert summary["gained_links"] == 2
    assert summary["links_total"] == 3
    assert summary["kept_links"] == 1
    assert summary["kept_nonempty"] == 1
    assert summary["unchanged"] == 1


def test_reparse_with_links_is_safe_to_rerun(db):
    _seed(db)
    _run(db)
    before = {r.gmail_id: (r.body, r.links) for r in db().query(Email).all()}

    summary = _run(db)

    assert summary["updated"] == 0
    assert {r.gmail_id: (r.body, r.links) for r in db().query(Email).all()} == before


def test_reparse_writes_body_exactly_as_parse_body_produces(db):
    from app.ingestion.parser import parse_body
    s = db()
    s.add(Email(id=1, gmail_id="links_only", subject="a", folder="inbox", body="old"))
    s.commit()

    _run(db)

    assert db().get(Email, 1).body == parse_body(MESSAGES["links_only"]).text == NEWSLETTER_BODY


def test_reparse_dry_run_reports_links_without_full_urls(db, capsys):
    _seed(db)
    s = db()
    s.add(Email(id=5, gmail_id="body_too", subject="e", folder="inbox", body="see https://old.example.com/page now"))
    s.commit()
    before = {r.gmail_id: (r.body, r.links) for r in db().query(Email).all()}
    lines = []
    messages = dict(MESSAGES, body_too=_html_message(NEWSLETTER))

    summary = backfill_script.reparse_bodies(db, FakeFetch(messages), sleep=lambda s: None,
                                             dry_run=True, log=lines.append)
    backfill_script.print_reparse_summary(summary, dry_run=True)
    out = capsys.readouterr().out + "\n".join(lines)

    assert {r.gmail_id: (r.body, r.links) for r in db().query(Email).all()} == before
    assert "of which gained links:" in out
    assert "links in changed rows:" in out
    assert "Shop now · shop.example.com" in out
    assert "Unsubscribe · shop.example.com" in out
    assert len(summary["link_samples"]) == 5
    assert "see [link] now" in out  # body sample before
    assert "Big sale this week at [link]" in out  # body sample after
    assert "http://" not in out and "https://" not in out


def test_reparse_masks_urls_in_error_messages(db):
    _seed(db)
    lines = []
    data = dict(MESSAGES, same=RuntimeError("<HttpError 500 when requesting https://gmail.googleapis.com/x>"))

    backfill_script.reparse_bodies(db, FakeFetch(data), sleep=lambda s: None, log=lines.append)

    assert any("[link]" in l for l in lines)
    assert not any("https://" in l for l in lines)


@pytest.mark.parametrize("text, expected", [
    ("go to https://a.com/x?y=1 now", "go to [link] now"),
    ("HTTP://A.COM and http://b.org/", "[link] and [link]"),
    ("mailto:a@b.com stays", "mailto:a@b.com stays"),
    ("no urls", "no urls"),
])
def test_mask_urls(text, expected):
    assert backfill_script.mask_urls(text) == expected


def test_link_samples_label_is_masked_when_it_is_a_url(db, capsys):
    s = db()
    s.add(Email(id=1, gmail_id="m", subject="a", folder="inbox", body="Visit https://x.example.com/deal"))
    s.commit()
    message = _html_message('<p>Visit <a href="https://x.example.com/deal">https://x.example.com/deal</a></p>')

    summary = backfill_script.reparse_bodies(db, FakeFetch({"m": message}), sleep=lambda s: None,
                                             dry_run=True, log=lambda *_: None)
    backfill_script.print_reparse_summary(summary, dry_run=True)
    out = capsys.readouterr().out

    assert "[link] · x.example.com" in out
    assert "https://" not in out
