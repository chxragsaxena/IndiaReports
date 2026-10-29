import json
import os

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.redis import get_redis
from app.db.session import engine
from app.events.outbox import relay_once
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
    assert [r.event_type for r in rows] == ["ReportCreated"]
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
    assert types == ["ReportCreated", "ReportStatusChanged"]


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
