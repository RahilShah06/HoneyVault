"""Generate plausible *normal* drive usage, so the model has a baseline.

A freshly seeded database has no history. Without it an anomaly model has
nothing to call normal, and any score it produced would be noise dressed up as
insight - which is worse than not shipping the feature.

So the baseline is manufactured explicitly and labelled as such
(`sessions.is_synthetic`). Every generated session is ordinary by construction:
the user's own folders plus the shared one, office hours, human-scale pacing,
no honeyfiles. The rule engine would score all of it zero, which is the point -
these sessions describe what "nothing happening" looks like for each person.

This is a stand-in for real history, and the honest limitation is that the model
can only be as good as this generator's idea of normal. Against real logs, drop
this module and train on those instead.
"""
import datetime as dt
import random

from app.models import ActivityLog, File, Folder, User, UserSession

# Benign things people actually search a shared drive for.
BENIGN_SEARCHES = [
    "report", "notes", "deck", "policy", "q3", "review", "draft",
    "invoice", "plan", "handbook", "onboarding", "roadmap", "minutes",
]

WORK_START_HOUR = 8
WORK_END_HOUR = 19

# Per-user variation, so baselines actually differ between people.
PERSONA_SPREAD = {
    "actions": (4, 14),
    "sessions_per_day": (0, 3),
}

# Real drive use is not all leisurely browsing: a decent share of visits are
# "log in, grab the one file, leave". Leaving those out makes any brief
# legitimate session look anomalous purely for being short and quick, which is
# a false positive the generator - not the model - would have caused.
QUICK_VISIT_RATE = 0.35
QUICK_VISIT_ACTIONS = (3, 5)
QUICK_VISIT_GAP_SECONDS = (3, 20)


def _folders_normal_for(db, role):
    return [f for f in db.query(Folder).all() if f.is_normal_for(role)]


def _files_in(db, folders):
    """Real files only - a normal session never touches a decoy."""
    ids = [f.id for f in folders]
    if not ids:
        return []
    return (
        db.query(File)
        .filter(File.folder_id.in_(ids), File.is_honeyfile.is_(False))
        .all()
    )


def _persona(rng):
    """A stable per-user tendency, so each person's normal is their own."""
    return {
        "chattiness": rng.uniform(0.6, 1.5),
        "download_rate": rng.uniform(0.05, 0.35),
        "search_rate": rng.uniform(0.1, 0.4),
        "start_hour": rng.randint(WORK_START_HOUR, WORK_START_HOUR + 3),
        "pace_seconds": rng.uniform(8, 70),
    }


def _one_session(db, user, files, persona, day, rng):
    quick = rng.random() < QUICK_VISIT_RATE
    if quick:
        lo, hi = QUICK_VISIT_ACTIONS
        n_actions = rng.randint(lo, hi)
    else:
        lo, hi = PERSONA_SPREAD["actions"]
        n_actions = max(3, int(rng.randint(lo, hi) * persona["chattiness"]))

    start_hour = min(
        WORK_END_HOUR - 1,
        max(WORK_START_HOUR, persona["start_hour"] + rng.randint(-1, 5)),
    )
    t = day.replace(
        hour=start_hour, minute=rng.randint(0, 59), second=rng.randint(0, 59),
        microsecond=0,
    )

    session = UserSession(
        user_id=user.id,
        login_time=t,
        total_risk_score=0,
        risk_level="LOW",
        is_synthetic=True,
    )
    db.add(session)
    db.flush()

    db.add(
        ActivityLog(
            session_id=session.id,
            user_id=user.id,
            action_type="LOGIN",
            points_awarded=0,
            reason="successful login",
            timestamp=t,
        )
    )

    for _ in range(n_actions):
        if quick:
            gap = rng.uniform(*QUICK_VISIT_GAP_SECONDS)
        else:
            gap = rng.uniform(4, persona["pace_seconds"] * 2)
        t = t + dt.timedelta(seconds=gap)
        roll = rng.random()
        if roll < persona["search_rate"]:
            db.add(
                ActivityLog(
                    session_id=session.id,
                    user_id=user.id,
                    action_type="SEARCH",
                    search_query=rng.choice(BENIGN_SEARCHES),
                    points_awarded=0,
                    timestamp=t,
                )
            )
        elif roll < persona["search_rate"] + persona["download_rate"] and files:
            f = rng.choice(files)
            db.add(
                ActivityLog(
                    session_id=session.id,
                    user_id=user.id,
                    action_type="DOWNLOAD",
                    target_file_id=f.id,
                    points_awarded=0,
                    timestamp=t,
                )
            )
        elif files:
            f = rng.choice(files)
            db.add(
                ActivityLog(
                    session_id=session.id,
                    user_id=user.id,
                    action_type="OPEN",
                    target_file_id=f.id,
                    points_awarded=0,
                    timestamp=t,
                )
            )

    session.logout_time = t + dt.timedelta(
        seconds=rng.uniform(5, 30) if quick else rng.uniform(10, 240)
    )
    return session


def generate(db, days: int = 45, seed: int = 11, verbose: bool = True) -> int:
    """Write `days` of ordinary history for every user. Returns sessions made."""
    rng = random.Random(seed)
    users = db.query(User).all()
    today = dt.datetime.now().replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    made = 0
    for user in users:
        folders = _folders_normal_for(db, user.role)
        files = _files_in(db, folders)
        persona = _persona(rng)

        for day_offset in range(days, 0, -1):
            day = today - dt.timedelta(days=day_offset)
            if day.weekday() >= 5 and rng.random() < 0.85:
                continue  # weekends are mostly quiet
            lo, hi = PERSONA_SPREAD["sessions_per_day"]
            for _ in range(rng.randint(lo, hi)):
                _one_session(db, user, files, persona, day, rng)
                made += 1

    db.flush()
    if verbose:
        print(
            "baseline: generated %d synthetic sessions across %d users over %d days"
            % (made, len(users), days)
        )
    return made


def clear(db) -> int:
    """Remove generated history (and its logs), leaving real sessions alone."""
    ids = [
        s.id
        for s in db.query(UserSession).filter(UserSession.is_synthetic.is_(True))
    ]
    if not ids:
        return 0
    db.query(ActivityLog).filter(ActivityLog.session_id.in_(ids)).delete(
        synchronize_session=False
    )
    db.query(UserSession).filter(UserSession.id.in_(ids)).delete(
        synchronize_session=False
    )
    db.flush()
    return len(ids)
