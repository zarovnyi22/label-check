"""Eval runner: every case through run_check / run_rules (no HTTP), extractions from caches.

    python -m eval.run --split dev|test [--live] [--limit N]
        make eval SPLIT=dev            # from the cache only, no model calls
        make eval-live SPLIT=dev [LIMIT=3]

Units (docs/SPEC.md §4):
- dev: synthetic dev cases;
- test: synthetic test cases, eval/real (Ukrainian labels, test only) — each without a recipe
  and once per semi-synthetic recipe (spec_variants), and eval/real_out_of_scope (group
  out_of_scope: reported apart, NOT in the trust number).
Extractions come from eval/cache/<split>/<case>.json (committed; key: case id +
PROMPT_VERSION + model, photo sha256 checked when the photos are there), else from the DB
cache, else (--live) from the model; every DB/live extraction is written to eval/cache, so a
clean clone reproduces the number without a key and without the real photos. The rules always
run on the current code. Without --live a case missing from every cache is an error listing
all such cases (nothing is run). With --live only the missing ones call the model,
EVAL_PAUSE_SECONDS apart (default 5, under the free-tier RPM); the trust number is the primary
model's, so no fallback provider.
A model error does not stop the run: the unit is `error` and counted apart; it is not cached,
so the next run retries only it. Result: eval/reports/<split>_<date>.json and .md (metrics).
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
from app.extraction import Extracted, cache_key, model_id
from app.images import PreparedImage, prepare_image
from app.rules.engine import RULES_VERSION, run_rules
from app.schemas import LabelExtraction, ProductSpec
from app.vision.base import VisionClient, get_vision_client
from app.vision.prompt import PROMPT_VERSION
from eval.metrics import write_markdown

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
CACHE = ROOT / "cache"  # committed extractions: eval/cache/<split>/<case>.json
DEFAULT_PAUSE_SECONDS = 5.0
PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


@dataclass
class Unit:
    """One check: a case's photos + one recipe (or none) + what the truth expects."""

    id: str
    case: str
    split: str  # dev | test: the eval/cache folder
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
        base = dict(case=folder.name, split="test", folder=folder, meta=_meta(truth))
        own = Unit(
            id=folder.name,
            group=group,
            spec_file=None,
            violations=truth["violations"],
            expected_flags=truth["expected_flags"],
            **base,
        )
        units.append(own)
        for variant in truth.get("spec_variants", []):
            units.append(
                Unit(
                    id=f"{folder.name}+{Path(variant['spec']).stem}",
                    group="semi" if group == "real" else group,
                    spec_file=variant["spec"],
                    # only the recipe's own violation: the label's violations and photo
                    # flags are counted once, on the case without a recipe
                    violations=variant["violations"],
                    expected_flags=[],
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
                split=split,
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
                f"{len(no_photos)} case(s) neither in eval/cache nor with photos (real photos are "
                f"not in git: put them into the case folder as photo_<i>.jpg): "
                f"{', '.join(no_photos)}"
            )
        super().__init__("\n".join(lines))


def prepare(unit: Unit) -> list[PreparedImage]:
    return [prepare_image(p.read_bytes(), p.name) for p in unit.photos()]


def cache_path(unit: Unit, cache_root: Path) -> Path:
    return cache_root / unit.split / f"{unit.case}.json"


def read_file_cache(path: Path, model: str, images: list[PreparedImage] | None) -> dict | None:
    """The committed extraction of a case (key: case id + PROMPT_VERSION + model); None if
    absent, for another model/prompt, or the photos on disk differ from the ones it was
    made from (sha256)."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["model"] != model or data["prompt_version"] != PROMPT_VERSION:
        return None
    if images is not None and data["photo_sha256"] != [i.sha256 for i in images]:
        return None
    return data


def write_file_cache(path: Path, case: str, extracted: Extracted, images, usage: dict) -> dict:
    data = {
        "case": case,
        "model": extracted.model,
        "prompt_version": PROMPT_VERSION,
        "photo_sha256": [i.sha256 for i in images],
        "usage": usage,
        "extraction": extracted.extraction.model_dump(),
        "raw_text": extracted.raw_text,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data


async def db_usage(pool: asyncpg.Pool, images: list[PreparedImage], model: str) -> dict:
    """Tokens of a DB-cached extraction (run_check reports {} on a cache hit)."""
    raw = await pool.fetchval(
        "SELECT usage FROM extraction_cache WHERE cache_key = $1", cache_key(images, model)
    )
    return (json.loads(raw) if isinstance(raw, str) else raw) or {}


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT.parent)) if path.is_relative_to(ROOT.parent) else str(path)


def _keys(items: list[dict]) -> list[dict]:
    return [{"rule_id": i["rule_id"], "target": i["target"]} for i in items]


def _findings(findings) -> list[dict]:
    return [{"rule_id": f.rule_id, "target": f.target, "status": f.status} for f in findings]


async def run_units(
    pool: asyncpg.Pool,
    vision: VisionClient,
    units: list[Unit],
    *,
    live: bool,
    pause_seconds: float,
    deadline_seconds: float,
    cache_root: Path = CACHE,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    log: Callable[[str], None] = print,
) -> list[dict]:
    """All units, or NotCachedError before any check when something cannot be run.

    Where an extraction comes from: eval/cache/<split>/<case>.json (committed: a clean clone
    reproduces the number without a key and without the real photos), else the DB cache, else
    (--live) the model. A DB or live extraction is written to eval/cache; the rules always run
    now, on the current code."""
    model = model_id(vision)
    images: dict[str, list[PreparedImage]] = {}
    files: dict[str, dict] = {}
    in_db: dict[str, bool] = {}
    for unit in units:
        if unit.case in images or unit.case in files:
            continue
        prepared = prepare(unit) if unit.photos() else None
        cached = read_file_cache(cache_path(unit, cache_root), model, prepared)
        if cached:
            files[unit.case] = cached
        if prepared is not None:
            images[unit.case] = prepared
            in_db[unit.case] = bool(
                await pool.fetchval(
                    "SELECT 1 FROM extraction_cache WHERE cache_key = $1",
                    cache_key(prepared, model),
                )
            )
    cases = dict.fromkeys(u.case for u in units)
    no_photos = [c for c in cases if c not in files and c not in images]
    missing = [c for c in cases if c not in files and c in images and not in_db[c]]
    if no_photos or (missing and not live):
        raise NotCachedError([] if live else missing, no_photos)

    results = []
    calls = 0
    for unit in units:
        spec = None
        if unit.spec_file:
            spec = ProductSpec.model_validate_json((unit.folder / unit.spec_file).read_text())
        row = {
            "id": unit.id,
            "case": unit.case,
            "group": unit.group,
            "in_trust_number": unit.in_trust_number,
            "folder": _rel(unit.folder),
            "spec": unit.spec_file,
            "violations": _keys(unit.violations),
            "expected_flags": _keys(unit.expected_flags),
            "meta": unit.meta,
        }
        if unit.case in files:
            data = files[unit.case]
            extraction = LabelExtraction.model_validate(data["extraction"])
            findings, verdict = run_rules(extraction, spec)
            row |= {
                "status": "done",
                "verdict": verdict,
                "findings": _findings(findings),
                "extraction": data["extraction"],
                "model": data["model"],
                "source": "file",
                "usage": data["usage"],
            }
            log(f"{unit.id}: {verdict} (eval/cache)")
            results.append(row)
            continue

        prepared = images[unit.case]
        if unit.case in missing:
            if calls:
                await sleep(pause_seconds)
            calls += 1
        try:
            run = await run_check(pool, vision, prepared, spec, deadline_seconds)
        except AppError as exc:
            row |= {"status": "error", "error": {"code": exc.code, "message": exc.message}}
            log(f"{unit.id}: error {exc.code}")
        else:
            ex = run.extracted
            usage = await db_usage(pool, prepared, ex.model) if ex.cache_hit else ex.usage
            files[unit.case] = write_file_cache(
                cache_path(unit, cache_root), unit.case, ex, prepared, usage
            )
            row |= {
                "status": "done",
                "verdict": run.verdict,
                "findings": _findings(run.findings),
                "extraction": ex.extraction.model_dump(),
                "model": ex.model,
                "source": "db" if ex.cache_hit else "live",
                "usage": usage,
                "duration_ms": run.duration_ms,
            }
            log(f"{unit.id}: {run.verdict}{' (db cache)' if ex.cache_hit else ''}")
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
    md = write_markdown(path)
    errors = sum(r["status"] == "error" for r in results)
    print(f"{len(results)} units, {errors} errors -> {_rel(path)}, {_rel(md)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
