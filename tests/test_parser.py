import base64
import textwrap

import pytest

from app.ingestion.parser import (
    html_to_text, get_plain_text_body, parse_body, select_body, fragment_stats, is_fragmented, extract_links,
    MAX_LINKS, MAX_LINK_URL, REASON_PLAIN, REASON_FRAGMENTED, REASON_NO_PLAIN, REASON_MISLABELLED, REASON_EMPTY,
)


def _b64(text):
    return base64.urlsafe_b64encode(text.encode('utf-8')).decode()


def _part(mime, text, filename='', headers=None):
    return {'mimeType': mime, 'filename': filename, 'headers': headers or [], 'body': {'data': _b64(text)}}


def _multipart(mime, *parts):
    return {'mimeType': mime, 'filename': '', 'headers': [], 'body': {'size': 0}, 'parts': list(parts)}


def _message(payload):
    return {'payload': payload}


# ---------- html_to_text ----------

def test_inline_links_and_bold_stay_on_one_line():
    html = ('<p>We invite you to the <a href="https://example.com/hack">Agentic AI Hackathon</a>, '
            'a <b>1-day</b> <span>hands-on</span> event.</p>')
    assert html_to_text(html) == 'We invite you to the Agentic AI Hackathon, a 1-day hands-on event.'


def test_link_urls_are_dropped():
    text = html_to_text('<p>Read <a href="https://example.com/secret-path">the post</a></p>')
    assert 'example.com' not in text
    assert text == 'Read the post'


def test_source_newlines_inside_a_paragraph_are_spaces():
    html = '<p>Hello\n      <strong>there</strong>,\n   friend</p>'
    assert html_to_text(html) == 'Hello there, friend'


def test_paragraphs_and_list_items_break_onto_separate_lines():
    html = '<p>First para.</p><p>Second para.</p><ul><li>one</li><li>two</li></ul>'
    lines = [l for l in html_to_text(html).splitlines() if l]
    assert lines == ['First para.', 'Second para.', 'one', 'two']


def test_br_breaks_a_line():
    assert html_to_text('Line one<br>Line two<br/>Line three') == 'Line one\nLine two\nLine three'


def test_nested_divs_do_not_stack_blank_lines():
    html = '<div><div><div>a</div></div></div><div><div>b</div></div>'
    assert html_to_text(html) == 'a\nb'


def test_table_layout_produces_readable_lines():
    html = """
    <table>
      <tr><td>Order</td><td>#123</td></tr>
      <tr><td>Total</td><td>$40.00</td></tr>
      <tr><td><table><tr><td>Thanks for shopping</td></tr></table></td></tr>
    </table>"""
    assert html_to_text(html).splitlines() == ['Order #123', 'Total $40.00', 'Thanks for shopping']


def test_title_head_script_style_removed():
    html = """<!DOCTYPE html><html><head><title>Email</title>
    <style>p { color: red; }</style><script>alert(1)</script></head>
    <body><!-- tracking comment --><p>Real content</p></body></html>"""
    assert html_to_text(html) == 'Real content'


def test_display_none_preheader_removed():
    html = ('<div style="display: none; max-height: 0px; overflow: hidden;">Preheader teaser</div>'
            '<p>Body text</p>')
    assert html_to_text(html) == 'Body text'


@pytest.mark.parametrize('style', [
    'DISPLAY : NONE',
    'visibility:hidden',
    'mso-hide: all',
    'font-size:0',
    'font-size: 0px; line-height: 0',
    'max-height:0;overflow:hidden',
    'color:#fff; display:none !important',
])
def test_hidden_styles_removed(style):
    assert html_to_text(f'<span style="{style}">hidden</span><p>shown</p>') == 'shown'


@pytest.mark.parametrize('style', ['font-size:0.9em', 'font-size:10px', 'max-height:0.5em', 'display:block'])
def test_visible_styles_kept(style):
    assert html_to_text(f'<p style="{style}">shown</p>') == 'shown'


def test_mso_hide_all_preheader_removed():
    html = ('<body><div style="mso-hide:all;font-size:1px;color:#ffffff">'
            'Your weekly digest is here &zwnj;&nbsp;&zwnj;&nbsp;</div>'
            '<p>Hi Khushi,</p><p>Here is your digest.</p></body>')
    assert html_to_text(html) == 'Hi Khushi,\n\nHere is your digest.'


def test_invisible_characters_removed():
    html = '<p>Hello​ ͏͏‌‍world﻿­⁠!</p><p>͏ ͏ ͏</p>'
    assert html_to_text(html) == 'Hello world!'


def test_entities_decode():
    html = '<p>Tom &amp; Jerry&nbsp;&nbsp;say&nbsp;hi &lt;3 &copy; 2026</p>'
    assert html_to_text(html) == 'Tom & Jerry say hi <3 © 2026'


def test_runs_of_blank_lines_collapse_to_one():
    html = 'a<br><br><br><br><br>b'
    assert html_to_text(html) == 'a\n\nb'


def test_inline_tags_separated_by_source_newlines_stay_on_one_line():
    html = ('<p>\n  <span>Festive Pocket Money</span>\n  <b>is</b>\n  <span>LIVE</span>\n  with\n'
            '  <a href="u">10,000+ internships</a>,\n  stipends up to\n  <strong>\u20b91,00,000/month</strong>.\n</p>')
    assert html_to_text(html) == 'Festive Pocket Money is LIVE with 10,000+ internships, stipends up to \u20b91,00,000/month.'


def test_tabs_and_crlf_in_source_are_spaces():
    html = '<div>Apply\r\n\t<em>now</em>\t\tbefore\r\n<b>Friday</b>.</div>'
    assert html_to_text(html) == 'Apply now before Friday.'


@pytest.mark.parametrize('space', ['\xa0', '&nbsp;', '\u2028', '\u202f', '\u2003', '\u3000'])
def test_unicode_spaces_collapse_to_one_space(space):
    assert html_to_text(f'<p>one{space}\n{space}two</p>') == 'one two'


@pytest.mark.parametrize('html', [
    '<b>upGrad,</b> <b>Marks</b> &amp; Spencer',
    '<span>upGrad, </span><span>Marks</span> &amp; Spencer',
    'upGrad,&nbsp;Marks &amp; Spencer',
])
def test_space_after_comma_between_inline_tags_is_kept(html):
    assert html_to_text(html) == 'upGrad, Marks & Spencer'


@pytest.mark.parametrize('style', ['mso-hide:all', 'max-height:0', 'font-size:0', 'display:none'])
def test_whitespace_inside_hidden_inline_element_still_separates_words(style):
    html = f'<b>upGrad,</b><span style="{style}"> </span><b>Marks</b> &amp; Spencer'
    assert html_to_text(html) == 'upGrad, Marks & Spencer'


def test_hidden_element_without_whitespace_adds_no_space():
    assert html_to_text('Hello<span style="display:none">x</span>, world') == 'Hello, world'


def test_br_still_breaks_lines_when_source_has_newlines():
    assert html_to_text('<p>Line\none<br>\nLine\ntwo</p>') == 'Line one\nLine two'


# ---------- get_plain_text_body ----------

def test_prefers_text_plain_over_html():
    msg = _message(_multipart('multipart/alternative',
                              _part('text/plain', 'plain version'),
                              _part('text/html', '<p>html version</p>')))
    assert get_plain_text_body(msg) == 'plain version'


def test_falls_back_to_html_when_no_plain():
    msg = _message(_multipart('multipart/alternative', _part('text/html', '<p>only <b>html</b></p>')))
    assert get_plain_text_body(msg) == 'only html'


def test_detects_html_mislabelled_as_text_plain():
    msg = _message(_part('text/plain', '<html><body><p>Hi <a href="x">there</a></p></body></html>'))
    assert get_plain_text_body(msg) == 'Hi there'


def test_invisible_chars_stripped_from_plain_text():
    msg = _message(_part('text/plain', 'Hi​ there͏'))
    assert get_plain_text_body(msg) == 'Hi there'


def test_blank_plain_part_falls_back_to_html():
    msg = _message(_multipart('multipart/alternative',
                              _part('text/plain', '͏ ​'),
                              _part('text/html', '<p>real</p>')))
    assert get_plain_text_body(msg) == 'real'


def test_nested_multipart_body_is_found():
    msg = _message(_multipart('multipart/mixed',
                              _multipart('multipart/alternative',
                                         _part('text/plain', 'nested plain'),
                                         _part('text/html', '<p>nested html</p>')),
                              {'mimeType': 'application/pdf', 'filename': 'a.pdf', 'headers': [],
                               'body': {'attachmentId': 'abc', 'size': 10}}))
    assert get_plain_text_body(msg) == 'nested plain'


def test_text_attachment_is_never_the_body():
    msg = _message(_multipart('multipart/mixed',
                              _part('text/plain', 'notes.txt contents', filename='notes.txt'),
                              _multipart('multipart/alternative',
                                         _part('text/html', '<p>the real body</p>'))))
    assert get_plain_text_body(msg) == 'the real body'


def test_content_disposition_attachment_without_filename_is_skipped():
    attachment = _part('text/plain', 'attached text',
                       headers=[{'name': 'Content-Disposition', 'value': 'Attachment; size=13'}])
    msg = _message(_multipart('multipart/mixed', attachment, _part('text/plain', 'real body')))
    assert get_plain_text_body(msg) == 'real body'


def test_inline_content_disposition_is_used():
    body = _part('text/plain', 'inline body', headers=[{'name': 'Content-Disposition', 'value': 'inline'}])
    assert get_plain_text_body(_message(_multipart('multipart/mixed', body))) == 'inline body'


def test_parts_deeper_than_limit_are_ignored():
    def nest(levels, leaf):
        node = leaf
        for _ in range(levels):
            node = _multipart('multipart/mixed', node)
        return node

    assert get_plain_text_body(_message(nest(10, _part('text/plain', 'deep')))) == 'deep'
    assert get_plain_text_body(_message(nest(11, _part('text/plain', 'too deep')))) == ''


def test_empty_payload_returns_empty_string():
    assert get_plain_text_body(_message({'mimeType': 'text/plain', 'body': {'size': 0}})) == ''


# ---------- choosing between text/plain and text/html ----------

def _alternative(plain, html):
    return _message(_multipart('multipart/alternative', _part('text/plain', plain), _part('text/html', html)))


FRAGMENTED_PLAIN = ('Festive Pocket Money\nis\nLIVE\nwith\n10,000+ internships,\nstipends up to\n'
                    '\u20b91,00,000/month,\nand\nexclusive rewards.\nApply\nnow')
MATCHING_HTML = ('<html><body><p>\n<span>Festive Pocket Money</span>\nis\n<b>LIVE</b>\nwith\n'
                 '<span>10,000+ internships,</span>\nstipends up to\n<b>\u20b91,00,000/month,</b>\nand\n'
                 'exclusive rewards.</p>\n<p><a href="u">Apply\nnow</a></p></body></html>')


def test_fragmented_plain_alternative_uses_html():
    choice = parse_body(_alternative(FRAGMENTED_PLAIN, MATCHING_HTML))
    assert choice.reason == REASON_FRAGMENTED
    assert choice.text == ('Festive Pocket Money is LIVE with 10,000+ internships, stipends up to '
                           '\u20b91,00,000/month, and exclusive rewards.\n\nApply now')
    assert choice.stats['plain_lines'] == 11


def test_human_plain_email_with_signature_keeps_plain():
    plain = ("Hi team,\n\nThe deploy finished at 3pm and all checks passed. Please review the release "
             "notes before tomorrow's standup and flag anything that looks off.\n\nThanks,\nAlex Kumar\n"
             "Senior Engineer\nAcme Corp\n+91 98765 43210")
    html = ("<p>Hi team,</p><p>The deploy finished at 3pm and all checks passed. Please review the release "
            "notes before tomorrow's standup and flag anything that looks off.</p>"
            "<p>Thanks,<br>Alex Kumar<br>Senior Engineer<br>Acme Corp<br>+91 98765 43210</p>")
    choice = parse_body(_alternative(plain, html))
    assert choice.reason == REASON_PLAIN
    assert choice.text == plain


def test_hard_wrapped_plain_email_is_not_fragmented():
    paragraph = ("We are writing to let you know that the quarterly maintenance window has moved to "
                 "Saturday night. During this time the dashboard and the public API will be unavailable "
                 "for roughly two hours. Scheduled reports will run once the window closes, and no data "
                 "will be lost. If you have automated jobs that depend on the API, please pause them "
                 "before the window starts and resume them afterwards. Reply to this email if you have "
                 "any questions.")
    plain = textwrap.fill(paragraph, width=72) + '\n\nRegards,\nThe Platform Team'
    html = f'<p>{paragraph}</p><p>Regards,<br>The Platform Team</p>'
    choice = parse_body(_alternative(plain, html))
    assert choice.reason == REASON_PLAIN
    assert choice.text == plain
    assert choice.stats['plain_avg'] < 0.5 * choice.stats['html_avg']  # only the short-line rule saves it


def test_human_numbered_and_bulleted_lists_keep_plain():
    plain = ("Agenda for Friday\n1. Budget review\n2. Hiring plan\n3. Office move\n4. Q4 goals\n5. Any other business\n\n"
             "Bring\n- laptop\n- badge\n- notes\n\nPriya")
    html = ("<p>Agenda for Friday</p><ol><li>Budget review</li><li>Hiring plan</li><li>Office move</li>"
            "<li>Q4 goals</li><li>Any other business</li></ol><p>Bring</p><ul><li>laptop</li><li>badge</li>"
            "<li>notes</li></ul><p>Priya</p>")
    choice = parse_body(_alternative(plain, html))
    assert choice.reason == REASON_PLAIN
    assert choice.text == plain
    assert choice.stats['short_share'] >= 0.6  # short lines alone are not enough


def test_fragmented_plain_with_stub_html_keeps_plain():
    choice = parse_body(_alternative(FRAGMENTED_PLAIN, '<p>View this email in your browser</p>'))
    assert choice.reason == REASON_PLAIN
    assert choice.text == FRAGMENTED_PLAIN


def test_short_fragmented_plain_below_min_lines_keeps_plain():
    plain = 'Sale\nis\nLIVE\nnow\nhere'
    choice = parse_body(_alternative(plain, '<p>Sale is LIVE now here and everywhere else too</p>'))
    assert choice.reason == REASON_PLAIN


def test_fragment_stats_values():
    stats = fragment_stats('aa\nbb.\n\ncccc', 'aa bb. cccc')
    assert stats['plain_lines'] == 3
    assert stats['plain_avg'] == pytest.approx(3.0)
    assert stats['html_avg'] == pytest.approx(11.0)
    assert stats['short_share'] == pytest.approx(2 / 3)
    assert stats['html_len_ratio'] == pytest.approx(1.0)
    assert not is_fragmented(stats)  # fewer than the minimum lines


@pytest.mark.parametrize('plain, html, reason', [
    ('<html><body><p>x</p></body></html>', None, REASON_MISLABELLED),
    ('\u200b ', '<p>x</p>', REASON_NO_PLAIN),
    (None, '<p>x</p>', REASON_NO_PLAIN),
    (None, None, REASON_EMPTY),
    ('plain', None, REASON_PLAIN),
    ('plain', '<p></p>', REASON_PLAIN),
])
def test_select_body_reasons(plain, html, reason):
    assert select_body(plain, html).reason == reason


# ---------- extract_links ----------

def _urls(links):
    return [link['url'] for link in links]


def test_extract_links_reads_anchor_text_through_nested_tags():
    links = extract_links('<p><a href="https://internshala.com/x"><span>Apply</span>\n <b>Now</b></a></p>', html=True)
    assert links == [{'text': 'Apply Now', 'url': 'https://internshala.com/x', 'domain': 'internshala.com',
                      'kind': 'link'}]


def test_extract_links_image_only_link_uses_alt_text():
    links = extract_links('<a href="https://shop.example.com"><img src="l.png" alt=" Shop  logo "></a>', html=True)
    assert links[0]['text'] == 'Shop logo'


def test_extract_links_without_text_or_alt_falls_back_to_domain():
    links = extract_links('<a href="https://www.example.com/p"><img src="l.png"></a>', html=True)
    assert links[0]['text'] == 'example.com'
    assert links[0]['domain'] == 'example.com'


@pytest.mark.parametrize('href', [
    'javascript:alert(1)', ' JavaScript:alert(1)', 'java\nscript:alert(1)', 'data:text/html,hi', 'tel:+911234',
    '/relative/path', 'page.html', '#top', '', '   ', '//cdn.example.com/x', 'https://', 'mailto:', 'ftp://x.com',
])
def test_extract_links_drops_unsafe_relative_and_empty_urls(href):
    assert extract_links(f'<a href="{href}">x</a><a>no href</a>', html=True) == []


def test_extract_links_keeps_mailto():
    links = extract_links('<a href="mailto:Help@Example.com?subject=Hi">Email us</a>', html=True)
    assert links[0]['url'] == 'mailto:Help@Example.com?subject=Hi'
    assert links[0]['domain'] == 'example.com'


def test_extract_links_dedupes_by_url_keeping_first():
    html = ('<a href="https://a.com/1">First</a><a href="https://b.com">B</a>'
            '<a href="https://a.com/1">Again</a>')
    links = extract_links(html, html=True)
    assert _urls(links) == ['https://a.com/1', 'https://b.com']
    assert links[0]['text'] == 'First'


@pytest.mark.parametrize('wrapper', [
    '<div style="display:none">{}</div>', '<span style="font-size:0px">{}</span>',
    '<td style="mso-hide: all">{}</td>', '<script>{}</script>', '<head>{}</head>',
])
def test_extract_links_skips_hidden_links(wrapper):
    html = wrapper.format('<a href="https://hidden.example.com">hidden</a>') + '<a href="https://shown.com">s</a>'
    assert _urls(extract_links(html, html=True)) == ['https://shown.com']


def test_extract_links_label_ignores_hidden_text_inside_anchor():
    html = '<a href="https://x.com">Read<span style="display:none">tracking123</span> more</a>'
    assert extract_links(html, html=True)[0]['text'] == 'Read more'


def test_extract_links_caps_count():
    html = ''.join(f'<a href="https://x.com/{i}">{i}</a>' for i in range(40))
    links = extract_links(html, html=True)
    assert len(links) == MAX_LINKS == 30
    assert links[-1]['url'] == 'https://x.com/29'


def test_extract_links_drops_overlong_urls():
    long_url = 'https://x.com/' + 'a' * (MAX_LINK_URL - len('https://x.com/') + 1)
    ok_url = 'https://x.com/' + 'a' * (MAX_LINK_URL - len('https://x.com/'))
    assert _urls(extract_links(f'<a href="{long_url}">l</a><a href="{ok_url}">o</a>', html=True)) == [ok_url]


def test_extract_links_from_plain_text_strips_trailing_punctuation():
    text = ('See https://a.com/x. Also (https://b.com/y), https://c.com/z; '
            'https://d.com/q?a=1! and https://e.com/w? and https://en.wikipedia.org/wiki/Foo_(bar).')
    assert _urls(extract_links(text, html=False)) == [
        'https://a.com/x', 'https://b.com/y', 'https://c.com/z', 'https://d.com/q?a=1', 'https://e.com/w',
        'https://en.wikipedia.org/wiki/Foo_(bar)',
    ]


def test_extract_links_plain_text_label_is_domain_and_ignores_other_schemes():
    links = extract_links('go to https://www.example.com/page or javascript:x or ftp://f.com', html=False)
    assert links == [{'text': 'example.com', 'url': 'https://www.example.com/page', 'domain': 'example.com',
                      'kind': 'link'}]


@pytest.mark.parametrize('label, url, kind', [
    ('Unsubscribe', 'https://x.com/a', 'unsubscribe'),
    ('Click here', 'https://x.com/UNSUBSCRIBE?id=1', 'unsubscribe'),
    ('Opt-out', 'https://x.com/a', 'unsubscribe'),
    ('here', 'https://x.com/optout', 'unsubscribe'),
    ('Manage   preferences', 'https://x.com/a', 'unsubscribe'),
    ('here', 'https://x.com/manage_preferences', 'unsubscribe'),
    ('here', 'https://x.com/?q=manage+preferences', 'unsubscribe'),
    ('Read more', 'https://x.com/a', 'link'),
    ('Preferences', 'https://x.com/settings', 'link'),
])
def test_extract_links_unsubscribe_kind(label, url, kind):
    assert extract_links(f'<a href="{url}">{label}</a>', html=True)[0]['kind'] == kind


def test_extract_links_empty_input():
    assert extract_links(None) == [] and extract_links('') == []


def test_parse_body_links_come_from_chosen_part():
    msg = _alternative('Hi, see https://plain.example.com/a for details. Thanks a lot for reading this.',
                       '<p>Hi, see <a href="https://html.example.com/a">details</a></p>')
    choice = parse_body(msg)
    assert choice.reason == REASON_PLAIN
    assert _urls(choice.links) == ['https://plain.example.com/a']


def test_parse_body_falls_back_to_other_part_for_links():
    msg = _alternative('Hi, the event starts at noon. Thanks a lot for reading this message.',
                       '<p>Hi, <a href="https://html.example.com/a">the event</a> starts at noon.</p>')
    assert _urls(parse_body(msg).links) == ['https://html.example.com/a']


def test_parse_body_fragmented_uses_html_links():
    choice = parse_body(_alternative(FRAGMENTED_PLAIN, MATCHING_HTML.replace('href="u"', 'href="https://u.com"')))
    assert choice.reason == REASON_FRAGMENTED
    assert _urls(choice.links) == ['https://u.com']


def test_parse_body_link_urls_never_enter_body_text():
    html = '<p>Read <a href="https://secret.example.com/path">the post</a></p>'
    msg = _message(_multipart('multipart/alternative', _part('text/html', html)))
    choice = parse_body(msg)
    assert 'secret.example.com' not in choice.text
    assert 'secret.example.com' not in get_plain_text_body(msg)
    assert _urls(choice.links) == ['https://secret.example.com/path']


def test_parse_body_survives_link_extraction_failure(monkeypatch):
    from app.ingestion import parser

    def boom(*args, **kwargs):
        raise RuntimeError('bad link')

    monkeypatch.setattr(parser, 'extract_links', boom)
    choice = parse_body(_message(_part('text/plain', 'body text')))
    assert choice.text == 'body text' and choice.links == []


def test_select_body_alone_leaves_links_unset():
    assert select_body('hi', None).links is None
