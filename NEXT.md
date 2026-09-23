# NEXT — deliberately deferred

Not built in the prototype. Kept here so the current scope stays honest about
what it is: a rule-based engine over a local simulated drive.

## 1. Working honeytokens

`production_api_keys.txt` currently contains `API_KEY=DEMO-PLACEHOLDER` and
nothing checks it. Embed a real (but fake) API key, then watch for that exact
string being *used* anywhere in the app — an auth header, a query parameter, a
request body. Any use is a near-certain compromise signal, not a behavioural
hint, so it should score **+40** and be its own action type rather than folding
into the existing OPEN/DOWNLOAD scoring.

## 2. ML-based anomaly detection

Complement or replace the hand-written rules with a model over the activity log:
per-user baselines of folders touched, session length, action cadence and time of
day, flagging deviation rather than matching fixed rules. The rule engine stays
as the explainable fallback and as labelled training signal.

## 3. Real object storage

Swap local text-in-SQLite for a real backend — AWS S3, Azure Blob, GCS, or MinIO
for a local S3-compatible option. Honeyfiles become real objects, and the
interaction log can be driven by the provider's own access logs (S3 access
logging, CloudTrail data events) instead of by API calls the app controls.

## 4. Adaptive honeyfiles

Show different decoys per role, so the bait is plausible to whoever is looking:
an `okr_2026.xlsx` for a Designer, a `payroll_run.csv` for Finance. A decoy is
only useful if the person reaching for it believes it.

## 5. Role-weighted risk scoring

Scoring is uniform today. An HR user opening an HR honeyfile is much less
interesting than a Designer doing the same, and the engine should say so —
weight each event by the distance between the user's role and the folder's
normal audience, rather than treating every open identically.

## 6. Admin notifications

Email or real-time push when a session crosses CRITICAL, so the dashboard does
not have to be watched. The polling feed is enough for a demo, not for response.

## 7. Visual session-timeline reconstruction

The timeline is a table. A visual reconstruction — actions on a time axis,
honeyfile hits marked, the score climbing alongside — would make the escalating
pattern legible at a glance, which is the whole argument for behavioural scoring
over single-event alerts.
