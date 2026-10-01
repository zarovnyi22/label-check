"""Metrics of an eval report (docs/SPEC.md §4) and its markdown next to the JSON.

    python -m eval.metrics eval/reports/<split>_<date>.json      (make eval runs it)

A violation counts as found ONLY by a finding with the same rule_id AND target and status
violation (strict) or violation/needs_review (safe), never by the verdict: a needs_review for a
blurry photo does not "find" a "без цукру" violation. Units with a model error are not in the
recall denominators, but are reported next to it (and the recall if each error were a miss).
The trust number covers in_trust_number units only; out_of_scope is reported apart.
"""

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from app.parsing import parse_amount, parse_energy
from app.rules.claims import find_claims
from app.rules.engine import run_rules
from app.schemas import LabelExtraction, ProductSpec

REPO = Path(__file__).resolve().parent.parent
SHOWN = ("violation", "needs_review")
LOAD_VERDICTS = ("fail", "needs_review")
NUMBERS = ("fat", "saturates", "carbs", "sugars", "fibre", "protein", "salt")
Key = tuple[str, str | None]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95 % Wilson score interval of k successes out of n; None for n = 0."""
    if n == 0:
        return None
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def _key(item: dict) -> Key:
    return item["rule_id"], item["target"]


def shown(row: dict, statuses=SHOWN) -> set[Key]:
    return {_key(f) for f in row.get("findings", []) if f["status"] in statuses}


def is_clean(row: dict) -> bool:
    return not row["violations"] and not row["expected_flags"]


def ratio(k: int, n: int) -> dict:
    return {"k": k, "n": n, "share": k / n if n else None, "ci": wilson(k, n)}


# --- truth side: rules on the ideal extraction, reading accuracy ------------------------------


def _truth(row: dict) -> tuple[LabelExtraction, ProductSpec | None]:
    folder = REPO / row["folder"]
    truth = json.loads((folder / "truth.json").read_text(encoding="utf-8"))
    spec = None
    if row["spec"]:
        spec = ProductSpec.model_validate_json((folder / row["spec"]).read_text())
    return LabelExtraction.model_validate(truth["extraction"]), spec


def _same_amount(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return a.qualifier == b.qualifier and math.isclose(a.value, b.value, abs_tol=1e-9)


def _not_emphasized(extraction: LabelExtraction) -> set[str]:
    findings, _ = run_rules(extraction, None)
    return {f.target for f in findings if f.rule_id == "ALG-EMPH" and f.status == "needs_review"}


def _pr(true_positive: int, predicted: int, actual: int) -> dict:
    return {
        "precision": ratio(true_positive, predicted),
        "recall": ratio(true_positive, actual),
    }


def reading(rows: list[dict]) -> dict:
    """Extraction vs truth.extraction, once per case (recipes share the extraction)."""
    numbers = Counter()
    emph = Counter()
    claims = Counter()
    seen = set()
    for row in rows:
        if row["status"] != "done" or row["case"] in seen:
            continue
        seen.add(row["case"])
        truth, _ = _truth(row)
        got = LabelExtraction.model_validate(row["extraction"])
        if truth.nutrition is not None:
            for field in NUMBERS:
                expected = parse_amount(getattr(truth.nutrition, field))
                if expected is None:
                    continue
                read = parse_amount(getattr(got.nutrition, field)) if got.nutrition else None
                numbers["n"] += 1
                numbers["ok"] += _same_amount(expected, read)
            expected_e = parse_energy(truth.nutrition.energy)
            read_e = parse_energy(got.nutrition.energy if got.nutrition else None)
            for unit in ("kj", "kcal"):
                if getattr(expected_e, unit) is not None:
                    numbers["n"] += 1
                    numbers["ok"] += getattr(expected_e, unit) == getattr(read_e, unit)
        t, p = _not_emphasized(truth), _not_emphasized(got)
        emph["tp"] += len(t & p)
        emph["pred"] += len(p)
        emph["actual"] += len(t)
        t, p = set(find_claims(truth)[0]), set(find_claims(got)[0])
        claims["tp"] += len(t & p)
        claims["pred"] += len(p)
        claims["actual"] += len(t)
    return {
        "cases": len(seen),
        "numbers": ratio(numbers["ok"], numbers["n"]),
        "not_emphasized": _pr(emph["tp"], emph["pred"], emph["actual"]),
        "claims_found": _pr(claims["tp"], claims["pred"], claims["actual"]),
    }


# --- the numbers ------------------------------------------------------------------------------


def score(rows: list[dict], with_truth: bool = True) -> dict:
    done = [r for r in rows if r["status"] == "done"]
    errors = [r for r in rows if r["status"] == "error"]
    found = {"safe": 0, "strict": 0}
    by_rule: dict[str, Counter] = defaultdict(Counter)
    by_quality: dict[str, Counter] = defaultdict(Counter)
    by_group: dict[str, Counter] = defaultdict(Counter)
    missed = []
    total = 0
    for row in done:
        safe, strict = shown(row), shown(row, ("violation",))
        on_truth = set()
        if with_truth and row["violations"]:
            findings, _ = run_rules(*_truth(row))
            on_truth = {(f.rule_id, f.target) for f in findings if f.status in SHOWN}
        for v in row["violations"]:
            key = _key(v)
            total += 1
            hit = key in safe
            found["safe"] += hit
            found["strict"] += key in strict
            quality = row["meta"].get("quality", "?")
            for bucket, name in ((by_rule, v["rule_id"]), (by_quality, quality)):
                bucket[name]["n"] += 1
                bucket[name]["k"] += hit
            by_group[row["group"]]["n"] += 1
            by_group[row["group"]]["k"] += hit
            by_rule[v["rule_id"]]["on_truth"] += key in on_truth
            if not hit:
                where = "читання" if key in on_truth else "правила (на правді теж)"
                missed.append({"id": row["id"], "rule_id": key[0], "target": key[1], "loss": where})
    error_violations = sum(len(r["violations"]) for r in errors)

    clean = [r for r in done if is_clean(r)]
    loaded = [r for r in clean if r["verdict"] in LOAD_VERDICTS]
    false_alarms = [
        {"id": r["id"], "rule_id": f["rule_id"], "target": f["target"]}
        for r in clean
        for f in r["findings"]
        if f["status"] == "violation"
    ]
    findings = [f for r in done for f in r["findings"]]
    flags: dict[str, Counter] = defaultdict(Counter)
    for row in done:
        for flag in row["expected_flags"]:
            flags[flag["rule_id"]]["n"] += 1
            flags[flag["rule_id"]]["k"] += _key(flag) in shown(row)
    for row in clean:
        by_quality[row["meta"].get("quality", "?")]["clean"] += 1
        by_quality[row["meta"].get("quality", "?")]["loaded"] += row in loaded
    return {
        "units": len(rows),
        "done": len(done),
        "errors": [{"id": r["id"], "code": r["error"]["code"]} for r in errors],
        "safe_recall": ratio(found["safe"], total),
        "strict_recall": ratio(found["strict"], total),
        "safe_recall_errors_as_missed": ratio(found["safe"], total + error_violations),
        "load": ratio(len(loaded), len(clean)),
        "needs_review_findings": ratio(
            sum(f["status"] == "needs_review" for f in findings), len(findings)
        ),  # fmt: skip
        "false_alarms": false_alarms,
        "clean_with_false_alarm": ratio(len({a["id"] for a in false_alarms}), len(clean)),
        "flags": {k: ratio(c["k"], c["n"]) for k, c in sorted(flags.items())},
        "by_rule": {
            k: {**ratio(c["k"], c["n"]), "on_truth": c["on_truth"]}
            for k, c in sorted(by_rule.items())
        },
        "by_quality": {k: dict(c) for k, c in sorted(by_quality.items())},
        "by_group": {k: ratio(c["k"], c["n"]) for k, c in sorted(by_group.items())},
        "missed": missed,
        "reading": reading(rows) if with_truth else None,
    }


def compute(report: dict, with_truth: bool = True) -> dict:
    units = report["units"]
    main = [r for r in units if r["in_trust_number"]]
    out = [r for r in units if not r["in_trust_number"]]
    return {
        "main": score(main, with_truth),
        "out_of_scope": score(out, with_truth) if out else None,
    }


# --- markdown ---------------------------------------------------------------------------------


def pct(r: dict) -> str:
    if not r["n"]:
        return "— (0 з 0)"
    s = f"{r['k']} з {r['n']} = {100 * r['share']:.0f} %"
    if r.get("ci"):
        lo, hi = r["ci"]
        s += f" [{100 * lo:.0f}–{100 * hi:.0f} %]"
    return s


def markdown(report: dict, m: dict) -> str:
    main = m["main"]
    synthetic = all(r["group"] == "synthetic" for r in report["units"])
    lines = [
        f"# Eval {report['split']} — {report['date']}",
        "",
        f"Модель `{report['model']}`, PROMPT_VERSION `{report['prompt_version']}`, "
        f"RULES_VERSION `{report['rules_version']}`. Кейсів (units): {main['units']}"
        f", виконано {main['done']}, помилок моделі {len(main['errors'])}."
        + (" **Дані синтетичні** (eval/generate.py)." if synthetic else ""),
        "",
        "## Головне число",
        "",
        f"- **Safe recall** (порушення показано технологу: violation або needs_review за тим "
        f"самим rule_id + target): **{pct(main['safe_recall'])}**, 95 % інтервал Вілсона.",
        f"- **Навантаження**: чисті кейси з вердиктом fail/needs_review — {pct(main['load'])}; "
        f"findings needs_review — {pct(main['needs_review_findings'])}.",
        "- Базова лінія «все → needs_review»: safe recall 100 %, навантаження 100 %.",
        f"- Strict recall (лише violation): {pct(main['strict_recall'])}.",
        f"- Хибні тривоги (violation на чистих): {len(main['false_alarms'])} findings у "
        f"{pct(main['clean_with_false_alarm'])} чистих кейсів.",
        "- Якщо помилка моделі = пропуск: safe recall "
        f"{pct(main['safe_recall_errors_as_missed'])}.",
        "",
        "## Де втрати: читання чи правила",
        "",
        "| порушення | safe recall сервісу | правила на правді (ідеальна екстракція) |",
        "|---|---|---|",
    ]
    for rule, r in main["by_rule"].items():
        lines.append(f"| {rule} | {pct(r)} | {r['on_truth']} з {r['n']} |")
    lines += ["", "Пропущені порушення:", ""]
    lines += [f"- {x['id']}: {x['rule_id']} / {x['target']} — {x['loss']}" for x in main["missed"]]
    if not main["missed"]:
        lines.append("- немає")
    lines += ["", "## Проблеми фото (expected_flags, окремо від safe recall)", ""]
    for rule, r in main["flags"].items():
        note = " — «до» для кандидата B6 (обрізаний склад)" if rule == "LABEL-TRUNCATED" else ""
        lines.append(f"- {rule}: помічено {pct(r)}{note}")
    lines += ["", "## Розбивка", "", "За групою (safe recall):", ""]
    lines += [f"- {g}: {pct(r)}" for g, r in main["by_group"].items()]
    lines += ["", "| якість фото | порушень знайдено | чистих з навантаженням |", "|---|---|---|"]
    for q, c in main["by_quality"].items():
        found = f"{c.get('k', 0)} з {c.get('n', 0)}"
        lines.append(f"| {q} | {found} | {c.get('loaded', 0)} з {c.get('clean', 0)} |")
    rd = main["reading"]
    if rd:
        lines += [
            "",
            f"## Точність читання ({rd['cases']} кейсів)",
            "",
            f"- Числа таблиці після parse_amount/parse_energy: {pct(rd['numbers'])}.",
            f"- «Не виділено» (ALG-EMPH needs_review): precision "
            f"{pct(rd['not_emphasized']['precision'])}, recall "
            f"{pct(rd['not_emphasized']['recall'])}.",
            f"- Знайдені твердження: precision {pct(rd['claims_found']['precision'])}, recall "
            f"{pct(rd['claims_found']['recall'])}.",
        ]
    if main["errors"]:
        lines += ["", "## Помилки моделі", ""]
        lines += [f"- {e['id']}: {e['code']}" for e in main["errors"]]
    if m["out_of_scope"]:
        o = m["out_of_scope"]
        lines += [
            "",
            "## Поза ринком, для інформації (неукраїнські етикетки, не в головному числі)",
            "",
            f"- safe recall {pct(o['safe_recall'])}; навантаження {pct(o['load'])}; "
            f"помилок {len(o['errors'])}.",
        ]
    if main["false_alarms"]:
        lines += ["", "## Хибні тривоги", ""]
        lines += [f"- {a['id']}: {a['rule_id']} / {a['target']}" for a in main["false_alarms"]]
    return "\n".join(lines) + "\n"


def write_markdown(json_path: Path) -> Path:
    report = json.loads(json_path.read_text(encoding="utf-8"))
    md = json_path.with_suffix(".md")
    md.write_text(markdown(report, compute(report)), encoding="utf-8")
    return md


if __name__ == "__main__":
    print(write_markdown(Path(sys.argv[1])))
