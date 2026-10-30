import json
import os

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.redis import get_redis
from app.db.session import engine
from app.events.outbox import relay_once
from app.events.rollup import rollup_once
from tests.conftest import sample_report

ADMIN = {"X-API-Key": os.environ["ADMIN_API_KEY"]}


async def test_create_and_get_report(client):
    r = await client.post("/api/v1/reports/", json=sample_report())
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "OPEN"
    assert body["created_at"] is not None

    got = await client.get(f"/api/v1/reports/{body['id']}")
    assert got.status_code == 200
    assert got.json()["title"] == "Large pothole"


async def test_validation_rejects_location_outside_india(client):
    r = await client.post("/api/v1/reports/", json=sample_report(latitude=51.5, longitude=-0.12))
    assert r.status_code == 422


async def test_create_writes_outbox_event_in_same_transaction(client):
    await client.post("/api/v1/reports/", json=sample_report())
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT event_type, published_at FROM outbox_events"))).all()
    assert [r.event_type for r in rows] == ["ReportCreated", "ReportTriageRequested"]
    assert rows[0].published_at is None


async def test_status_change_requires_admin_key(client):
    created = (await client.post("/api/v1/reports/", json=sample_report())).json()
    url = f"/api/v1/reports/{created['id']}/status"

    assert (await client.patch(url, json={"status": "RESOLVED"})).status_code == 401
    assert (
        await client.patch(url, json={"status": "RESOLVED"}, headers={"X-API-Key": "wrong"})
    ).status_code == 401


async def test_status_change_emits_event_once(client):
    created = (await client.post("/api/v1/reports/", json=sample_report())).json()
    url = f"/api/v1/reports/{created['id']}/status"

    r = await client.patch(url, json={"status": "IN_PROGRESS"}, headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["status"] == "IN_PROGRESS"

    # Same status again must be a no-op (idempotent, no duplicate event).
    again = await client.patch(url, json={"status": "IN_PROGRESS"}, headers=ADMIN)
    assert again.status_code == 200

    async with engine.connect() as conn:
        types = [
            r.event_type
            for r in (await conn.execute(text("SELECT event_type FROM outbox_events ORDER BY id"))).all()
        ]
    assert types == ["ReportCreated", "ReportTriageRequested", "ReportStatusChanged"]


async def test_status_change_404(client):
    r = await client.patch(
        "/api/v1/reports/00000000-0000-0000-0000-000000000000/status",
        json={"status": "RESOLVED"},
        headers=ADMIN,
    )
    assert r.status_code == 404


async def test_dashboard_counts_and_recent_order(client):
    for i in range(7):
        await client.post("/api/v1/reports/", json=sample_report(title=f"Report {i}"))
    created = (await client.post("/api/v1/reports/", json=sample_report(title="Newest", category="Fire"))).json()
    await client.patch(
        f"/api/v1/reports/{created['id']}/status", json={"status": "RESOLVED"}, headers=ADMIN
    )

    await rollup_once()  # the dashboard reads the rollup, which is applied in the background
    d = (await client.get("/api/v1/reports/dashboard")).json()
    assert d["total_reports"] == 8
    assert d["open_reports"] == 7
    assert d["resolved_reports"] == 1
    assert d["by_category"]["Fire"] == 1
    assert len(d["recent_reports"]) == 5
    assert d["recent_reports"][0]["title"] == "Newest"


async def test_viewport_filter_and_limit(client):
    await client.post("/api/v1/reports/", json=sample_report(title="Delhi one"))
    await client.post(
        "/api/v1/reports/",
        json=sample_report(title="Mumbai one", latitude=19.076, longitude=72.8777, city="Mumbai"),
    )

    delhi = (
        await client.get(
            "/api/v1/reports/",
            params={"min_lat": 28, "max_lat": 29, "min_lng": 76, "max_lng": 78},
        )
    ).json()
    assert [r["title"] for r in delhi] == ["Delhi one"]

    limited = (await client.get("/api/v1/reports/", params={"limit": 1})).json()
    assert len(limited) == 1


async def test_clusters_group_nearby_reports(client):
    for _ in range(3):
        await client.post("/api/v1/reports/", json=sample_report())
    await rollup_once()
    clusters = (
        await client.get(
            "/api/v1/reports/clusters",
            params={"min_lat": 6, "max_lat": 38, "min_lng": 68, "max_lng": 98, "zoom": 4},
        )
    ).json()
    assert sum(c["count"] for c in clusters) == 3
    assert len(clusters) == 1

async def test_relay_publishes_each_event_once(client):
    redis = get_redis()
    if redis is None:
        pytest.skip("REDIS_URL not set")

    created = (await client.post("/api/v1/reports/", json=sample_report())).json()
    await client.patch(
        f"/api/v1/reports/{created['id']}/status", json={"status": "RESOLVED"}, headers=ADMIN
    )

    assert await relay_once() == 2
    assert await relay_once() == 0  # nothing is published twice

    entries = await redis.xrange(settings.EVENT_STREAM)
    assert [e[1]["type"] for e in entries] == ["ReportCreated", "ReportStatusChanged"]
    payload = json.loads(entries[1][1]["data"])
    assert payload["old_status"] == "OPEN" and payload["new_status"] == "RESOLVED"


async def test_rate_limit_blocks_excess_writes(client, monkeypatch):
    if get_redis() is None:
        pytest.skip("REDIS_URL not set")
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 2)

    codes = [
        (await client.post("/api/v1/reports/", json=sample_report())).status_code
        for _ in range(3)
    ]
    assert codes == [201, 201, 429]


async def test_pins_are_lightweight_and_filtered(client):
    await client.post("/api/v1/reports/", json=sample_report(title="Delhi pin"))
    await client.post(
        "/api/v1/reports/",
        json=sample_report(title="Mumbai pin", latitude=19.076, longitude=72.8777, city="Mumbai"),
    )
    r = await client.get(
        "/api/v1/reports/pins",
        params={"min_lat": 28, "max_lat": 29, "min_lng": 76, "max_lng": 78},
    )
    body = r.json()
    assert r.status_code == 200
    assert body["truncated"] is False
    assert len(body["pins"]) == 1
    assert abs(body["pins"][0]["latitude"] - 28.6139) < 1e-6
    # Only what the map draws: no title, description, address, officer or timestamps.
    assert set(body["pins"][0]) == {"id", "status", "latitude", "longitude"}


async def test_pins_report_truncation(client, monkeypatch):
    monkeypatch.setattr(settings, "MAX_PINS_PER_QUERY", 2)
    for i in range(3):
        await client.post("/api/v1/reports/", json=sample_report(title=f"Pin {i}"))
    body = (
        await client.get(
            "/api/v1/reports/pins",
            params={"min_lat": 28, "max_lat": 29, "min_lng": 76, "max_lng": 78},
        )
    ).json()
    assert body["truncated"] is True
    assert len(body["pins"]) == 2


async def _rollup(conn, level):
    rows = await conn.execute(
        text("SELECT status, category, sum(cnt)::int AS n FROM report_cells WHERE level = :l GROUP BY 1, 2 HAVING sum(cnt) > 0"),
        {"l": level},
    )
    return {(r.status, r.category): r.n for r in rows}


async def _table_counts(conn):
    rows = await conn.execute(text("SELECT status, category, count(*)::int AS n FROM reports GROUP BY 1, 2"))
    return {(r.status, r.category): r.n for r in rows}


async def test_rollup_stays_consistent_with_the_reports_table(client):
    ids = []
    for i in range(6):
        cat = ["Road", "Fire", "Garbage"][i % 3]
        created = (await client.post("/api/v1/reports/", json=sample_report(category=cat, title=f"Report {i}"))).json()
        ids.append(created["id"])
    await client.patch(f"/api/v1/reports/{ids[0]}/status", json={"status": "IN_PROGRESS"}, headers=ADMIN)
    await client.patch(f"/api/v1/reports/{ids[1]}/status", json={"status": "RESOLVED"}, headers=ADMIN)
    await client.patch(f"/api/v1/reports/{ids[1]}/status", json={"status": "OPEN"}, headers=ADMIN)

    await rollup_once()
    async with engine.connect() as conn:
        expected = await _table_counts(conn)
        for level in (3, 6, 10):  # coarse, middle and finest grids all agree with the table
            assert await _rollup(conn, level) == expected


async def test_rebuild_repairs_a_damaged_rollup(client):
    from app.db.session import AsyncSessionLocal
    from app.services.cell_service import rebuild

    for i in range(4):
        r = await client.post("/api/v1/reports/", json=sample_report(title=f"Report {i}"))
        assert r.status_code == 201
    async with engine.begin() as conn:
        assert await _table_counts(conn)  # the table really has rows to compare against
        await conn.execute(text("DELETE FROM report_cells WHERE level >= 5"))

    async with AsyncSessionLocal() as session:
        await rebuild(session)
        await session.commit()

    async with engine.connect() as conn:
        expected = await _table_counts(conn)
        assert await _rollup(conn, 3) == expected
        assert await _rollup(conn, 9) == expected

    # Rebuilding marked the pending events as counted, so the applier must not add them again.
    assert await rollup_once() == 0
    async with engine.connect() as conn:
        assert await _rollup(conn, 3) == expected


async def test_cluster_centroid_and_filter(client):
    await client.post("/api/v1/reports/", json=sample_report(latitude=28.60, longitude=77.20, category="Road"))
    await client.post("/api/v1/reports/", json=sample_report(latitude=28.62, longitude=77.22, category="Road"))
    await client.post("/api/v1/reports/", json=sample_report(latitude=28.61, longitude=77.21, category="Fire"))

    await rollup_once()
    params = {"min_lat": 6, "max_lat": 38, "min_lng": 68, "max_lng": 98, "zoom": 10}
    everything = (await client.get("/api/v1/reports/clusters", params=params)).json()
    assert sum(c["count"] for c in everything) == 3

    roads = (await client.get("/api/v1/reports/clusters", params=params | {"category": "Road"})).json()
    assert sum(c["count"] for c in roads) == 2
    assert all(28.5 < c["latitude"] < 28.7 and 77.1 < c["longitude"] < 77.3 for c in roads)


async def test_single_flight_computes_a_cold_key_once():
    import asyncio

    from app.core.cache import cached_json

    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.2)
        return {"ok": True}

    results = await asyncio.gather(*[cached_json("cache:test:single-flight", 30, compute) for _ in range(25)])
    assert calls == 1
    assert all(r == '{"ok":true}' for r in results)


async def test_helper_rejects_nothing_silently(client):
    """Guards the tests above: a create that fails must not be mistaken for an empty table."""
    r = await client.post("/api/v1/reports/", json=sample_report(title="ab"))
    assert r.status_code == 422


async def test_rollup_is_applied_exactly_once_per_event(client):
    for i in range(3):
        r = await client.post("/api/v1/reports/", json=sample_report(title=f"Report {i}"))
        assert r.status_code == 201

    assert await rollup_once() == 6  # each report queues a created event and a triage request
    assert await rollup_once() == 0  # nothing is applied twice

    async with engine.connect() as conn:
        assert await _rollup(conn, 3) == await _table_counts(conn)


async def test_writes_do_not_touch_the_rollup_in_the_request(client):
    """The request path only writes the report and its event; the map catches up after."""
    await client.post("/api/v1/reports/", json=sample_report())
    async with engine.connect() as conn:
        assert await _rollup(conn, 3) == {}
    await rollup_once()
    async with engine.connect() as conn:
        assert sum((await _rollup(conn, 3)).values()) == 1


async def test_responses_are_compressed_when_large(client):
    for i in range(30):
        await client.post("/api/v1/reports/", json=sample_report(title=f"Report {i}", description="x" * 200))
    r = await client.get("/api/v1/reports/", params={"limit": 30}, headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"


async def test_exhausted_connection_pool_answers_503_with_retry_after(client):
    """When every database connection is busy the API sheds load politely, not with a 500."""
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from app.db.session import get_db
    from app.main import app

    async def broken_db():
        raise PoolTimeout("QueuePool limit reached")
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = broken_db
    try:
        r = await client.get("/api/v1/reports/dashboard")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 503
    assert r.headers["retry-after"] == "2"
