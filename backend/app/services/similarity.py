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


# Words that say nothing about WHICH problem it is. Without this, "the road near the school" matches every other
# report that has "the" and "near" in it. Only everyday function words and place prepositions are listed (a standard
# English list plus the common Hindi and Hinglish ones), never words that name a problem such as "pothole" or "garbage".
STOP_WORDS = frozenset(
    """the and for are was were has have had not but with from that this there their they them these those been being into onto
    over under out our your its all any can will would should could very just also than then too more most some such only
    near outside inside next beside around opposite behind front side here every each also about after before since while
    when where which who what why how due because please kindly issue problem
    नहीं कोई बहुत हमारी हमारे हमारा रहा रही रहे गया गई गये करें करो जिससे लिए वाले वालों इसके उसके यहाँ वहाँ
    hai hain nahi koi bahut hamare hamari hamara raha rahi rahe liye wala wale""".split()
)


def words(*parts: str) -> set[str]:
    return {w.lower() for part in parts for w in _WORD.findall(part) if w.lower() not in STOP_WORDS}


def text_match(a: set[str], b: set[str]) -> float:
    """Overlap of two word sets, relative to the smaller one (a short title inside a long
    description should still match)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def is_duplicate(metres: float, score: float, radius: float = RADIUS_M, same_spot: float = SAME_SPOT_M, min_text: float = MIN_TEXT_MATCH) -> bool:
    """The rule itself, apart from the database: close enough, and either at the same spot or worded alike.
    The defaults are what the server uses; the arguments exist so the evaluation can try other values."""
    return metres <= radius and (metres <= same_spot or score >= min_text)


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
        score = text_match(mine, words(report.title, report.description))
        if is_duplicate(metres, score):
            matches.append(Match(report, float(metres), score))
    matches.sort(key=lambda m: (-m.text_score, m.distance_m))
    return matches[:limit]
