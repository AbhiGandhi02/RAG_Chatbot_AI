import os
from dotenv import load_dotenv

load_dotenv()

# Groq API
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Server
PORT = int(os.getenv("PORT", 8000))

# LLM Models
MODEL_SIMPLE = "llama-3.1-8b-instant"
MODEL_COMPLEX = "llama-3.3-70b-versatile"

# RAG Configuration
CHUNK_SIZE = 500          # Target chunk size in characters
CHUNK_OVERLAP = 100       # Overlap between chunks in characters
TOP_K = 8                 # Number of chunks to retrieve
SIMILARITY_THRESHOLD = 0.15  # Minimum similarity score; intentionally permissive so
                              # short structured docs (CVs, resumes, single-pagers) where
                              # headers split from content still surface useful chunks.

# Paths
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CHUNKS_FILE = os.path.join(DATA_DIR, "chunks.json")
FAISS_INDEX_PATH = os.path.join(DATA_DIR, "faiss_index")

# Embedding Model
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

# Corrective RAG (CRAG)
#   When enabled, retrieved chunks are graded for relevance by a fast LLM,
#   and the pipeline falls back to a web search (with a rewritten query)
#   when local retrieval is insufficient.
CRAG_ENABLED = os.getenv("CRAG_ENABLED", "true").lower() in ("1", "true", "yes", "on")
CRAG_GRADER_MODEL = "llama-3.1-8b-instant"
CRAG_WEB_MAX_RESULTS = 5
