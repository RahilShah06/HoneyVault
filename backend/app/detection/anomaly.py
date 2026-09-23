"""Isolation Forest over session shape, trained on each user's own baseline.

This sits *beside* the rule engine, never inside it. `total_risk_score` is
untouched by anything here, and nothing here reads it. The two are meant to be
readable against each other: the rules say "you opened three decoys, here is
the arithmetic", and the model says "this session does not look like how you
normally use the drive". Agreement is corroboration; disagreement is the
interesting case, and it is the rules - not the model - that an analyst can
argue with.

Both dependencies are optional. With scikit-learn absent or no model file on
disk, `score_session` returns None, `sessions.anomaly_score` stays NULL, the
dashboard shows a dash, and every other feature behaves exactly as before.
"""
import os

from sqlalchemy.orm import Session as DbSession

from app.detection import features
from app.models import UserSession

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_PATH = os.path.join(BASE_DIR, "anomaly_model.joblib")

# Expected share of training sessions that are odd. The synthetic baseline is
# all meant to be normal, so this only absorbs generated outliers.
CONTAMINATION = 0.02
N_ESTIMATORS = 200
RANDOM_STATE = 7

# Isolation Forest's decision_function is positive for inliers and negative for
# outliers. Anything at or below this is reported as anomalous.
FLAG_THRESHOLD = 0.0

_cache = {"loaded": False, "model": None}


def available() -> bool:
    """True when scikit-learn is importable. Never raises."""
    try:
        import sklearn  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _load():
    """Load the trained model once per process. Missing model is not an error."""
    if _cache["loaded"]:
        return _cache["model"]
    _cache["loaded"] = True

    if not os.path.exists(MODEL_PATH) or not available():
        _cache["model"] = None
        return None
    try:
        import joblib

        _cache["model"] = joblib.load(MODEL_PATH)
    except Exception as exc:  # noqa: BLE001
        print("anomaly: could not load model, detection disabled - %s" % exc)
        _cache["model"] = None
    return _cache["model"]


def status() -> str:
    if not available():
        return "scikit-learn is not installed - anomaly detection off"
    if not os.path.exists(MODEL_PATH):
        return "no trained model at %s - run seeding to train one" % MODEL_PATH
    return "model loaded from %s" % MODEL_PATH


def train(db: DbSession, verbose: bool = True):
    """Fit the forest on every session that has a usable per-user baseline.

    Each training row is a session expressed as z-scores against its own
    user's baseline, so the model learns the *shape of normal deviation*
    rather than absolute volumes that differ from person to person.
    """
    if not available():
        print("anomaly: scikit-learn not installed, skipping training")
        return None

    from sklearn.ensemble import IsolationForest
    import joblib

    sessions = (
        db.query(UserSession).filter(UserSession.is_synthetic.is_(True)).all()
    )
    baselines = {}
    rows = []
    for s in sessions:
        if s.user_id not in baselines:
            baselines[s.user_id] = features.baseline_for(db, s.user_id)
        base = baselines[s.user_id]
        if base is None:
            continue
        vector = features.extract(db, s)
        if vector is None:
            continue
        rows.append(features.to_deviation(vector, base))

    if len(rows) < 20:
        print(
            "anomaly: only %d usable training sessions, need 20 - not training"
            % len(rows)
        )
        return None

    model = IsolationForest(
        n_estimators=N_ESTIMATORS,
        contamination=CONTAMINATION,
        random_state=RANDOM_STATE,
    )
    model.fit(rows)
    joblib.dump(model, MODEL_PATH)
    _cache["loaded"] = True
    _cache["model"] = model

    if verbose:
        print(
            "anomaly: trained on %d baseline sessions across %d users -> %s"
            % (len(rows), len(baselines), os.path.basename(MODEL_PATH))
        )
    return model


def score_session(db: DbSession, session: UserSession):
    """Return (score, is_anomalous, explanation) or None if unscoreable.

    Unscoreable is the normal case early on: too few actions to have a shape,
    or a user without enough history to have a baseline yet.
    """
    model = _load()
    if model is None:
        return None

    vector = features.extract(db, session)
    if vector is None:
        return None

    base = features.baseline_for(db, session.user_id, exclude_session_id=session.id)
    if base is None:
        return None

    deviation = features.to_deviation(vector, base)
    try:
        score = float(model.decision_function([deviation])[0])
    except Exception as exc:  # noqa: BLE001
        print("anomaly: scoring failed, skipping - %s" % exc)
        return None

    return score, score <= FLAG_THRESHOLD, features.describe_deviation(deviation)


def update_session(db: DbSession, session: UserSession) -> None:
    """Refresh a live session's anomaly columns. Never raises, never scores."""
    try:
        result = score_session(db, session)
    except Exception as exc:  # noqa: BLE001
        print("anomaly: update failed, session left unscored - %s" % exc)
        return
    if result is None:
        return
    score, flagged, _why = result
    session.anomaly_score = score
    session.anomaly_flag = bool(flagged)
