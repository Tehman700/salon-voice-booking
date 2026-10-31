"""Opaque keyset cursors: base64url("<created_at ISO>|<id>")."""

import base64
import binascii
import uuid
from datetime import datetime

from app.core.errors import ValidationFailedError

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{row_id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created_at, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(created_at), uuid.UUID(row_id)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValidationFailedError(
            "The cursor is not valid.", details={"cursor": ["Invalid cursor"]}
        ) from exc
