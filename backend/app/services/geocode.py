"""Best-effort reverse geocoding on the server, for reports that arrive without a typed address (WhatsApp).

Uses OpenStreetMap's public Nominatim, which is meant for light use (one request a second, a real
User-Agent). Any failure returns blanks, so a slow or blocked geocoder never stops a report being filed.
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

URL = "https://nominatim.openstreetmap.org/reverse"


async def reverse_geocode(latitude: float, longitude: float) -> dict[str, str]:
    blank = {"address": "", "city": "", "district": "", "state": "", "pincode": ""}
    try:
        async with httpx.AsyncClient(timeout=3.0, headers={"User-Agent": f"IndiaReports/1.0 ({settings.PUBLIC_APP_URL or 'civic reporting'})"}) as client:
            response = await client.get(
                URL, params={"format": "jsonv2", "addressdetails": 1, "accept-language": "en", "zoom": 18, "lat": latitude, "lon": longitude}
            )
        if response.status_code != 200:
            return blank
        a = response.json().get("address") or {}
    except (httpx.HTTPError, ValueError):
        logger.info("reverse geocoding failed; filing without an address")
        return blank
    return {
        "address": ", ".join(p for p in (a.get("road"), a.get("neighbourhood") or a.get("suburb")) if p)[:500],
        "city": str(a.get("city") or a.get("town") or a.get("village") or a.get("county") or "")[:100],
        "district": str(a.get("state_district") or a.get("county") or "")[:100],
        "state": str(a.get("state") or "")[:100],
        "pincode": str(a.get("postcode") or "").replace(" ", "")[:10],
    }
