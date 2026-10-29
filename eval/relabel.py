"""Interactive labeler for inbox emails. See eval/LABELING.md for the label rules.

    python -m eval.relabel [--db mailwise.db] [--seed 42]

Reads mailwise.db read-only and never reads what the pipeline decided
(urgency, tasks, draft, confidence, draft_status).
"""
import argparse
import json
import os
import random
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frontend.utils import full_date, strip_quoted

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "mailwise.db"
PRIVATE_DIR = Path(__file__).resolve().parent / "private"
LABELS_PATH = PRIVATE_DIR / "labeled_set_v2.jsonl"
SKIPPED_PATH = PRIVATE_DIR / "skipped_v2.jsonl"

QUERY = "SELECT gmail_id, subject, sender, body, received_at FROM emails WHERE folder = 'inbox'"
KEYS = {"u": "urgent", "r": "routine", "n": "notification", "w": "newsletter"}
PREVIEW_CHARS = 600
STORED_BODY_CHARS = 1500
PROMPT = "[u]rgent [r]outine [n]otification ne[w]sletter  [s]kip [b]ack [q]uit > "


def load_inbox(db_path):
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(QUERY).fetchall()
    finally:
        conn.close()
    cols = ("gmail_id", "subject", "sender", "body", "received_at")
    return [dict(zip(cols, row)) for row in rows]


def load_jsonl(path):
    records = {}
    path = Path(path)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    records[rec["gmail_id"]] = rec
    return records


def save_jsonl(records, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for rec in records.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def undo_last(labels, skipped):
    """Remove the most recent label or skip (across sessions). Returns its gmail_id or None."""
    last_label = next(reversed(labels.values()), None)
    last_skip = next(reversed(skipped.values()), None)
    if last_label is None and last_skip is None:
        return None
    if last_skip is None or (last_label is not None and last_label["labeled_at"] >= last_skip["skipped_at"]):
        return labels.pop(last_label["gmail_id"])["gmail_id"]
    return skipped.pop(last_skip["gmail_id"])["gmail_id"]


def show(email, position, total, counts, out):
    body = strip_quoted(email["body"] or "").strip()
    preview = body[:PREVIEW_CHARS] + ("…" if len(body) > PREVIEW_CHARS else "")
    summary = "  ".join(f"{label}={counts.get(label, 0)}" for label in KEYS.values())
    out("")
    out("=" * 72)
    out(f"[{position}/{total}]  {summary}")
    out(f"From:    {email['sender'] or 'Unknown'}")
    out(f"Subject: {email['subject'] or '(no subject)'}")
    out(f"Date:    {full_date(email['received_at'])}")
    out("-" * 72)
    out(preview or "(empty body)")
    out("-" * 72)


def run(db_path=DB_PATH, labels_path=LABELS_PATH, skipped_path=SKIPPED_PATH, seed=42, input_fn=input, out=print):
    emails = {e["gmail_id"]: e for e in load_inbox(db_path)}
    labels = load_jsonl(labels_path)
    skipped = load_jsonl(skipped_path)

    order = sorted(emails)
    random.Random(seed).shuffle(order)
    queue = [gid for gid in order if gid not in labels and gid not in skipped]

    total = len(emails)
    labeled_here = sum(1 for gid in labels if gid in emails)
    skipped_here = sum(1 for gid in skipped if gid in emails)
    out(f"Inbox emails: {total}  labeled: {labeled_here}  skipped: {skipped_here}  remaining: {len(queue)}")

    while queue:
        gid = queue[0]
        done = sum(1 for g in emails if g in labels or g in skipped)
        show(emails[gid], done + 1, total, Counter(r["true_label"] for r in labels.values()), out)
        try:
            key = input_fn(PROMPT).strip().lower()
        except EOFError:
            key = "q"

        if key == "q":
            break
        if key in KEYS:
            e = emails[gid]
            labels[gid] = {
                "gmail_id": gid,
                "subject": e["subject"],
                "sender": e["sender"],
                "body": (e["body"] or "")[:STORED_BODY_CHARS],
                "received_at": e["received_at"],
                "true_label": KEYS[key],
                "labeled_at": now_iso(),
            }
            save_jsonl(labels, labels_path)
            queue.pop(0)
        elif key == "s":
            skipped[gid] = {"gmail_id": gid, "skipped_at": now_iso()}
            save_jsonl(skipped, skipped_path)
            queue.pop(0)
        elif key == "b":
            undone = undo_last(labels, skipped)
            if undone is None:
                out("Nothing to undo.")
                continue
            save_jsonl(labels, labels_path)
            save_jsonl(skipped, skipped_path)
            out(f"Undid {undone}.")
            if undone in emails:
                queue.insert(0, undone)
        else:
            out("Unknown key.")

    counts = Counter(r["true_label"] for r in labels.values())
    out(f"Saved. Labeled: {len(labels)} {dict(sorted(counts.items()))}  remaining: {len(queue)}")
    return labels


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        return 1
    run(db_path=args.db, seed=args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
