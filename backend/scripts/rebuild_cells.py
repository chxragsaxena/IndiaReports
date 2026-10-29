"""Rebuild the clusters/dashboard rollup from the reports table.

    python -m scripts.rebuild_cells

Run after loading data directly into the database (the application keeps the rollup
current on its own for every report it creates or updates).
"""

import asyncio

from app.db.session import AsyncSessionLocal
from app.services.cell_service import rebuild


async def main() -> None:
    async with AsyncSessionLocal() as session:
        cells = await rebuild(session)
        await session.commit()
    print(f"rebuilt rollup: {cells} cells")


if __name__ == "__main__":
    asyncio.run(main())
