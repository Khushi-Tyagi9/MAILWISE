"""Show how the parser sees one stored email. Never writes to the database.

Looks up the row in mailwise.db (opened read-only), fetches that message from
Gmail with format='full' and prints the MIME tree, the start of the decoded
text/plain part, the start of the converted HTML part, and which source the
parser chose and why.

    python scripts/debug_email_parts.py --id 42
    python scripts/debug_email_parts.py --subject-contains "Pocket Money" --max-chars 800
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ingestion.parser import (
    find_text_parts, html_to_text, select_body, fragment_stats, is_fragmented, format_fragment_stats,
    REASON_DESCRIPTIONS,
)

DB_PATH = Path(__file__).resolve().parent.parent / 'mailwise.db'
MAX_MATCHES = 20


def connect_read_only(db_path):
    # mode=ro fails instead of creating the file, and rejects every write
    return sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)


def find_rows(db_path, email_id=None, subject_contains=None, limit=MAX_MATCHES + 1):
    """Returns [(id, gmail_id, subject, folder, received_at), ...] newest first."""
    conn = connect_read_only(db_path)
    try:
        sql = 'SELECT id, gmail_id, subject, folder, received_at FROM emails'
        if email_id is not None:
            return conn.execute(sql + ' WHERE id = ?', (email_id,)).fetchall()
        escaped = subject_contains.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        return conn.execute(
            sql + " WHERE subject LIKE ? ESCAPE '\\' ORDER BY received_at DESC, id DESC LIMIT ?",
            (f'%{escaped}%', limit),
        ).fetchall()
    finally:
        conn.close()


def mime_tree_lines(part, depth=0):
    body = part.get('body') or {}
    size = body.get('size', len(body.get('data') or ''))
    filename = part.get('filename') or ''
    line = f"{'  ' * depth}{part.get('mimeType') or '?'}  size={size}"
    if filename:
        line += f"  filename={filename!r}"
    lines = [line]
    for child in part.get('parts') or []:
        lines.extend(mime_tree_lines(child, depth + 1))
    return lines


def _clip(text, n):
    return text if len(text) <= n else text[:n] + '...'


def describe(message, max_chars):
    found = find_text_parts(message['payload'])
    plain = found.get('text/plain')
    html = found.get('text/html')
    converted = html_to_text(html) if html else None

    out = ['MIME tree:']
    out += ['  ' + line for line in mime_tree_lines(message['payload'])]

    out.append(f'\n--- text/plain (decoded, first {max_chars} chars) ---')
    out.append(_clip(plain, max_chars) if plain is not None else '(no text/plain part)')
    out.append(f'\n--- text/html (converted, first {max_chars} chars) ---')
    out.append(_clip(converted, max_chars) if converted is not None else '(no text/html part)')

    choice = select_body(plain, html)
    out.append(f'\nParser chose: {REASON_DESCRIPTIONS[choice.reason]} ({choice.reason})')
    stats = choice.stats
    if stats is None and plain and plain.strip() and converted:
        stats = fragment_stats(plain, converted)
    if stats is not None:
        out.append(f'  {format_fragment_stats(stats)}')
        out.append(f"  fragmented rule {'fired' if is_fragmented(stats) else 'did not fire'}")
    return '\n'.join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--id', type=int, help='emails.id of the row')
    target.add_argument('--subject-contains', metavar='TEXT', help='case-insensitive subject match')
    parser.add_argument('--max-chars', type=int, default=400, help='chars to show of each part (default 400)')
    args = parser.parse_args(argv)

    print('Note: this output contains email text.')

    rows = find_rows(DB_PATH, email_id=args.id, subject_contains=args.subject_contains)
    if not rows:
        print('No matching email in the database.')
        return 1
    if len(rows) > 1:
        shown = rows[:MAX_MATCHES]
        more = ' (showing the first 20)' if len(rows) > MAX_MATCHES else ''
        print(f'Several emails match{more}; rerun with --id:')
        for email_id, _, subject, folder, received_at in shown:
            print(f'  id={email_id}  {received_at or "-"}  [{folder}]  {subject}')
        return 1

    email_id, gmail_id, subject, folder, received_at = rows[0]
    print(f'id={email_id} gmail_id={gmail_id} folder={folder} received_at={received_at}')
    print(f'subject: {subject}\n')

    from app.auth.gmail_auth import get_gmail_service
    service = get_gmail_service()
    message = service.users().messages().get(userId='me', id=gmail_id, format='full').execute()
    print(describe(message, args.max_chars))
    return 0


if __name__ == '__main__':
    sys.exit(main())
