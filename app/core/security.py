"""
Password hashing and JWT handling.

Password hashing uses the `bcrypt` library directly rather than Passlib. Passlib 1.7.4's
bcrypt backend probes `bcrypt.__about__` (removed in bcrypt 5.x) and self-tests with a
>72-byte password (hard-rejected by bcrypt 5.x), which broke `hash_password()` for every
input. Calling bcrypt directly removes the compatibility layer entirely.

The stored format is unchanged: Passlib's bcrypt scheme and `bcrypt.hashpw` both emit
`$2b$12$...`, and `bcrypt.checkpw` verifies hashes produced by either. Existing users keep
their passwords -- no migration is required.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import structlog
from jose import JWTError, jwt

from app.core.config import settings

logger = structlog.get_logger()

# bcrypt hashes at most the first 72 bytes of a password and raises on longer input rather
# than silently truncating. Callers must reject longer passwords before hashing.
BCRYPT_MAX_PASSWORD_BYTES = 72

# Work factor. 12 matches what Passlib's default produced, so existing and new hashes are
# indistinguishable in cost.
BCRYPT_ROUNDS = 12


class PasswordTooLongError(ValueError):
    """Raised when a password exceeds what bcrypt can hash without truncation."""

    def __init__(self, byte_length: int):
        super().__init__(
            f"password is {byte_length} bytes; bcrypt hashes at most "
            f"{BCRYPT_MAX_PASSWORD_BYTES} bytes"
        )
        self.byte_length = byte_length


def hash_password(password: str) -> str:
    """
    Hash a password with bcrypt.

    Raises PasswordTooLongError for input over 72 bytes rather than truncating it, because
    silent truncation would mean two different passwords hash to the same value.
    """
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise PasswordTooLongError(len(encoded))
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """
    Check a password against a stored hash.

    Total by design: an over-long password, a malformed hash or a hash produced by an
    unknown scheme is a failed login, never an exception that would surface as a 500.
    """
    if not plain or not hashed:
        return False

    encoded = plain.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        return False

    try:
        return bcrypt.checkpw(encoded, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed or non-bcrypt stored hash. Log without echoing the hash itself.
        logger.warning("password_hash_unverifiable", hash_prefix=str(hashed)[:4])
        return False


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(seconds=settings.JWT_EXPIRES_IN)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except JWTError:
        return None
