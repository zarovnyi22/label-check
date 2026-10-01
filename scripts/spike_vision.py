"""One-off probe of the vision model on real label photos (step B1b; not part of the service).

Sends 1-3 photos in ONE Gemini generateContent call with a draft transcription prompt and
prints the raw JSON answer and usageMetadata. No database, no FastAPI. Key and model come
from .env (GEMINI_API_KEY, VISION_MODEL). Needs internet, so it runs in the `tools` service:

    make spike FILES="samples/p02_front.jpg samples/p02_back.jpg"

Photos are prepared roughly as the service will do it (EXIF rotation, longest side <= 2048
px, JPEG), so token counts are representative. The prompt is a draft for B3b.
"""

import argparse
import base64
import io
import json
import sys
import time
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from app.config import get_settings

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MAX_SIDE = 2048
MAX_PHOTOS = 3

PROMPT = """\
You transcribe food packaging photos. You are NOT a reviewer: never judge legality,
never correct, translate or complete the text. Copy exactly what is printed.
All photos belong to ONE product; photo indexes start at 0 in the order given.

Return ONE JSON object with exactly these keys (any value may be null):
{
  "photos": [{"index": 0, "side": "front|back|side|unknown",
              "quality": "ok|blurry|glare|cropped|not_a_label", "note": "short or null"}],
  "emphasis_visible": true | false | null,
  "ingredients_marked": {"text": "...", "photo_index": 0} | null,
  "may_contain_text": {"text": "...", "photo_index": 0} | null,
  "nutrition": {"per": "100g|100ml|portion|prepared|null", "portion_text": "... or null",
                "energy": "...", "fat": "...", "saturates": "...", "carbs": "...",
                "sugars": "...", "fibre": "...", "protein": "...", "salt": "...",
                "photo_index": 0} | null,
  "other_text": [{"text": "...", "photo_index": 0}]
}

Rules:
- Language: if the ingredients are printed in several languages, transcribe the Ukrainian
  block only (other languages are ignored).
- ingredients_marked: the ingredient list verbatim, starting after "Склад:", letter case
  as printed. Wrap every fragment printed in a DIFFERENT font weight or style (bold,
  underlined, coloured) in **double asterisks**. Mark nothing else. Do not mark words
  just because they are allergens. Do not mark text that is in capitals but same weight.
- emphasis_visible: true if you can tell font weights apart in the ingredient list,
  false if the photo does not let you see it, null if there is no ingredient list.
- may_contain_text: the "may contain / може містити" sentence verbatim, or null.
- nutrition: values as STRINGS exactly as printed, with units and signs ("0,5 г", "<0,5 г",
  "120 кДж / 28 ккал"). Keep the comma. Use the per-100 g/ml column if there is one;
  "per" says which column you copied. A value you cannot read is null; never guess.
- other_text: every other printed line (name, claims, slogans, storage, producer), one
  item per line or phrase, verbatim. Do not repeat the ingredients or nutrition table.
- Anything unreadable, cut off or hidden: null (or omit the fragment) - never invent.
- photos.quality: "cropped" if text needed above runs off the edge.
"""


def prepare(path: Path) -> tuple[bytes, tuple[int, int]]:
    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue(), image.size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path, help=f"1-{MAX_PHOTOS} photos")
    args = parser.parse_args()
    if len(args.files) > MAX_PHOTOS:
        sys.exit(f"at most {MAX_PHOTOS} photos")
    if any("samples/test" in str(f) for f in args.files):
        sys.exit("samples/test/ is the held-out test set: not for the spike")
    settings = get_settings()
    if not settings.gemini_api_key:
        sys.exit("GEMINI_API_KEY is empty in .env")

    parts: list[dict] = [{"text": PROMPT}]
    for i, path in enumerate(args.files):
        data, size = prepare(path)
        print(f"photo {i}: {path} -> {size[0]}x{size[1]}, {len(data) // 1024} KB")
        parts.append({"text": f"Photo {i}:"})
        parts.append(
            {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(data).decode()}}
        )
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }

    started = time.monotonic()
    # The key goes in a header, never in the URL: URLs end up in logs and tracebacks.
    resp = httpx.post(
        f"{BASE_URL}/{settings.vision_model}:generateContent",
        headers={"x-goog-api-key": settings.gemini_api_key},
        json=body,
        timeout=settings.vision_timeout_seconds,
    )
    seconds = time.monotonic() - started
    print(f"model: {settings.vision_model}, HTTP {resp.status_code}, {seconds:.1f} s")
    if resp.status_code != 200:
        sys.exit(resp.text[:2000])

    answer = resp.json()
    candidate = (answer.get("candidates") or [{}])[0]
    raw = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []))
    print("finishReason:", candidate.get("finishReason"))
    print("usageMetadata:", json.dumps(answer.get("usageMetadata"), ensure_ascii=False))
    print("--- raw answer ---")
    try:
        print(json.dumps(json.loads(raw), ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print("(not valid JSON)")
        print(raw)


if __name__ == "__main__":
    main()
