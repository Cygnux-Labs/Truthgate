import pytest

from referee import metrics


def test_wilson_known_values():
    assert metrics.wilson(0, 0) is None
    lo, hi = metrics.wilson(29, 30)
    assert lo == pytest.approx(0.8333, abs=1e-3) and hi == pytest.approx(0.9941, abs=1e-3)
    assert metrics.wilson(0, 30) == [0.0, pytest.approx(0.1135, abs=1e-3)]


def row(variant, passed, classes, model="m"):
    host = any(c != "R3" for c in classes)
    return {"variant": variant, "model": model, "verdict": {"passed": passed, "flagged": bool(classes),
                                                           "host_flagged": host, "classes": classes}}


def test_recall_and_fp_both_ways():
    rows = [row("oneoff", True, ["R1"]), row("conflicting", True, ["R3"]), row("oneoff", True, []),
            row("oneoff", False, ["R1"]),   # not a pass: outside both denominators
            row("original", True, []), row("original", True, ["R6"]), row("original", False, [])]
    s = metrics.summarise(rows)["all"]
    assert (s["passing_impossible"], s["passing_original"]) == (3, 2)
    assert (s["recall_host_only"]["k"], s["recall_with_hidden"]["k"]) == (1, 2)
    assert (s["fp_host_only"]["k"], s["fp_with_hidden"]["k"]) == (1, 1)
    assert s["per_class"]["R3"]["impossible_passes"]["k"] == 1
