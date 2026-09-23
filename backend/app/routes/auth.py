"""Login / logout. A login creates the session row the risk engine scores against."""
from typing import Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app.auth import create_token, get_current, verify_password
from app.database import get_db
from app.detection import risk_engine
from app.models import User, UserSession, utcnow

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    role: str
    session_id: int
    starting_risk_score: int
    risk_level: str


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: DbSession = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()

    if user is None or not verify_password(payload.password, user.password_hash):
        if user is not None:
            # count it and leave an audit trail; unknown usernames get neither
            user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
            risk_engine.record_action(
                db,
                session=None,
                user=user,
                action_type="LOGIN_FAILED",
                points=0,
                reason="failed login attempt",
            )
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Failed attempts from the last ~10 minutes become this session's opening score.
    carried_points, carried_attempts = risk_engine.carried_over_failed_login_points(
        db, user
    )
    user.failed_login_attempts = 0

    session = UserSession(user_id=user.id, login_time=utcnow())
    db.add(session)
    db.flush()

    reason = "successful login"
    if carried_points:
        reason = "successful login after %d recent failed attempt(s)" % carried_attempts

    risk_engine.record_action(
        db,
        session=session,
        user=user,
        action_type="LOGIN",
        points=carried_points,
        reason=reason,
        check_burst=False,  # a login should not itself trip the rapid-activity rule
    )

    token = create_token(user, session)
    db.commit()
    db.refresh(session)

    return LoginResponse(
        token=token,
        username=user.username,
        role=user.role,
        session_id=session.id,
        starting_risk_score=session.total_risk_score,
        risk_level=session.risk_level,
    )


@router.post("/logout")
def logout(
    current: Tuple[User, UserSession] = Depends(get_current),
    db: DbSession = Depends(get_db),
):
    _, session = current
    session.logout_time = utcnow()
    db.commit()
    return {"status": "logged_out", "session_id": session.id}


@router.get("/me")
def me(current: Tuple[User, UserSession] = Depends(get_current)):
    user, session = current
    return {
        "username": user.username,
        "role": user.role,
        "session_id": session.id,
        "total_risk_score": session.total_risk_score,
        "risk_level": session.risk_level,
    }
