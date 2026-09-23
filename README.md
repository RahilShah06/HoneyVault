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
      detection/
        risk_engine.py    the scoring rules
        decoy_generator.py  role-tailored decoy content, generated and cached
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
decoy body; `--regenerate-decoys` throws those bodies away and writes fresh
ones.

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
LLM_PROVIDER=
LLM_API_KEY=
```

Copy `backend/.env.example` to `backend/.env` and fill them in. `.env` is
gitignored and **no key value appears anywhere in this repository**. The
supported provider value is `anthropic`.

### With no key set

The fallback path is not a degraded mode — it is the default one. If the key is
missing, the provider is unsupported, or the call fails or is declined, the
generator uses pre-written per-role content and prints the reason:

```
decoy: using fallback decoy content for bank_credentials.txt - no LLM_PROVIDER or LLM_API_KEY set in backend/.env
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

1. Log in as `employee02` / `employee123`.
2. Search for `salary` → +15
3. Search for `credentials` → +15
4. Search for `api` → +15
5. Open `employee_salary_2026.xlsx` → +10, plus +15 because five actions landed
   inside 60 seconds
6. Open `bank_credentials.txt` → +15 (2nd distinct honeyfile)
7. Download `bank_credentials.txt` → +20
8. Open `production_api_keys.txt` → +20 (3rd distinct honeyfile)

Raw total 125, capped at **100 — CRITICAL**. The admin dashboard shows a
**SECURITY ALERT** card for the session and a timeline where every row explains
the points it earned.

### Scenario 3 — the vault fights back

Step 8 above is where the score crosses 75, so the response has already fired.
Without logging out:

1. On the admin dashboard, open this session. The timeline has an
   **ACTIVE DECEPTION TRIGGERED** row right after the action that crossed 75,
   and the detail card carries an `ACTIVE DECEPTION ENGAGED` banner.
2. Back as `employee02`, open `project_report.pdf` — an ordinary, real file in
   a folder this user is entitled to. It comes back as a fabricated
   `INTERNAL DATA EXPORT`. Downloading it gives the same fake body.
3. In a third tab, log in as `employee01` and open the same
   `project_report.pdf`. It is the real Q3 report, untouched.

That contrast is the point: the intruder is now reading fiction, and nobody
else is affected.

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
| GET    | `/admin/summary`              | admin; the four dashboard tiles              |
| GET    | `/admin/events?limit=50`      | admin; newest-first feed (the UI polls this) |
| GET    | `/admin/sessions`             | admin; all sessions with score, level and `decoy_mode` |
| GET    | `/admin/sessions/{id}`        | admin; full action timeline for one session  |
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
- Decoy files never contain a usable secret: credential fields are written as
  `<redacted in this build>`. Nothing checks whether those fake credentials are
  ever *used* — that is the honeytoken work described in [NEXT.md](NEXT.md).
- Decoy generation is a single non-streaming call with no retry of its own
  beyond the SDK's. Anything that fails lands on the fallback content, which is
  the right trade for a demo but means a slow provider silently costs you the
  generated text.
- Decoy mode is never cleared once latched. A session stays poisoned until it
  ends; there is no admin control to lift it.
- Scoring is uniform across roles, so an Admin opening a honeyfile scores the
  same as a Designer. Role-weighted scoring is also in NEXT.md.
