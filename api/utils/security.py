from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
import jwt


DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"invalid-password", bcrypt.gensalt()).decode()


def verify_password(password: str, hashed_password: str) -> bool:
    encoded_password = password.encode("utf-8")
    if len(encoded_password) > 72:
        return False
    try:
        return bcrypt.checkpw(encoded_password, hashed_password.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(admin_id: UUID, secret: str, expire_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(admin_id),
            "iat": now,
            "exp": now + timedelta(minutes=expire_minutes),
        },
        secret,
        algorithm="HS256",
    )


def get_token_admin_id(token: str, secret: str) -> UUID:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "iat", "exp"]},
        )
        return UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError) as error:
        raise PermissionError("Invalid or expired access token") from error
