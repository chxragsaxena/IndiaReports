import asyncio
import random

from sqlalchemy import delete

from app.db.session import AsyncSessionLocal
from app.models.report import Report
from app.models.enums import ReportCategory, ReportStatus

# --------------------------------------------------
# Cities
# --------------------------------------------------

CITIES = [
    ("Delhi", "New Delhi", "Delhi", "110001", 28.6139, 77.2090),
    ("Mumbai", "Mumbai", "Maharashtra", "400001", 19.0760, 72.8777),
    ("Bengaluru", "Bengaluru Urban", "Karnataka", "560001", 12.9716, 77.5946),
    ("Hyderabad", "Hyderabad", "Telangana", "500001", 17.3850, 78.4867),
    ("Chennai", "Chennai", "Tamil Nadu", "600001", 13.0827, 80.2707),
    ("Pune", "Pune", "Maharashtra", "411001", 18.5204, 73.8567),
    ("Kolkata", "Kolkata", "West Bengal", "700001", 22.5726, 88.3639),
    ("Ahmedabad", "Ahmedabad", "Gujarat", "380001", 23.0225, 72.5714),
    ("Jaipur", "Jaipur", "Rajasthan", "302001", 26.9124, 75.7873),
    ("Bhopal", "Bhopal", "Madhya Pradesh", "462001", 23.2599, 77.4126),
]

CITY_WEIGHTS = [60, 50, 45, 35, 30, 25, 25, 20, 15, 20]

# --------------------------------------------------
# Issues
# --------------------------------------------------

ISSUES = [
    {
        "title": "Large pothole",
        "category": ReportCategory.ROAD.value,
        "description": "Large pothole causing inconvenience to commuters."
    },
    {
        "title": "Damaged road surface",
        "category": ReportCategory.ROAD.value,
        "description": "Road surface has deteriorated after heavy rainfall."
    },
    {
        "title": "Water pipeline leakage",
        "category": ReportCategory.WATER.value,
        "description": "Continuous leakage wasting clean drinking water."
    },
    {
        "title": "Power outage",
        "category": ReportCategory.ELECTRICITY.value,
        "description": "Frequent electricity disruption reported."
    },
    {
        "title": "Electric pole sparking",
        "category": ReportCategory.ELECTRICITY.value,
        "description": "Electric pole is sparking and poses safety risks."
    },
    {
        "title": "Garbage not collected",
        "category": ReportCategory.GARBAGE.value,
        "description": "Garbage has accumulated for several days."
    },
    {
        "title": "Overflowing garbage bin",
        "category": ReportCategory.GARBAGE.value,
        "description": "Garbage bin has overflowed causing foul smell."
    },
    {
        "title": "Blocked drainage",
        "category": ReportCategory.DRAINAGE.value,
        "description": "Drain blockage causing waterlogging."
    },
    {
        "title": "Broken street light",
        "category": ReportCategory.STREET_LIGHT.value,
        "description": "Street light has stopped working."
    },
    {
        "title": "Traffic signal malfunction",
        "category": ReportCategory.TRAFFIC.value,
        "description": "Traffic signal not functioning properly."
    },
    {
        "title": "Damaged bus stop",
        "category": ReportCategory.PUBLIC_TRANSPORT.value,
        "description": "Public bus stop shelter needs repair."
    },
    {
        "title": "Suspicious activity",
        "category": ReportCategory.CRIME.value,
        "description": "Residents have reported suspicious activity."
    },
    {
        "title": "Medical emergency assistance",
        "category": ReportCategory.MEDICAL.value,
        "description": "Medical help urgently required."
    },
    {
        "title": "Damaged fire hydrant",
        "category": ReportCategory.FIRE.value,
        "description": "Fire hydrant damaged and requires maintenance."
    },
    {
        "title": "Other civic issue",
        "category": ReportCategory.OTHER.value,
        "description": "General civic issue reported."
    },
]

# --------------------------------------------------
# Landmarks
# --------------------------------------------------

LANDMARKS = {
    "Delhi": [
        "Connaught Place",
        "India Gate",
        "Karol Bagh",
        "Dwarka",
        "Saket",
        "Rohini",
    ],
    "Mumbai": [
        "Marine Drive",
        "Bandra",
        "Andheri",
        "Powai",
        "Dadar",
        "Juhu",
    ],
    "Bengaluru": [
        "MG Road",
        "Koramangala",
        "Whitefield",
        "Indiranagar",
        "Electronic City",
    ],
    "Hyderabad": [
        "Charminar",
        "Hitech City",
        "Banjara Hills",
        "Gachibowli",
    ],
    "Chennai": [
        "Marina Beach",
        "Anna Nagar",
        "Velachery",
        "T Nagar",
    ],
    "Pune": [
        "FC Road",
        "Kothrud",
        "Hinjewadi",
        "Shivaji Nagar",
    ],
    "Kolkata": [
        "Park Street",
        "Howrah",
        "Salt Lake",
        "New Town",
    ],
    "Ahmedabad": [
        "SG Highway",
        "Satellite",
        "Navrangpura",
        "Maninagar",
    ],
    "Jaipur": [
        "MI Road",
        "Vaishali Nagar",
        "Malviya Nagar",
        "C Scheme",
    ],
    "Bhopal": [
        "DB Mall",
        "AIIMS",
        "MP Nagar",
        "New Market",
        "Kolar Road",
        "Arera Colony",
    ],
}

# --------------------------------------------------

async def seed():

    async with AsyncSessionLocal() as session:

        print("Deleting old reports...")

        await session.execute(delete(Report))
        await session.commit()

        reports = []

        for _ in range(500):

            city, district, state, pincode, lat, lon = random.choices(
                CITIES,
                weights=CITY_WEIGHTS,
                k=1,
            )[0]

            issue = random.choice(ISSUES)

            landmark = random.choice(
                LANDMARKS[city]
            )

            report = Report(

                title=issue["title"],
                description=issue["description"],
                category=issue["category"],

                latitude=lat + random.uniform(-0.03, 0.03),
                longitude=lon + random.uniform(-0.03, 0.03),

                address=f"Near {landmark}",
                landmark=landmark,

                city=city,
                district=district,
                state=state,
                pincode=pincode,

                status=random.choices(
                    [
                        ReportStatus.OPEN.value,
                        ReportStatus.IN_PROGRESS.value,
                        ReportStatus.RESOLVED.value,
                    ],
                    weights=[55, 25, 20],
                    k=1,
                )[0],
            )

            reports.append(report)

        session.add_all(reports)

        await session.commit()

        print(f"Successfully inserted {len(reports)} reports.")


if __name__ == "__main__":
    asyncio.run(seed())