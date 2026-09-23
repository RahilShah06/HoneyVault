"""Rule-based behavioural risk engine.

The point of this module is that no single click convicts anyone: points
accumulate on the *session*, and the level is recomputed from the running
total after every scored action.

    Event                                              Points
    ---------------------------------------------------------
    Open 1st distinct honeyfile in session              +10
    Open 2nd distinct honeyfile in session              +15
    Open 3rd+ distinct honeyfile in session             +20 each
    Download a honeyfile                                +20

Honeyfile points are then role-weighted: halved when the file sits in the
user's own folder, and multiplied by 1.5 when it does not.
    Sensitive-keyword search                            +15
    Open a non-honeyfile outside the role's folders     +20
    Using a planted honeytoken anywhere in a request    +40
    5+ actions in any 60s window (once per session)     +15
    Carried-over failed logins on login                 +10 each, max +30

The moment a session's running total first crosses into CRITICAL the engine
latches `sessions.decoy_mode` and logs ACTIVE_DECEPTION_TRIGGERED. From then on
the file routes serve that session fake content for everything it asks for.
"""
import datetime as dt
from typing import Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.detection import anomaly
from app.models import ActivityLog, File, User, UserSession, utcnow

MAX_SCORE = 100

SENSITIVE_KEYWORDS = [
    "password",
    "credential",
    "salary",
    "database",
    "api",
    "key",
    "bank",
    "confidential",
    "secret",
]

# honeyfile opens: 1st, 2nd, then everything after
HONEYFILE_OPEN_POINTS = [10, 15]
HONEYFILE_OPEN_POINTS_AFTER = 20
HONEYFILE_DOWNLOAD_POINTS = 20
SENSITIVE_SEARCH_POINTS = 15
RESTRICTED_ATTEMPT_POINTS = 20

# Role weighting. The same click means different things depending on who made
# it: an HR user opening an HR decoy is doing something close to their job,
# a Designer opening the same file is reaching well outside it. The weight is
# the distance between the user's role and the folder's normal audience.
ROLE_WEIGHT_IN_ROLE = 0.5
ROLE_WEIGHT_OUT_OF_ROLE = 1.5

BURST_POINTS = 15
BURST_WINDOW_SECONDS = 60
BURST_ACTION_THRESHOLD = 5

# Using a credential lifted out of a decoy file. Not a behavioural hint - it
# is close to proof - so one occurrence alone clears CRITICAL on its own.
HONEYTOKEN_POINTS = 40

FAILED_LOGIN_POINTS = 10
FAILED_LOGIN_MAX = 30
FAILED_LOGIN_LOOKBACK_MINUTES = 10

RISK_LEVELS = [
    (25, "LOW"),
    (50, "MEDIUM"),
    (75, "HIGH"),
    (MAX_SCORE, "CRITICAL"),
]

# above this, the session is CRITICAL and active deception kicks in
CRITICAL_THRESHOLD = 75


def risk_level_for(score: int) -> str:
    """0-25 LOW, 26-50 MEDIUM, 51-75 HIGH, 76-100 CRITICAL."""
    for ceiling, level in RISK_LEVELS:
        if score <= ceiling:
            return level
    return "CRITICAL"


def matched_sensitive_keywords(query: str) -> list:
    q = (query or "").lower()
    return [kw for kw in SENSITIVE_KEYWORDS if kw in q]


def carried_over_failed_login_points(db: DbSession, user: User) -> Tuple[int, int]:
    """Failed logins for this user in the last ~10 minutes, as start-of-session points.

    Returns (points, attempts_counted).
    """
    cutoff = utcnow() - dt.timedelta(minutes=FAILED_LOGIN_LOOKBACK_MINUTES)
    recent = (
        db.query(func.count(ActivityLog.id))
        .filter(
            ActivityLog.user_id == user.id,
            ActivityLog.action_type == "LOGIN_FAILED",
            ActivityLog.timestamp >= cutoff,
        )
        .scalar()
        or 0
    )
    # the counter on the user row is the source of truth; the log is the audit trail
    attempts = min(int(user.failed_login_attempts or 0), int(recent))
    if attempts <= 0:
        return 0, 0
    return min(attempts * FAILED_LOGIN_POINTS, FAILED_LOGIN_MAX), attempts


def distinct_honeyfiles_opened(db: DbSession, session: UserSession) -> int:
    return (
        db.query(func.count(func.distinct(ActivityLog.target_file_id)))
        .join(File, File.id == ActivityLog.target_file_id)
        .filter(
            ActivityLog.session_id == session.id,
            ActivityLog.action_type == "OPEN",
            File.is_honeyfile.is_(True),
        )
        .scalar()
        or 0
    )


def _honeyfile_open_points(nth: int) -> int:
    """nth is 1-based: the 1st distinct honeyfile of the session is nth=1."""
    if nth <= len(HONEYFILE_OPEN_POINTS):
        return HONEYFILE_OPEN_POINTS[nth - 1]
    return HONEYFILE_OPEN_POINTS_AFTER


def _already_opened_in_session(db: DbSession, session: UserSession, file_id: int) -> bool:
    return (
        db.query(ActivityLog.id)
        .filter(
            ActivityLog.session_id == session.id,
            ActivityLog.action_type == "OPEN",
            ActivityLog.target_file_id == file_id,
        )
        .first()
        is not None
    )


def role_weight(user: User, file: File):
    """Return (multiplier, explanation) for this user reaching for this file.

    Folder membership is the measure, not the decoy's target_role: what makes
    an access interesting is whether the person had business being there.
    """
    folder = file.folder
    if folder is not None and not folder.is_normal_for(user.role):
        return (
            ROLE_WEIGHT_OUT_OF_ROLE,
            "x%.2g, %s is outside the %s role" % (
                ROLE_WEIGHT_OUT_OF_ROLE, folder.name, user.role
            ),
        )
    return (
        ROLE_WEIGHT_IN_ROLE,
        "x%.2g, %s is normal for the %s role" % (
            ROLE_WEIGHT_IN_ROLE,
            folder.name if folder else "this folder",
            user.role,
        ),
    )


def _weighted(points: int, user: User, file: File):
    """Apply the role weight and return (points, note) for the reason string."""
    weight, why = role_weight(user, file)
    return int(round(points * weight)), why


def score_open(db: DbSession, session: UserSession, user: User, file: File):
    """Return (action_type, points, reason) for an OPEN."""
    if file.is_honeyfile:
        if _already_opened_in_session(db, session, file.id):
            # re-opening the same decoy is not new evidence
            return "OPEN", 0, "honeyfile re-opened (already counted this session)"
        nth = distinct_honeyfiles_opened(db, session) + 1
        base = _honeyfile_open_points(nth)
        pts, why = _weighted(base, user, file)
        ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(nth, str(nth) + "th")
        return (
            "OPEN",
            pts,
            "opened %s distinct honeyfile this session (%d base, %s)"
            % (ordinal, base, why),
        )

    folder = file.folder
    if folder is not None and not folder.is_normal_for(user.role):
        return (
            "RESTRICTED_ATTEMPT",
            RESTRICTED_ATTEMPT_POINTS,
            "opened a file in " + folder.name + ", outside the " + user.role + " role",
        )
    return "OPEN", 0, None


def score_download(db: DbSession, session: UserSession, user: User, file: File):
    """Return (action_type, points, reason) for a DOWNLOAD."""
    if file.is_honeyfile:
        pts, why = _weighted(HONEYFILE_DOWNLOAD_POINTS, user, file)
        return (
            "DOWNLOAD",
            pts,
            "downloaded a honeyfile (%d base, %s)"
            % (HONEYFILE_DOWNLOAD_POINTS, why),
        )
    return "DOWNLOAD", 0, None


def score_search(query: str):
    """Return (action_type, points, reason) for a SEARCH."""
    hits = matched_sensitive_keywords(query)
    if hits:
        return (
            "SEARCH",
            SENSITIVE_SEARCH_POINTS,
            "sensitive-keyword search: " + ", ".join(hits),
        )
    return "SEARCH", 0, None


def _burst_bonus(db: DbSession, session: UserSession, now: dt.datetime) -> int:
    """+15 once per session when 5+ actions land inside any 60-second window.

    Called after the triggering row is written, so the current action counts.
    """
    if session.burst_awarded:
        return 0
    window_start = now - dt.timedelta(seconds=BURST_WINDOW_SECONDS)
    count = (
        db.query(func.count(ActivityLog.id))
        .filter(
            ActivityLog.session_id == session.id,
            ActivityLog.timestamp >= window_start,
            ActivityLog.timestamp <= now,
        )
        .scalar()
        or 0
    )
    if count >= BURST_ACTION_THRESHOLD:
        session.burst_awarded = True
        return BURST_POINTS
    return 0


def apply_score(db: DbSession, session: UserSession, points: int) -> None:
    """Add points to the session total (capped at 100) and recompute the level."""
    total = int(session.total_risk_score or 0) + max(0, int(points))
    session.total_risk_score = min(total, MAX_SCORE)
    session.risk_level = risk_level_for(session.total_risk_score)


def _maybe_trigger_decoy_mode(db: DbSession, session: UserSession):
    """Latch active deception the first time this session turns CRITICAL.

    Written as its own activity_logs row rather than folded into the
    triggering action, because it is the system responding rather than the
    user acting - the admin timeline should show it as a separate beat.
    """
    if session.decoy_mode or session.risk_level != "CRITICAL":
        return None

    session.decoy_mode = True
    log = ActivityLog(
        session_id=session.id,
        user_id=session.user_id,
        action_type="ACTIVE_DECEPTION_TRIGGERED",
        points_awarded=0,
        reason=(
            "session crossed into CRITICAL (score "
            + str(session.total_risk_score)
            + " > "
            + str(CRITICAL_THRESHOLD)
            + ") - every file this session opens is now served decoy content"
        ),
        timestamp=utcnow(),
    )
    db.add(log)
    db.flush()
    return log


def record_action(
    db: DbSession,
    session: Optional[UserSession],
    user: User,
    action_type: str,
    points: int = 0,
    reason: Optional[str] = None,
    file: Optional[File] = None,
    search_query: Optional[str] = None,
    honeytoken=None,
    check_burst: bool = True,
) -> ActivityLog:
    """Write one activity log, fold in the burst bonus, update the session score.

    The burst bonus is added to the triggering action's points_awarded (rather
    than a synthetic log row) and called out in `reason`, so an admin reading
    the timeline still sees the numbers add up to the session total.
    """
    now = utcnow()
    log = ActivityLog(
        session_id=session.id if session else None,
        user_id=user.id if user else None,
        action_type=action_type,
        target_file_id=file.id if file else None,
        search_query=search_query,
        honeytoken_id=honeytoken.id if honeytoken else None,
        points_awarded=max(0, int(points)),
        reason=reason,
        timestamp=now,
    )
    db.add(log)
    db.flush()  # the burst check has to see this row

    if session is not None:
        if check_burst:
            bonus = _burst_bonus(db, session, now)
            if bonus:
                log.points_awarded += bonus
                burst_note = (
                    str(BURST_ACTION_THRESHOLD)
                    + "+ actions in "
                    + str(BURST_WINDOW_SECONDS)
                    + "s (rapid activity)"
                )
                log.reason = log.reason + "; " + burst_note if log.reason else burst_note
        apply_score(db, session, log.points_awarded)
        _maybe_trigger_decoy_mode(db, session)
        # Runs beside the rules and cannot influence them: it reads the
        # session's shape and writes only its own columns.
        anomaly.update_session(db, session)

    db.flush()
    return log
