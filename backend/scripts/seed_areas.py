"""Demo data: one rectangular jurisdiction and one officer per seeded city, plus the main admin.

    python -m scripts.seed_areas

Telegram chat ids default to placeholders. To receive real alerts set
ADMIN_CHAT_ID and OFFICER_CHAT_ID (one chat can play every role in a demo).
Safe to run repeatedly: existing areas and the admin are left alone.
"""

import asyncio
import os

from geoalchemy2.elements import WKTElement
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.area import Area, Officer

# name, centre lat, centre lng
CITIES = [
    ("Delhi", 28.6139, 77.2090),
    ("Mumbai", 19.0760, 72.8777),
    ("Bengaluru", 12.9716, 77.5946),
    ("Hyderabad", 17.3850, 78.4867),
    ("Chennai", 13.0827, 80.2707),
    ("Pune", 18.5204, 73.8567),
    ("Kolkata", 22.5726, 88.3639),
    ("Ahmedabad", 23.0225, 72.5714),
    ("Jaipur", 26.9124, 75.7873),
    ("Bhopal", 23.2599, 77.4126),
]

HALF_SIDE = 0.25  # degrees, roughly a 55 km square


def square_wkt(lat: float, lng: float) -> str:
    s, n, w, e = lat - HALF_SIDE, lat + HALF_SIDE, lng - HALF_SIDE, lng + HALF_SIDE
    return f"MULTIPOLYGON((({w} {s}, {e} {s}, {e} {n}, {w} {n}, {w} {s})))"


async def seed() -> None:
    admin_chat = os.environ.get("ADMIN_CHAT_ID", "900000001")
    officer_chat = os.environ.get("OFFICER_CHAT_ID")

    async with AsyncSessionLocal() as session:
        admin = (
            await session.execute(select(Officer).where(Officer.role == "admin", Officer.active.is_(True)))
        ).scalar_one_or_none()
        if admin is None:
            session.add(Officer(name="Main Admin", role="admin", telegram_chat_id=admin_chat))
            print("created main admin")

        for i, (city, lat, lng) in enumerate(CITIES):
            name = f"{city} jurisdiction"
            exists = (await session.execute(select(Area).where(Area.name == name))).scalar_one_or_none()
            if exists:
                continue
            area = Area(name=name, geom=WKTElement(square_wkt(lat, lng), srid=4326))
            session.add(area)
            await session.flush()
            session.add(
                Officer(
                    name=f"{city} officer",
                    role="officer",
                    telegram_chat_id=officer_chat or str(100000001 + i),
                    area_id=area.id,
                )
            )
            print(f"created {name}")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
