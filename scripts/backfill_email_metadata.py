"""Fill in received_at and correct folder for emails already in the database.

Fetches each message from Gmail with format='metadata' (read-only) and updates
received_at from internalDate and folder from labelIds. If the labels say neither
INBOX nor SENT (e.g. archived received mail), the folder is left unchanged.

    python scripts/backfill_email_metadata.py --dry-run   # show what would change
    python scripts/backfill_email_metadata.py             # rows with received_at NULL
    python scripts/backfill_email_metadata.py --all       # re-check every row

--reparse-bodies instead re-fetches every message with format='full', runs the
current parser and updates only the body and links columns. A row is never
overwritten with an empty body, and stored links are never replaced by an empty
list. Safe to re-run: unchanged rows are not written. Printed output never shows
a full URL: links show only their label and domain, and URLs in body samples
become [link].

    python scripts/backfill_email_metadata.py --reparse-bodies --dry-run
    python scripts/backfill_email_metadata.py --reparse-bodies
    python scripts/backfill_email_metadata.py --reparse-bodies --dry-run --subject-contains "Pocket Money"

The summary also counts which source the parser chose for each message and lists
a few ids where the fragmented-plain-text rule switched to HTML.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.crud import _to_naive_utc, dump_links
from app.db.models import Email
from app.ingestion.gmail_utils import internal_date_to_utc, folder_from_labels
from app.ingestion.parser import (
    parse_body, format_fragment_stats, REASON_DESCRIPTIONS, REASON_FRAGMENTED,
)

SAMPLE_CHARS = 200
FRAGMENTED_SAMPLES = 3
LINK_SAMPLES = 5

_URL = re.compile(r'https?://\S+', re.IGNORECASE)


def mask_urls(text):
    """Replaces every http:// or https:// URL with [link] so printed output never shows one."""
    return _URL.sub('[link]', str(text))


def _stored_links(raw):
    try:
        links = json.loads(raw) if raw else []
    except ValueError:
        return []
    return links if isinstance(links, list) else []


def make_metadata_fetcher(service):
    """Returns fetch(gmail_id) -> message dict, or None if Gmail no longer has the message."""
    from googleapiclient.errors import HttpError

    def fetch(gmail_id):
        try:
            return service.users().messages().get(
                userId='me', id=gmail_id, format='metadata', metadataHeaders=['Date']
            ).execute()
        except HttpError as exc:
            if getattr(exc, 'resp', None) is not None and exc.resp.status == 404:
                return None
            raise

    return fetch


def make_full_fetcher(service):
    """Returns fetch(gmail_id) -> full message dict, or None if Gmail no longer has the message."""
    from googleapiclient.errors import HttpError

    def fetch(gmail_id):
        try:
            return service.users().messages().get(userId='me', id=gmail_id, format='full').execute()
        except HttpError as exc:
            if getattr(exc, 'resp', None) is not None and exc.resp.status == 404:
                return None
            raise

    return fetch


def _like_pattern(text):
    escaped = text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f"%{escaped}%"


def reparse_bodies(session_factory, fetch, sleep=time.sleep, delay=0.2, dry_run=False, log=print,
                   subject_contains=None):
    summary = Counter()
    sample = None
    fragmented = []
    link_samples = []  # (label, domain) only, never the URL

    session = session_factory()
    try:
        query = session.query(Email)
        if subject_contains:
            query = query.filter(Email.subject.ilike(_like_pattern(subject_contains), escape='\\'))
        rows = query.order_by(Email.id).all()
        summary['scanned'] = len(rows)

        for i, email in enumerate(rows):
            if i:
                sleep(delay)
            try:
                message = fetch(email.gmail_id)
            except Exception as exc:
                summary['errors'] += 1
                log(f"  error   id={email.id} gmail_id={email.gmail_id}: {mask_urls(exc)}")
                continue
            if message is None:
                summary['missing'] += 1
                log(f"  missing id={email.id} gmail_id={email.gmail_id} (not found in Gmail, left unchanged)")
                continue

            try:
                choice = parse_body(message)
            except Exception as exc:
                summary['errors'] += 1
                log(f"  error   id={email.id} gmail_id={email.gmail_id}: parse failed: {mask_urls(exc)}")
                continue
            new_body = choice.text
            summary[f'source_{choice.reason}'] += 1
            if choice.reason == REASON_FRAGMENTED and len(fragmented) < FRAGMENTED_SAMPLES:
                fragmented.append((email.id, choice.stats))

            new_links = choice.links or []

            old_body = email.body or ""
            old_links = _stored_links(email.links)
            body_changed = new_body != old_body
            links_changed = new_links != old_links
            guarded = False
            if body_changed and not new_body.strip():
                summary['kept_nonempty'] += 1
                log(f"  keep    id={email.id}: new body is empty, stored body left unchanged")
                body_changed, guarded = False, True
            if links_changed and not new_links:
                summary['kept_links'] += 1
                log(f"  keep    id={email.id}: new parse found no links, stored links left unchanged")
                links_changed, guarded = False, True
            if not body_changed and not links_changed:
                if not guarded:
                    summary['unchanged'] += 1
                continue

            changes = []
            if body_changed:
                summary['body_changed'] += 1
                if not old_body.strip():
                    summary['empty_to_filled'] += 1
                if sample is None:
                    sample = (email.id, old_body, new_body)
                changes.append(f"body {len(old_body)} -> {len(new_body)} chars")
            if links_changed:
                summary['links_changed'] += 1
                summary['links_total'] += len(new_links)
                if not old_links:
                    summary['gained_links'] += 1
                for link in new_links[:LINK_SAMPLES - len(link_samples)]:
                    link_samples.append((link.get('text', ''), link.get('domain', '')))
                changes.append(f"links {len(old_links)} -> {len(new_links)}")
            log(f"  {'would update' if dry_run else 'update'} id={email.id}: {', '.join(changes)}")

            if not dry_run:
                if body_changed:
                    email.body = new_body
                if links_changed:
                    email.links = dump_links(new_links)
                session.commit()
            summary['updated'] += 1
    finally:
        session.close()

    summary['sample'] = sample
    summary['fragmented_samples'] = fragmented
    summary['link_samples'] = link_samples
    return summary


def _truncate(text, n=SAMPLE_CHARS):
    return text if len(text) <= n else text[:n] + "..."


def print_reparse_summary(summary, dry_run):
    label = "Dry run, nothing written" if dry_run else "Done"
    print(f"\n{label}.")
    rows = [
        ("scanned", summary['scanned']),
        ("would change" if dry_run else "changed", summary['updated']),
        ("  body changed", summary['body_changed']),
        ("  of which empty before, non-empty after", summary['empty_to_filled']),
        ("  links changed", summary['links_changed']),
        ("  of which gained links", summary['gained_links']),
        ("  links in changed rows", summary['links_total']),
        ("unchanged", summary['unchanged']),
        ("kept (new body would be empty)", summary['kept_nonempty']),
        ("kept links (new parse found none)", summary['kept_links']),
        ("missing", summary['missing']),
        ("errors", summary['errors']),
    ]
    for name, value in rows:
        print(f"  {name + ':':<42}{value}")
    print("\nBody source chosen (every parsed message):")
    for reason, description in REASON_DESCRIPTIONS.items():
        print(f"  {description + ':':<42}{summary[f'source_{reason}']}")
    if summary['fragmented_samples']:
        print(f"\nFragmented rule fired on (first {FRAGMENTED_SAMPLES}):")
        for email_id, stats in summary['fragmented_samples']:
            print(f"  id={email_id}: {format_fragment_stats(stats)}")
    if summary['link_samples']:
        print(f"\nSample links (first {LINK_SAMPLES}, label \u00b7 domain):")
        for label, domain in summary['link_samples']:
            print(f"  {_truncate(mask_urls(label), 60)} \u00b7 {domain}")
    if summary['sample']:
        email_id, before, after = summary['sample']
        print(f"\nSample (id={email_id}, first {SAMPLE_CHARS} chars, URLs shown as [link]):")
        print("--- before ---")
        print(mask_urls(_truncate(before)))
        print("--- after ---")
        print(mask_urls(_truncate(after)))


def backfill(session_factory, fetch, sleep=time.sleep, delay=0.2,
             include_all=False, dry_run=False, log=print):
    summary = Counter()
    folder_changes = Counter()

    session = session_factory()
    try:
        query = session.query(Email)
        if not include_all:
            query = query.filter(Email.received_at.is_(None))
        rows = query.order_by(Email.id).all()
        summary['scanned'] = len(rows)

        for i, email in enumerate(rows):
            if i:
                sleep(delay)
            try:
                message = fetch(email.gmail_id)
            except Exception as exc:
                summary['errors'] += 1
                log(f"  error   id={email.id} gmail_id={email.gmail_id}: {mask_urls(exc)}")
                continue
            if message is None:
                summary['missing'] += 1
                log(f"  missing id={email.id} gmail_id={email.gmail_id} (not found in Gmail, left unchanged)")
                continue

            new_received = _to_naive_utc(internal_date_to_utc(message.get('internalDate')))
            new_folder = folder_from_labels(message.get('labelIds'))

            changes = {}
            if new_received is not None and new_received != email.received_at:
                changes['received_at'] = new_received
            if new_folder is not None and new_folder != email.folder:
                changes['folder'] = new_folder

            if not changes:
                summary['unchanged'] += 1
                continue

            parts = []
            if 'received_at' in changes:
                parts.append(f"received_at {email.received_at} -> {changes['received_at']}")
            if 'folder' in changes:
                parts.append(f"folder {email.folder} -> {changes['folder']}")
                folder_changes[(email.folder, changes['folder'])] += 1
            log(f"  {'would update' if dry_run else 'update'} id={email.id}: " + "; ".join(parts))

            if not dry_run:
                for field, value in changes.items():
                    setattr(email, field, value)
                session.commit()
            summary['updated'] += 1
    finally:
        session.close()

    summary['folder_changes'] = dict(folder_changes)
    return summary


def print_summary(summary, dry_run):
    label = "Dry run, nothing written" if dry_run else "Done"
    print(f"\n{label}.")
    print(f"  scanned:   {summary['scanned']}")
    print(f"  {'would update' if dry_run else 'updated'}: {summary['updated']}")
    print(f"  unchanged: {summary['unchanged']}")
    print(f"  missing:   {summary['missing']}")
    print(f"  errors:    {summary['errors']}")
    if summary['folder_changes']:
        print("  folder changes:")
        for (old, new), n in sorted(summary['folder_changes'].items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
            print(f"    {old} -> {new}: {n}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--all', action='store_true', help='re-check every row, not just rows with received_at NULL')
    parser.add_argument('--dry-run', action='store_true', help='call Gmail and print changes, but write nothing')
    parser.add_argument('--delay', type=float, default=0.2, help='seconds to sleep between Gmail calls (default 0.2)')
    parser.add_argument('--reparse-bodies', action='store_true',
                        help="re-fetch every message with format='full' and rewrite only the body and links columns")
    parser.add_argument('--subject-contains', metavar='TEXT',
                        help='with --reparse-bodies, only rows whose subject contains TEXT (case-insensitive)')
    args = parser.parse_args(argv)
    if args.reparse_bodies and args.all:
        parser.error('--all does not apply to --reparse-bodies (it always scans every row)')
    if args.subject_contains is not None and not args.reparse_bodies:
        parser.error('--subject-contains only applies to --reparse-bodies')

    from app.auth.gmail_auth import get_gmail_service
    from app.db.session import SessionLocal, ensure_schema

    ensure_schema()
    service = get_gmail_service()
    if args.reparse_bodies:
        summary = reparse_bodies(SessionLocal, make_full_fetcher(service), delay=args.delay, dry_run=args.dry_run,
                                 subject_contains=args.subject_contains)
        print_reparse_summary(summary, args.dry_run)
        return
    summary = backfill(SessionLocal, make_metadata_fetcher(service), delay=args.delay,
                       include_all=args.all, dry_run=args.dry_run)
    print_summary(summary, args.dry_run)


if __name__ == "__main__":
    main()
