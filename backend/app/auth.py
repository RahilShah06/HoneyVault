"""Password hashing, JWT issuing, and the session-backed auth dependency."""
import datetime as dt
import os
from typing import Optional, Tuple

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session as DbSession

from app.database import get_db
from app.models import User, UserSession, utcnow

# Demo prototype: a fixed fallback secret keeps `uvicorn --reload` sessions valid.
SECRET_KEY = os.environ.get("HONEYVAULT_SECRET", "honeyvault-dev-secret-change-me")
ALGORITHM = "HS256"
TOKEN_TTL_HOURS = 12

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def create_token(user: User, session: UserSession) -> str:
    payload = {
        "sub": str(user.id),
        "sid": session.id,
        "username": user.username,
        "role": user.role,
        "exp": utcnow() + dt.timedelta(hours=TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def get_current(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: DbSession = Depends(get_db),
) -> Tuple[User, UserSession]:
    """Resolve the bearer token to (user, active session).

    A logged-out session is rejected even if the token has not expired yet.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    payload = _decode(credentials.credentials)
    user = db.query(User).filter(User.id == int(payload.get("sub", 0))).first()
    session = (
        db.query(UserSession).filter(UserSession.id == payload.get("sid")).first()
    )
    if user is None or session is None or session.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown session"
        )
    if session.logout_time is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session already ended"
        )
    return user, session


def get_current_admin(
    current: Tuple[User, UserSession] = Depends(get_current),
) -> Tuple[User, UserSession]:
    user, _ = current
    if user.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required"
        )
    return current
