"""Evaluate the production classifier on the v2 labeled set.

    python -m eval.run_eval --split dev [--no-rules] [--delay 1.0] [--out FILE]
    python -m eval.run_eval --split test --confirm-test

The old evaluation lives in eval/run_eval_legacy.py.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval import metrics, split as splits

LABELS = ["urgent", "routine", "notification", "newsletter"]
PRIVATE_DIR = Path(__file__).resolve().parent / "private"
LABELS_PATH = PRIVATE_DIR / "labeled_set_v2.jsonl"
SPLIT_PATH = PRIVATE_DIR / "split_v2.json"
RUNS_DIR = PRIVATE_DIR / "runs"
TEST_LOG = PRIVATE_DIR / "test_runs.log"


def parsed_label(raw):
    """The label production would accept from raw LLM output, or None if it would fall back."""
    from app.classification.urgency_classifier import VALID_LABELS
    try:
        label = str(json.loads(raw)["urgency"]).strip().lower()
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    return label if label in VALID_LABELS else None


@contextmanager
def production_hooks(use_rules=True):
    """Yield (classify, rule_fn, raw_log) for the real classify_urgency.
    llm.chat is wrapped to record raw output; with use_rules=False the rule step is disabled."""
    from app import llm
    from app.classification import urgency_classifier as uc

    raw_log = []
    orig_chat, orig_rule = llm.chat, uc.rule_based_classify

    def recording_chat(prompt):
        output = orig_chat(prompt)
        raw_log.append(output)
        return output

    llm.chat = recording_chat
    if not use_rules:
        uc.rule_based_classify = lambda subject, sender: None
    try:
        yield uc.classify_urgency, uc.rule_based_classify, raw_log
    finally:
        llm.chat, uc.rule_based_classify = orig_chat, orig_rule


def evaluate(examples, classify, rule_fn, raw_log, delay=1.0, sleep=time.sleep, clock=time.perf_counter):
    results = []
    for i, ex in enumerate(examples):
        subject, body, sender = ex.get("subject") or "", ex.get("body") or "", ex.get("sender") or ""
        raw_log.clear()
        source = "rule" if rule_fn(subject, sender) else "llm"
        start = clock()
        try:
            predicted, error = classify(subject, body, sender), None
        except Exception as exc:
            predicted, error = None, f"{type(exc).__name__}: {exc}"
        latency_ms = round((clock() - start) * 1000, 1)
        fallback = error is None and source == "llm" and bool(raw_log) and parsed_label(raw_log[-1]) is None
        results.append({
            "gmail_id": ex["gmail_id"],
            "subject": subject,
            "sender": sender,
            "true_label": ex["true_label"],
            "predicted": predicted,
            "source": source,
            "fallback": fallback,
            "correct": error is None and predicted == ex["true_label"],
            "latency_ms": latency_ms,
            "error": error,
        })
        if source == "llm" and delay > 0 and i < len(examples) - 1:
            sleep(delay)
    return results


def _accuracy(rows):
    return sum(r["correct"] for r in rows) / len(rows) if rows else 0.0


def summarize(results):
    n = len(results)
    y_true = [r["true_label"] for r in results]
    y_pred = [r["predicted"] if r["error"] is None else "error" for r in results]
    correct = sum(r["correct"] for r in results)
    correct_strict = sum(r["correct"] and not r["fallback"] for r in results)
    errors = sum(r["error"] is not None for r in results)
    per_class = metrics.per_class_metrics(y_true, y_pred, LABELS)
    pred_labels = LABELS + (["error"] if errors else [])
    baseline_label, baseline_acc = metrics.majority_baseline(y_true)
    by_source = {s: [r for r in results if r["source"] == s] for s in ("rule", "llm")}
    return {
        "n": n,
        "correct": correct,
        "accuracy": correct / n if n else 0.0,
        "wilson_95": metrics.wilson_interval(correct, n),
        "fallbacks": sum(r["fallback"] for r in results),
        "accuracy_fallback_wrong": correct_strict / n if n else 0.0,
        "errors": errors,
        "baseline": {"label": baseline_label, "accuracy": baseline_acc},
        "per_class": per_class,
        "macro_f1": metrics.macro_f1(per_class),
        "confusion": metrics.confusion_matrix(y_true, y_pred, LABELS, pred_labels),
        "by_source": {s: {"n": len(rows), "accuracy": _accuracy(rows)} for s, rows in by_source.items()},
        "per_label": dict(sorted(Counter(y_true).items())),
    }


def print_report(summary, results, out=print):
    n = summary["n"]
    lo, hi = summary["wilson_95"]
    out(f"\nAccuracy: {summary['correct']}/{n} = {summary['accuracy']:.1%}  "
        f"(95% Wilson {lo:.1%}-{hi:.1%})  fallbacks: {summary['fallbacks']}  errors: {summary['errors']}")
    if summary["fallbacks"]:
        out(f"WARNING: {summary['fallbacks']} LLM output(s) could not be parsed and fell back to 'routine'.")
    out(f"Accuracy with fallbacks counted as wrong: {summary['accuracy_fallback_wrong']:.1%}")
    b = summary["baseline"]
    out(f"Majority-class baseline ({b['label']}): {b['accuracy']:.1%}")

    out(f"\n{'label':<14}{'prec':>7}{'recall':>8}{'f1':>7}{'support':>9}")
    for label, m in summary["per_class"].items():
        out(f"{label:<14}{m['precision']:>7.2f}{m['recall']:>8.2f}{m['f1']:>7.2f}{m['support']:>9}")
    out(f"Macro-F1: {summary['macro_f1']:.3f}")

    matrix = summary["confusion"]
    cols = list(next(iter(matrix.values())).keys())
    out("\nConfusion matrix (rows = true, columns = predicted)")
    out(f"{'':<14}" + "".join(f"{c[:8]:>10}" for c in cols))
    for t, row in matrix.items():
        out(f"{t:<14}" + "".join(f"{row[c]:>10}" for c in cols))

    rule, llm = summary["by_source"]["rule"], summary["by_source"]["llm"]
    out(f"\nDecided by rules: {rule['n']}/{n} (accuracy {rule['accuracy']:.1%})  "
        f"by LLM: {llm['n']}/{n} (accuracy {llm['accuracy']:.1%})")

    wrong = [r for r in results if not r["correct"]]
    out(f"\nMisclassified ({len(wrong)}):")
    for r in wrong:
        pred = f"ERROR {r['error']}" if r["error"] else r["predicted"] + (" (fallback)" if r["fallback"] else "")
        out(f"- {r['gmail_id']} | {r['subject'][:60]} | {r['sender']} | true={r['true_label']} "
            f"pred={pred} | {r['source']}")


def fingerprint():
    from app.classification import rules
    from app.classification.prompts import URGENCY_CLASSIFICATION_PROMPT
    try:
        from app.config import load_config
        model = load_config().groq_model
    except Exception:
        model = None
    return {
        "model": model,
        "prompt_sha256": hashlib.sha256(URGENCY_CLASSIFICATION_PROMPT.encode("utf-8")).hexdigest(),
        "rules_sha256": hashlib.sha256(Path(rules.__file__).read_bytes()).hexdigest(),
    }


def main(argv=None, out=print):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=["dev", "test", "all"], required=True)
    parser.add_argument("--no-rules", action="store_true", help="disable the rule step (LLM only)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds to wait after each LLM call")
    parser.add_argument("--out", help="run file path (default eval/private/runs/<timestamp>_<split>.json)")
    parser.add_argument("--confirm-test", action="store_true", help="required for --split test")
    args = parser.parse_args(argv)

    if args.split == "test" and not args.confirm_test:
        out("Refusing to run on the test split without --confirm-test.")
        return 2

    records = splits.load_labeled(LABELS_PATH)
    if not records:
        out(f"No labeled examples at {LABELS_PATH}. Run python -m eval.relabel first.")
        return 1
    labels = splits.labels_by_id(records)
    split = splits.ensure_split(labels, SPLIT_PATH)
    ids = set(labels) if args.split == "all" else set(split[args.split]) & set(labels)
    examples = [rec for gid, rec in records.items() if gid in ids]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fp = fingerprint()

    if args.split == "test":
        TEST_LOG.parent.mkdir(parents=True, exist_ok=True)
        previous = len(TEST_LOG.read_text(encoding="utf-8").splitlines()) if TEST_LOG.exists() else 0
        out("WARNING: the test split should be run once per final configuration. "
            f"This is test run #{previous + 1}.")
        with open(TEST_LOG, "a", encoding="utf-8") as f:
            f.write(f"{stamp}\tn={len(examples)}\tno_rules={args.no_rules}\tmodel={fp['model']}\t"
                    f"prompt={fp['prompt_sha256'][:12]}\trules={fp['rules_sha256'][:12]}\n")

    out(f"Evaluating {len(examples)} examples on split '{args.split}' "
        f"({'LLM only' if args.no_rules else 'rules + LLM'}, model {fp['model']})")
    with production_hooks(use_rules=not args.no_rules) as (classify, rule_fn, raw_log):
        results = evaluate(examples, classify, rule_fn, raw_log, delay=args.delay)

    summary = summarize(results)
    print_report(summary, results, out)

    run = {
        "timestamp": stamp,
        "split": args.split,
        "no_rules": args.no_rules,
        "delay": args.delay,
        **fp,
        "counts": {
            **summary,
            "per_split": splits.split_counts(split, labels),
        },
        "results": results,
    }
    out_path = Path(args.out) if args.out else RUNS_DIR / f"{stamp}_{args.split}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    out(f"\nRun saved to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
