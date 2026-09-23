"""Raw activity-log queries. Admin only - these rows expose honeyfile status."""
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app.auth import get_current_admin
from app.database import get_db
from app.models import ActivityLog, File, User, UserSession

router = APIRouter(prefix="/activity", tags=["activity"])


class ActivityOut(BaseModel):
    id: int
    session_id: Optional[int]
    user_id: Optional[int]
    username: Optional[str]
    role: Optional[str]
    action_type: str
    target_file_id: Optional[int]
    filename: Optional[str]
    folder_name: Optional[str]
    is_honeyfile: bool
    search_query: Optional[str]
    honeytoken_label: Optional[str]
    points_awarded: int
    reason: Optional[str]
    timestamp: str


def serialize_log(log: ActivityLog) -> ActivityOut:
    f: Optional[File] = log.target_file
    user: Optional[User] = log.user
    return ActivityOut(
        id=log.id,
        session_id=log.session_id,
        user_id=log.user_id,
        username=user.username if user else None,
        role=user.role if user else None,
        action_type=log.action_type,
        target_file_id=log.target_file_id,
        filename=f.filename if f else None,
        folder_name=(f.folder.name if f and f.folder else None),
        is_honeyfile=bool(f.is_honeyfile) if f else False,
        search_query=log.search_query,
        honeytoken_label=(log.honeytoken.label if log.honeytoken else None),
        points_awarded=log.points_awarded,
        reason=log.reason,
        timestamp=log.timestamp.isoformat() + "Z",
    )


@router.get("/logs", response_model=List[ActivityOut])
def list_logs(
    session_id: Optional[int] = None,
    user_id: Optional[int] = None,
    action_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    current: Tuple[User, UserSession] = Depends(get_current_admin),
    db: DbSession = Depends(get_db),
):
    """Newest-first activity log, optionally filtered."""
    q = db.query(ActivityLog)
    if session_id is not None:
        q = q.filter(ActivityLog.session_id == session_id)
    if user_id is not None:
        q = q.filter(ActivityLog.user_id == user_id)
    if action_type:
        q = q.filter(ActivityLog.action_type == action_type.upper())
    logs = q.order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc()).limit(limit).all()
    return [serialize_log(log) for log in logs]
