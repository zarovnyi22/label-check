"""Download real Ukrainian label photos from Open Food Facts (CC BY-SA 3.0).

One-off helper, run by a human (needs internet, so not in the offline test service):

    docker run --rm -v "$PWD":/w -w /w python:3.12.14-slim-bookworm \
        python scripts/fetch_off_photos.py --dev 3 --test 12

Layout (samples/ is git-ignored):
    samples/pNN_front.jpg, pNN_back.jpg (ingredients), pNN_nutrition.jpg  -> dev / spike
    samples/test/pNN_*.jpg                                                 -> test only
Each folder gets SOURCES.md with barcode, product URL and licence (attribution).
Do not open samples/test/ while tuning the prompt: those photos are the held-out test set.
"""

import argparse
import json
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://world.openfoodfacts.org/api/v2/search"
PRODUCT_API = "https://world.openfoodfacts.org/api/v2/product"
FIELDS = "code,product_name,image_front_url,image_ingredients_url,image_nutrition_url"
USER_AGENT = "label-check-eval/0.1 (test task, one-off photo download)"
LICENSE = "CC BY-SA 3.0 (Open Food Facts contributors)"


def get(url: str, timeout: int = 30, attempts: int = 3, pause: int = 3) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404 or attempt == attempts - 1:
                raise
        except urllib.error.URLError:
            if attempt == attempts - 1:
                raise
        wait = pause * (attempt + 1)
        print(f"  OFF busy, retry in {wait} s…")
        time.sleep(wait)
    raise RuntimeError("unreachable")


def search(pages: int) -> list[dict]:
    """Barcodes of Ukrainian products. The search API does not return image URLs."""
    products = []
    for page in range(1, pages + 1):
        url = (
            f"{API}?countries_tags_en=ukraine&fields=code,product_name"
            f"&page_size=100&page={page}&sort_by=unique_scans_n"
        )
        try:
            # The search API is rate limited (~10/min) and often answers 503: wait longer.
            products += json.loads(get(url, attempts=5, pause=15)).get("products", [])
        except urllib.error.HTTPError as exc:
            if not products:
                raise SystemExit(
                    f"OFF search unavailable ({exc.code}); try again in a few minutes"
                ) from None
            break
        time.sleep(7)
    return products


def details(code: str) -> dict:
    """Image URLs come from the product API (≈ 100 requests per minute allowed)."""
    time.sleep(0.8)
    try:
        data = json.loads(get(f"{PRODUCT_API}/{code}.json?fields={FIELDS}"))
    except (urllib.error.URLError, json.JSONDecodeError):
        return {}
    return data.get("product") or {}


def usable(p: dict) -> bool:
    keys = ("product_name", "image_ingredients_url", "image_nutrition_url")
    return all(p.get(k) for k in keys)


def full_size(url: str) -> str:
    return url.replace(".400.jpg", ".full.jpg")


def download(url: str, dest: Path) -> bool:
    for candidate in (full_size(url), url):
        try:
            dest.write_bytes(get(candidate))
            return True
        except urllib.error.HTTPError:
            continue
    return False


def save_product(p: dict, idx: int, folder: Path) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"p{idx:02d}"
    files = []
    sides = [("back", "image_ingredients_url"), ("nutrition", "image_nutrition_url")]
    if p.get("image_front_url"):
        sides.insert(0, ("front", "image_front_url"))
    for side, key in sides:
        if download(p[key], folder / f"{stem}_{side}.jpg"):
            files.append(f"{stem}_{side}.jpg")
        time.sleep(1)
    link = f"https://world.openfoodfacts.org/product/{p['code']}"
    return f"| {stem} | {p['product_name']} | {p['code']} | {link} | {', '.join(files)} |"


def write_sources(folder: Path, rows: list[str]) -> None:
    header = [
        "# Джерела фото",
        "",
        f"Фото з Open Food Facts, ліцензія {LICENSE}.",
        "",
        "| id | продукт | штрихкод | сторінка | файли |",
        "|---|---|---|---|---|",
    ]
    (folder / "SOURCES.md").write_text("\n".join(header + rows) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dev", type=int, default=3, help="products for samples/ (spike, B3)")
    parser.add_argument("--test", type=int, default=12, help="products for samples/test/")
    parser.add_argument("--pages", type=int, default=1, help="search pages of 100 products")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    need = args.dev + args.test
    found = [p for p in search(args.pages) if p.get("code")]
    random.Random(args.seed).shuffle(found)
    print(f"search: {len(found)} Ukrainian products; checking photos one by one…")
    uk, other = [], []
    for p in found:
        if len(uk) >= need:
            break
        prod = details(p["code"])
        if not usable(prod):
            continue
        prod["code"] = p["code"]
        lang_uk = "ingredients_uk" in prod["image_ingredients_url"]
        (uk if lang_uk else other).append(prod)
        print(f"  {'uk' if lang_uk else '--'} {p['code']} {prod['product_name']}")
    chosen = (uk + other)[:need]
    print(f"usable: {len(uk)} with Ukrainian ingredient photo, {len(other)} other")
    if len(chosen) < need:
        print(f"only {len(chosen)} products available, wanted {need}; try --pages 4")
    root = Path("samples")
    groups = [(chosen[: args.dev], root, 1), (chosen[args.dev :], root / "test", args.dev + 1)]
    for products, folder, start in groups:
        rows = []
        for i, p in enumerate(products, start=start):
            rows.append(save_product(p, i, folder))
            print(rows[-1])
        if rows:
            write_sources(folder, rows)


if __name__ == "__main__":
    main()
