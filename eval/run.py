"""Eval runner: every case through app.checks.run_check (no HTTP), extractions from the cache.

    python -m eval.run --split dev|test [--live] [--limit N]
        make eval SPLIT=dev            # from the cache only, no model calls
        make eval-live SPLIT=dev [LIMIT=3]

Units (docs/SPEC.md §4):
- dev: synthetic dev cases;
- test: synthetic test cases, eval/real (Ukrainian labels, test only) — each without a recipe
  and once per semi-synthetic recipe (spec_variants), and eval/real_out_of_scope (group
  out_of_scope: reported apart, NOT in the trust number).
Without --live a case missing from the cache is an error listing all such cases (nothing is
run). With --live only the missing ones call the model, EVAL_PAUSE_SECONDS apart (default 5,
under the free-tier RPM); the trust number is the primary model's, so no fallback provider.
A model error does not stop the run: the unit is `error` and counted apart; it is not cached,
so the next run retries only it. Result: eval/reports/<split>_<date>.json.
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import asyncpg

from app.checks import run_check
from app.config import get_settings
from app.db import apply_migrations, create_pool
from app.errors import AppError
from app.extraction import cache_key, model_id
from app.images import PreparedImage, prepare_image
from app.rules.engine import RULES_VERSION
from app.schemas import ProductSpec
from app.vision.base import VisionClient, get_vision_client
from app.vision.prompt import PROMPT_VERSION

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
DEFAULT_PAUSE_SECONDS = 5.0
PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


@dataclass
class Unit:
    """One check: a case's photos + one recipe (or none) + what the truth expects."""

    id: str
    case: str
    group: str  # synthetic | real | semi | out_of_scope
    folder: Path
    spec_file: str | None
    violations: list[dict]
    expected_flags: list[dict]
    meta: dict = field(default_factory=dict)

    @property
    def in_trust_number(self) -> bool:
        return self.group != "out_of_scope"

    def photos(self) -> list[Path]:
        return sorted(p for p in self.folder.glob("photo_*") if p.suffix in PHOTO_SUFFIXES)


def _truth(folder: Path) -> dict:
    return json.loads((folder / "truth.json").read_text(encoding="utf-8"))


def _meta(truth: dict) -> dict:
    meta = truth["meta"]
    keep = ("synthetic", "quality", "template", "scenario", "oov", "ambiguous", "source")
    return {k: meta[k] for k in keep if k in meta}


def _real_units(root: Path, group: str) -> list[Unit]:
    units = []
    for folder in sorted(p.parent for p in root.glob("*/truth.json")):
        truth = _truth(folder)
        base = dict(
            case=folder.name,
            folder=folder,
            expected_flags=truth["expected_flags"],
            meta=_meta(truth),
        )
        violations = truth["violations"]
        own = Unit(id=folder.name, group=group, spec_file=None, violations=violations, **base)
        units.append(own)
        for variant in truth.get("spec_variants", []):
            units.append(
                Unit(
                    id=f"{folder.name}+{Path(variant['spec']).stem}",
                    group="semi" if group == "real" else group,
                    spec_file=variant["spec"],
                    violations=truth["violations"] + variant["violations"],
                    **base,
                )
            )
    return units


def collect_units(split: str, root: Path = ROOT) -> list[Unit]:
    units = []
    for folder in sorted(p.parent for p in (root / "cases" / split).glob("*/truth.json")):
        truth = _truth(folder)
        spec = "spec.json" if (folder / "spec.json").exists() else None
        units.append(
            Unit(
                id=folder.name,
                case=folder.name,
                group="synthetic",
                folder=folder,
                spec_file=spec,
                violations=truth["violations"],
                expected_flags=truth["expected_flags"],
                meta=_meta(truth),
            )
        )
    if split == "test":  # real photos are test only
        units += _real_units(root / "real", "real")
        units += _real_units(root / "real_out_of_scope", "out_of_scope")
    return units


class NotCachedError(Exception):
    def __init__(self, missing: list[str], no_photos: list[str]) -> None:
        lines = []
        if missing:
            lines.append(
                f"{len(missing)} case(s) not in the extraction cache (run with --live / "
                f"make eval-live): {', '.join(missing)}"
            )
        if no_photos:
            lines.append(
                f"{len(no_photos)} case(s) without photos (real photos are not in git: put them "
                f"into the case folder as photo_<i>.jpg): {', '.join(no_photos)}"
            )
        super().__init__("\n".join(lines))


def prepare(unit: Unit) -> list[PreparedImage]:
    return [prepare_image(p.read_bytes(), p.name) for p in unit.photos()]


async def is_cached(pool: asyncpg.Pool, vision: VisionClient, images: list[PreparedImage]) -> bool:
    key = cache_key(images, model_id(vision))
    return bool(await pool.fetchval("SELECT 1 FROM extraction_cache WHERE cache_key = $1", key))


def _keys(items: list[dict]) -> list[dict]:
    return [{"rule_id": i["rule_id"], "target": i["target"]} for i in items]


async def run_units(
    pool: asyncpg.Pool,
    vision: VisionClient,
    units: list[Unit],
    *,
    live: bool,
    pause_seconds: float,
    deadline_seconds: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    log: Callable[[str], None] = print,
) -> list[dict]:
    """All units, or NotCachedError before any check when not live and something is missing."""
    no_photos = sorted({u.case for u in units if not u.photos()})
    prepared = {u.case: prepare(u) for u in units if u.photos()}
    cached = {case: await is_cached(pool, vision, images) for case, images in prepared.items()}
    missing = sorted(case for case, hit in cached.items() if not hit)
    if no_photos or (missing and not live):
        raise NotCachedError([] if live else missing, no_photos)

    results = []
    calls = 0
    for unit in units:
        images = prepared[unit.case]
        if not cached[unit.case]:
            if calls:
                await sleep(pause_seconds)
            calls += 1
        spec = None
        if unit.spec_file:
            spec = ProductSpec.model_validate_json((unit.folder / unit.spec_file).read_text())
        row = {
            "id": unit.id,
            "case": unit.case,
            "group": unit.group,
            "in_trust_number": unit.in_trust_number,
            "spec": unit.spec_file,
            "violations": _keys(unit.violations),
            "expected_flags": _keys(unit.expected_flags),
            "meta": unit.meta,
        }
        try:
            run = await run_check(pool, vision, images, spec, deadline_seconds)
        except AppError as exc:
            row |= {"status": "error", "error": {"code": exc.code, "message": exc.message}}
            log(f"{unit.id}: error {exc.code}")
        else:
            cached[unit.case] = True  # the next recipe of the same photos reuses it
            ex = run.extracted
            row |= {
                "status": "done",
                "verdict": run.verdict,
                "findings": [
                    {"rule_id": f.rule_id, "target": f.target, "status": f.status}
                    for f in run.findings
                ],
                "extraction": ex.extraction.model_dump(),
                "model": ex.model,
                "cache_hit": ex.cache_hit,
                "usage": ex.usage,
                "duration_ms": run.duration_ms,
            }
            log(f"{unit.id}: {run.verdict}{' (cache)' if ex.cache_hit else ''}")
        results.append(row)
    return results


def write_report(split: str, results: list[dict], vision: VisionClient, live: bool) -> Path:
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"{split}_{date.today().isoformat()}.json"
    report = {
        "split": split,
        "date": date.today().isoformat(),
        "model": model_id(vision),
        "prompt_version": PROMPT_VERSION,
        "rules_version": RULES_VERSION,
        "live": live,
        "units": results,
        "errors": sum(r["status"] == "error" for r in results),
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--live", action="store_true", help="call the model for missing cases")
    parser.add_argument("--limit", type=int, help="only the first N units")
    args = parser.parse_args(argv)

    # The trust number is measured on the primary model only (CLAUDE.md, decision 7).
    settings = get_settings().model_copy(update={"vision_fallback_provider": ""})
    vision = get_vision_client(settings)
    units = collect_units(args.split)[: args.limit]
    pause = float(os.environ.get("EVAL_PAUSE_SECONDS", DEFAULT_PAUSE_SECONDS))
    pool = await create_pool(settings.database_url)
    try:
        await apply_migrations(pool)
        results = await run_units(
            pool,
            vision,
            units,
            live=args.live,
            pause_seconds=pause,
            deadline_seconds=settings.vision_deadline_seconds,
        )
    except NotCachedError as exc:
        print(exc, file=sys.stderr)
        return 2
    finally:
        await pool.close()
        await vision.aclose()
    path = write_report(args.split, results, vision, args.live)
    errors = sum(r["status"] == "error" for r in results)
    print(f"{len(results)} units, {errors} errors -> {path.relative_to(ROOT.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
