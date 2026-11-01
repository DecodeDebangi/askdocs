import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres@localhost:5433/askdocs"
)

# Local, free, 384-d. Runs on CPU in a few ms per query.
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"

# Any OpenAI-compatible chat API. Defaults to a local Ollama model.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b")

PRODUCT_NAME = os.environ.get("PRODUCT_NAME", "Supabase")
# Below this reranker score the best source is unrelated, so we hand off instead of answering.
MIN_RERANK_SCORE = float(os.environ.get("MIN_RERANK_SCORE", "-6.0"))

SITEMAP_URL = os.environ.get("SITEMAP_URL", "https://supabase.com/docs/sitemap.xml")
URL_PREFIX = os.environ.get("URL_PREFIX", "https://supabase.com/docs/guides/")

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
PAGES_DIR = DATA_DIR / "pages"
