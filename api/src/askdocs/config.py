import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres@localhost:5433/askdocs"
)

# Any OpenAI-compatible chat API. Defaults to a local Ollama model.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b")

# Embeddings. "local": bge-small on CPU, no API calls, needs ~1 CPU and ~300 MB.
# "gemini": Gemini embedding API, nothing loaded in memory, runs on tiny free hosts.
EMBED_PROVIDER = os.environ.get("EMBED_PROVIDER", "local")
_GEMINI = EMBED_PROVIDER == "gemini"
EMBED_MODEL = os.environ.get("EMBED_MODEL", "gemini-embedding-2" if _GEMINI else "BAAI/bge-small-en-v1.5")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "768" if _GEMINI else "384"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", LLM_API_KEY)
# ONNX threads for local models. On a fractional CPU (e.g. 0.1), 1 thread avoids contention.
MODEL_THREADS = int(os.environ["MODEL_THREADS"]) if os.environ.get("MODEL_THREADS") else None

# Reranking. "local": MiniLM cross-encoder on CPU. "none": skip it and give the LLM more
# sources to choose from (for hosts too small to run the model).
RERANK = os.environ.get("RERANK", "local")
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"

PRODUCT_NAME = os.environ.get("PRODUCT_NAME", "Supabase")
# Sources scoring below these are unrelated; if none pass, we hand off without calling the LLM.
MIN_RERANK_SCORE = float(os.environ.get("MIN_RERANK_SCORE", "-6.0"))  # with RERANK=local
MIN_SIMILARITY = float(os.environ.get("MIN_SIMILARITY", "0.0"))  # cosine, with RERANK=none
# Source text sent to the LLM. 12k chars is ~3k tokens; use 7000 for a local 4k-token model.
CONTEXT_CHARS = int(os.environ.get("CONTEXT_CHARS", "12000"))
# Questions matching this go straight to a human: money and legal matters, where a
# docs-based answer that is slightly off costs more than a short wait.
ESCALATE_PATTERN = os.environ.get(
    "ESCALATE_PATTERN",
    r"\brefund|\bchargeback|money back|charged twice|double.charged|\bdispute\b|\blawsuit|\blawyer|legal action",
)

SITEMAP_URL = os.environ.get("SITEMAP_URL", "https://supabase.com/docs/sitemap.xml")
URL_PREFIX = os.environ.get("URL_PREFIX", "https://supabase.com/docs/guides/")

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
PAGES_DIR = DATA_DIR / "pages"
