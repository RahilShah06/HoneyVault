"""Turning one session into a feature vector, and a user into a baseline.

The features here are deliberately **independent of the rule engine**. Nothing
derived from `points_awarded`, `is_honeyfile`, or any scoring decision goes in.
If the model were fed the rules' own outputs it would agree with them by
construction and tell you nothing you did not already know - the point of
running both is that they can disagree.

What goes in instead is the shape of the session: where the person went, how
much they touched, how fast, how long, and at what hour.
"""
import math

from sqlalchemy import or_
from sqlalchemy.orm import Session as DbSession

from app.models import ActivityLog, File, Folder, UserSession

# Order matters and is part of the saved model - changing it invalidates any
# model trained before the change.
FEATURE_NAMES = [
    "action_count",
    "distinct_files",
    "distinct_folders",
    "out_of_role_ratio",
    "download_ratio",
    "search_ratio",
    "duration_minutes",
    "actions_per_minute",
    "hour_of_day",
]

# Counts and rates are unbounded and heavy-tailed: a scripted burst can run
# hundreds of actions per minute against a baseline of two or three. Left raw,
# that one feature produces z-scores in the dozens and drowns out every other
# signal, turning the model into a speed alarm. Log-compressing them first puts
# every feature on a comparable scale.
LOG_SCALED = {
    "action_count",
    "distinct_files",
    "distinct_folders",
    "duration_minutes",
    "actions_per_minute",
}

# Even after compression, one extreme feature should not be able to dominate
# the forest. Deviations are clipped to this many standard deviations.
MAX_DEVIATION = 6.0

# A session needs at least this many actions before its shape means anything.
MIN_ACTIONS = 3

# How many past sessions a user needs before we trust their personal baseline.
MIN_BASELINE_SESSIONS = 8

# Only sessions the rule engine left alone count towards someone's "normal".
# Without this a user's baseline absorbs their own past intrusions: do the bad
# thing often enough and it becomes your normal, and the model goes quiet. That
# is baseline poisoning, and it is the standard attack on anomaly detection.
# Using the rules as the label here is deliberate - they are the explainable
# signal, so they are what decides which history was clean.
BASELINE_MAX_RULE_SCORE = 25


def _safe_ratio(numerator, denominator):
    return float(numerator) / float(denominator) if denominator else 0.0


def extract(db: DbSession, session: UserSession):
    """Feature vector for one session, or None if there is too little to judge.

    Returns a plain list of floats in FEATURE_NAMES order.
    """
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.session_id == session.id)
        .order_by(ActivityLog.timestamp.asc())
        .all()
    )
    # LOGIN is bookkeeping, not behaviour.
    acted = [l for l in logs if l.action_type != "LOGIN"]
    if len(acted) < MIN_ACTIONS:
        return None

    user = session.user
    role = user.role if user else ""

    file_ids = {l.target_file_id for l in acted if l.target_file_id}
    folder_ids = set()
    out_of_role = 0
    if file_ids:
        rows = (
            db.query(File.id, File.folder_id, Folder.allowed_roles)
            .join(Folder, Folder.id == File.folder_id)
            .filter(File.id.in_(file_ids))
            .all()
        )
        normal_by_file = {}
        for fid, folder_id, allowed in rows:
            folder_ids.add(folder_id)
            allowed = allowed or []
            normal_by_file[fid] = "*" in allowed or role in allowed
        for l in acted:
            if l.target_file_id and not normal_by_file.get(l.target_file_id, True):
                out_of_role += 1

    downloads = sum(1 for l in acted if l.action_type == "DOWNLOAD")
    searches = sum(1 for l in acted if l.action_type == "SEARCH")

    start = acted[0].timestamp
    end = acted[-1].timestamp
    duration_min = max((end - start).total_seconds() / 60.0, 0.0)
    # A burst of actions in the same second is the interesting case, not a
    # division-by-zero problem: floor the divisor rather than the rate.
    cadence = len(acted) / max(duration_min, 0.25)

    raw = {
        "action_count": float(len(acted)),
        "distinct_files": float(len(file_ids)),
        "distinct_folders": float(len(folder_ids)),
        "out_of_role_ratio": _safe_ratio(out_of_role, len(acted)),
        "download_ratio": _safe_ratio(downloads, len(acted)),
        "search_ratio": _safe_ratio(searches, len(acted)),
        "duration_minutes": float(duration_min),
        "actions_per_minute": float(cadence),
        "hour_of_day": float(start.hour),
    }
    return [
        math.log1p(raw[name]) if name in LOG_SCALED else raw[name]
        for name in FEATURE_NAMES
    ]


def baseline_for(db: DbSession, user_id: int, exclude_session_id=None):
    """Per-user mean and standard deviation for each feature.

    Built from that user's own *clean* past sessions, which is what makes the
    model per-user: the same absolute behaviour is ordinary for one person and
    unusual for another, and a global mean would flatten that away. Sessions
    the rules already scored above LOW are excluded, so a user cannot drag
    their own baseline towards their intrusions.

    Returns (means, stds, n_sessions), or None when there is not enough history.
    """
    q = db.query(UserSession).filter(
        UserSession.user_id == user_id,
        or_(
            UserSession.is_synthetic.is_(True),
            UserSession.total_risk_score <= BASELINE_MAX_RULE_SCORE,
        ),
    )
    if exclude_session_id is not None:
        q = q.filter(UserSession.id != exclude_session_id)
    sessions = q.all()

    vectors = []
    for s in sessions:
        v = extract(db, s)
        if v is not None:
            vectors.append(v)

    if len(vectors) < MIN_BASELINE_SESSIONS:
        return None

    n = len(vectors)
    width = len(FEATURE_NAMES)
    means = [sum(v[i] for v in vectors) / n for i in range(width)]
    stds = []
    for i in range(width):
        var = sum((v[i] - means[i]) ** 2 for v in vectors) / n
        # Floor the deviation so a feature that never varied in training
        # cannot turn a small change into an enormous z-score. The floor is
        # small because most features are now in log or ratio space.
        stds.append(max(var ** 0.5, 0.05))
    return means, stds, n


def to_deviation(vector, baseline):
    """Express a raw feature vector as z-scores against a user's baseline.

    This is the representation the model actually sees, so one model serves
    every user while each is judged against their own normal.
    """
    means, stds, _n = baseline
    out = []
    for i in range(len(vector)):
        z = (vector[i] - means[i]) / stds[i]
        out.append(max(-MAX_DEVIATION, min(MAX_DEVIATION, z)))
    return out


def describe_deviation(deviation, top=3):
    """The features that moved most, for the admin-facing explanation.

    An anomaly score on its own is unactionable; this is what makes it
    readable next to the rule engine's plain-language reasons.
    """
    pairs = sorted(
        zip(FEATURE_NAMES, deviation), key=lambda p: abs(p[1]), reverse=True
    )
    out = []
    for name, z in pairs[:top]:
        if abs(z) < 0.75:
            continue
        direction = "above" if z > 0 else "below"
        out.append("%s %.1f sd %s normal" % (name.replace("_", " "), abs(z), direction))
    return out
