from pydantic import BaseModel
from app.schemas.report import ReportResponse

class DashboardResponse(BaseModel):
    total_reports: int
    open_reports: int
    in_progress_reports: int
    resolved_reports: int
    recent_reports: list[ReportResponse]

