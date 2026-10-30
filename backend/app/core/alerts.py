"""Small rules about AI findings, kept here because the report-service decides who gets told."""

from app.core.config import settings

SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")


def analysis_enabled() -> bool:
    """Whether an ai-service is wired up (used by the admin view to explain an empty panel)."""
    return bool(settings.INTERNAL_API_KEY)


def needs_admin_attention(severity: str, flags: list[str]) -> bool:
    """Findings that justify messaging the administrator right away."""
    return severity in ("high", "critical") or "inappropriate" in flags
