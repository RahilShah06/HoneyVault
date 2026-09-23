"""Inbound request scanning for planted honeytokens.

This runs on every request, before routing, because the point of a honeytoken
is that it can turn up anywhere: pasted into an `Authorization` header by
someone trying the credential they found, appended to a query string, or
buried in a JSON body. A route-level dependency would only see the endpoints
we thought to decorate.

Whoever presents a honeytoken is *not* authenticated by it. The token is
recorded and scored, and the request then continues on its own merits - which,
for a fake credential, means failing auth like any other bad token.
"""
import jwt

from app.auth import ALGORITHM, SECRET_KEY
from app.database import SessionLocal
from app.detection import honeytoken, risk_engine
from app.models import User, UserSession


def _session_from_authorization(db, header_value):
    """Best-effort (user, session) from a bearer token. Never raises.

    A honeytoken use often arrives with no valid session at all - that is the
    case where someone is trying the stolen credential itself - so this has to
    degrade to (None, None) rather than reject the request.
    """
    if not header_value or not header_value.lower().startswith("bearer "):
        return None, None
    token = header_value.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None, None

    user = db.query(User).filter(User.id == int(payload.get("sub", 0))).first()
    session = db.query(UserSession).filter(
        UserSession.id == payload.get("sid")
    ).first()
    if user is None or session is None or session.user_id != user.id:
        return None, None
    if session.logout_time is not None:
        return user, None
    return user, session


def _scannable(request, body: bytes) -> str:
    """Everything about this request a token could be hiding in."""
    parts = [request.url.query or ""]
    parts.extend(str(v) for v in request.headers.values())
    if body:
        parts.append(
            body[: honeytoken.MAX_SCAN_BYTES].decode("utf-8", errors="ignore")
        )
    return "\n".join(parts)


async def honeytoken_watch(request, call_next):
    """Scan, score, then let the request proceed untouched."""
    body = b""
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            body = await request.body()
        except Exception:  # noqa: BLE001 - scanning must never break a request
            body = b""

    try:
        _record_if_present(request, body)
    except Exception as exc:  # noqa: BLE001
        print("honeytoken: scan failed, request continues - %s" % exc)

    return await call_next(request)


def _record_if_present(request, body: bytes) -> None:
    haystack = _scannable(request, body)
    # Cheap prefix check first: almost every request stops here without ever
    # opening a database session.
    if honeytoken.TOKEN_PREFIX not in haystack:
        return

    db = SessionLocal()
    try:
        row = honeytoken.find_in(db, haystack)
        if row is None:
            return

        honeytoken.mark_used(db, row)
        user, session = _session_from_authorization(
            db, request.headers.get("authorization")
        )

        where = "request body"
        if honeytoken.TOKEN_PREFIX in (request.url.query or ""):
            where = "query string"
        elif any(
            honeytoken.TOKEN_PREFIX in str(v) for v in request.headers.values()
        ):
            where = "request header"

        planted_in = row.file.filename if row.file else "a decoy file"
        reason = "used honeytoken %s planted in %s (%s %s, %s)" % (
            (row.label or "credential"),
            planted_in,
            request.method,
            request.url.path,
            where,
        )

        risk_engine.record_action(
            db,
            session=session,
            user=user,
            action_type="HONEYTOKEN_USED",
            points=risk_engine.HONEYTOKEN_POINTS,
            reason=reason,
            file=row.file,
            honeytoken=row,
            check_burst=False,
        )
        db.commit()
        print("honeytoken: %s" % reason)
    finally:
        db.close()
