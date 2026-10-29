import base64
import sqlite3

import pytest

from scripts import debug_email_parts as debug


def _b64(text):
    return base64.urlsafe_b64encode(text.encode('utf-8')).decode()


@pytest.fixture
def db_path(tmp_path):
    # A path with a space checks that the file URI is built correctly on Windows
    path = tmp_path / 'dir with space' / 'test.db'
    path.parent.mkdir()
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE emails (id INTEGER PRIMARY KEY, gmail_id TEXT, subject TEXT, '
                 'folder TEXT, received_at TEXT)')
    conn.executemany('INSERT INTO emails VALUES (?, ?, ?, ?, ?)', [
        (1, 'g1', 'Festive Pocket Money is LIVE', 'inbox', '2026-10-01 10:00:00'),
        (2, 'g2', 'Pocket money reminder', 'inbox', '2026-10-02 10:00:00'),
        (3, 'g3', '100% off_today', 'inbox', None),
    ])
    conn.commit()
    conn.close()
    return path


def test_find_by_id(db_path):
    assert [r[0] for r in debug.find_rows(db_path, email_id=3)] == [3]
    assert debug.find_rows(db_path, email_id=99) == []


def test_find_by_subject_is_case_insensitive_and_newest_first(db_path):
    assert [r[0] for r in debug.find_rows(db_path, subject_contains='POCKET money')] == [2, 1]


def test_find_by_subject_treats_wildcards_literally(db_path):
    assert [r[0] for r in debug.find_rows(db_path, subject_contains='0%')] == [3]
    assert [r[0] for r in debug.find_rows(db_path, subject_contains='f_t')] == [3]
    assert debug.find_rows(db_path, subject_contains='%%%') == []


def test_connection_is_read_only(db_path):
    conn = debug.connect_read_only(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("UPDATE emails SET subject = 'x'")
    finally:
        conn.close()


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / 'absent.db'
    with pytest.raises(sqlite3.OperationalError):
        debug.find_rows(path, email_id=1)
    assert not path.exists()


def _message():
    plain = 'Festive Pocket Money\nis\nLIVE\nwith\n10,000+ internships,\nstipends up to\nand more\nApply\nnow'
    html = '<p>Festive Pocket Money is LIVE with 10,000+ internships, stipends up to and more</p><p>Apply now</p>'
    return {'payload': {
        'mimeType': 'multipart/mixed', 'filename': '', 'body': {'size': 0}, 'parts': [
            {'mimeType': 'multipart/alternative', 'filename': '', 'body': {'size': 0}, 'parts': [
                {'mimeType': 'text/plain', 'filename': '', 'body': {'size': len(plain), 'data': _b64(plain)}},
                {'mimeType': 'text/html', 'filename': '', 'body': {'size': len(html), 'data': _b64(html)}},
            ]},
            {'mimeType': 'application/pdf', 'filename': 'offer.pdf', 'body': {'size': 1234, 'attachmentId': 'a'}},
        ]}}


def test_mime_tree_lines_show_type_size_and_filename():
    lines = debug.mime_tree_lines(_message()['payload'])
    assert lines[0] == 'multipart/mixed  size=0'
    assert lines[1] == '  multipart/alternative  size=0'
    assert lines[2].startswith('    text/plain  size=')
    assert lines[4] == "  application/pdf  size=1234  filename='offer.pdf'"


def test_describe_reports_parts_and_choice():
    out = debug.describe(_message(), max_chars=12)
    assert 'Festive Pock...' in out
    assert 'Parser chose: HTML, plain text was fragmented (html_fragmented_plain)' in out
    assert 'plain 9 lines' in out
    assert 'fragmented rule fired' in out
