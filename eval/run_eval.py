import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.classification.urgency_classifier import classify_urgency

def load_labeled_set(path):
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            examples.append(json.loads(line))
    return examples

def run_eval():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "labeled_set.jsonl")
    examples = load_labeled_set(path)

    correct = 0
    results = []

    for ex in examples:
        predicted = classify_urgency(ex["subject"], ex["body"])
        true_label = ex["true_urgency"]
        is_correct = predicted == true_label
        correct += is_correct

        results.append({
            "subject": ex["subject"][:50],
            "true": true_label,
            "predicted": predicted,
            "correct": is_correct
        })

        status = "correct" if is_correct else "WRONG"
        print(f"[{status}] {ex['subject'][:50]} | true={true_label} predicted={predicted}")

    accuracy = correct / len(examples)
    print(f"\nAccuracy: {correct}/{len(examples)} = {accuracy:.1%}")

    return results, accuracy


if __name__ == "__main__":
    run_eval()