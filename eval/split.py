"""Deterministic stratified dev/test split, saved once to eval/private/split_v2.json.

    python -m eval.split            # create if missing, assign newly labeled emails, show counts
    python -m eval.split --resplit  # regenerate from scratch (asks for confirmation)
"""
import argparse
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PRIVATE_DIR = Path(__file__).resolve().parent / "private"
LABELS_PATH = PRIVATE_DIR / "labeled_set_v2.jsonl"
SPLIT_PATH = PRIVATE_DIR / "split_v2.json"
SEED = 42
DEV_FRACTION = 0.7


def load_labeled(path):
    """{gmail_id: record} in file order."""
    path = Path(path)
    records = {}
    if not path.exists():
        return records
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                records[rec["gmail_id"]] = rec
    return records


def labels_by_id(records):
    return {gid: rec["true_label"] for gid, rec in records.items()}


def stratified_split(labels, seed=SEED, dev_fraction=DEV_FRACTION):
    """Split {gmail_id: label} per class. Every class with 2+ examples lands in both splits."""
    rng = random.Random(seed)
    dev, test = [], []
    for label in sorted(set(labels.values())):
        ids = sorted(gid for gid, l in labels.items() if l == label)
        rng.shuffle(ids)
        n_dev = round(len(ids) * dev_fraction)
        if len(ids) >= 2:
            n_dev = min(max(n_dev, 1), len(ids) - 1)
        dev += ids[:n_dev]
        test += ids[n_dev:]
    return {"seed": seed, "dev_fraction": dev_fraction, "dev": sorted(dev), "test": sorted(test)}


def assign_new(split, labels, dev_fraction=DEV_FRACTION):
    """Add labeled ids missing from the split without moving existing ones.
    Each goes where its class ends up closest to dev_fraction; ties go to dev.
    Returns the list of ids added."""
    dev, test = set(split["dev"]), set(split["test"])
    new = sorted(gid for gid in labels if gid not in dev and gid not in test)
    for gid in new:
        label = labels[gid]
        d = sum(1 for x in dev if labels.get(x) == label)
        t = sum(1 for x in test if labels.get(x) == label)
        total = d + t + 1
        if abs((d + 1) / total - dev_fraction) <= abs(d / total - dev_fraction):
            dev.add(gid)
        else:
            test.add(gid)
    split["dev"], split["test"] = sorted(dev), sorted(test)
    return new


def save_split(split, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(split, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def ensure_split(labels, path=None):
    """Load the saved split (creating it the first time) and assign any new ids."""
    path = Path(path or SPLIT_PATH)
    if not path.exists():
        split = stratified_split(labels)
        save_split(split, path)
        return split
    split = json.loads(path.read_text(encoding="utf-8"))
    if assign_new(split, labels):
        save_split(split, path)
    return split


def split_counts(split, labels):
    """{"dev": {label: n}, "test": {label: n}} counting only currently labeled ids."""
    return {
        name: dict(sorted(Counter(labels[g] for g in split[name] if g in labels).items()))
        for name in ("dev", "test")
    }


def main(argv=None, input_fn=input, labels_path=None, split_path=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--resplit", action="store_true", help="regenerate the split from scratch")
    args = parser.parse_args(argv)

    split_path = Path(split_path or SPLIT_PATH)
    labels = labels_by_id(load_labeled(labels_path or LABELS_PATH))
    if not labels:
        print("No labeled emails yet. Run python -m eval.relabel first.")
        return 1

    if args.resplit and split_path.exists():
        answer = input_fn("Regenerating the split moves examples between dev and test. Type yes to continue: ")
        if answer.strip().lower() != "yes":
            print("Split left unchanged.")
            return 1
        split_path.unlink()

    split = ensure_split(labels, split_path)
    for name, counts in split_counts(split, labels).items():
        print(f"{name}: {sum(counts.values())} {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
