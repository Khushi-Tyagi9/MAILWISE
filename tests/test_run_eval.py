import json
from contextlib import contextmanager

import pytest

from eval import run_eval


def example(gid, label, subject=None, sender="Person <p@x.com>", body=None):
    return {"gmail_id": gid, "subject": subject or f"Subject {gid}", "sender": sender,
            "body": body or f"BODYTEXT-{gid}", "true_label": label}


def no_rule(subject, sender):
    return None


# --- evaluate -----------------------------------------------------------------

def test_errors_are_counted_separately_and_never_correct():
    def classify(subject, body, sender):
        if "boom" in subject:
            raise RuntimeError("LLM down")
        return "urgent"

    examples = [example("a", "urgent"), example("b", "urgent", subject="boom"), example("c", "routine")]
    results = run_eval.evaluate(examples, classify, no_rule, [], delay=0)
    assert [r["correct"] for r in results] == [True, False, False]
    assert results[1]["predicted"] is None
    assert results[1]["error"] == "RuntimeError: LLM down"

    s = run_eval.summarize(results)
    assert (s["n"], s["correct"], s["errors"]) == (3, 1, 1)
    assert s["accuracy"] == pytest.approx(1 / 3)
    assert s["confusion"]["urgent"]["error"] == 1
    assert s["per_class"]["urgent"]["recall"] == 0.5


def test_source_and_delay():
    rule_fn = lambda subject, sender: "newsletter" if "noreply" in sender else None
    sleeps = []
    examples = [example("a", "routine"), example("b", "newsletter", sender="noreply@x.com"),
                example("c", "routine"), example("d", "routine")]
    results = run_eval.evaluate(examples, lambda s, b, se: rule_fn(s, se) or "routine", rule_fn, [],
                                delay=1.5, sleep=sleeps.append)
    assert [r["source"] for r in results] == ["llm", "rule", "llm", "llm"]
    assert sleeps == [1.5, 1.5]  # after LLM calls only, not after the last example

    s = run_eval.summarize(results)
    assert s["by_source"] == {"rule": {"n": 1, "accuracy": 1.0}, "llm": {"n": 3, "accuracy": 1.0}}


def test_fallback_counts_as_routine_but_is_flagged(fake_groq):
    fake_groq.reply("not json", '{"urgency": "urgent"}', '{"urgency": "banana"}')
    examples = [example("a", "routine"), example("b", "urgent"), example("c", "newsletter")]
    with run_eval.production_hooks() as (classify, rule_fn, raw_log):
        results = run_eval.evaluate(examples, classify, rule_fn, raw_log, delay=0)
    assert [r["predicted"] for r in results] == ["routine", "urgent", "routine"]
    assert [r["fallback"] for r in results] == [True, False, True]
    assert [r["correct"] for r in results] == [True, True, False]

    s = run_eval.summarize(results)
    assert s["fallbacks"] == 2
    assert s["accuracy"] == pytest.approx(2 / 3)
    assert s["accuracy_fallback_wrong"] == pytest.approx(1 / 3)

    lines = []
    run_eval.print_report(s, results, out=lines.append)
    text = "\n".join(lines)
    assert "fallbacks: 2" in lines[0]
    assert "WARNING: 2 LLM output(s) could not be parsed" in text
    assert "Accuracy with fallbacks counted as wrong: 33.3%" in text


def test_no_warning_without_fallbacks():
    results = run_eval.evaluate([example("a", "routine")], lambda *a: "routine", no_rule, [], delay=0)
    lines = []
    run_eval.print_report(run_eval.summarize(results), results, out=lines.append)
    assert not any(line.startswith("WARNING") for line in lines)


def test_no_rules_sends_everything_to_the_llm(fake_groq):
    fake_groq.reply(default='{"urgency": "routine"}')
    examples = [example("a", "newsletter", sender="noreply@shop.com")]

    with run_eval.production_hooks(use_rules=True) as (classify, rule_fn, raw_log):
        with_rules = run_eval.evaluate(examples, classify, rule_fn, raw_log, delay=0)
    assert with_rules[0]["source"] == "rule" and with_rules[0]["predicted"] == "newsletter"
    assert fake_groq.calls == []

    with run_eval.production_hooks(use_rules=False) as (classify, rule_fn, raw_log):
        llm_only = run_eval.evaluate(examples, classify, rule_fn, raw_log, delay=0)
    assert llm_only[0]["source"] == "llm" and llm_only[0]["predicted"] == "routine"
    assert len(fake_groq.calls) == 1

    # hooks are restored afterwards
    from app.classification import urgency_classifier as uc
    assert uc.rule_based_classify("x", "noreply@shop.com") == "newsletter"


def test_print_report_lists_misclassified():
    results = run_eval.evaluate([example("a", "urgent", subject="Exam today")], lambda *a: "routine",
                                no_rule, [], delay=0)
    lines = []
    run_eval.print_report(run_eval.summarize(results), results, out=lines.append)
    assert "- a | Exam today | Person <p@x.com> | true=urgent pred=routine | llm" in lines


# --- main -------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    monkeypatch.setattr(run_eval, "LABELS_PATH", private / "labels.jsonl")
    monkeypatch.setattr(run_eval, "SPLIT_PATH", private / "split.json")
    monkeypatch.setattr(run_eval, "RUNS_DIR", private / "runs")
    monkeypatch.setattr(run_eval, "TEST_LOG", private / "test_runs.log")

    records = [example(f"u{i}", "urgent") for i in range(4)] + [example(f"r{i}", "routine") for i in range(6)]
    with open(private / "labels.jsonl", "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    @contextmanager
    def fake_hooks(use_rules=True):
        yield (lambda subject, body, sender: "routine"), no_rule, []

    monkeypatch.setattr(run_eval, "production_hooks", fake_hooks)
    return private


def run_main(argv):
    lines = []
    rc = run_eval.main(argv, out=lines.append)
    return rc, "\n".join(lines)


def test_test_split_requires_confirmation(workspace):
    rc, output = run_main(["--split", "test"])
    assert rc == 2
    assert "--confirm-test" in output
    assert not (workspace / "test_runs.log").exists()
    assert not (workspace / "runs").exists()


def test_test_runs_are_logged_and_counted(workspace):
    rc, output = run_main(["--split", "test", "--confirm-test", "--delay", "0"])
    assert rc == 0
    assert "WARNING: the test split should be run once per final configuration" in output
    assert "test run #1" in output
    rc, output = run_main(["--split", "test", "--confirm-test", "--delay", "0"])
    assert "test run #2" in output
    log = (workspace / "test_runs.log").read_text().splitlines()
    assert len(log) == 2 and "model=test-model" in log[0]


def test_dev_run_does_not_log_test_run(workspace):
    rc, _ = run_main(["--split", "dev", "--delay", "0"])
    assert rc == 0
    assert not (workspace / "test_runs.log").exists()


def test_run_file_contents_and_no_bodies(workspace, tmp_path):
    out = tmp_path / "run.json"
    rc, output = run_main(["--split", "all", "--delay", "0", "--out", str(out)])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "BODYTEXT" not in text
    assert '"body"' not in text
    run = json.loads(text)
    assert run["split"] == "all"
    assert run["model"] == "test-model"
    assert len(run["prompt_sha256"]) == 64 and len(run["rules_sha256"]) == 64
    counts = run["counts"]
    assert counts["n"] == 10 and counts["correct"] == 6
    assert counts["per_label"] == {"routine": 6, "urgent": 4}
    assert counts["per_split"]["dev"] == {"routine": 4, "urgent": 3}
    assert counts["per_split"]["test"] == {"routine": 2, "urgent": 1}
    assert counts["baseline"] == {"label": "routine", "accuracy": 0.6}
    assert len(run["results"]) == 10
    assert "Accuracy: 6/10 = 60.0%" in output


def test_default_run_file_location(workspace):
    rc, _ = run_main(["--split", "dev", "--delay", "0"])
    files = list((workspace / "runs").glob("*_dev.json"))
    assert rc == 0 and len(files) == 1
    assert json.loads(files[0].read_text())["counts"]["n"] == 7


def test_missing_labels_file(workspace):
    (workspace / "labels.jsonl").unlink()
    rc, output = run_main(["--split", "dev"])
    assert rc == 1 and "eval.relabel" in output
