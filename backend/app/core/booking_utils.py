"""Small helpers for bookings: phone numbers and speakable reference codes."""

import re
import secrets

# Dialling codes for locations whose customers type local numbers like 0300 1234567.
_COUNTRY_CODES = {
    "PK": "92",
    "AE": "971",
    "IN": "91",
    "GB": "44",
    "US": "1",
    "CA": "1",
    "SA": "966",
}

# How many digits follow the country code, for countries we know. A number that doesn't fit is
# almost always a digit dropped or added while reading it out, so it is refused, not stored.
_NATIONAL_LENGTHS = {
    "92": (10,),  # Pakistan: 3XX XXXXXXX mobiles, 2X XXXXXXXX landlines
    "971": (8, 9),
    "91": (10,),
    "44": (10,),
    "1": (10,),
    "966": (8, 9),
}

# No 0/O, 1/I/L: they sound or look alike when read out over the phone.
_REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
REFERENCE_LENGTH = 5


class InvalidPhoneError(ValueError):
    pass


def normalize_phone(raw: str, country: str | None = None) -> str:
    """Turn what a person typed or a phone system reported into one canonical form: +<digits>.

    '+92 300 1234567', '0092 300-1234567' and (for a Pakistani salon) '0300 1234567' all become
    '+923001234567', so the same customer is recognised however their number arrives.
    """
    cleaned = re.sub(r"[\s\-().]", "", raw)
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if cleaned.startswith("+"):
        digits = cleaned[1:]
    elif cleaned.startswith("0") and country in _COUNTRY_CODES:
        digits = _COUNTRY_CODES[country] + cleaned[1:]
    else:
        digits = cleaned  # assume the country code is already included
    if not digits.isdigit() or not 8 <= len(digits) <= 15:
        raise InvalidPhoneError("Enter a valid phone number, with the country code if possible")
    code = _COUNTRY_CODES.get(country or "")
    if code and digits.startswith(code) and len(digits) - len(code) not in _NATIONAL_LENGTHS[code]:
        raise InvalidPhoneError("That phone number has too many or too few digits")
    return "+" + digits


def new_reference() -> str:
    return "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(REFERENCE_LENGTH))
