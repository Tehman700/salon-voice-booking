from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

# Longest cancellation window we accept: 30 days.
MAX_CANCELLATION_WINDOW_MINUTES = 30 * 24 * 60


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError("Unknown timezone; use an IANA name such as 'Asia/Karachi'") from exc
    return value


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Timezone = Annotated[str, AfterValidator(_validate_timezone)]
# E.164: a plus sign, then 7 to 15 digits, not starting with 0.
Phone = Annotated[str, StringConstraints(pattern=r"^\+[1-9]\d{6,14}$")]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
CancellationWindow = Annotated[int, Field(ge=0, le=MAX_CANCELLATION_WINDOW_MINUTES)]
Password = Annotated[str, StringConstraints(min_length=10, max_length=128)]


class Page[T](BaseModel):
    """Standard list envelope: {"items": [...], "next_cursor": "..." | null}."""

    items: list[T]
    next_cursor: str | None = None
