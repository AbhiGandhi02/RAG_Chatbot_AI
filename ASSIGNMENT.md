# Assignment 03 — Google NotebookLM RAG
**Student:** Abhi Gandhi | **Roll No:** 2024eb02485

| | Link |
|---|---|
| **GitHub Repository** | https://github.com/AbhiGandhi02/RAG_Chatbot_AI_Systems |
| **Live Project** | *(add your Render URL here)* |

---

## What Was Built

A full **Retrieval-Augmented Generation (RAG)** chatbot modelled after Google NotebookLM. Users sign in with Google, upload their own PDF / TXT / MD documents, and have a grounded conversation with them. The system retrieves relevant chunks from the uploaded document and passes only those chunks to the LLM — the LLM is explicitly instructed not to answer from memory.

The app also includes **Corrective RAG (CRAG)** — an extension where the system grades its own retrieved chunks for relevance, and falls back to a web search if local retrieval is insufficient. This was implemented beyond the base requirements.

---

## Marking Scheme — 10 Points

### 1. GitHub Repository — 2 pts

- Public repo: `github.com/AbhiGandhi02/RAG_Chatbot_AI_Systems`
- Contains full source code, `requirements.txt`, `render.yaml`, `.env.example`, and this documentation
- `README.md` covers architecture, setup, API reference, and project structure

---

### 2. Live Project — 2 pts

- Deployed on **Render** using `render.yaml`
- No local setup needed — sign in with Google and start uploading
- Live URL: *(add your Render URL here)*

---

### 3. RAG Pipeline — 3 pts

The full pipeline is implemented end-to-end across four stages:

#### Stage 1 — Ingestion & Parsing (`backend/rag/pdf_parser.py`)
- Accepts PDF, TXT, and MD files up to 15 MB
- PDFs parsed with **PyPDF2** page-by-page, preserving page numbers for source citations
- Plain text files treated as a single page

#### Stage 2 — Chunking (`backend/rag/chunker.py`)
**Strategy: Recursive Character Splitter**

The document text is split in three levels of priority:
1. Paragraph breaks (`\n\n`) — preserve natural document structure
2. Sentence boundaries (`. `) — if a paragraph is still too long
3. Word boundaries — last resort for unbreakable blocks

| Parameter | Value |
|-----------|-------|
| Chunk size | 500 characters |
| Overlap | 100 characters |

The overlap ensures that context at chunk boundaries is not lost — a sentence split across two chunks will still appear in both.

#### Stage 3 — Embedding & Storage (`backend/rag/embeddings.py`)
- Chunks embedded using **fastembed** (`sentence-transformers/all-MiniLM-L6-v2`, ONNX runtime)
- Model runs locally — no API calls for embedding, no cost, no latency overhead
- Embeddings: **384-dimensional** float vectors
- Stored in **PostgreSQL + pgvector** (Supabase) with an **HNSW index** (cosine similarity, `m=16, ef_construction=64`)
- Each chunk is tagged with `user_id` — users can only retrieve their own documents

#### Stage 4 — Retrieval & Generation (`backend/rag/retriever.py`, `backend/llm/groq_client.py`)
- Query is embedded with the same fastembed model
- pgvector performs cosine similarity search: top-8 chunks returned, filtered by `user_id`
- Retrieved chunks are injected into the LLM prompt as `<context>` blocks
- **Groq API** (Llama 3.1 8B or 3.3 70B) generates the final answer

**Query routing** (no LLM cost): a deterministic 6-signal scorer decides which model to use:
- Simple queries (score < 2) → `llama-3.1-8b-instant` (faster, cheaper)
- Complex queries (score ≥ 2) → `llama-3.3-70b-versatile` (more capable)

---

### 4. Answer Quality — 2 pts

The system is designed at multiple layers to prevent hallucination:

**System prompt** (`backend/llm/groq_client.py`):
> "Answer EXCLUSIVELY from the provided `<context>` blocks. Do not invent facts, dates, names, numbers, or details that aren't present in the context. If the context does not contain the answer, say so plainly."

**Post-generation Evaluator** (`backend/evaluator/evaluator.py`):
After the LLM responds, the evaluator checks for three reliability issues:

| Flag | What it detects |
|------|----------------|
| `no_context` | No relevant chunks retrieved, or all chunk similarity scores below threshold |
| `refusal` | LLM hedged or said it doesn't know despite having context |
| `conflicting_info` | Answer references contradicting sources |

If any flag is raised, the response is prefixed with `⚠️ Low confidence — …` in the UI — the user is warned rather than silently served a bad answer.

**Corrective RAG (CRAG)** — bonus (`backend/rag/corrective_rag.py`):
An additional pre-generation reliability layer. Retrieved chunks are graded (`yes / partial / no`) by a fast LLM call. Based on grades:
- ≥ 2 `yes` → use local retrieval
- 1 `yes` or ≥ 2 `partial` → mix local + web search results
- Otherwise → fall back to web search (DuckDuckGo) with a rewritten query

This means even if the user's document doesn't fully cover a topic, the system supplements it with live web results rather than hallucinating.

---

### 5. Code Quality & Documentation — 1 pt

**Structure:**
```
backend/
├── main.py          # FastAPI app — all endpoints
├── config.py        # Single source of truth for all config values
├── auth/            # Firebase token verification
├── db/              # SQLAlchemy models, CRUD, async migrations
├── rag/             # Parser, chunker, embedder, retriever, CRAG
├── llm/             # Groq client (sync + streaming)
├── evaluator/       # Post-generation quality flags
└── models/          # Pydantic schemas
frontend/
├── index.html       # Chat UI
├── script.js        # SSE streaming, auth, uploads
└── style.css
```

**Key design decisions documented:**
- Similarity threshold set to `0.15` (permissive) because short structured docs like CVs max out around `0.35–0.45` — a stricter threshold would suppress valid results
- CRAG grader prompt returns JSON only, with `temperature=0` and `response_format: json_object` for reliable structured output
- Conversation history capped at last 5 turns, assistant messages truncated to 500 chars — prevents context window blowout on long conversations
- Runtime SQL migrations (`database.py`) instead of Alembic — simpler for a single-schema app

---

## Tech Stack Summary

| Component | Technology | Reason |
|-----------|-----------|--------|
| Backend | FastAPI + Uvicorn | Async-first, native SSE streaming support |
| Vector DB | PostgreSQL + pgvector (Supabase) | No separate vector DB needed — HNSW index in Postgres |
| Embeddings | fastembed (ONNX) | Runs locally, zero API cost, 384-dim vectors |
| LLM | Groq API — Llama 3.1 8B & 3.3 70B | Fastest open-model inference available |
| Auth | Firebase + Google Sign-In | Managed auth, per-user data isolation |
| Web Fallback | DuckDuckGo Search | Free, no API key needed |
| Deployment | Render | `render.yaml` config, zero manual setup |

---

## Design Decisions & Trade-offs

### Web Search Fallback — Deliberately Disabled

CRAG supports a **DuckDuckGo web search fallback** (`duckduckgo-search` library) for cases where local retrieval is insufficient. It was evaluated and intentionally removed from the deployment.

**How it works:** When the CRAG grader rates retrieved chunks as poor (`action = "search"` or `"mix"`), it rewrites the query and fetches live web snippets via DuckDuckGo, supplementing or replacing local chunks before generation.

**Why it was removed:**
- This is a *document chatbot* — the core contract is that answers come from the user's uploaded file, not the internet
- DuckDuckGo results are non-deterministic: the same question returns different snippets on different calls, producing inconsistent answers
- When the document doesn't cover a topic, the correct behaviour is an honest gap (`"I couldn't find that in the documents you've provided."`) — not a silently web-sourced answer the user can't verify
- Leaving it enabled caused the deployed version to give different answers to the same question across sessions

**What CRAG still does without it:** The grader still runs — chunks are still graded `yes / partial / no`, bad chunks are filtered out, and the LLM only sees the chunks that passed grading. The web fallback step is simply skipped gracefully (logged as a warning, no crash).
