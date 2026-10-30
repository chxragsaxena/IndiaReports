import asyncio
import random

from datetime import datetime, timedelta, timezone

from geoalchemy2.elements import WKTElement
from sqlalchemy import delete

from app.db.session import AsyncSessionLocal
from app.events.outbox import add_event, report_created_payload, status_changed_payload
from app.models.outbox import OutboxEvent
from app.models.report import Report
from app.services.assignment_service import find_assignee, get_admin
from app.services.cell_service import rebuild
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

HISTORY_DAYS = 30
ESCALATION_DAYS = 7


def pick_times(now: datetime, status: str) -> tuple[datetime, datetime | None]:
    """A creation time within the last 30 days (recent days are busier) and, for
    resolved reports, a resolution time after a realistic delay (hours to ~10 days)."""
    created = now - timedelta(days=HISTORY_DAYS * random.random() ** 1.6, minutes=random.randint(0, 1439))
    created = min(created, now - timedelta(minutes=5))
    if status != ReportStatus.RESOLVED.value:
        return created, None
    delay = timedelta(hours=min(240.0, random.lognormvariate(3.0, 1.0)))
    return created, min(created + delay, now - timedelta(minutes=1))


async def seed():
    """Replaces all reports with demo data. Events are marked historical so the
    notifier does not alert anyone about them, while analytics still counts them."""

    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:

        print("Deleting old reports and events...")

        await session.execute(delete(Report))
        await session.execute(delete(OutboxEvent))
        await session.commit()

        admin = await get_admin(session)
        escalate_after = timedelta(days=ESCALATION_DAYS)

        for _ in range(500):

            city, district, state, pincode, lat, lon = random.choices(
                CITIES,
                weights=CITY_WEIGHTS,
                k=1,
            )[0]

            issue = random.choice(ISSUES)
            landmark = random.choice(LANDMARKS[city])

            status = random.choices(
                [
                    ReportStatus.OPEN.value,
                    ReportStatus.IN_PROGRESS.value,
                    ReportStatus.RESOLVED.value,
                ],
                weights=[55, 25, 20],
                k=1,
            )[0]
            created_at, resolved_at = pick_times(now, status)

            latitude = lat + random.uniform(-0.03, 0.03)
            longitude = lon + random.uniform(-0.03, 0.03)

            report = Report(
                title=issue["title"],
                description=issue["description"],
                category=issue["category"],
                latitude=latitude,
                longitude=longitude,
                geom=WKTElement(f"POINT({longitude} {latitude})", srid=4326),
                address=f"Near {landmark}",
                landmark=landmark,
                city=city,
                district=district,
                state=state,
                pincode=pincode,
                status=ReportStatus.OPEN.value,
                created_at=created_at,
                updated_at=created_at,
            )
            session.add(report)
            await session.flush()

            assignee = await find_assignee(session, latitude, longitude)
            if assignee is not None:
                report.assigned_officer_id = assignee.id
                report.assigned_at = created_at
                if assignee.role == "officer":
                    report.area_id = assignee.area_id

            # Old, never-acknowledged reports have already escalated to the admin; recording
            # that here stops the live escalation job from alerting about the whole backlog.
            if (
                status == ReportStatus.OPEN.value
                and assignee is not None
                and admin is not None
                and assignee.id != admin.id
                and created_at + escalate_after < now
            ):
                report.escalated_at = created_at + escalate_after
                report.assigned_officer_id = admin.id

            created_payload = report_created_payload(report) | {"historical": True}
            add_event(session, "ReportCreated", created_payload)

            if status != ReportStatus.OPEN.value:
                changed_at = resolved_at or (created_at + timedelta(hours=random.randint(1, 36)))
                changed_at = min(changed_at, now - timedelta(minutes=1))
                report.status = status
                if status == ReportStatus.RESOLVED.value:
                    report.resolved_at = changed_at
                    if random.random() < 0.12:
                        report.reopen_count = 1
                report.acknowledged_at = created_at + timedelta(minutes=random.randint(10, 600))
                report.updated_at = changed_at
                add_event(
                    session,
                    "ReportStatusChanged",
                    status_changed_payload(report, ReportStatus.OPEN.value, changed_at) | {"historical": True},
                )

        await session.commit()

    # The reports were written directly, so build the map/dashboard rollup from them.
    # (This also marks the seeded events as already counted.)
    async with AsyncSessionLocal() as session:
        cells = await rebuild(session)
        await session.commit()

    print(f"Successfully inserted 500 reports with history ({cells} map cells).")


if __name__ == "__main__":
    asyncio.run(seed())
