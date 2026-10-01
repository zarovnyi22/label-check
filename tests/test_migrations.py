from app.db import apply_migrations


async def test_migrations_run_twice_without_errors_and_keep_data(db_pool):
    check_id = await db_pool.fetchval("INSERT INTO checks (status) VALUES ('done') RETURNING id")

    await apply_migrations(db_pool)  # db_pool has already applied them once
    await apply_migrations(db_pool)

    tables = await db_pool.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    assert {"checks", "check_images", "extraction_cache"} <= {r["table_name"] for r in tables}
    assert await db_pool.fetchval("SELECT count(*) FROM checks WHERE id = $1", check_id) == 1


async def test_checks_keeps_raw_model_output(db_pool):
    # raw_text is stored on model errors too (docs/SPEC.md §3).
    raw = await db_pool.fetchval(
        "INSERT INTO checks (status, raw_text) VALUES ('error', 'not json{') RETURNING raw_text"
    )
    assert raw == "not json{"
