import re
import secrets
import unicodedata


def slugify(text: str, *, fallback: str = "salon", max_length: int = 60) -> str:
    """'Glow & Co. Salon' -> 'glow-co-salon'. Non-ASCII letters are folded ('Café' -> 'cafe')."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:max_length].strip("-")
    return slug or fallback


def unique_slug(base: str, taken: set[str], *, max_length: int = 80) -> str:
    """Return `base`, or `base-2`, `base-3`... the first one not in `taken`."""
    if base not in taken:
        return base
    for n in range(2, 10_000):
        suffix = f"-{n}"
        candidate = f"{base[: max_length - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
    return f"{base[: max_length - 7]}-{secrets.token_hex(3)}"


def randomized_slug(base: str, *, max_length: int = 80) -> str:
    """`base-3f9a`: for retries after losing a race, where the next sequential slug would just
    collide with every other request that lost the same race."""
    suffix = f"-{secrets.token_hex(2)}"
    return f"{base[: max_length - len(suffix)]}{suffix}"
