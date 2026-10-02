"""POST /checks and GET /checks/{id} end to end with the database and FakeVision.

The model's answers are the spike's real ones (tests/spike_outputs.py); photos are generated
here with Pillow (each colour a different sha256).
"""

import asyncio
import io
import json

import pytest
from PIL import Image

from app.config import get_settings
from app.main import app
from app.vision.base import VisionError
from app.vision.fake import FakeVision
from app.vision.prompt import PROMPT_VERSION
from tests.spike_outputs import P02, P16

COLOURS = ("red", "green", "blue", "white", "black")


def photo(colour: str) -> tuple[str, tuple[str, bytes, str]]:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), colour).save(out, format="JPEG")
    return ("images", (f"{colour}.jpg", out.getvalue(), "image/jpeg"))


def photos(n: int, start: int = 0) -> list:
    return [photo(c) for c in COLOURS[start : start + n]]


@pytest.fixture
def fake():
    vision = FakeVision()
    app.state.vision = vision
    yield vision
    del app.state.vision


async def post(client, files, spec: str | None = None):
    return await client.post("/checks", files=files, data={"spec": spec} if spec else None)


async def test_full_path_is_stored_and_read_back(db_client, db_pool, fake):
    fake.answers = [P02]
    resp = await post(db_client, photos(3))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "done"
    assert body["verdict"] in ("fail", "needs_review", "incomplete")  # no recipe: never pass
    assert body["cache_hit"] is False and body["model"] == "fake/fake"
    assert body["prompt_version"] == PROMPT_VERSION
    assert body["summary"] and body["findings"]
    assert body["extraction"]["photos"][0]["side"] == "front"

    images, prompt, _ = fake.calls[0]
    assert len(images) == 3
    assert "There are 3 photos" in prompt

    row = await db_pool.fetchrow("SELECT * FROM checks WHERE id = $1", body["check_id"])
    assert row["status"] == "done" and row["verdict"] == body["verdict"]
    assert row["raw_text"] == P02
    assert json.loads(row["findings"]) == body["findings"]
    assert row["rules_version"] and row["prompt_version"] == PROMPT_VERSION
    assert row["usage"] is not None and row["duration_ms"] is not None
    stored = await db_pool.fetch(
        "SELECT idx, sha256, mime, data FROM check_images WHERE check_id = $1 ORDER BY idx",
        body["check_id"],
    )
    assert [r["idx"] for r in stored] == [0, 1, 2]
    assert all(r["mime"] == "image/jpeg" and r["data"] for r in stored)
    assert stored[0]["data"] == images[0].data  # exactly what the model saw

    got = await db_client.get(f"/checks/{body['check_id']}")
    assert got.status_code == 200
    assert got.json() == body


async def test_recipe_is_used(db_client, fake):
    fake.answers = [P16]
    spec = json.dumps(
        {"ingredients": [{"name": "борошно пшеничне", "allergens": ["cereals"]}], "form": "solid"}
    )
    body = (await post(db_client, photos(2), spec)).json()
    rules = {(f["rule_id"], f["target"]) for f in body["findings"]}
    assert ("ALG-SPEC-MISSING", "cereals") in rules


@pytest.mark.parametrize(
    "spec",
    ['{"ingredients": [{"name": "молоко", "alergens": ["milk"]}]}', "not json", '{"form": "gas"}'],
)
async def test_invalid_spec_is_422_before_the_model(db_client, fake, spec):
    resp = await post(db_client, photos(1), spec)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
    assert resp.json()["error"]["message"].startswith("spec")
    assert fake.calls == []


async def test_no_photos_is_422(db_client, fake):
    resp = await db_client.post("/checks", data={"spec": "{}"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
    assert fake.calls == []


async def test_five_photos_is_422(db_client, fake):
    resp = await post(db_client, photos(5))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "too_many_images"
    assert fake.calls == []


async def test_not_an_image_is_422(db_client, fake):
    resp = await post(db_client, [("images", ("label.pdf", b"%PDF-1.4", "application/pdf"))])
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "image_unsupported"
    assert fake.calls == []


async def test_cache_hit_skips_the_model_but_order_is_part_of_the_key(db_client, fake):
    fake.answers = [P02, P02]
    first = (await post(db_client, photos(3))).json()
    second = (await post(db_client, photos(3))).json()
    assert len(fake.calls) == 1
    assert second["cache_hit"] is True
    assert second["extraction"] == first["extraction"]
    assert second["check_id"] != first["check_id"]

    reordered = list(reversed(photos(3)))
    third = (await post(db_client, reordered)).json()
    assert len(fake.calls) == 2  # photo_index depends on the order: a different key
    assert third["cache_hit"] is False


async def test_model_error_is_stored_as_error_never_a_verdict(db_client, db_pool, fake):
    fake.answers = [VisionError("gemini: ліміт", code="vision_rate_limited", status_code=503)]
    resp = await post(db_client, photos(2))
    assert resp.status_code == 503
    error = resp.json()["error"]
    assert error["code"] == "vision_rate_limited"
    row = await db_pool.fetchrow("SELECT * FROM checks ORDER BY id DESC LIMIT 1")
    assert (row["status"], row["verdict"]) == ("error", None)
    assert json.loads(row["error"])["code"] == "vision_rate_limited"
    assert str(row["id"]) in error["message"]
    count = "SELECT count(*) FROM check_images WHERE check_id = $1"
    assert await db_pool.fetchval(count, row["id"]) == 2

    got = (await db_client.get(f"/checks/{row['id']}")).json()
    assert (got["status"], got["verdict"], got["findings"]) == ("error", None, [])
    assert got["error"]["code"] == "vision_rate_limited"
    # nothing cached from a failure
    assert await db_pool.fetchval("SELECT count(*) FROM extraction_cache") == 0


async def test_bad_output_twice_is_vision_bad_output_with_raw_text(db_client, db_pool, fake):
    fake.answers = ["I cannot read this label.", '{"photos": "front"}']
    resp = await post(db_client, photos(1))
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "vision_bad_output"
    assert len(fake.calls) == 2
    assert "could not be used" in fake.calls[1][1]  # the re-ask quotes the reason
    row = await db_pool.fetchrow("SELECT * FROM checks ORDER BY id DESC LIMIT 1")
    assert row["status"] == "error" and row["verdict"] is None
    assert "I cannot read this label." in row["raw_text"] and '"front"' in row["raw_text"]


async def test_bad_output_once_then_valid(db_client, fake):
    fake.answers = ["```json\n{ broken", P02]
    body = (await post(db_client, photos(3))).json()
    assert body["status"] == "done"
    assert len(fake.calls) == 2


class SlowVision(FakeVision):
    async def extract(self, images, prompt, *, schema=None):
        await asyncio.sleep(5)
        return await super().extract(images, prompt, schema=schema)


async def test_deadline_gives_504_and_an_error_record(db_client, db_pool, monkeypatch):
    monkeypatch.setattr(get_settings(), "vision_deadline_seconds", 0.05)
    app.state.vision = SlowVision([P02])
    try:
        resp = await post(db_client, photos(1))
    finally:
        del app.state.vision
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "vision_timeout"
    row = await db_pool.fetchrow("SELECT * FROM checks ORDER BY id DESC LIMIT 1")
    assert (row["status"], row["verdict"]) == ("error", None)
    assert json.loads(row["error"])["code"] == "vision_timeout"


async def test_get_unknown_check_is_404(db_client):
    resp = await db_client.get("/checks/999999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("check_id", ["0", "-1", "99999999999999999999"])
async def test_get_check_id_out_of_range_is_422_not_500(db_client, check_id):
    # Review 02.10.2026: an id past BIGINT reached asyncpg and gave 500 internal_error.
    resp = await db_client.get(f"/checks/{check_id}")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_openapi_documents_the_errors(db_client):
    spec = (await db_client.get("/openapi.json")).json()
    post_op = spec["paths"]["/checks"]["post"]
    assert {"422", "502", "503", "504"} <= set(post_op["responses"])
