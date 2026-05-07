# NotebookLM-style RAG Chatbot

A **Retrieval-Augmented Generation (RAG)** chatbot in the spirit of Google NotebookLM. Signed-in users upload their own PDF / text documents; the system chunks, embeds, and stores them in a per-user pgvector index, then answers questions strictly grounded in those documents. Built with FastAPI, PostgreSQL/pgvector, fastembed, and the Groq LLM API.

## Architecture

```
User uploads doc → Parser → Chunker → Embedder → pgvector (scoped by user_id)

User Query → Router (classify) → Retriever (per-user pgvector search) → LLM (Groq) → Evaluator → Response
```

### Three-Layer Pipeline

| Layer | Component | Purpose |
|-------|-----------|---------|
| **Layer 1: Model Router** | Deterministic Rule-Based Classifier | Routes queries using a custom 6-signal complexity scorer heuristics. Simple queries (score < 2) → 8B, Complex queries (score ≥ 2) → 70B. No LLMs used for decision-making. |
| **Layer 2: RAG Retriever** | `PyPDF2` + Recursive Chunking + pgvector | Custom-built extraction and chunking pipeline (no external RAG services). pgvector similarity search retrieves relevant context. |
| **Layer 3: Output Evaluator** | Flagged Validations | Evaluates LLM output post-generation for `no_context`, `refusal` (non-answers), and `conflicting_info` (domain-specific check). Flags trigger a low-confidence UI warning. |

### Note on Chunking Strategy (Assignment Requirement)
Chunks are generated using a manual **Recursive Character Text Splitter**.
- **Chunk Size:** 500 characters
- **Overlap:** 100 characters
- **Strategy:** Sentences are kept whole. If a sentence exceeds the chunk boundary, it breaks cleanly on a space. This size was chosen because the provided PDFs often contain brief, bulleted steps (like setting up SSO) where 500 characters captures the full instructional thought without diluting the embedding vector with unrelated surrounding text, while the 100-character overlap prevents cutting a critical step or code snippet in half.

### Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI + Uvicorn |
| Database | PostgreSQL + pgvector (Supabase) |
| Embeddings | fastembed (`all-MiniLM-L6-v2`, ONNX runtime) |
| Vector Store | pgvector with HNSW index (cosine similarity) |
| LLM | Groq API (Llama 3.1 8B + Llama 3.3 70B) |
| Auth | Firebase Admin SDK (Google Sign-In) |
| Frontend | Vanilla HTML/CSS/JS |

---

## Quick Start

### Prerequisites
- Python 3.10+
- Groq API key ([get one here](https://console.groq.com/keys))
- Supabase project (free, for PostgreSQL + pgvector)
- Firebase project (for Google Sign-In authentication)

### 1. Clone & Install

```bash
git clone <repo-url>
cd AI_System_Assignment

# Create virtual environment
python -m venv venv

# Activate (Windows)
.\venv\Scripts\activate

# Activate (Mac/Linux)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

1. Create a `.env` file in the root directory (see `.env.example` for reference):
```bash
GROQ_API_KEY=your_groq_api_key_here
DATABASE_URL=postgresql+asyncpg://postgres:[YOUR-PASSWORD]@aws-0-us-west-1.pooler.supabase.com:6543/postgres
PORT=8000

# Firebase Config (for frontend auth)
FIREBASE_API_KEY=your_key
FIREBASE_AUTH_DOMAIN=your_project.firebaseapp.com
FIREBASE_PROJECT_ID=your_project_id
FIREBASE_STORAGE_BUCKET=your_project.appspot.com
FIREBASE_MESSAGING_SENDER_ID=your_sender_id
FIREBASE_APP_ID=your_app_id
```

2. Download your Firebase Admin SDK service account credentials and place the file in the root directory exactly named `serviceAccountKey.json`.

### 3. Build the default vector index (first run only)

```bash
python -m backend.rag.embeddings
```

This ingests the 30 PDFs in `docs/` with `user_id = NULL`, which the retriever treats as a **global/default corpus** that's always available to every signed-in user.

### 4. Run the Server

```bash
python -m backend.main
```

The server runs a lightweight migration on startup that adds the `user_id` column to `document_chunks` if needed — no manual SQL required.

Open **http://localhost:8000** in your browser. Sign in with Google to chat against the default ClearPath corpus, and click **+ Upload** in the sidebar to add your own PDF / TXT / MD on top — uploaded documents are scoped to your account and merged into retrieval alongside the default corpus.

---

## API Endpoints

### `POST /upload` (multipart/form-data, requires Bearer token)

Upload a PDF / TXT / MD. The file is parsed, chunked (500 chars / 100 overlap), embedded, and indexed under the authenticated user's `user_id`.

**Form field:** `file` — the document (max 15 MB)

**Response:**
```json
{ "document": "policy.pdf", "chunks_indexed": 42, "pages": 11 }
```

### `GET /documents` (requires Bearer token)
Returns the current user's uploaded documents and chunk counts.

### `DELETE /documents/{document_name}` (requires Bearer token)
Removes all chunks for that document for the current user.

### `POST /query`

**Request:**
```json
{
    "question": "What is the Pro plan price?",
    "conversation_id": "optional-id"
}
```

**Response:**
```json
{
    "answer": "The Pro plan costs $49/month...",
    "metadata": {
        "model_used": "llama-3.1-8b-instant",
        "classification": "simple",
        "tokens": { "input": 716, "output": 63 },
        "latency_ms": 340,
        "chunks_retrieved": 5,
        "evaluator_flags": []
    },
    "sources": [
        { "document": "14_Pricing_Sheet_2024.pdf", "page": 1, "relevance_score": 0.72 }
    ],
    "conversation_id": "conv_abc123"
}
```

### `GET /health`
Returns `{ "status": "ok" }`.

---

## Project Structure

```
AI_System_Assignment/
├── backend/
│   ├── main.py                 # FastAPI app, /query and /query/stream endpoints
│   ├── config.py               # Centralized configuration
│   ├── db/
│   │   ├── database.py         # SQLAlchemy async engine + session factory
│   │   ├── models.py           # User, Conversation, Message, DocumentChunk (pgvector)
│   │   └── crud.py             # Database CRUD operations
│   ├── rag/
│   │   ├── pdf_parser.py       # PDF text extraction (PyPDF2)
│   │   ├── chunker.py          # Recursive text chunking (500 chars, 100 overlap)
│   │   ├── embeddings.py       # Embedding generation + pgvector insertion (fastembed)
│   │   └── retriever.py        # Cosine similarity search + context builder
│   ├── router/
│   │   └── classifier.py       # Deterministic rule-based query classifier (6 signals)
│   ├── llm/
│   │   └── groq_client.py      # Groq API wrapper with streaming + token tracking
│   ├── evaluator/
│   │   └── evaluator.py        # Output evaluation (3 flags including custom check)
│   └── models/
│       └── schemas.py          # Pydantic request/response models
├── frontend/
│   ├── index.html              # Chat interface with Firebase Google Sign-In
│   ├── style.css               # Dark theme styling
│   └── script.js               # Chat logic, streaming, clickable debug panel
├── docs/                       # 30 source PDFs
├── .env.example                # Environment variable template
├── .python-version             # Pinned to 3.10.0 for Render deployment
├── requirements.txt
├── eval_harness.py             # Automated evaluation test suite
├── written_answers.md
├── bonus_challenges.md
└── README.md
```

---

## Model Routing Strategy

The router relies entirely on a deterministic, rule-based classifier. Calling an LLM simply to classify a query is too expensive and slow for the first hop of a support bot. The router instead scores the input on 6 signals (greetings, query length, complex keywords, multi-part questions, complaints, and subordinate clauses). See `written_answers.md` Q1 for the exact scoring breakdown.

| Classification | Model | Trigger |
|---------------|-------|---------|
| **Simple** (Score < 2) | `llama-3.1-8b-instant` | Greetings, short factual queries, single-keyword lookups |
| **Complex** (Score ≥ 2)| `llama-3.3-70b-versatile` | Multi-part questions, comparisons, troubleshooting, long queries |

---

## Evaluator Flags

| Flag | Triggers When |
|------|--------------|
| `no_context` | LLM answered but 0 relevant chunks were retrieved |
| `refusal` | LLM response contains hedging phrases ("I don't have", "not enough information") |
| `conflicting_info` | Response references contradicting sources or uses conflict language |

When any flag is raised, the response is prefixed with: *"⚠️ Low confidence — please verify with support."*

---

## Testing

```bash
# Test individual layers
python test_retriever.py    # Retriever + context + LLM
python test_router.py       # Query classifier (10/10)
python test_evaluator.py    # Evaluator flags (5/5)
python test_api.py          # API endpoint (5/5)

# Full E2E suite (11 queries, 5 categories)
python test_e2e.py
```

---

## Known Issues

1. **Greeting false positives**: Short messages starting with "Hi/Hello" AND containing a question (≤5 words total) may be routed as greetings. Messages >5 words go through the full RAG pipeline.
2. **Poisoned document**: `22_Q4_2023_Team_Retrospective.pdf` contains prompt injection text. The system prompt provides partial defense, but sophisticated injection may bypass it.
3. **Cross-document queries**: Questions spanning multiple topics (e.g., "keyboard shortcuts for mobile app") may retrieve chunks biased toward one topic.
