"""Pins parse_body's text and reason to the output recorded before link extraction was added.

The labeled evaluation set was built from these bodies, so any change here is a regression.
EXPECTED was recorded by running the parser as it was before extract_links existed.
"""
import base64

import pytest

from app.ingestion.parser import parse_body, get_plain_text_body


def _b64(text):
    return base64.urlsafe_b64encode(text.encode('utf-8')).decode()


def _part(mime, text, filename=''):
    return {'mimeType': mime, 'filename': filename, 'headers': [], 'body': {'data': _b64(text)}}


def _multipart(mime, *parts):
    return {'mimeType': mime, 'filename': '', 'headers': [], 'body': {'size': 0}, 'parts': list(parts)}


NEWSLETTER_HTML = (
    '<!DOCTYPE html><html><head><title>Weekly</title><style>p{color:red}</style></head><body>'
    '<div style="display:none;max-height:0">Preheader ​‌ hidden text '
    '<a href="https://hidden.example.com/track">hidden link</a></div>'
    '<table><tr><td><a href="https://news.example.com/"><img src="logo.png" alt="Example News"></a></td>'
    '<td>Issue&nbsp;#42</td></tr></table>'
    '<h1>This   week</h1>'
    '<p>Read <a href="https://news.example.com/story?id=1&amp;src=mail">the <b>big</b>\n story</a> and '
    '<a href="javascript:alert(1)">this</a>.</p>'
    '<ul><li><a href="/relative">Relative</a></li><li><a href="mailto:editor@example.com">Write to us</a></li></ul>'
    '<p>Tom &amp; Jerry &copy; 2026<br>Line two</p>'
    '<p style="font-size:0px">tiny</p>'
    '<p><a href="https://news.example.com/unsubscribe?u=1">Unsubscribe</a> | '
    '<a href="https://news.example.com/prefs">Manage preferences</a></p>'
    '</body></html>'
)

FRAGMENTED_PLAIN = ('Festive Pocket Money\nis\nLIVE\nwith\n10,000+ internships,\nstipends up to\n'
                    '₹1,00,000/month,\nand\nexclusive rewards.\nApply\nnow')
FRAGMENTED_HTML = ('<html><body><p>\n<span>Festive Pocket Money</span>\nis\n<b>LIVE</b>\nwith\n'
                   '<span>10,000+ internships,</span>\nstipends up to\n<b>₹1,00,000/month,</b>\nand\n'
                   'exclusive rewards.</p>\n<p><a href="https://internshala.com/apply">Apply\nnow</a></p></body></html>')

HUMAN_PLAIN = ("Hi team,\n\nThe deploy finished at 3pm, see https://ci.example.com/run/7.\n"
               "Please review the notes (https://wiki.example.com/notes) before standup!\n\nThanks,\nAlex")
HUMAN_HTML = ('<p>Hi team,</p><p>The deploy finished at 3pm, see <a href="https://ci.example.com/run/7">the run</a>.</p>'
              '<p>Please review the notes before standup!</p><p>Thanks,<br>Alex</p>')

MESSAGES = {
    'plain_only': _part('text/plain', 'Hello​ there,\r\nsee https://example.com/a.\r\n\r\n> quoted\n'),
    'plain_and_html': _multipart('multipart/alternative', _part('text/plain', HUMAN_PLAIN),
                                 _part('text/html', HUMAN_HTML)),
    'fragmented': _multipart('multipart/alternative', _part('text/plain', FRAGMENTED_PLAIN),
                             _part('text/html', FRAGMENTED_HTML)),
    'html_only': _multipart('multipart/alternative', _part('text/html', NEWSLETTER_HTML)),
    'blank_plain': _multipart('multipart/alternative', _part('text/plain', '͏ ​'),
                              _part('text/html', NEWSLETTER_HTML)),
    'mislabelled': _part('text/plain', '<html><body><p>Hi <a href="https://x.example.com">there</a></p>'
                                       '<div style="visibility:hidden">secret</div></body></html>'),
    'nested_with_attachment': _multipart(
        'multipart/mixed',
        _part('text/plain', 'attachment text', filename='notes.txt'),
        _multipart('multipart/alternative', _part('text/html', '<div>Row<br>two</div><p>end</p>'))),
    'empty': {'mimeType': 'text/plain', 'body': {'size': 0}},
}

_NEWSLETTER_TEXT = ('Issue #42\n\nThis week\n\nRead the big story and this.\n\nRelative\nWrite to us\n\n'
                    'Tom & Jerry \xa9 2026\nLine two\n\nUnsubscribe | Manage preferences')

EXPECTED = {
    'blank_plain': (_NEWSLETTER_TEXT, 'html_no_plain'),
    'empty': ('', 'empty'),
    'fragmented': ('Festive Pocket Money is LIVE with 10,000+ internships, stipends up to ₹1,00,000/month, '
                   'and exclusive rewards.\n\nApply now', 'html_fragmented_plain'),
    'html_only': (_NEWSLETTER_TEXT, 'html_no_plain'),
    'mislabelled': ('Hi there', 'html_mislabelled_plain'),
    'nested_with_attachment': ('Row\ntwo\n\nend', 'html_no_plain'),
    'plain_and_html': ('Hi team,\n\nThe deploy finished at 3pm, see https://ci.example.com/run/7.\n'
                       'Please review the notes (https://wiki.example.com/notes) before standup!\n\nThanks,\nAlex',
                       'plain'),
    'plain_only': ('Hello there,\r\nsee https://example.com/a.\r\n\r\n> quoted\n', 'plain'),
}


@pytest.mark.parametrize('name', sorted(MESSAGES))
def test_parse_body_text_and_reason_unchanged(name):
    choice = parse_body({'payload': MESSAGES[name]})
    assert (choice.text, choice.reason) == EXPECTED[name]


@pytest.mark.parametrize('name', sorted(MESSAGES))
def test_get_plain_text_body_matches_parse_body_text(name):
    assert get_plain_text_body({'payload': MESSAGES[name]}) == EXPECTED[name][0]
