import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_CHAT_ID = re.compile(r"^(-?\d{1,20}|@[A-Za-z0-9_]{5,32})$")


class AreaCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    # GeoJSON geometry, Polygon or MultiPolygon, WGS84 [lng, lat].
    geometry: dict


class AreaResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime | None = None


class OfficerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    role: Literal["officer", "admin"] = "officer"
    telegram_chat_id: str
    area_id: UUID | None = None

    @field_validator("telegram_chat_id")
    @classmethod
    def valid_chat_id(cls, v: str) -> str:
        v = v.strip()
        if not _CHAT_ID.match(v):
            raise ValueError("must be a numeric Telegram chat id or @channelname")
        return v


class OfficerResponse(BaseModel):
    id: UUID
    name: str
    role: str
    telegram_chat_id: str
    area_id: UUID | None = None
    active: bool


class AcknowledgeRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)
