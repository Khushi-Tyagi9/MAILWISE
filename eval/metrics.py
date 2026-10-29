"""Pure metric helpers for the classifier evaluation. No app imports."""
import math
from collections import Counter


def wilson_interval(k, n, z=1.96):
    """Wilson score interval for k successes out of n trials."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def majority_baseline(y_true):
    """(label, accuracy) of always predicting the most common true label."""
    if not y_true:
        return (None, 0.0)
    counts = Counter(y_true)
    label = max(sorted(counts), key=lambda l: counts[l])
    return (label, counts[label] / len(y_true))


def per_class_metrics(y_true, y_pred, labels):
    """{label: {precision, recall, f1, support}}. Predictions outside `labels`
    (e.g. "error") count as misses for the true class."""
    out = {}
    for c in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == c and p != c)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out[c] = {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}
    return out


def macro_f1(per_class):
    """Mean F1 over classes that have support."""
    scores = [m["f1"] for m in per_class.values() if m["support"]]
    return sum(scores) / len(scores) if scores else 0.0


def confusion_matrix(y_true, y_pred, labels, pred_labels=None):
    """{true: {pred: count}}. `pred_labels` defaults to `labels`."""
    pred_labels = list(pred_labels or labels)
    matrix = {t: {p: 0 for p in pred_labels} for t in labels}
    for t, p in zip(y_true, y_pred):
        if t in matrix and p in matrix[t]:
            matrix[t][p] += 1
    return matrix
