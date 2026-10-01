"""Photo intake: generated in the test with Pillow, no files on disk."""

import hashlib
import io

import pytest
from PIL import Image

from app.errors import AppError
from app.images import MAX_BYTES, MAX_SIDE, prepare_image


def encode(image: Image.Image, fmt: str = "JPEG", **kw) -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt, **kw)
    return out.getvalue()


def test_jpeg_is_prepared_with_hash_of_what_the_model_sees():
    prepared = prepare_image(encode(Image.new("RGB", (300, 200), "red")))
    assert (prepared.width, prepared.height, prepared.mime) == (300, 200, "image/jpeg")
    assert prepared.sha256 == hashlib.sha256(prepared.data).hexdigest()
    assert Image.open(io.BytesIO(prepared.data)).format == "JPEG"


def test_same_photo_same_hash():
    raw = encode(Image.new("RGB", (64, 64), "blue"))
    assert prepare_image(raw).sha256 == prepare_image(raw).sha256


def test_exif_rotation_is_applied():
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90° clockwise to display
    raw = encode(Image.new("RGB", (400, 100), "white"), exif=exif)
    prepared = prepare_image(raw)
    assert (prepared.width, prepared.height) == (100, 400)


def test_longest_side_is_capped_keeping_aspect():
    prepared = prepare_image(encode(Image.new("RGB", (4096, 1024), "white"), "PNG"))
    assert (prepared.width, prepared.height) == (MAX_SIDE, 512)


def test_small_photo_is_not_upscaled():
    prepared = prepare_image(encode(Image.new("RGB", (100, 50)), "WEBP"))
    assert (prepared.width, prepared.height) == (100, 50)


def test_transparent_png_goes_on_white():
    raw = encode(Image.new("RGBA", (10, 10), (0, 0, 0, 0)), "PNG")
    pixel = Image.open(io.BytesIO(prepare_image(raw).data)).getpixel((5, 5))
    assert all(c > 240 for c in pixel)


@pytest.mark.parametrize(
    "raw",
    [b"not an image at all", b"", b"%PDF-1.4 ...", encode(Image.new("RGB", (8, 8)), "GIF")],
)
def test_not_a_supported_image(raw):
    with pytest.raises(AppError) as err:
        prepare_image(raw, "photo.jpg")
    assert (err.value.status_code, err.value.code) == (422, "image_unsupported")
    assert "photo.jpg" in err.value.message


def test_truncated_jpeg_is_unsupported_not_500():
    raw = encode(Image.new("RGB", (500, 500), "green"))
    with pytest.raises(AppError) as err:
        prepare_image(raw[: len(raw) // 2])
    assert err.value.code == "image_unsupported"


def test_too_large_file():
    with pytest.raises(AppError) as err:
        prepare_image(b"\xff" * (MAX_BYTES + 1))
    assert (err.value.status_code, err.value.code) == (422, "image_too_large")


def test_too_many_pixels():
    raw = encode(Image.new("1", (10_000, 6_000)), "PNG")  # 60 Mp, a few KB
    assert len(raw) < MAX_BYTES
    with pytest.raises(AppError) as err:
        prepare_image(raw)
    assert err.value.code == "image_too_large"
