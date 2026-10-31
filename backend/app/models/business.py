import enum

from sqlalchemy import CheckConstraint, Enum, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import Timestamps, UUIDPrimaryKey

DEFAULT_CANCELLATION_WINDOW_MINUTES = 120


class LocationMode(enum.StrEnum):
    single = "single"
    multiple = "multiple"


location_mode_enum = Enum(
    LocationMode,
    name="location_mode",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class Business(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "businesses"
    __table_args__ = (
        CheckConstraint(
            "cancellation_window_minutes >= 0", name="cancellation_window_non_negative"
        ),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    location_mode: Mapped[LocationMode] = mapped_column(location_mode_enum, nullable=False)
    default_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    cancellation_window_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_CANCELLATION_WINDOW_MINUTES,
        server_default=text(str(DEFAULT_CANCELLATION_WINDOW_MINUTES)),
    )
