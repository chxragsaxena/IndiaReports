from fastapi import APIRouter

from app.api.v1.endpoints import admin, auth, internal, reports, scorecards

api_router = APIRouter()

api_router.include_router(
    reports.router,
    prefix="/reports",
    tags=["Reports"],
)

api_router.include_router(
    admin.router,
    prefix="/admin",
    tags=["Admin"],
)

api_router.include_router(scorecards.router, prefix="/scorecards", tags=["Scorecards"])

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(auth.me_router, prefix="/me", tags=["Me"])

# Service-to-service calls (the ai-service reports its findings here). Not for browsers.
api_router.include_router(internal.router, prefix="/internal", tags=["Internal"])
