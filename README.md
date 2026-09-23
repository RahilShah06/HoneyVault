# Cloud HoneyVault

A behaviour-based deception system for cloud storage, as a local prototype.

It simulates an organizational shared drive, plants realistic-looking fake
sensitive files (**honeyfiles**) among the real ones, logs how users interact
with the storage, and scores that behaviour with a rule-based risk engine.
The point is that no single click convicts anyone: points accumulate across a
session, and a level (LOW / MEDIUM / HIGH / CRITICAL) is recomputed after every
scored action. An admin dashboard shows live activity and risk.

Two things make the deception adaptive rather than static:

- **Decoy content is written per role.** A honeyfile stores a *target role*,
  not a fixed body. The body is generated once - by an LLM when one is
  configured, from pre-written content otherwise - then cached, so the bait an
  HR snoop finds reads like HR material and the bait a Designer finds reads
  like design material.
- **The system answers back.** Once a session crosses into CRITICAL, it is
  switched into decoy mode: every file it opens or downloads from then on
  returns fake content, honeyfile or not.

Everything runs locally, and everything runs with **no API key configured** -
the LLM is an upgrade to the decoy text, never a dependency.

---

## Stack

| Layer    | Choice                                            |
| -------- | ------------------------------------------------- |
| Backend  | Python + FastAPI                                  |
| Frontend | React (Vite)                                      |
| Database | SQLite (`backend/honeyvault.db`, created on seed)  |
| Auth     | bcrypt password hashing (passlib) + JWT bearer token |
| Decoys   | pluggable LLM provider (Gemini or Anthropic), with an offline fallback |
| Anomaly  | scikit-learn Isolation Forest over per-user baselines (optional) |

## Layout

```
honeyVault/
  backend/
    app/
      main.py             FastAPI app, CORS, router wiring
      database.py         SQLite engine / session
      models.py           users, folders, files, sessions, activity_logs
      auth.py             hashing, JWT, auth dependencies
      config.py           the one place env vars are read (loads .env)
      seed_data.py        folders, files, honeyfiles, demo users
      routes/
        auth.py           POST /login, POST /logout, GET /me
        files.py          folders, file open/download, search
        activity.py       raw activity-log queries (admin)
        dashboard.py      summary tiles, event feed, session drill-down
      baseline_traffic.py  synthetic normal history, so the model has a baseline
      middleware.py       honeytoken scanning on every inbound request
      detection/
        risk_engine.py    the scoring rules
        decoy_generator.py  role-tailored decoy content, generated and cached
        honeytoken.py     planting tokens in decoys, and catching their use
        features.py       session -> feature vector, and per-user baselines
        anomaly.py        Isolation Forest: train, load, score
    .env.example        LLM_PROVIDER / LLM_API_KEY, both empty
    requirements.txt
  frontend/               Vite React app: Login, Drive, Admin
  NEXT.md                 deliberately deferred work
  README.md
```

---

## Setup and run

Two terminals: one for the API, one for the UI.

### 1. Backend

```bash
cd backend

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt

cp .env.example .env             # optional - see "Decoy generation" below

python -m app.seed_data          # create tables + seed demo data
# python -m app.seed_data --reset  # wipe everything and start over

uvicorn app.main:app --reload --port 8000
```

API on <http://localhost:8000>, interactive docs at <http://localhost:8000/docs>.

`--reset` drops every table, which also clears sessions and activity logs — the
fastest way to get back to a clean demo. Seeding also fills in each honeyfile's
decoy body, plants honeytokens in them, generates 45 days of baseline traffic
and trains the anomaly model on it.

| Flag | Effect |
| ---- | ------ |
| `--reset` | drop every table first |
| `--regenerate-decoys` | discard cached decoy bodies and write fresh ones |
| `--no-history` | skip baseline generation and model training |
| `--history-days N` | days of baseline traffic to generate (default 45) |

The `.env` step is optional. With no `.env` at all, seeding prints
`using fallback decoy content — no LLM_PROVIDER or LLM_API_KEY set` for each
honeyfile and carries on; every feature below works.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

UI on <http://localhost:5173>. If the API is not on port 8000, copy
`.env.example` to `.env` and set `VITE_API_URL`.

---

## Demo credentials

| Username     | Password      | Role     |
| ------------ | ------------- | -------- |
| `admin`      | `admin123`    | Admin    |
| `employee01` | `employee123` | Designer |
| `employee02` | `employee123` | Designer |
| `hr01`       | `hr123`       | HR       |
| `finance01`  | `finance123`  | Finance  |
| `it01`       | `it123`       | IT       |

Passwords are bcrypt-hashed in the database; these plaintexts exist only here
and in `seed_data.py`.

---

## Seeded contents

Every user sees every folder — exactly like a real shared org drive. The
restriction is **behavioural, not an access wall**: reaching into another
role's folder is logged and scored, never blocked.

| Folder     | Normal for      | Real files                                | Honeyfile (target role)                  |
| ---------- | --------------- | ----------------------------------------- | ---------------------------------------- |
| `Projects` | everyone        | `project_report.pdf`, `presentation.pptx` | `design_budget_2026.xlsx` (Designer)     |
| `HR`       | HR, Admin       | `leave_policy.pdf`                        | `employee_salary_2026.xlsx` (HR)         |
| `Finance`  | Finance, Admin  | `invoice.pdf`                             | `bank_credentials.txt` (Finance)         |
| `IT`       | IT, Admin       | `deployment_notes.txt`                    | `production_api_keys.txt` (IT)           |

The Designer bait sits in `Projects`, the folder Designers use every day —
role-targeted decoys do not have to hide in a folder the target has no reason
to visit.

File contents are stored as **plain text**; the extension is only used for
display. Opening shows the text in a viewer pane, downloading serves the same
text as a blob. No real PDF/XLSX rendering is involved.

**Honeyfile status is never sent to the non-admin frontend.** The `/folders`,
`/files/{id}/open` and `/search` responses carry no `is_honeyfile` field, and the
Drive page shows no score or warning. Only the admin routes reveal decoys.

---

## Decoy generation

A honeyfile row carries a `target_role` instead of a hardcoded body. The first
time that body is needed — during seeding, or lazily on the first `/open` if it
is still empty — `detection/decoy_generator.py` produces it, writes it to
`files.content`, and stamps `files.decoy_generated_at`.

**It is generated once.** Every later open or download serves the cached
column, so a full demo costs at most one generation per honeyfile, and the text
an admin reviews is the same text the user saw. `python -m app.seed_data
--regenerate-decoys` is the only way to get new bodies.

The kind of document is inferred from the filename (salary sheet, credentials
file, API key list, budget document, contract summary), and the target role
decides who it is written for — so `employee_salary_2026.xlsx` reads as HR
material and `design_budget_2026.xlsx` reads as design material.

### Configuration

Two variables, read from `backend/.env` via `python-dotenv`, in one place —
`app/config.py`:

```
LLM_PROVIDER=gemini
LLM_API_KEY=your-key-here
```

Copy `backend/.env.example` to `backend/.env` and fill them in. `.env` is
gitignored and **no key value appears anywhere in this repository**.

| `LLM_PROVIDER` | Backend | Default model |
| -------------- | ------- | ------------- |
| `gemini` (or `google`) | Google AI Studio, via `google-genai` | `gemini-3.5-flash-lite` |
| `anthropic`            | Anthropic API, via `anthropic`       | `claude-opus-5` |

Set `LLM_MODEL` in `.env` to override the default for whichever provider is
selected. An unrecognised `LLM_PROVIDER` is not an error — it logs and falls
back, like a missing key.

Adding a provider means writing one function in `detection/decoy_generator.py`
with the signature `(filename, target_role, kind) -> str` and listing it in the
`PROVIDERS` dict. Caching, fallback and reporting are all provider-agnostic, so
nothing else changes.

### With no key set

The fallback path is not a degraded mode — it is the default one. If the key is
missing, the provider is unsupported, or the call fails or is declined, the
generator uses pre-written per-role content and prints the reason:

```
decoy: using fallback decoy content for bank_credentials.txt - no LLM_PROVIDER or LLM_API_KEY set in backend/.env
```

With a key set, the same step reports what it made instead:

```
decoy: generated salary sheet content for employee_salary_2026.xlsx (target role: HR)
```

Every honeyfile still ends up with plausible role-specific content, and the
entire walkthrough below runs with no network access at all.

---

## Active response

Detection that only writes to a log lets the intruder keep reading real files.
So the moment a session's score first crosses **75 into CRITICAL**, the risk
engine latches `sessions.decoy_mode` and writes an `ACTIVE_DECEPTION_TRIGGERED`
row for that session.

From that point on, `/files/{id}/open` and `/files/{id}/download` serve that
session fake content for **any** file it asks for — honeyfile or not. A
honeyfile returns its tailored decoy body; anything else returns a generic
fake-dataset template stamped with the requested filename.

Three properties worth stating plainly:

- **Nothing is mutated.** The stored row and the real content are untouched.
  Decoy mode is a property of one session's responses, so every other user
  — and the same user in a new session — still gets the real file.
- **It latches once.** The event is logged a single time per session, at the
  crossing, not on every subsequent action.
- **The client cannot tell.** The poisoned response has the same shape as a
  real one. Nothing in the Drive UI changes.

On the admin dashboard the trigger shows up as a distinct dark row in both the
recent-events feed and the session timeline, and a session in decoy mode gets
an `ACTIVE DECEPTION ENGAGED` banner on its detail card.

---

## Honeytokens

A honeyfile tells you someone **looked**. A honeytoken tells you someone took
what they found and **tried it**. Browsing a folder has innocent explanations;
replaying a credential lifted out of a decoy does not — so it scores +40, enough
to clear CRITICAL on its own, and gets its own action type.

**Planting.** The decoy generator is instructed to write
`<redacted in this build>` wherever a secret would go. Before the body is
cached, every one of those markers is replaced with a freshly minted
`hv_live_…` token and its own `honeytokens` row, labelled with the field it
stood in. A decoy with no marker — a budget spreadsheet — carries no token,
because a real one wouldn't.

The model tends to embed them in realistic shapes, which makes them more
convincing, not less:

```
AWS_PRODUCTION_ADMIN_KEY=AKIAhv_live_8ecc4431e4e64b2ec55b44d6b36f0691
DATABASE_MASTER_CONN=postgresql://admin:hv_live_7964a99…@prod-db-cluster.internal:5432/enterprise
```

**Catching.** `app/middleware.py` scans every inbound request — headers, query
string, and body — before routing. It runs as middleware rather than a route
dependency precisely because a stolen credential is most likely to turn up on
requests that never reach a route: a bad `Authorization` header, a probe at a
404. A cheap prefix check short-circuits almost every request without opening a
database session.

Three properties worth stating:

- **A honeytoken never authenticates anything.** Presenting one is logged and
  scored; the request then fails auth like any other bad token.
- **Unauthenticated use is still recorded**, with a null session — that is the
  case where someone is trying the credential itself.
- **It is scored once per use, not per token**, and the event names the field it
  was planted as, so a leak is traceable to the exact line of the exact decoy.

---

## Behavioural anomaly detection

An Isolation Forest runs **alongside** the rule engine and never inside it.
`total_risk_score` is untouched by it, and it never reads `total_risk_score`.
The two are meant to be read against each other: the rules say *"you opened
three decoys, here is the arithmetic"*, the model says *"this session does not
look like how you normally use the drive"*. Agreement is corroboration;
disagreement is the interesting case. Only the rules can be argued with, which
is why they stay the explainable primary signal.

### Independence is the whole point

Nothing derived from the rules goes into the model. The nine features are:

```
action_count  distinct_files  distinct_folders  out_of_role_ratio
download_ratio  search_ratio  duration_minutes  actions_per_minute  hour_of_day
```

No points, no honeyfile flag, no honeytoken. A model fed the rules' own outputs
would agree with them by construction and tell you nothing new.

### Per-user baselines

The same behaviour is ordinary for one person and strange for another, so each
session is expressed as **z-scores against that user's own history** before the
model sees it. One forest then learns the shape of normal *deviation* rather
than absolute volumes that differ from person to person — which is also what
makes a single model viable on this much data.

Counts and rates are log-compressed and deviations clipped to ±6 sd. Without
that, a fast session runs hundreds of actions per minute against a baseline of
two or three, that one feature reaches z ≈ 70, and the model collapses into a
speed alarm that flags any brisk user.

### The baseline problem, stated honestly

A freshly seeded database has no history, and a model with nothing to call
normal produces noise dressed up as insight. So seeding generates **45 days of
ordinary usage** per user (`app/baseline_traffic.py`), marked
`sessions.is_synthetic` and hidden from the dashboard's operational views:
office hours, own folders, human pacing, no decoys. The rule engine would score
every one of them zero, which is the point.

**The model is only as good as that generator's idea of normal.** Against real
logs you would delete that module and train on those instead. It is a stand-in,
not a substitute.

```
baseline: generated 309 synthetic sessions across 6 users over 45 days
anomaly:  trained on 309 baseline sessions across 6 users -> anomaly_model.joblib
anomaly:  10/309 baseline sessions flagged (3.2% - expect a small number)
```

About a third of generated sessions are **quick visits** — three to five actions
a few seconds apart. Leaving those out was a real bug: every baseline session
spanned minutes, so an ordinary "log in, grab one file, leave" was flagged
purely for being short. That false positive came from the generator's idea of
normal, not the model.

### Baseline poisoning

A user's baseline is built only from their sessions the **rule engine left at
LOW**. Without that filter a user's own past intrusions count towards their
normal: do the bad thing often enough and it stops looking unusual, and the
model goes quiet exactly when it matters. That is the standard attack on
anomaly detection, and using the rules as the label for "this history was
clean" is what NEXT.md meant by the rule engine serving as training signal.

Verified by running the same intrusion three times over: the score holds
instead of drifting toward normal.

```
repeat 1: rules=97  anomaly=-0.000  flagged=True
repeat 2: rules=97  anomaly=-0.000  flagged=True
repeat 3: rules=97  anomaly=-0.000  flagged=True
```

Those repeats sit close to the threshold — they are shorter runs than the full
scenario — but they stay flagged rather than decaying into the baseline.

### Measured separation

Both sessions below were driven at human pace against the same trained model:

| Session | Rule score | Anomaly score | Flagged |
| ------- | ---------- | ------------- | ------- |
| Designer, own folders, 4 actions | 15 (LOW) | **+0.059** | no |
| Designer hunting across HR/Finance/IT | 100 (CRITICAL) | **−0.035** | yes |

Top reasons given for the second: *distinct folders 6.0 sd above normal · out
of role ratio 6.0 sd above normal · actions per minute 3.9 sd above normal.*

Note that the leading reasons are **behavioural**, not speed. An earlier
version scored raw counts and rates, `actions_per_minute` reached 70 sd, and
the model degenerated into a speed alarm that flagged any brisk user. Log
compression plus the ±6 sd clip is what moved "where they went" ahead of "how
fast they went".

### Optional, like everything else here

`scikit-learn` absent, or no `anomaly_model.joblib` on disk, and
`score_session` returns `None`: the column stays NULL, the dashboard shows a
dash, and every other feature behaves identically. Verified by moving the model
file away — the rule engine still scored a hunting session 75/HIGH with the
anomaly column null.

Skip it entirely with `python -m app.seed_data --reset --no-history`.

---

## Risk engine

Points accumulate on the active session and the total is capped at 100.

| Event                                            | Points               |
| ------------------------------------------------ | -------------------- |
| Open 1st distinct honeyfile in session           | +10                  |
| Open 2nd distinct honeyfile in session           | +15                  |
| Open 3rd+ distinct honeyfile in session          | +20 each             |
| Download a honeyfile                             | +20                  |
| Sensitive-keyword search                         | +15                  |
| Open a non-honeyfile outside the role's folders  | +20 (RESTRICTED_ATTEMPT) |
| 5+ actions within any 60-second window           | +15, once per session |
| Carried-over failed logins (on successful login) | +10 each, capped at +30 |
| **Using a planted honeytoken, anywhere**         | **+40 (HONEYTOKEN_USED)** |

Honeyfile open and download points are then **role-weighted**: multiplied by
**0.5** when the file sits in a folder normal for the user's role, and **1.5**
when it does not. An IT user opening the IT decoy scores 5; a Designer opening
the same file scores 15. The multiplier and the reason for it are written into
each event's "Why" column.

Sensitive keywords: `password`, `credential`, `salary`, `database`, `api`,
`key`, `bank`, `confidential`, `secret`.

Levels: **0–25 LOW**, **26–50 MEDIUM**, **51–75 HIGH**, **76–100 CRITICAL**.

Details worth knowing:

- Re-opening a honeyfile already opened in the same session scores 0. Only
  *distinct* honeyfiles escalate.
- Failed logins increment `users.failed_login_attempts` and write a
  `LOGIN_FAILED` row. On the next successful login, attempts from the last
  10 minutes roll into the new session's starting score, then the counter resets.
- The burst bonus is folded into the triggering action's `points_awarded` and
  explained in its `reason`, so an admin reading a timeline sees the numbers add
  up to the session total.
- `GET /admin/scoring-rules` returns the live configuration, which is handy to
  show during a demo.
- A session counts as **active** only while its token could still work: not
  logged out, and started within the token lifetime (12h). People rarely log out
  explicitly, so without that cutoff every past login would sit in the "Active
  sessions" tile forever.
- An admin can force-end someone's session from the session detail card. Their
  token stops working immediately. Ending a session writes no `activity_logs`
  row, because it is an admin action rather than user behaviour and would
  otherwise show up in the scored timeline.

Columns additive to the base schema, and why each exists:
`sessions.burst_awarded` (the rapid-activity bonus fires once per session),
`sessions.decoy_mode` (latched when the session first hits CRITICAL),
`activity_logs.reason` (the human-readable breakdown shown in the "Why"
column), `files.target_role` (whose bait a honeyfile is) and
`files.decoy_generated_at` (when its body was generated and cached).

Existing databases are migrated in place on startup — `init_db()` adds any
missing column rather than requiring a reset.

---

## Walkthrough

Start from a clean database (`python -m app.seed_data --reset`) and keep the
admin dashboard open in a second tab or window.

**Each tab or window is its own login.** Credentials are held in
`sessionStorage`, so a new tab starts logged out and you can watch the admin
dashboard in one window while acting as `employee02` in another. Logging out of
one never affects the other. (Use a genuinely new tab — "Duplicate tab" copies
`sessionStorage` and would carry the login across.)

### Scenario 1 — normal employee, stays LOW

1. Log in as `employee01` / `employee123`.
2. Open the **Projects** folder, open `project_report.pdf` and `presentation.pptx`.
3. Search for `report`.
4. On the admin dashboard, open this session: **score 0, LOW**.

Everything this user did was normal for a Designer, so nothing scored — which is
the behaviour the engine is designed to leave alone.

### Scenario 2 — insider hunting, escalates to CRITICAL

`employee02` is a **Designer**, so every folder below is outside their role and
every honeyfile open is weighted x1.5.

| # | Action | Points | Running |
| - | ------ | ------ | ------- |
| 1 | Log in as `employee02` / `employee123` | 0 | 0 |
| 2 | Search `salary` | +15 | 15 |
| 3 | Search `credentials` | +15 | 30 |
| 4 | Search `api` | +15 | 45 |
| 5 | Open `employee_salary_2026.xlsx` | **+30** | 75 |
| 6 | Open `bank_credentials.txt` | +22 | 97 |
| 7 | Download `bank_credentials.txt` | +30 | 100 |
| 8 | Open `production_api_keys.txt` | +30 | 100 |

Step 5 is 10 base x1.5 for reaching into HR, **plus** +15 because five actions
landed inside 60 seconds. Step 6 is the 2nd-distinct-honeyfile rate of 15,
weighted to 22. Raw total 157, capped at **100 — CRITICAL**.

The admin dashboard shows a **SECURITY ALERT** card for the session and a
timeline where every row explains the points it earned, including the
multiplier and why it applied.

### Scenario 3 — the vault fights back

Role weighting means the score crosses 75 at **step 6**, not step 8 — the
response fires earlier than it would have unweighted. Without logging out:

1. On the admin dashboard, open this session. The timeline has an
   **ACTIVE DECEPTION TRIGGERED** row right after step 6,
   and the detail card carries an `ACTIVE DECEPTION ENGAGED` banner.
2. Back as `employee02`, open `project_report.pdf` — an ordinary, real file in
   a folder this user is entitled to. It comes back as a fabricated
   `INTERNAL DATA EXPORT`. Downloading it gives the same fake body.
3. In a third tab, log in as `employee01` and open the same
   `project_report.pdf`. It is the real Q3 report, untouched.

That contrast is the point: the intruder is now reading fiction, and nobody
else is affected.

### Scenario 4 — the credential gets used

The strongest signal in the system, and the shortest path to CRITICAL.

1. As `employee02`, open `production_api_keys.txt` and copy one of the
   `hv_live_…` values out of the viewer pane.
2. Paste it anywhere the app will see it — the search box is easiest:
   search for that token.
3. The session jumps **+40** and the admin dashboard shows a red
   **HONEYTOKEN USED** row naming the field it was planted as
   (`AWS_PRODUCTION_ADMIN_KEY`, say), plus the `Honeytokens used` tile
   incrementing.

Try it as a bare `Authorization: Bearer <token>` too — it is rejected as auth
and still logged, with no session attached:

```bash
curl -s -o /dev/null -w "%{http_code}
"   -H "Authorization: Bearer hv_live_..." http://localhost:8000/me
# 401, and a HONEYTOKEN_USED row appears on the dashboard
```

### Risk reconstruction

Open any session on the dashboard and the **Risk reconstruction** chart sits
above the action table: the score climbing to 100, each scored action marked by
shape (honeyfile, out-of-role, honeytoken) and coloured by severity, the
CRITICAL threshold drawn at 75, and a rule marking the moment decoys engaged.
Hovering any marker gives the action, the time and the points. The table
underneath is the same data in accessible form.

Sessions shorter than 20 seconds are spread by action order rather than elapsed
time, and the axis says so — a scripted run finishes in milliseconds and a true
time axis would stack every point in one column.

To demonstrate the remaining two rules:

- **Restricted attempt:** as `employee02`, open `leave_policy.pdf` in the HR
  folder — an ordinary file in someone else's folder, +20.
- **Failed-login carry-over:** fail the `hr01` login twice, then log in
  correctly — the session starts at 20 instead of 0.

---

## API

All routes except `POST /login` and `GET /health` need
`Authorization: Bearer <token>`. Admin routes additionally require the Admin role
and return 403 otherwise.

| Method | Path                          | Notes                                        |
| ------ | ----------------------------- | -------------------------------------------- |
| POST   | `/login`                      | returns token, role, starting score          |
| POST   | `/logout`                     | ends the session; the token stops working    |
| GET    | `/me`                         | current session score and level              |
| GET    | `/folders`                    | all folders, for every role                  |
| GET    | `/folders/{id}/files`         | filenames only — no honeyfile flag           |
| POST   | `/files/{id}/open`            | returns content, logs and scores the open; decoy content if the session is in decoy mode |
| POST   | `/files/{id}/download`        | returns a text blob, same decoy-mode rule    |
| POST   | `/search`                     | `{"query": "..."}` substring match on filenames |
| GET    | `/activity/logs`              | admin; filter by session, user or action     |
| GET    | `/admin/summary`              | admin; the dashboard tiles, incl. honeytokens planted/used |
| GET    | `/admin/events?limit=50`      | admin; newest-first feed (the UI polls this) |
| GET    | `/admin/sessions`             | admin; real sessions with score, level, `decoy_mode`, anomaly |
| GET    | `/admin/sessions/{id}`        | admin; timeline plus the model's reasons     |
| POST   | `/admin/sessions/{id}/end`    | admin; force-end a session (not your own)    |
| GET    | `/admin/scoring-rules`        | admin; the live engine config, incl. active response |

---

## Prototype boundaries

This is a prototype, and a few things are deliberately simple:

- The JWT secret falls back to a hardcoded development value. Set
  `HONEYVAULT_SECRET` for anything beyond a local demo.
- Tokens are stored in `sessionStorage` (per tab) rather than `localStorage`, so
  two tabs are two independent logins. That is what makes the side-by-side demo
  work, but browser storage of any kind is still a local-demo choice, not a
  production one. `RequireAuth` re-checks the token against `GET /me` on every
  mount, so a token that expired or whose session was ended elsewhere lands on
  the login page instead of rendering the app shell.
- Decoy files never contain a usable secret. The generator is told to write
  `<redacted in this build>` wherever a credential would go, and every one of
  those markers is replaced at plant time with an `hv_live_…` honeytoken that
  nothing in the system ever accepts as valid.
- Decoy generation is a single non-streaming call with no retry of its own
  beyond the SDK's, bounded by a 30s timeout so a slow provider cannot hang a
  request. Anything that fails lands on the fallback content, which is the
  right trade for a demo but means an overloaded model silently costs you the
  generated text. Both SDKs are imported lazily, inside the provider function,
  so the one you are not using is never loaded.
- Decoy mode is never cleared once latched. A session stays poisoned until it
  ends; there is no admin control to lift it.
- The honeytoken scanner reads the request body into memory, capped at 64 KB.
  That is fine for JSON APIs and would need rethinking for file uploads.
- Honeytokens are only caught when presented *to this app*. Catching one used
  against a real external service is the object-storage work in
  [NEXT.md](NEXT.md).
- The anomaly model trains on **generated** history, so it learns one
  generator's idea of normal. Its measured separation is real, but it is not
  evidence the model would work on a real organization's logs.
- A user needs at least 8 clean past sessions before they have a baseline, and
  a session needs 3 actions before it has a shape. Below either, sessions are
  left unscored rather than guessed at.
- The baseline filter leans on the rule engine to decide which history was
  clean. An intrusion the rules never notice would also land in the baseline.
- The model is retrained only at seed time. There is no online learning, so
  genuine drift in someone's habits will eventually read as anomalous.
- Scoring is uniform across roles, so an Admin opening a honeyfile scores the
  same as a Designer. Role-weighted scoring is also in NEXT.md.
