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

# Small, cheap generation: a dozen lines of fake text per honeyfile. These are
# per-provider defaults; which one applies depends on LLM_PROVIDER. Setting
# LLM_MODEL in .env overrides whichever is chosen.
# gemini-3.5-flash-lite answers this in ~3s and is plenty for 15 lines of
# fake text. The 2.5-era models are no longer issued to new keys.
GEMINI_MODEL = "gemini-3.5-flash-lite"
ANTHROPIC_MODEL = "claude-opus-5"

LLM_MODEL = (os.environ.get("LLM_MODEL") or "").strip()
LLM_MAX_TOKENS = 1024
LLM_TIMEOUT_SECONDS = 30.0

# Which provider names are wired up lives with the implementations, in
# detection/decoy_generator.py, so adding one means touching a single file.


def llm_configured() -> bool:
    """True when a provider *and* a key are both present.

    Whether that provider is one this build can actually call is the decoy
    generator's question to answer - it owns the implementations.
    """
    return bool(LLM_API_KEY) and bool(LLM_PROVIDER)


def llm_status() -> str:
    """One line explaining why the LLM path is or is not available."""
    if not LLM_API_KEY and not LLM_PROVIDER:
        return "no LLM_PROVIDER or LLM_API_KEY set in backend/.env"
    if not LLM_API_KEY:
        return "LLM_API_KEY is empty in backend/.env"
    if not LLM_PROVIDER:
        return "LLM_PROVIDER is empty in backend/.env"
    return "provider %s configured" % LLM_PROVIDER
