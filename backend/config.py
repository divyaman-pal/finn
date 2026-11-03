"""Static configuration: paths, keys, and the demo portfolio."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("FINN_DATA_DIR", ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "finn.db"
SEED_DB = ROOT / "seed" / "finn_seed.db"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Mock book: symbol -> portfolio weight (%). Mix of large, mid and small caps across sectors.
PORTFOLIO: dict[str, float] = {
    "RELIANCE": 10.0,
    "HDFCBANK": 10.0,
    "INFY": 8.0,
    "ITC": 7.0,
    "LT": 7.0,
    "SUNPHARMA": 6.0,
    "BAJFINANCE": 6.0,
    "MARUTI": 6.0,
    "TRENT": 6.0,
    "ETERNAL": 5.0,
    "PERSISTENT": 5.0,
    "CDSL": 5.0,
    "IRCTC": 4.0,
    "KPITTECH": 4.0,
    "DEEPAKNTR": 3.0,
    "CAMPUS": 2.0,
}

# Companies outside the book, used to demo on-demand research.
RESEARCH_DEMO = ["ASIANPAINT", "HAL", "PAYTM", "IDEA"]
