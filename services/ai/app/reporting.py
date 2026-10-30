"""Sends results back to the report-service, which owns reports and photos.

This service never touches the report-service's database: it asks over HTTP, with a shared key.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class Rejected(Exception):
    """The report-service refused the result for good (the photo is gone, the key is wrong).
    Retrying cannot help."""


class Unavailable(Exception):
    """The report-service could not be reached or failed. Try again later."""


class ReportServiceClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=settings.REPORT_SERVICE_URL.rstrip("/"),
            headers={"X-Internal-Key": settings.INTERNAL_API_KEY or ""},
            timeout=httpx.Timeout(20.0, connect=10.0),
        )

    async def send_analysis(self, image_id: str, body: dict) -> None:
        await self._post(f"/api/v1/internal/images/{image_id}/analysis", body)

    async def send_triage(self, report_id: str, body: dict) -> None:
        await self._post(f"/api/v1/internal/reports/{report_id}/triage", body)

    async def _post(self, path: str, body: dict) -> None:
        try:
            response = await self._client.post(path, json=body)
        except httpx.HTTPError as e:
            raise Unavailable(f"report-service unreachable: {e.__class__.__name__}") from e
        if response.status_code >= 500 or response.status_code in (408, 429):
            raise Unavailable(f"report-service answered {response.status_code}")
        if response.status_code >= 400:
            raise Rejected(f"report-service refused the result ({response.status_code})")
