import json

from eval import split as splits


def make_labels():
    labels = {}
    for i in range(20):
        labels[f"n{i:02d}"] = "newsletter"
    for i in range(10):
        labels[f"r{i:02d}"] = "routine"
    for i in range(4):
        labels[f"u{i:02d}"] = "urgent"
    labels["t00"], labels["t01"] = "notification", "notification"
    return labels


def test_split_is_deterministic_and_disjoint():
    labels = make_labels()
    a = splits.stratified_split(labels)
    b = splits.stratified_split(dict(reversed(list(labels.items()))))
    assert a == b
    assert not set(a["dev"]) & set(a["test"])
    assert set(a["dev"]) | set(a["test"]) == set(labels)


def test_split_is_stratified_with_every_class_in_both():
    labels = make_labels()
    s = splits.stratified_split(labels)
    counts = splits.split_counts(s, labels)
    assert counts["dev"] == {"newsletter": 14, "notification": 1, "routine": 7, "urgent": 3}
    assert counts["test"] == {"newsletter": 6, "notification": 1, "routine": 3, "urgent": 1}


def test_single_example_class_goes_to_dev():
    s = splits.stratified_split({"a": "urgent", "b": "routine", "c": "routine"})
    assert "a" in s["dev"]


def test_different_seed_changes_split():
    labels = make_labels()
    assert splits.stratified_split(labels, seed=1) != splits.stratified_split(labels, seed=42)


def test_ensure_split_saves_once_and_never_moves_existing(tmp_path):
    path = tmp_path / "split.json"
    labels = make_labels()
    first = splits.ensure_split(labels, path)
    saved = json.loads(path.read_text())
    assert saved == first

    more = dict(labels)
    for i in range(10):
        more[f"x{i:02d}"] = "routine"
    second = splits.ensure_split(more, path)
    assert set(first["dev"]) <= set(second["dev"])
    assert set(first["test"]) <= set(second["test"])
    assert not set(second["dev"]) & set(second["test"])
    assert set(second["dev"]) | set(second["test"]) == set(more)
    routine = splits.split_counts(second, more)
    assert routine["dev"]["routine"] == 14 and routine["test"]["routine"] == 6

    # Loading again with no new labels changes nothing.
    assert splits.ensure_split(more, path) == second


def test_new_class_lands_in_both_splits(tmp_path):
    path = tmp_path / "split.json"
    labels = {"a": "routine", "b": "routine"}
    splits.ensure_split(labels, path)
    labels.update({"u1": "urgent", "u2": "urgent"})
    s = splits.ensure_split(labels, path)
    counts = splits.split_counts(s, labels)
    assert counts["dev"].get("urgent") == 1 and counts["test"].get("urgent") == 1


def write_labels(path, labels):
    with open(path, "w", encoding="utf-8") as f:
        for gid, label in labels.items():
            f.write(json.dumps({"gmail_id": gid, "true_label": label}) + "\n")


def test_resplit_requires_yes(tmp_path):
    labels_path, split_path = tmp_path / "labels.jsonl", tmp_path / "split.json"
    write_labels(labels_path, make_labels())
    assert splits.main([], labels_path=labels_path, split_path=split_path) == 0
    split_path.write_text(json.dumps({"seed": 0, "dev": ["n00"], "test": []}))

    rc = splits.main(["--resplit"], input_fn=lambda prompt: "no", labels_path=labels_path, split_path=split_path)
    assert rc == 1
    assert json.loads(split_path.read_text())["seed"] == 0

    rc = splits.main(["--resplit"], input_fn=lambda prompt: "yes", labels_path=labels_path, split_path=split_path)
    assert rc == 0
    assert json.loads(split_path.read_text()) == splits.stratified_split(make_labels())
