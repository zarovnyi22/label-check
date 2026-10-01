"""Photo intake: the type by content (not by name or header), EXIF rotation, longest side
<= MAX_SIDE, one JPEG encoding, sha256 of what the model will see.

The prepared bytes are what goes to the model and into check_images, so the sha256 (the
extraction cache key, B3b) changes whenever the preparation does.
"""

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.errors import AppError

MAX_BYTES = 10 * 1024 * 1024
MAX_SIDE = 2048  # B1b: ~1100 tokens a photo at 2048 px, text still readable
MAX_PIXELS = 50_000_000  # a 10 MB file can still decode to gigabytes (decompression bomb)
ACCEPTED = {"JPEG", "PNG", "WEBP"}
JPEG_QUALITY = 90


@dataclass(frozen=True)
class PreparedImage:
    data: bytes  # JPEG, what the model sees
    mime: str
    width: int
    height: int
    sha256: str


def image_error(code: str, message: str) -> AppError:
    return AppError(422, code, message)


def prepare_image(raw: bytes, name: str = "image") -> PreparedImage:
    """Uploaded bytes -> PreparedImage; 422 image_too_large / image_unsupported."""
    if len(raw) > MAX_BYTES:
        raise image_error(
            "image_too_large",
            f"{name}: {len(raw) / 1024 / 1024:.1f} МБ, максимум {MAX_BYTES // 1024 // 1024} МБ",
        )
    try:
        image = Image.open(io.BytesIO(raw))
    except Image.DecompressionBombError:
        raise image_error("image_too_large", f"{name}: забагато пікселів") from None
    except (UnidentifiedImageError, OSError):
        raise image_error("image_unsupported", f"{name}: не зображення") from None
    try:
        kind = image.format
        if kind not in ACCEPTED:
            raise image_error(
                "image_unsupported", f"{name}: формат {kind or 'невідомий'}, потрібен JPEG/PNG/WebP"
            )
        if image.width * image.height > MAX_PIXELS:
            raise image_error(
                "image_too_large",
                f"{name}: {image.width}×{image.height} px, максимум {MAX_PIXELS // 1_000_000} Мп",
            )
        image = ImageOps.exif_transpose(image)
        image = _to_rgb(image)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        # Not an image, or a truncated/corrupt one (Pillow raises OSError while decoding).
        raise image_error("image_unsupported", f"{name}: файл зображення пошкоджено") from None
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=JPEG_QUALITY)
    data = out.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    return PreparedImage(data, "image/jpeg", image.width, image.height, digest)


def _to_rgb(image: Image.Image) -> Image.Image:
    """Transparent PNG/WebP on white (black would hide dark text), everything else RGB."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")
