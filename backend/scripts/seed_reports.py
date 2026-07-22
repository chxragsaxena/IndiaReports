import asyncio
import random

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.session import AsyncSessionLocal
from app.models.report import Report
from app.models.enums import ReportCategory, ReportStatus

cities = [
    ("Bhopal", "Bhopal", "Madhya Pradesh", "462001", 23.2599, 77.4126),
    ("Delhi", "New Delhi", "Delhi", "110001", 28.6139, 77.2090),
    ("Mumbai", "Mumbai", "Maharashtra", "400001", 19.0760, 72.8777),
    ("Bengaluru", "Bengaluru Urban", "Karnataka", "560001", 12.9716, 77.5946),
    ("Hyderabad", "Hyderabad", "Telangana", "500001", 17.3850, 78.4867),
    ("Pune", "Pune", "Maharashtra", "411001", 18.5204, 73.8567),
    ("Chennai", "Chennai", "Tamil Nadu", "600001", 13.0827, 80.2707),
    ("Kolkata", "Kolkata", "West Bengal", "700001", 22.5726, 88.3639),
    ("Ahmedabad", "Ahmedabad", "Gujarat", "380001", 23.0225, 72.5714),
    ("Jaipur", "Jaipur", "Rajasthan", "302001", 26.9124, 75.7873),
]

titles = [
    "Large pothole",
    "Garbage not collected",
    "Water leakage",
    "Broken street light",
    "Road damaged",
    "Open drain",
    "Electric pole issue",
    "Traffic signal not working",
    "Overflowing garbage bin",
    "Illegal dumping",
]

descriptions = [
    "Residents have complained for several days.",
    "Issue is causing inconvenience to commuters.",
    "Needs immediate municipal attention.",
    "Public safety is affected.",
    "Problem has existed for over a week.",
]

landmarks = [
    "Near Bus Stand",
    "Near Railway Station",
    "Near Market",
    "Near School",
    "Near Hospital",
    "Near Temple",
    "Near Petrol Pump",
]

categories = [c.value for c in ReportCategory]
statuses = [s.value for s in ReportStatus]


async def seed():
    async with AsyncSessionLocal() as session:

        reports = []

        for _ in range(250):

            city, district, state, pincode, lat, lon = random.choice(cities)

            latitude = lat + random.uniform(-0.04, 0.04)
            longitude = lon + random.uniform(-0.04, 0.04)

            report = Report(
                title=random.choice(titles),
                description=random.choice(descriptions),
                category=random.choice(categories),
                latitude=latitude,
                longitude=longitude,
                address=f"{random.randint(1,300)} Main Road",
                landmark=random.choice(landmarks),
                city=city,
                district=district,
                state=state,
                pincode=pincode,
                status=random.choices(
                    statuses,
                    weights=[60, 25, 15],
                    k=1,
                )[0],
            )

            reports.append(report)

        session.add_all(reports)

        await session.commit()

        print(f"Inserted {len(reports)} reports.")


if __name__ == "__main__":
    asyncio.run(seed())