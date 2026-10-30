"""What the AI is asked to return, and how it is cleaned before anyone sees it."""

from typing import Literal

from pydantic import BaseModel

from app.categories import CATEGORIES

Severity = Literal["low", "medium", "high", "critical"]
SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")
Flag = Literal[
    "inappropriate",
    "people_visible",
    "license_plate_visible",
    "screenshot_or_stock_photo",
    "likely_unrelated",
]
CategoryName = Literal[CATEGORIES]  # type: ignore[valid-type]


class RawFindings(BaseModel):
    """The shape requested from the model. Kept free of length constraints (not every
    constraint is supported in structured output); `clean` enforces them afterwards."""

    summary: str
    issue_visible: bool
    suggested_category: CategoryName
    category_matches_report: bool
    severity: Severity
    hazards: list[str]
    recommended_action: str
    image_quality: Literal["good", "poor", "unusable"]
    flags: list[Flag]
    confidence: float


class Findings(BaseModel):
    summary: str
    issue_visible: bool
    suggested_category: str
    category_matches_report: bool
    severity: Severity
    hazards: list[str]
    recommended_action: str
    image_quality: str
    flags: list[str]
    confidence: float


def _text(value: str, limit: int) -> str:
    value = " ".join(str(value).split())  # collapse whitespace and newlines
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


def clean(raw: RawFindings) -> Findings:
    """Bound everything the model said. Its output is data shown to staff, so it is
    length-limited and de-duplicated no matter what it contained."""
    return Findings(
        summary=_text(raw.summary, 400),
        issue_visible=raw.issue_visible,
        suggested_category=raw.suggested_category,
        category_matches_report=raw.category_matches_report,
        severity=raw.severity,
        hazards=[_text(h, 120) for h in dict.fromkeys(raw.hazards)][:6],
        recommended_action=_text(raw.recommended_action, 300),
        image_quality=raw.image_quality,
        flags=list(dict.fromkeys(raw.flags)),
        confidence=min(1.0, max(0.0, float(raw.confidence))),
    )


def needs_admin_attention(f: Findings) -> bool:
    """Findings that justify messaging the administrator right away."""
    return f.severity in ("high", "critical") or "inappropriate" in f.flags
