"""run_rules(extraction, spec) -> (findings, verdict): all rules, pure, shared by API and eval."""

from app.parsing import parse_ingredients
from app.rules.allergens import check_allergens
from app.rules.claims import check_claims
from app.rules.general import (
    check_front,
    check_image_quality,
    check_label_missing,
    check_per,
    check_truncated,
)
from app.rules.nutrition import check_nutrition, read_nutrition
from app.schemas import Finding, LabelExtraction, ProductSpec, Verdict

# Bump on any change of a rule, threshold or dictionary: stored with every check (audit).
RULES_VERSION = "2026-10-02.1"


def verdict_of(findings: list[Finding]) -> Verdict:
    """fail (a violation) > needs_review > incomplete (something not_checked) > pass."""
    statuses = {f.status for f in findings}
    if "violation" in statuses:
        return "fail"
    if "needs_review" in statuses:
        return "needs_review"
    if "not_checked" in statuses:
        return "incomplete"
    return "pass"


def run_rules(
    extraction: LabelExtraction, spec: ProductSpec | None
) -> tuple[list[Finding], Verdict]:
    item = extraction.ingredients_marked
    ing = parse_ingredients(item.text if item else None)
    facts = read_nutrition(extraction.nutrition)
    findings = [
        *check_image_quality(extraction),
        *check_label_missing(extraction, facts),
        *check_truncated(extraction, ing),
        *check_front(extraction),
        *check_per(facts),
        *check_allergens(extraction, spec),
        *check_claims(extraction, spec, facts, ing),
        *check_nutrition(extraction, spec),
    ]
    return findings, verdict_of(findings)
