"""Finding reports that are probably the same problem.

Two reports are likely the same when they are about the same kind of problem, close together,
still unresolved, and either worded alike or practically at the same spot. Words are compared
as sets, so this works for any script; when two reports are in different languages the wording
will not match, and only the very-close-by rule can link them.
"""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2 import Geography

from app.models.enums import ReportStatus
from app.models.report import Report

RADIUS_M = 150  # only reports this close are candidates
SAME_SPOT_M = 30  # this close, it is the same problem whatever the wording
MIN_TEXT_MATCH = 0.2  # share of words in common that counts as "worded alike"
# 0.002 degrees is at least 180 m anywhere in India: a cheap box the spatial index can use,
# before the exact distance in metres is measured.
BOX_DEGREES = 0.002

# \w leaves out the combining vowel signs that Indian scripts depend on, so add those blocks.
_WORD = re.compile(r"[\ẁ-ͯऀ-෿]{3,}", re.UNICODE)


def words(*parts: str) -> set[str]:
    return {w.lower() for part in parts for w in _WORD.findall(part)}


def text_match(a: set[str], b: set[str]) -> float:
    """Overlap of two word sets, relative to the smaller one (a short title inside a long
    description should still match)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


@dataclass(frozen=True)
class Match:
    report: Report
    distance_m: float
    text_score: float


async def find_similar(
    db: AsyncSession,
    latitude: float,
    longitude: float,
    category: str,
    title: str,
    description: str,
    exclude_id: uuid.UUID | None = None,
    limit: int = 3,
) -> list[Match]:
    """Open, still-visible reports nearby that look like the same problem, best first."""
    point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)
    distance = func.ST_Distance(cast(Report.geom, Geography), cast(point, Geography))
    query = (
        select(Report, distance)
        .where(
            func.ST_DWithin(Report.geom, point, BOX_DEGREES),
            Report.category == category,
            Report.status != ReportStatus.RESOLVED.value,
            Report.archived_at.is_(None),
            Report.possible_duplicate_of.is_(None),  # link to the original, never to another copy
        )
        .order_by(distance)
        .limit(25)
    )
    if exclude_id is not None:
        query = query.where(Report.id != exclude_id)

    mine = words(title, description)
    matches = []
    for report, metres in (await db.execute(query)).all():
        if metres > RADIUS_M:
            continue
        score = text_match(mine, words(report.title, report.description))
        if metres <= SAME_SPOT_M or score >= MIN_TEXT_MATCH:
            matches.append(Match(report, float(metres), score))
    matches.sort(key=lambda m: (-m.text_score, m.distance_m))
    return matches[:limit]
