"""Admin dashboard: summary tiles, live event feed, per-session drill-down."""
import datetime as dt
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, func
from sqlalchemy.orm import Session as DbSession

from app.auth import TOKEN_TTL_HOURS, get_current_admin
from app.database import get_db
from app.detection import anomaly, features, risk_engine
from app.models import ActivityLog, File, Honeytoken, User, UserSession, utcnow
from app.routes.activity import ActivityOut, serialize_log

router = APIRouter(prefix="/admin", tags=["dashboard"])

SUSPICIOUS_THRESHOLD = 25
HIGH_RISK_THRESHOLD = 50


def _stale_cutoff() -> dt.datetime:
    return utcnow() - dt.timedelta(hours=TOKEN_TTL_HOURS)


def active_session_clause():
    """A session counts as active only while its token could still work.

    Users rarely log out explicitly, so without this every login would stay
    "active" forever and inflate the dashboard tile.
    """
    return and_(
        UserSession.logout_time.is_(None),
        UserSession.login_time >= _stale_cutoff(),
    )


def is_session_active(s: UserSession) -> bool:
    return s.logout_time is None and s.login_time >= _stale_cutoff()


class SummaryOut(BaseModel):
    active_sessions: int
    suspicious_sessions: int
    total_honeyfile_interactions: int
    high_risk_users: int
    total_sessions: int
    honeytokens_planted: int
    honeytokens_used: int


class SessionOut(BaseModel):
    id: int
    user_id: int
    username: str
    role: str
    login_time: str
    logout_time: Optional[str]
    is_active: bool
    total_risk_score: int
    risk_level: str
    action_count: int
    honeyfile_interactions: int
    decoy_mode: bool
    anomaly_score: Optional[float]
    anomaly_flag: bool


class SessionDetailOut(BaseModel):
    session: SessionOut
    timeline: List[ActivityOut]
    # Why the model found this session unusual, in plain language. Empty when
    # the session is unscored or nothing deviated far enough to name.
    anomaly_reasons: List[str]


def _iso(value) -> Optional[str]:
    return value.isoformat() + "Z" if value else None


def _session_out(db: DbSession, s: UserSession) -> SessionOut:
    action_count = (
        db.query(func.count(ActivityLog.id))
        .filter(ActivityLog.session_id == s.id)
        .scalar()
        or 0
    )
    honey = (
        db.query(func.count(ActivityLog.id))
        .join(File, File.id == ActivityLog.target_file_id)
        .filter(
            ActivityLog.session_id == s.id,
            File.is_honeyfile.is_(True),
            ActivityLog.action_type.in_(["OPEN", "DOWNLOAD"]),
        )
        .scalar()
        or 0
    )
    return SessionOut(
        id=s.id,
        user_id=s.user_id,
        username=s.user.username if s.user else "?",
        role=s.user.role if s.user else "?",
        login_time=_iso(s.login_time) or "",
        logout_time=_iso(s.logout_time),
        is_active=is_session_active(s),
        total_risk_score=s.total_risk_score,
        risk_level=s.risk_level,
        action_count=int(action_count),
        honeyfile_interactions=int(honey),
        decoy_mode=bool(s.decoy_mode),
        anomaly_score=s.anomaly_score,
        anomaly_flag=bool(s.anomaly_flag),
    )


@router.get("/summary", response_model=SummaryOut)
def summary(
    current: Tuple[User, UserSession] = Depends(get_current_admin),
    db: DbSession = Depends(get_db),
):
    active = (
        db.query(func.count(UserSession.id))
        .filter(active_session_clause())
        .scalar()
        or 0
    )
    suspicious = (
        db.query(func.count(UserSession.id))
        .filter(
            UserSession.total_risk_score > SUSPICIOUS_THRESHOLD,
            UserSession.is_synthetic.is_(False),
        )
        .scalar()
        or 0
    )
    honey_interactions = (
        db.query(func.count(ActivityLog.id))
        .join(File, File.id == ActivityLog.target_file_id)
        .filter(
            File.is_honeyfile.is_(True),
            ActivityLog.action_type.in_(["OPEN", "DOWNLOAD"]),
        )
        .scalar()
        or 0
    )
    high_risk_users = (
        db.query(func.count(func.distinct(UserSession.user_id)))
        .filter(UserSession.total_risk_score > HIGH_RISK_THRESHOLD)
        .scalar()
        or 0
    )
    total_sessions = (
        db.query(func.count(UserSession.id))
        .filter(UserSession.is_synthetic.is_(False))
        .scalar()
        or 0
    )
    planted = db.query(func.count(Honeytoken.id)).scalar() or 0
    used = (
        db.query(func.count(Honeytoken.id))
        .filter(Honeytoken.first_used_at.isnot(None))
        .scalar()
        or 0
    )

    return SummaryOut(
        active_sessions=int(active),
        suspicious_sessions=int(suspicious),
        total_honeyfile_interactions=int(honey_interactions),
        high_risk_users=int(high_risk_users),
        total_sessions=int(total_sessions),
        honeytokens_planted=int(planted),
        honeytokens_used=int(used),
    )


@router.get("/events", response_model=List[ActivityOut])
def recent_events(
    limit: int = Query(50, ge=1, le=200),
    current: Tuple[User, UserSession] = Depends(get_current_admin),
    db: DbSession = Depends(get_db),
):
    """Newest-first feed for the dashboard; the frontend just polls this."""
    logs = (
        db.query(ActivityLog)
        .order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc())
        .limit(limit)
        .all()
    )
    return [serialize_log(log) for log in logs]


@router.get("/sessions", response_model=List[SessionOut])
def list_sessions(
    active_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    current: Tuple[User, UserSession] = Depends(get_current_admin),
    db: DbSession = Depends(get_db),
):
    q = db.query(UserSession).filter(UserSession.is_synthetic.is_(False))
    if active_only:
        q = q.filter(active_session_clause())
    sessions = q.order_by(UserSession.login_time.desc()).limit(limit).all()
    return [_session_out(db, s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
def session_detail(
    session_id: int,
    current: Tuple[User, UserSession] = Depends(get_current_admin),
    db: DbSession = Depends(get_db),
):
    s = db.query(UserSession).filter(UserSession.id == session_id).first()
    if s is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    timeline = (
        db.query(ActivityLog)
        .filter(ActivityLog.session_id == s.id)
        .order_by(ActivityLog.timestamp.asc(), ActivityLog.id.asc())
        .all()
    )
    scored = anomaly.score_session(db, s)
    return SessionDetailOut(
        session=_session_out(db, s),
        timeline=[serialize_log(log) for log in timeline],
        anomaly_reasons=(scored[2] if scored else []),
    )


@router.post("/sessions/{session_id}/end", response_model=SessionOut)
def end_session(
    session_id: int,
    current: Tuple[User, UserSession] = Depends(get_current_admin),
    db: DbSession = Depends(get_db),
):
    """Force-end someone else's session; their token stops working immediately.

    No activity_logs row is written: this is an admin action, not user
    behaviour, and it would otherwise pollute the scored timeline.
    """
    _, own_session = current
    s = db.query(UserSession).filter(UserSession.id == session_id).first()
    if s is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    if s.id == own_session.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use Log out to end your own session",
        )
    if s.logout_time is None:  # already-ended sessions are left as they are
        s.logout_time = utcnow()
        db.commit()
        db.refresh(s)
    return _session_out(db, s)


@router.get("/scoring-rules")
def scoring_rules(
    current: Tuple[User, UserSession] = Depends(get_current_admin),
):
    """What the engine is actually configured with - handy during a demo."""
    return {
        "levels": {
            "LOW": "0-25",
            "MEDIUM": "26-50",
            "HIGH": "51-75",
            "CRITICAL": "76-100",
        },
        "max_score": risk_engine.MAX_SCORE,
        "honeyfile_open": {
            "1st": risk_engine.HONEYFILE_OPEN_POINTS[0],
            "2nd": risk_engine.HONEYFILE_OPEN_POINTS[1],
            "3rd+": risk_engine.HONEYFILE_OPEN_POINTS_AFTER,
        },
        "honeyfile_download": risk_engine.HONEYFILE_DOWNLOAD_POINTS,
        "sensitive_search": risk_engine.SENSITIVE_SEARCH_POINTS,
        "restricted_attempt": risk_engine.RESTRICTED_ATTEMPT_POINTS,
        "rapid_activity": {
            "points": risk_engine.BURST_POINTS,
            "threshold": risk_engine.BURST_ACTION_THRESHOLD,
            "window_seconds": risk_engine.BURST_WINDOW_SECONDS,
            "once_per_session": True,
        },
        "failed_login_carryover": {
            "points_each": risk_engine.FAILED_LOGIN_POINTS,
            "max": risk_engine.FAILED_LOGIN_MAX,
            "lookback_minutes": risk_engine.FAILED_LOGIN_LOOKBACK_MINUTES,
        },
        "honeytoken_used": risk_engine.HONEYTOKEN_POINTS,
        "role_weighting": {
            "in_role": risk_engine.ROLE_WEIGHT_IN_ROLE,
            "out_of_role": risk_engine.ROLE_WEIGHT_OUT_OF_ROLE,
            "applies_to": "honeyfile open and download points",
        },
        "anomaly_detection": {
            "status": anomaly.status(),
            "features": features.FEATURE_NAMES,
            "independent_of_rules": True,
            "flag_threshold": anomaly.FLAG_THRESHOLD,
        },
        "sensitive_keywords": risk_engine.SENSITIVE_KEYWORDS,
        "active_response": {
            "trigger": "session score first exceeds %d (CRITICAL)"
            % risk_engine.CRITICAL_THRESHOLD,
            "effect": "every file this session opens or downloads is served "
            "decoy content; stored files are not modified",
            "event": "ACTIVE_DECEPTION_TRIGGERED",
        },
    }
