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
