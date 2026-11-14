"""Central configuration. Everything is read from environment variables so the
same code runs locally, in tests, and on Streamlit Community Cloud."""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

# SQLite file. Override with KOTLER_DB_PATH (tests point this at a temp file).
DB_PATH = Path(os.environ.get("KOTLER_DB_PATH", DATA_DIR / "kotler.db"))

# Brand we simulate. Phase 2+ prompts use this.
BRAND_NAME = os.environ.get("KOTLER_BRAND_NAME", "Glow & Co.")

# Shipping rule used by the generator and (later) the agents.
FREE_SHIPPING_THRESHOLD = 499.0
SHIPPING_FEE = 49.0

# --- LLM ---------------------------------------------------------------------
# Provider "gemini" = Google's native Gemini API (works with both "AIza..." keys and the newer
# "AQ..." auth keys). Provider "openai" = any OpenAI-compatible endpoint, set by the URL below:
#   Gemini : https://generativelanguage.googleapis.com/v1beta/openai/
#   Ollama : http://localhost:11434/v1/            (model e.g. "qwen2.5:7b")
#   Groq   : https://api.groq.com/openai/v1/
LLM_PROVIDER = os.environ.get("KOTLER_LLM_PROVIDER", "gemini")
LLM_BASE_URL = os.environ.get("KOTLER_LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
LLM_MODEL = os.environ.get("KOTLER_LLM_MODEL", "gemini-3.5-flash")  # pinned: "latest" aliases change under you
# Tried in order when the main model is overloaded (503) or rate-limited (429) after retries.
LLM_FALLBACK_MODELS = [m for m in os.environ.get("KOTLER_LLM_FALLBACK_MODELS", "gemini-3.1-flash-lite").split(",") if m]


def llm_api_key() -> str | None:
    """API key from the environment. Locally, put it in .streamlit/secrets.toml
    (app.py copies it into the environment) or export GEMINI_API_KEY."""
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("KOTLER_LLM_API_KEY")
