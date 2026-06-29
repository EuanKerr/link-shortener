import secrets
import string

ALPHABET = string.ascii_letters + string.digits  # base62: a-z A-Z 0-9


def generate(length: int = 5) -> str:
    """Return a cryptographically random base62 code of the given length."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))
