"""eval/metrics.py: Wilson on known numbers; a violation is found only by its own rule_id +
target; errors and out_of_scope are kept out of the trust number."""

import pytest

from eval.metrics import compute, markdown, score, wilson


def test_wilson_on_known_values():
    assert wilson(0, 10) == pytest.approx((0.0, 0.2775), abs=1e-4)
    assert wilson(5, 10) == pytest.approx((0.2366, 0.7634), abs=1e-4)
    assert wilson(28, 30) == pytest.approx((0.7868, 0.9815), abs=1e-4)
    assert wilson(0, 0) is None


def row(id="c1", violations=(), flags=(), findings=(), verdict="pass", status="done", **extra):
    out = {
        "id": id,
        "case": id,
        "group": "synthetic",
        "in_trust_number": True,
        "folder": "-",
        "spec": None,
        "violations": [{"rule_id": r, "target": t} for r, t in violations],
        "expected_flags": [{"rule_id": r, "target": t} for r, t in flags],
        "meta": {"quality": "clean"},
        "status": status,
    }
    out |= extra
    if status == "done":
        out |= {
            "verdict": verdict,
            "findings": [{"rule_id": r, "target": t, "status": s} for r, t, s in findings],
        }
    else:
        out["error"] = {"code": "vision_unavailable", "message": "-"}
    return out


SUGAR = ("sugar_free", "sugar_free")


def test_a_finding_with_another_target_does_not_count():
    r = row(violations=[SUGAR], findings=[("sugar_free", "low_sugar", "violation")], verdict="fail")
    assert score([r], with_truth=False)["safe_recall"]["k"] == 0


def test_needs_review_for_a_bad_photo_does_not_find_another_violation():
    r = row(
        violations=[SUGAR],
        findings=[("IMG-QUALITY", "photo_0", "needs_review"), ("sugar_free", "sugar_free", "pass")],
        verdict="needs_review",
    )
    s = score([r], with_truth=False)
    assert s["safe_recall"]["k"] == 0 and s["safe_recall"]["n"] == 1


def test_safe_strict_load_false_alarms():
    rows = [
        row("v1", violations=[SUGAR], findings=[("sugar_free", "sugar_free", "needs_review")]),
        row("v2", violations=[SUGAR], findings=[("sugar_free", "sugar_free", "violation")]),
        row("c1", findings=[("NUT-ENERGY", "energy", "needs_review")], verdict="needs_review"),
        row("c2", findings=[("fat_low", "fat_low", "violation")], verdict="fail"),
        row("c3", findings=[("ALG-SPEC-MISSING", None, "not_checked")], verdict="incomplete"),
    ]
    s = score(rows, with_truth=False)
    assert (s["safe_recall"]["k"], s["safe_recall"]["n"]) == (2, 2)
    assert (s["strict_recall"]["k"], s["strict_recall"]["n"]) == (1, 2)
    assert (s["load"]["k"], s["load"]["n"]) == (2, 3)  # incomplete is not load
    assert s["false_alarms"] == [{"id": "c2", "rule_id": "fat_low", "target": "fat_low"}]


def test_photo_flags_are_apart_from_recall_and_errors_are_not_in_the_denominator():
    rows = [
        row(
            "crop",
            flags=[("LABEL-TRUNCATED", "ingredients")],
            findings=[("LABEL-TRUNCATED", "ingredients", "pass")],
        ),
        row("err", violations=[SUGAR], status="error"),
        row("v", violations=[SUGAR], findings=[("sugar_free", "sugar_free", "violation")]),
    ]
    s = score(rows, with_truth=False)
    assert s["flags"]["LABEL-TRUNCATED"]["k"] == 0 and s["flags"]["LABEL-TRUNCATED"]["n"] == 1
    assert (s["safe_recall"]["k"], s["safe_recall"]["n"]) == (1, 1)
    assert (s["safe_recall_errors_as_missed"]["k"], s["safe_recall_errors_as_missed"]["n"]) == (
        1,
        2,
    )
    assert s["errors"] == [{"id": "err", "code": "vision_unavailable"}]
    assert s["load"]["n"] == 0  # a cropped case is not a clean one


def test_out_of_scope_is_not_in_the_main_number():
    rows = [
        row("ua", violations=[SUGAR], findings=[("sugar_free", "sugar_free", "violation")]),
        row("bg", violations=[SUGAR], in_trust_number=False),
    ]
    rows[1]["group"] = "out_of_scope"
    m = compute({"units": rows}, with_truth=False)
    assert (m["main"]["safe_recall"]["k"], m["main"]["safe_recall"]["n"]) == (1, 1)
    assert m["out_of_scope"]["safe_recall"]["n"] == 1
    report = {"split": "test", "date": "d", "model": "m", "prompt_version": "p",
              "rules_version": "r", "units": rows}  # fmt: skip
    text = markdown(report, m)
    assert "Поза ринком, для інформації" in text and "1 з 1 = 100 %" in text
