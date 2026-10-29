"""The grid rollup behind clusters and dashboard counts.

Each report is counted once per map level in `report_cells`. Reading clusters is then
a range scan over a few thousand rows however many reports exist, instead of an
aggregate over the whole reports table.
"""

import math
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Map zoom level -> grid cell size in degrees. Pins replace clusters from PIN_ZOOM.
LEVELS: dict[int, float] = {3: 2.0, 4: 1.2, 5: 0.7, 6: 0.35, 7: 0.18, 8: 0.1, 9: 0.05, 10: 0.025}
MIN_LEVEL = min(LEVELS)
MAX_LEVEL = max(LEVELS)
PIN_ZOOM = 11

# Level whose cells cover every report exactly once: used for global counts.
TOTALS_LEVEL = MIN_LEVEL


def level_for_zoom(zoom: int) -> int:
    return max(MIN_LEVEL, min(MAX_LEVEL, zoom))


def grid_for_zoom(zoom: int) -> float:
    return LEVELS[level_for_zoom(zoom)]


def cell_of(value: float, grid: float) -> int:
    return math.floor(value / grid)


_UPSERT = text(
    """
    INSERT INTO report_cells (level, cx, cy, status, category, cnt, sum_lat, sum_lng)
    SELECT * FROM unnest(
        CAST(:level AS smallint[]), CAST(:cx AS integer[]), CAST(:cy AS integer[]),
        CAST(:status AS text[]), CAST(:category AS text[]),
        CAST(:cnt AS bigint[]), CAST(:sum_lat AS double precision[]), CAST(:sum_lng AS double precision[])
    )
    ON CONFLICT (level, cx, cy, status, category) DO UPDATE SET
        cnt = report_cells.cnt + EXCLUDED.cnt,
        sum_lat = report_cells.sum_lat + EXCLUDED.sum_lat,
        sum_lng = report_cells.sum_lng + EXCLUDED.sum_lng
    """
)


async def apply_deltas(
    db: AsyncSession,
    changes: Iterable[tuple[float, float, str, str, int]],
) -> None:
    """Add (lat, lng, status, category, +1 or -1) changes to the rollup, in the
    caller's transaction. Rows are applied in primary-key order so two concurrent
    transactions touching overlapping cells cannot deadlock each other."""
    merged: dict[tuple[int, int, int, str, str], list[float]] = {}
    for lat, lng, status, category, delta in changes:
        for level, grid in LEVELS.items():
            key = (level, cell_of(lat, grid), cell_of(lng, grid), status, category)
            acc = merged.setdefault(key, [0, 0.0, 0.0])
            acc[0] += delta
            acc[1] += delta * lat
            acc[2] += delta * lng

    if not merged:
        return

    rows = sorted(merged.items())
    await db.execute(
        _UPSERT,
        {
            "level": [k[0] for k, _ in rows],
            "cx": [k[1] for k, _ in rows],
            "cy": [k[2] for k, _ in rows],
            "status": [k[3] for k, _ in rows],
            "category": [k[4] for k, _ in rows],
            "cnt": [int(v[0]) for _, v in rows],
            "sum_lat": [v[1] for _, v in rows],
            "sum_lng": [v[2] for _, v in rows],
        },
    )


async def rebuild(db: AsyncSession) -> int:
    """Recompute the whole rollup from the reports table (repair, or after bulk loads
    that bypass the application). Returns the number of cells written.

    Must be the first statement of its transaction. It runs on one snapshot so the
    table scan and the "events already counted" marker agree: every event visible
    here is reflected in the rebuilt cells, and none is applied a second time. If
    the background applier is writing at the same moment this fails with a
    serialization error, which is safe: just run it again."""
    await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    await db.execute(text("DELETE FROM report_cells"))
    for level, grid in LEVELS.items():
        await db.execute(
            text(
                f"""
                INSERT INTO report_cells (level, cx, cy, status, category, cnt, sum_lat, sum_lng)
                SELECT {int(level)}, floor(latitude / {float(grid)})::int, floor(longitude / {float(grid)})::int,
                       status, category, count(*), sum(latitude), sum(longitude)
                FROM reports
                GROUP BY 2, 3, status, category
                """
            )
        )
    # The rebuilt cells already include every event in this snapshot.
    await db.execute(text("UPDATE outbox_events SET rolled_up_at = now() WHERE rolled_up_at IS NULL"))
    result = await db.execute(text("SELECT count(*) FROM report_cells"))
    return int(result.scalar_one())
