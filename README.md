# DocChat — NotebookLM-style RAG Chatbot

A **Retrieval-Augmented Generation** chatbot in the spirit of Google NotebookLM. Signed-in users upload their own PDF / text documents; the system parses, chunks, embeds, and stores them in a per-user pgvector index, then answers questions strictly grounded in those documents.

Built with FastAPI, PostgreSQL/pgvector, fastembed, Groq LLM API, and Firebase Auth.

## Architecture

```
Upload:  PDF/TXT/MD → Parser → Chunker → Embedder → pgvector (scoped by user_id)

Query:   Question → Router (classify) → Retriever (per-user pgvector) → LLM (Groq) → Evaluator → Response
```

### Three-layer pipeline

| Layer | Component | Purpose |
|---|---|---|
| **Router** | Deterministic 6-signal classifier | Routes to `llama-3.1-8b-instant` (simple) or `llama-3.3-70b-versatile` (complex). No LLM calls used to make the routing decision. |
| **Retriever** | PyPDF2 + recursive chunking + pgvector | Custom extraction & chunking. Cosine similarity over a HNSW index, filtered by `user_id`. |
| **Evaluator** | Post-generation flags | `no_context`, `refusal`, `conflicting_info`. Triggers a low-confidence UI warning. |

### Chunking strategy
Recursive character splitter — split on paragraphs, then sentences, then words.
- **Chunk size:** 500 characters
- **Overlap:** 100 characters

### Tech Stack

| Component | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Database | PostgreSQL + pgvector (Supabase) |
| Embeddings | fastembed (`all-MiniLM-L6-v2`, ONNX) |
| Vector store | pgvector with HNSW index (cosine similarity) |
| LLM | Groq API (Llama 3.1 8B + Llama 3.3 70B) |
| Auth | Firebase Admin SDK (Google Sign-In) |
| Frontend | Vanilla HTML/CSS/JS |

---

## Quick Start

### Prerequisites
- Python 3.10+
- Groq API key — https://console.groq.com/keys
- Supabase project (free) for PostgreSQL + pgvector
- Firebase project for Google Sign-In

### 1. Install

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Configure environment

Create `.env` in the project root:

```
GROQ_API_KEY=your_groq_api_key
DATABASE_URL=postgresql+asyncpg://postgres:[YOUR-PASSWORD]@<host>:6543/postgres
PORT=8000

FIREBASE_API_KEY=...
FIREBASE_AUTH_DOMAIN=...
FIREBASE_PROJECT_ID=...
FIREBASE_STORAGE_BUCKET=...
FIREBASE_MESSAGING_SENDER_ID=...
FIREBASE_APP_ID=...
```

Place your Firebase Admin SDK service-account JSON at the project root as `serviceAccountKey.json`.

### 3. Run

```powershell
python -m backend.main
```

The server runs a lightweight migration on startup (adds `user_id` to `document_chunks` if missing). Open **http://localhost:8000**, sign in with Google, click **+ Upload** in the sidebar to add a PDF / TXT / MD, and start asking questions.

---

## API Endpoints

All endpoints except `/health` and `/api/firebase-config` require a Firebase ID token in `Authorization: Bearer <token>`.

### `POST /upload` — `multipart/form-data`
Parse, chunk, embed, and index a document under the current user.
- **Form field:** `file` (PDF / TXT / MD, max 15 MB)
- **Response:** `{ "document": "cv.pdf", "chunks_indexed": 42, "pages": 11 }`

### `GET /documents`
List the current user's uploaded documents and chunk counts.

### `DELETE /documents/{document_name}`
Remove all chunks for that document, for the current user only.

### `POST /query` and `POST /query/stream`
Ask a grounded question against the user's documents.

```json
{ "question": "What projects are listed in my CV?", "conversation_id": null }
```

Streaming endpoint emits Server-Sent Events: a `metadata` event, then `token` events, then a `done` event.

### `GET /conversations` / `GET /conversations/{id}` / `PUT` / `DELETE`
Manage chat history (per user).

### `GET /health`
Returns `{ "status": "ok" }`.

---

## Project structure

```
RAG_Chatbot_AI/
├── backend/
│   ├── main.py                  # FastAPI app: /upload, /query, /query/stream, /documents, /conversations
│   ├── config.py                # Centralized configuration
│   ├── auth/                    # Firebase Admin SDK token verification
│   ├── db/
│   │   ├── database.py          # SQLAlchemy async engine + lightweight migrations
│   │   ├── models.py            # User, Conversation, Message, DocumentChunk (pgvector + user_id)
│   │   └── crud.py              # CRUD helpers
│   ├── rag/
│   │   ├── pdf_parser.py        # PyPDF2 extraction (file path or raw bytes)
│   │   ├── chunker.py           # Recursive char/sentence/word splitter
│   │   ├── embeddings.py        # fastembed → pgvector insertion
│   │   └── retriever.py         # Cosine similarity search, scoped by user_id
│   ├── router/classifier.py     # Deterministic 6-signal router
│   ├── llm/groq_client.py       # Groq chat completion (sync + streaming)
│   ├── evaluator/evaluator.py   # no_context / refusal / conflicting_info flags
│   └── models/schemas.py        # Pydantic request/response models
├── frontend/
│   ├── index.html               # Chat UI + Firebase Google Sign-In + upload widget
│   ├── style.css                # Theme
│   └── script.js                # Auth, conversations, uploads, streaming chat
├── alembic/                     # DB migration tooling (optional)
├── requirements.txt
├── render.yaml                  # Render deployment config
└── README.md
```

---

## Model routing

Deterministic, rule-based scoring on 6 signals (greetings, query length, complex keywords, multi-part questions, complaints, subordinate clauses).

| Classification | Model | Trigger |
|---|---|---|
| **Simple** (score < 2) | `llama-3.1-8b-instant` | Greetings, short factual queries, single-keyword lookups |
| **Complex** (score ≥ 2) | `llama-3.3-70b-versatile` | Multi-part questions, comparisons, troubleshooting, long queries |

---

## Evaluator flags

| Flag | Triggers When |
|---|---|
| `no_context` | 0 relevant chunks were retrieved (or all chunk scores < 0.4) |
| `refusal` | LLM response contains hedging phrases despite relevant context |
| `conflicting_info` | Response references contradicting sources or uses conflict language |

When any flag is raised, the response is prefixed with a `⚠️ Low confidence — …` warning.

---

## Optional: clear leftover default-corpus chunks

If your database has leftover chunks from a previous run with `user_id IS NULL`, run this once in your Supabase SQL editor (or via psql) to remove them:

```sql
DELETE FROM document_chunks WHERE user_id IS NULL;
```

After that, the only chunks in the index are the ones each signed-in user has uploaded for themselves.
