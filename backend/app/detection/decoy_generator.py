"""Role-tailored decoy content for honeyfiles, generated once and cached.

Two things live here:

1. **Decoy bodies.** A honeyfile row carries a `target_role` rather than fixed
   text. The first time its body is needed it is generated - by an LLM when one
   is configured, from pre-written content otherwise - written to
   `files.content`, and stamped with `files.decoy_generated_at`. Every later
   read serves the cached column. Generation never happens on a `/open` that
   already has content, so a demo costs at most one call per honeyfile.

2. **Poisoned bodies.** Once a session latches into decoy mode, every file it
   touches is served fake content instead of the real thing. Nothing on disk or
   in the database is modified: this is a per-session response, not a mutation.

The fallback path is not a degraded mode. With no key set at all, every
honeyfile still has plausible role-specific content and the whole demo runs
with zero network access.
"""
import datetime as dt

from sqlalchemy.orm import Session as DbSession

from app import config
from app.detection import honeytoken
from app.models import ANY_ROLE, File, utcnow

# ---------------------------------------------------------------------------
# What kind of document a decoy is, inferred from its filename.
# ---------------------------------------------------------------------------

DOC_KINDS = [
    # (substrings in the filename, description used in the prompt)
    (("salary", "payroll", "compensation"), "salary sheet"),
    (("credential", "password", "login"), "credentials file"),
    (("api_key", "apikey", "api-key", "token"), "API key list"),
    (("budget", "forecast", "spend"), "budget document"),
    (("contract", "invoice"), "contract summary"),
]

DEFAULT_DOC_KIND = "confidential internal document"


def doc_kind_for(filename: str) -> str:
    name = (filename or "").lower()
    for needles, kind in DOC_KINDS:
        if any(needle in name for needle in needles):
            return kind
    return DEFAULT_DOC_KIND


# ---------------------------------------------------------------------------
# Fallback content: pre-written, per role. Used when no key is configured and
# whenever a call fails. Every value below is invented.
# ---------------------------------------------------------------------------

FALLBACK_BY_ROLE = {
    "HR": (
        "CONFIDENTIAL - PEOPLE OPS\n"
        "employee,role,band,annual_ctc,review_cycle\n"
        "A. Sharma,Engineering Lead,L5,4200000,H2-2026\n"
        "R. Menon,Product Designer,L3,1850000,H1-2026\n"
        "K. Iyer,Finance Manager,L4,2600000,H2-2026\n"
        "S. Das,HR Partner,L3,1700000,H1-2026\n"
        "N. Rao,Support Lead,L3,1620000,H2-2026\n"
        "notes: band revisions pending sign-off from the comp committee\n"
    ),
    "Finance": (
        "CORPORATE BANKING - OPS ACCESS\n\n"
        "portal:   https://corp-banking.internal/login\n"
        "account:  0041-88213-05\n"
        "username: fin_ops_admin\n"
        "password: <redacted in this build>\n"
        "approver: K. Iyer (limit 500000 per transfer)\n"
        "backup:   treasury-ops@internal.example\n"
        "note: rotate quarterly, last rotation 2026-04-02\n"
    ),
    "IT": (
        "PRODUCTION API KEYS - DO NOT DISTRIBUTE\n\n"
        "PAYMENTS_API_KEY=<redacted in this build>\n"
        "STORAGE_SECRET=<redacted in this build>\n"
        "DB_PASSWORD=<redacted in this build>\n"
        "JWT_SIGNING_KEY=<redacted in this build>\n"
        "region: ap-south-1\n"
        "owner:  platform-infra@internal.example\n"
        "note: staging keys live in the vault, not here\n"
    ),
    "Designer": (
        "DESIGN ORG BUDGET 2026 - DRAFT\n\n"
        "line_item,vendor,committed,spent_ytd\n"
        "Design system rebuild,Northwind Studio,1800000,1120000\n"
        "User research panel,Lumen Insights,640000,410000\n"
        "Motion + brand film,Harbour Post,950000,0\n"
        "Tooling licences,Figma + Maze,310000,268000\n"
        "headcount: 2 open roles held for Q3, not yet approved\n"
    ),
    "Developer": (
        "INTERNAL SERVICE NOTES - PLATFORM\n\n"
        "staging_db:  postgres://svc_app@db-stg.internal:5432/appdb\n"
        "admin_panel: https://admin-stg.internal/ops\n"
        "service_account: svc_deploy\n"
        "service_token:   <redacted in this build>\n"
        "on-call rotation: platform-infra, weekly handover Mondays\n"
        "note: prod credentials are never checked into this drive\n"
    ),
    "Admin": (
        "ORG ADMIN - PRIVILEGED ACCOUNTS\n\n"
        "root_console: https://admin.internal/console\n"
        "break_glass_user: org_break_glass\n"
        "break_glass_secret: <redacted in this build>\n"
        "mfa_reset_queue: 3 pending\n"
        "audit_export: s3://internal-audit-exports/2026/\n"
        "note: break-glass use must be filed within 24h\n"
    ),
}

FALLBACK_DEFAULT = (
    "CONFIDENTIAL - INTERNAL ONLY\n\n"
    "This document is restricted to the owning team.\n"
    "reference: INT-2026-0447\n"
    "owner: internal-ops@internal.example\n"
    "classification: confidential\n"
    "note: do not forward outside the organization\n"
)


def fallback_content(target_role: str) -> str:
    return FALLBACK_BY_ROLE.get(target_role or "", FALLBACK_DEFAULT)


# ---------------------------------------------------------------------------
# LLM generation
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You write decoy files for a defensive security honeypot used in a lab "
    "demo. Everything you produce is entirely fictional: invented names, "
    "invented account numbers, invented amounts. Never output a real or "
    "real-looking secret - write the literal placeholder "
    "'<redacted in this build>' wherever a credential value would go. "
    "Reply with the file body only: no preamble, no commentary, no code fences."
)

USER_PROMPT = (
    "Generate a short, realistic but entirely fictional {kind} for someone "
    "with the role {role} at a mid-sized company. The file is named "
    "{filename}. The data must be fake but plausible enough that someone "
    "snooping through a shared drive would stop and read it. Keep it under "
    "15 lines."
)


def _prompt_for(filename: str, target_role: str, kind: str) -> str:
    """The one user-facing instruction, shared by every provider."""
    role = target_role if target_role and target_role != ANY_ROLE else "an employee"
    return USER_PROMPT.format(kind=kind, role=role, filename=filename)


def _generate_via_anthropic(filename: str, target_role: str, kind: str) -> str:
    """One short, non-streaming Messages call. Raises on any failure."""
    import anthropic

    client = anthropic.Anthropic(
        api_key=config.LLM_API_KEY,
        timeout=config.LLM_TIMEOUT_SECONDS,
    )

    response = client.beta.messages.create(
        model=config.LLM_MODEL or config.ANTHROPIC_MODEL,
        max_tokens=config.LLM_MAX_TOKENS,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": _prompt_for(filename, target_role, kind)}
        ],
    )

    # Safety classifiers can decline this kind of request; that is a normal
    # outcome to handle, not a bug, and it lands on the fallback content.
    if response.stop_reason == "refusal":
        raise RuntimeError("model declined to generate this decoy")

    text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    if not text:
        raise RuntimeError("model returned no text")
    return text + "\n"


def _generate_via_gemini(filename: str, target_role: str, kind: str) -> str:
    """One short generate_content call against Google AI Studio.

    Raises on any failure, including a safety block - the caller turns that
    into the pre-written fallback body.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=config.LLM_API_KEY,
        # Without an explicit timeout a slow model would hang a /open request.
        http_options=types.HttpOptions(
            timeout=int(config.LLM_TIMEOUT_SECONDS * 1000)
        ),
    )

    response = client.models.generate_content(
        model=config.LLM_MODEL or config.GEMINI_MODEL,
        contents=_prompt_for(filename, target_role, kind),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=config.LLM_MAX_TOKENS,
        ),
    )

    # A prompt refused outright reports why on prompt_feedback and comes back
    # with no candidates at all.
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        raise RuntimeError("prompt blocked: %s" % feedback.block_reason)

    if not response.candidates:
        raise RuntimeError("no candidates returned")

    finish = response.candidates[0].finish_reason
    # STOP is the clean finish. MAX_TOKENS still carries usable text; anything
    # else (SAFETY, RECITATION, ...) is a block.
    if finish is not None and finish.name not in ("STOP", "MAX_TOKENS"):
        raise RuntimeError("generation stopped: %s" % finish.name)

    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("model returned no text")
    return text + "\n"


# Every wired-up provider, by the value you put in LLM_PROVIDER. Adding one
# means writing a function with this signature - (filename, target_role, kind)
# -> the file body, raising on any failure - and listing it here. Nothing else
# changes: the caching, the fallback and the terminal reporting are all
# provider-agnostic.
PROVIDERS = {
    "gemini": _generate_via_gemini,
    "google": _generate_via_gemini,  # the same thing under the name people type
    "anthropic": _generate_via_anthropic,
}


def generate_content(filename: str, target_role: str):
    """Return (content, source) where source is 'llm' or 'fallback'.

    Never raises: anything that goes wrong becomes the fallback body, with the
    reason printed to the terminal.
    """
    kind = doc_kind_for(filename)

    if not config.llm_configured():
        print(
            "decoy: using fallback decoy content for %s - %s"
            % (filename, config.llm_status())
        )
        return fallback_content(target_role), "fallback"

    generate = PROVIDERS.get(config.LLM_PROVIDER)
    if generate is None:
        print(
            "decoy: using fallback decoy content for %s - LLM_PROVIDER=%s is not "
            "wired up (available: %s)"
            % (filename, config.LLM_PROVIDER, ", ".join(sorted(PROVIDERS)))
        )
        return fallback_content(target_role), "fallback"

    try:
        content = generate(filename, target_role, kind)
    except Exception as exc:  # noqa: BLE001 - the demo must not depend on this
        print(
            "decoy: using fallback decoy content for %s - %s generation failed: %s"
            % (filename, config.LLM_PROVIDER, exc)
        )
        return fallback_content(target_role), "fallback"

    print(
        "decoy: generated %s content for %s (target role: %s)"
        % (kind, filename, target_role)
    )
    return content, "llm"


# ---------------------------------------------------------------------------
# Cache-aware entry points
# ---------------------------------------------------------------------------


def build_and_plant(db: DbSession, f: File) -> str:
    """Generate one decoy body and plant a honeytoken at every redaction marker.

    The generator is told to write `<redacted in this build>` wherever a secret
    would go; those markers become the planted tokens. Callers are responsible
    for committing.
    """
    honeytoken.clear_tokens(db, f)
    content, _source = generate_content(f.filename, f.target_role)
    content = honeytoken.plant_tokens(db, f, content)
    f.content = content
    f.decoy_generated_at = utcnow()
    return content


def ensure_decoy_content(db: DbSession, f: File) -> File:
    """Fill a honeyfile's body once, then leave it alone forever.

    This sits on the open/download path, so the common case - content already
    cached - has to stay a single attribute read and nothing more.
    """
    if not f.is_honeyfile or (f.content or "").strip():
        return f

    build_and_plant(db, f)
    db.commit()
    return f


def poisoned_content(f: File) -> str:
    """The body served to a session in decoy mode, for any file it asks for.

    A honeyfile already has a tailored decoy body, so that gets reused.
    Anything else gets a generic fake-dataset template. The stored row is
    never touched - the real file is still there for everyone else.
    """
    if f.is_honeyfile and (f.content or "").strip():
        return f.content

    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        "INTERNAL DATA EXPORT\n"
        "source_file: %s\n"
        "generated: %s\n"
        "record_count: 4\n\n"
        "record_id,account_ref,owner,value,status\n"
        "1,AC-77120-41,M. Fernandes,184300,settled\n"
        "2,AC-77120-88,P. Kulkarni,96750,pending\n"
        "3,AC-77121-02,T. Abraham,231400,settled\n"
        "4,AC-77121-19,V. Joseph,58900,on hold\n\n"
        "note: figures are provisional and subject to reconciliation\n"
    ) % (f.filename, stamp)
