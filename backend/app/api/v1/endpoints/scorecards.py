"""Public scorecards: how each area is doing at fixing what is reported in it.

Public on purpose: the point is that residents can see whether their area's reports get fixed.
Only counts and times are shown, never report text. Reports the text triage flagged as spam
are left out, so an area is not marked down for them."""

import json

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cached_json
from app.core.config import settings
from app.db.session import get_db

router = APIRouter()

CACHE_TTL_SECONDS = 60
# Below this many judged reports a percentage says little, so the area is listed but not ranked.
MIN_RANKED = 5

AREA_STATS = text(
    """
    SELECT a.id, a.name,
        count(r.id) AS received,
        count(*) FILTER (WHERE r.status = 'RESOLVED') AS resolved,
        count(*) FILTER (WHERE r.status = 'RESOLVED' AND r.escalated_at IS NULL
                         AND r.resolved_at - r.assigned_at <= make_interval(secs => :sla)) AS in_time,
        count(*) FILTER (WHERE r.status <> 'RESOLVED' AND (r.escalated_at IS NOT NULL
                         OR r.assigned_at <= now() - make_interval(secs => :sla))) AS late_open,
        count(*) FILTER (WHERE r.status <> 'RESOLVED') AS open_now,
        count(*) FILTER (WHERE r.escalated_at IS NOT NULL) AS escalated,
        count(*) FILTER (WHERE r.reopen_count > 0) AS reopened,
        count(*) FILTER (WHERE r.reopen_count > 0 AND r.status <> 'RESOLVED') AS reopened_open,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM r.resolved_at - r.assigned_at))
            FILTER (WHERE r.status = 'RESOLVED' AND r.resolved_at IS NOT NULL AND r.assigned_at IS NOT NULL) AS median_secs
    FROM areas a
    JOIN reports r ON r.area_id = a.id AND NOT coalesce((r.triage ->> 'is_spam')::boolean, false)
    GROUP BY a.id, a.name
    """
)

OFFICERS = text(
    "SELECT area_id, name FROM officers WHERE role = 'officer' AND active AND area_id IS NOT NULL ORDER BY created_at"
)


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole > 0 else None


async def _compute(db: AsyncSession) -> dict:
    stats = (await db.execute(AREA_STATS, {"sla": float(settings.ESCALATION_AFTER_SECONDS)})).mappings().all()
    officers: dict = {}
    for row in (await db.execute(OFFICERS)).mappings():
        officers.setdefault(row["area_id"], []).append(row["name"])

    areas = []
    for s in stats:
        judged = s["resolved"] + s["late_open"]  # reports whose deadline has been decided one way or the other
        ever_resolved = s["resolved"] + s["reopened_open"]
        areas.append({
            "area_id": str(s["id"]),
            "area": s["name"],
            "officers": officers.get(s["id"], []),
            "received": s["received"],
            "resolved": s["resolved"],
            "open_now": s["open_now"],
            "late_open": s["late_open"],
            "escalated": s["escalated"],
            "reopened": s["reopened"],
            "in_time_rate": _rate(s["in_time"], judged),
            "reopen_rate": _rate(s["reopened"], ever_resolved),
            "median_resolution_hours": round(s["median_secs"] / 3600, 1) if s["median_secs"] is not None else None,
            "ranked": judged >= MIN_RANKED,
        })
    # Ranked areas first, best first; the rest alphabetically.
    areas.sort(key=lambda a: (not a["ranked"], -(a["in_time_rate"] or 0) if a["ranked"] else 0, a["area"]))
    return {
        "resolve_within_days": round(settings.ESCALATION_AFTER_SECONDS / 86400, 1),
        "min_ranked": MIN_RANKED,
        "areas": areas,
    }


@router.get("")
async def scorecards(db: AsyncSession = Depends(get_db)):
    body = await cached_json("scorecards", CACHE_TTL_SECONDS, lambda: _compute(db))
    return Response(content=body, media_type="application/json", headers={"Cache-Control": "public, max-age=30"})
