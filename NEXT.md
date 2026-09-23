# NEXT — deliberately deferred

Not built. Kept here so the current scope stays honest about what it is: a
rule-based engine and an anomaly model, over a local simulated drive that the
app both serves and watches.

## 1. Real object storage

Swap local text-in-SQLite for a real backend — AWS S3, Azure Blob, GCS, or MinIO
for a local S3-compatible option. Honeyfiles become real objects, and the
interaction log can be driven by the provider's own access logs (S3 access
logging, CloudTrail data events) instead of by API calls the app controls.

That last part is the real prize and the real work: today the app is both the
thing being watched and the thing doing the watching, which is exactly the
assumption an insider with direct storage access would break.

## 2. Admin notifications

Email or real-time push when a session crosses CRITICAL, so the dashboard does
not have to be watched. The polling feed is enough for a demo, not for response.

Needs a channel decision and credentials: SMTP, a transactional email provider,
or a webhook into Slack/Teams. A credential-free first step is server-sent
events to an already-open dashboard, which removes the 4s poll but not the
need to have the tab open.

---

## Shipped since this file was first written

- **ML-based anomaly detection.** An Isolation Forest over per-user baselines,
  trained on generated history, running alongside the rules and independent of
  them. The baseline generator is the honest weak point: it learns one
  generator's idea of normal, and real logs would replace it.
- **Working honeytokens.** Each decoy carries planted `hv_live_…` credentials,
  one `honeytokens` row per planted field. Every inbound request is scanned —
  headers, query string, body — and any use scores +40 as its own
  `HONEYTOKEN_USED` action type. Nothing ever accepts one as valid.
- **Adaptive honeyfiles.** Decoys carry a `target_role` and their bodies are
  generated per role, then cached.
- **Role-weighted risk scoring.** Honeyfile points are multiplied by 0.5 inside
  the user's own folder and 1.5 outside it, with the weighting spelled out in
  each event's reason.
- **Visual session-timeline reconstruction.** The score plotted over the session
  with each scored action marked, the CRITICAL threshold drawn, and the moment
  active deception engaged annotated.
