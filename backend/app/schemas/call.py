import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.models.call import CallOutcome


class TranscriptTurn(BaseModel):
    role: Literal["agent", "user"]
    text: str


class CallOut(BaseModel):
    id: uuid.UUID
    retell_call_id: str
    location_id: uuid.UUID
    from_number: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    outcome: CallOutcome
    summary: str | None
    transcript: list[TranscriptTurn] | None
    booking_id: uuid.UUID | None


class DayCount(BaseModel):
    date: date
    count: int


class CallStats(BaseModel):
    total: int
    by_outcome: dict[CallOutcome, int]
    per_day: list[DayCount]
