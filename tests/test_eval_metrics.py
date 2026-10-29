import pytest

from eval import metrics

LABELS = ["urgent", "routine", "notification", "newsletter"]
Y_TRUE = ["urgent", "urgent", "urgent", "routine", "routine", "notification", "newsletter", "newsletter"]
Y_PRED = ["urgent", "urgent", "routine", "routine", "urgent", "notification", "newsletter", "error"]


def test_per_class_metrics_match_hand_computed_values():
    m = metrics.per_class_metrics(Y_TRUE, Y_PRED, LABELS)
    # urgent: tp=2 fp=1 fn=1
    assert m["urgent"]["precision"] == pytest.approx(2 / 3)
    assert m["urgent"]["recall"] == pytest.approx(2 / 3)
    assert m["urgent"]["f1"] == pytest.approx(2 / 3)
    assert m["urgent"]["support"] == 3
    # routine: tp=1 fp=1 fn=1
    assert (m["routine"]["precision"], m["routine"]["recall"], m["routine"]["f1"]) == pytest.approx((0.5, 0.5, 0.5))
    # notification: perfect
    assert (m["notification"]["precision"], m["notification"]["recall"]) == (1.0, 1.0)
    # newsletter: tp=1 fp=0 fn=1 (the "error" prediction is a miss)
    assert m["newsletter"]["precision"] == 1.0
    assert m["newsletter"]["recall"] == 0.5
    assert m["newsletter"]["f1"] == pytest.approx(2 / 3)
    assert m["newsletter"]["support"] == 2


def test_macro_f1():
    m = metrics.per_class_metrics(Y_TRUE, Y_PRED, LABELS)
    assert metrics.macro_f1(m) == pytest.approx((2 / 3 + 0.5 + 1.0 + 2 / 3) / 4)


def test_macro_f1_ignores_classes_without_support():
    m = metrics.per_class_metrics(["urgent", "urgent"], ["urgent", "routine"], LABELS)
    assert metrics.macro_f1(m) == pytest.approx(2 / 3)


def test_zero_denominators_give_zero():
    m = metrics.per_class_metrics(["urgent"], ["urgent"], LABELS)
    assert m["routine"] == {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 0}


def test_confusion_matrix():
    cm = metrics.confusion_matrix(Y_TRUE, Y_PRED, LABELS, LABELS + ["error"])
    assert cm["urgent"] == {"urgent": 2, "routine": 1, "notification": 0, "newsletter": 0, "error": 0}
    assert cm["routine"] == {"urgent": 1, "routine": 1, "notification": 0, "newsletter": 0, "error": 0}
    assert cm["notification"]["notification"] == 1
    assert cm["newsletter"] == {"urgent": 0, "routine": 0, "notification": 0, "newsletter": 1, "error": 1}
    assert sum(sum(row.values()) for row in cm.values()) == len(Y_TRUE)


def test_wilson_interval_hand_computed():
    # p=0.8, n=10, z=1.96: centre=0.99208/1.38416, half=1.96*sqrt(0.025604)/1.38416
    lo, hi = metrics.wilson_interval(8, 10)
    assert lo == pytest.approx(0.49016, abs=1e-4)
    assert hi == pytest.approx(0.94332, abs=1e-4)


def test_wilson_interval_edges():
    lo, hi = metrics.wilson_interval(0, 10)
    assert lo == 0.0
    assert hi == pytest.approx(0.27753, abs=1e-4)
    lo, hi = metrics.wilson_interval(10, 10)
    assert lo == pytest.approx(0.72247, abs=1e-4)
    assert hi == 1.0
    assert metrics.wilson_interval(0, 0) == (0.0, 0.0)


def test_majority_baseline():
    assert metrics.majority_baseline(Y_TRUE) == ("urgent", 3 / 8)
    assert metrics.majority_baseline([]) == (None, 0.0)
    # ties break alphabetically so the result is deterministic
    assert metrics.majority_baseline(["routine", "newsletter"])[0] == "newsletter"
