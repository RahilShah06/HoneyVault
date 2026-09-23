# Demo video pipeline

Produces `cloud-honeyvault-demo.mp4` from the **real running app**. No UI is
mocked, restyled or recoloured anywhere in this pipeline: Playwright drives the
actual frontend at :5173 against the actual backend at :8000, and Remotion only
edits the resulting footage.

```
video/          Playwright recorders
recordings/     raw .webm clips, one per browser context
remotion/       the edit: sequencing, trims, crossfades, overlays
```

## Prerequisites

Both services running, and a freshly seeded database:

```bash
cd backend
python -m app.seed_data --reset          # decoys, honeytokens, baseline, model
uvicorn app.main:app --port 8000

cd frontend && npm run dev               # :5173
```

Restart the backend after seeding — it caches the anomaly model in-process, so
a server started before training keeps the old one.

## 1. Record

```bash
cd video
npm install
npx playwright install chromium
node record.mjs
```

Writes 14 clips to `recordings/`. The script asserts its prerequisites first
and throws rather than producing footage of the wrong thing — if a honeytoken
is missing from a decoy, or a selector stops matching, it fails loudly.

**Why separate contexts.** The app keeps credentials in `sessionStorage`, which
is per-context, so each clip gets a genuinely isolated login exactly like the
multi-tab demo in the main README. Playwright writes one video per context on
close, so clips that continue an earlier session re-seed `sessionStorage` with
that session's token instead of logging in again. The backend session carries
on untouched; only the browser context is new.

`record-clip08.mjs` re-records clip 8 alone. Everything it does is read-only,
so a framing fix there costs one clip rather than the whole film.

### Clips

| File | Shows |
| ---- | ----- |
| `01-normal-use` + `01b-normal-use-admin` | employee01 browsing normally; the session at 0 / LOW |
| `02-decoy` | the Designer-targeted decoy sitting in Projects |
| `03-insider-hunting` | README Scenario 2, in order |
| `04-dashboard-reacts` | SECURITY ALERT card, per-row "Why", risk reconstruction chart |
| `05-active-response-intruder` + `05b-...-honest` | the same file, fabricated for one session and real for another |
| `06-honeytoken-used` + `06b-honeytoken-admin` | a planted token lifted from the viewer and used |
| `07-second-opinion` | the Anomaly column and the model's reasons |
| `08-nothing-hidden` | live scoring rules, then the force-end control |
| `09-restricted-attempt` + `09b-failed-logins` + `09c-carryover-admin` | the last two rules |

### Two deliberate choices

**Clip 8 goes through `/docs`.** `GET /admin/scoring-rules` needs a bearer
token, so a plain browser tab returns 403. FastAPI's own Swagger UI is part of
the running backend — not something built for this video — and it is the app's
own way of showing an authenticated response.

**The token is kept out of frame.** Swagger echoes the request as a curl
command containing the admin bearer token. The recorder scrolls the JSON
response to the top of the viewport so that block sits above the frame, then
*asserts* the token is not visible before it records. A working credential
should not be legible in a video anyone might share.

## 2. Edit

```bash
cd remotion
npm install
cp ../recordings/*.webm public/
```

`src/clips.js` is the edit decision list: which segments belong to which
feature, how much to trim off each head, and the overlay copy. `src/Demo.jsx`
sequences them with `<TransitionSeries>` and crossfades, and draws the
bottom-third overlays as a separate layer so one caption can span several
segments of the same feature.

Overlays are post-production chrome — a translucent dark bar with an accent
rule — deliberately unlike the recorded app's light theme, so they never read
as part of the product.

## 3. Render

```bash
npm run render     # -> ../cloud-honeyvault-demo.mp4, 1920x1080, 30fps
```

## Re-recording

The footage is only as current as the app. After changing the frontend, the
scoring rules or the decoy content, re-record rather than re-cutting — the
overlays make claims about what is on screen.

One case worth knowing: decoy bodies come from an LLM and fall back to
pre-written content when the provider errors. Clip 2's overlay says an LLM
wrote that file, so check before recording that it actually did:

```bash
cd backend
python -c "
from app.database import SessionLocal
from app.detection.decoy_generator import FALLBACK_BY_ROLE
from app.models import File
db = SessionLocal()
for f in db.query(File).filter(File.is_honeyfile.is_(True)):
    stem = FALLBACK_BY_ROLE.get(f.target_role, '').split(chr(10))[0].strip()
    print(f.filename, 'FALLBACK' if stem and stem in f.content else 'LLM')
"
```

Re-running `--regenerate-decoys` until every row says `LLM` is the fix; the
provider tends to succeed on a retry after a transient 504.
