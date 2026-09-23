"""Single configuration load point for the backend.

Environment variables are read from `backend/.env` (via python-dotenv) and
nowhere else. No key value is ever hardcoded here or anywhere in the repo: if
`LLM_API_KEY` is empty the decoy generator uses its pre-written fallback
content and says so on the terminal, and every other feature works unchanged.
"""
import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")

# override=False: a variable already exported in the shell wins over the file.
load_dotenv(ENV_PATH, override=False)

LLM_PROVIDER = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
LLM_API_KEY = (os.environ.get("LLM_API_KEY") or "").strip()

# Providers this build knows how to call. Anything else falls back.
SUPPORTED_PROVIDERS = ("anthropic",)

# Small, cheap generation: a dozen lines of fake text per honeyfile.
LLM_MODEL = "claude-opus-5"
LLM_MAX_TOKENS = 1024
LLM_TIMEOUT_SECONDS = 30.0


def llm_configured() -> bool:
    """True only when a supported provider *and* a key are both present."""
    return bool(LLM_API_KEY) and LLM_PROVIDER in SUPPORTED_PROVIDERS


def llm_status() -> str:
    """One line explaining why the LLM path is or is not available."""
    if not LLM_API_KEY and not LLM_PROVIDER:
        return "no LLM_PROVIDER or LLM_API_KEY set in backend/.env"
    if not LLM_API_KEY:
        return "LLM_API_KEY is empty in backend/.env"
    if not LLM_PROVIDER:
        return "LLM_PROVIDER is empty in backend/.env"
    if LLM_PROVIDER not in SUPPORTED_PROVIDERS:
        return "LLM_PROVIDER=%s is not supported (supported: %s)" % (
            LLM_PROVIDER,
            ", ".join(SUPPORTED_PROVIDERS),
        )
    return "provider %s configured" % LLM_PROVIDER
