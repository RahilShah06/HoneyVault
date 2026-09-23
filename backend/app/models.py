"""ORM models.

Columns additive to the spec'd schema, and why each exists:
  * sessions.burst_awarded   - the rapid-activity bonus fires once per session
  * sessions.decoy_mode      - latched on when the session first hits CRITICAL
  * activity_logs.reason     - human-readable breakdown of points_awarded
  * files.decoy_generated_at - when this decoy's content was generated/cached
"""
import datetime as dt

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base

ROLES = ["HR", "Developer", "Designer", "Finance", "IT", "Admin"]

ACTION_TYPES = [
    "LOGIN",
    "LOGIN_FAILED",
    "OPEN",
    "DOWNLOAD",
    "SEARCH",
    "RESTRICTED_ATTEMPT",
    "ACTIVE_DECEPTION_TRIGGERED",
]

# target_role value meaning "this decoy is bait for anyone"
ANY_ROLE = "any"


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    sessions = relationship("UserSession", back_populates="user")


class Folder(Base):
    __tablename__ = "folders"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    # JSON list of roles for whom this folder is "normal". ["*"] == everyone.
    allowed_roles = Column(JSON, nullable=False, default=list)

    files = relationship("File", back_populates="folder")

    def is_normal_for(self, role: str) -> bool:
        roles = self.allowed_roles or []
        return "*" in roles or role in roles


class File(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    is_honeyfile = Column(Boolean, nullable=False, default=False)
    content = Column(Text, nullable=False, default="")
    # Honeyfile rows only: whose bait this is. A role name, or ANY_ROLE.
    target_role = Column(String(32), nullable=True)
    # Stamped when the decoy body was generated, so it is never regenerated.
    decoy_generated_at = Column(DateTime, nullable=True)

    folder = relationship("Folder", back_populates="files")


class UserSession(Base):
    """One login session. Table name stays `sessions` per the spec."""

    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    login_time = Column(DateTime, nullable=False, default=utcnow)
    logout_time = Column(DateTime, nullable=True)
    total_risk_score = Column(Integer, nullable=False, default=0)
    risk_level = Column(String(16), nullable=False, default="LOW")
    burst_awarded = Column(Boolean, nullable=False, default=False)
    # Latched true the first time this session crosses into CRITICAL. From then
    # on every file this session opens or downloads is served decoy content.
    decoy_mode = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="sessions")
    logs = relationship("ActivityLog", back_populates="session")

    @property
    def is_active(self) -> bool:
        return self.logout_time is None


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True)
    # nullable: a failed login happens before any session exists
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action_type = Column(String(32), nullable=False)
    target_file_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    search_query = Column(String(255), nullable=True)
    points_awarded = Column(Integer, nullable=False, default=0)
    reason = Column(String(255), nullable=True)
    timestamp = Column(DateTime, nullable=False, default=utcnow, index=True)

    session = relationship("UserSession", back_populates="logs")
    user = relationship("User")
    target_file = relationship("File")
