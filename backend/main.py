"""
DocChat — NotebookLM-style RAG FastAPI application.

Main entry point. Serves the chat + upload endpoints and the frontend UI.
Orchestrates: Router → Retriever (per-user + default corpus) → LLM → Evaluator → Response
"""

import logging
import json
import os
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, delete

from backend.db.database import get_db, AsyncSessionLocal, run_lightweight_migrations
from backend.db.models import User, DocumentChunk
from backend.db import crud
from backend.auth.dependencies import get_current_user

from backend.models.schemas import (
    QueryRequest, QueryResponse, Metadata, Source, TokenUsage, ConversationUpdate,
    UploadResponse, UserDocument,
)
from backend.router.classifier import classify_query, create_routing_log
from backend.rag.retriever import Retriever
from backend.rag.pdf_parser import extract_text_from_bytes, extract_text_from_plain
from backend.rag.chunker import chunk_pages
from backend.rag.embeddings import EmbeddingService
from backend.llm.groq_client import get_groq_client
from backend.evaluator.evaluator import evaluate_response, get_warning_message
from backend.config import PORT, CHUNK_SIZE, CHUNK_OVERLAP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# Global instances (lazy initialized)
retriever = None
groq_client = None
embedding_service = None


@asynccontextmanager
async def lifespan(app):
    """Initialize retriever, embedder, LLM client and run migrations on startup."""
    global retriever, groq_client, embedding_service

    logger.info("Initializing RAG Chatbot...")

    try:
        await run_lightweight_migrations()
        logger.info("Database migrations applied.")
    except Exception as e:
        logger.error(f"Migration failed (continuing): {e}")

    try:
        retriever = Retriever()
        logger.info("Retriever initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize retriever: {e}")
        raise

    try:
        embedding_service = EmbeddingService()
        logger.info("Embedding service initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize embedding service: {e}")
        raise

    try:
        groq_client = get_groq_client()
        logger.info("Groq client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Groq client: {e}")
        raise

    logger.info("RAG Chatbot ready!")
    yield


app = FastAPI(
    title="DocChat — NotebookLM-style RAG",
    description="Upload your own documents and chat with them; falls back to a built-in default corpus.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Conversation History Helpers ---

def generate_conversation_title(question: str) -> str:
    """Generate a short title based on the user's first question using Groq."""
    prompt = f"Write a short, concise 3 to 5 word title for a conversation that starts with this question:\n\n{question}\n\nDo not include quotes or extra text. Just the title."
    try:
        if groq_client:
            result = groq_client.generate(prompt, "", "llama-3.1-8b-instant")
            # Clear markdown bold asterisks and quotes
            return result["answer"].replace('*', '').strip(' "''')
    except Exception as e:
        logger.error(f"Title generation failed: {e}")
    return question[:30] + "..." if len(question) > 30 else question


async def get_or_create_conversation(db: AsyncSession, user: User, conversation_id: str = None, question: str = None):
    if conversation_id:
        conv = await crud.get_conversation(db, conversation_id, user.id)
        if not conv:
            raise HTTPException(status_code=403, detail="Conversation not found or access denied.")
        return conv
        
    title = generate_conversation_title(question) if question else "New Chat"
    return await crud.create_conversation(db, user.id, title=title)


async def get_formatted_history(db: AsyncSession, conversation_id: str, max_turns: int = 5):
    """Fetch history from DB and format for Groq LLM (list of dicts)."""
    messages = await crud.get_conversation_messages(db, conversation_id)
    # Get last N messages based on turns (each turn = 2 messages: user + assistant)
    recent_messages = messages[-(max_turns * 2):] if len(messages) > max_turns * 2 else messages
    
    history = []
    for msg in recent_messages:
        # We truncated assistant answers to 200 chars in memory before, do same here for context
        content = msg.content
        if msg.role == "assistant" and len(content) > 500:
            content = content[:500] + "..."
            
        history.append({
            "role": msg.role,
            "content": content
        })
    return history


# --- Main Endpoints ---

@app.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Main chatbot endpoint."""
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    
    question = request.question.strip()
    
    # Get or create DB Conversation
    conv = await get_or_create_conversation(db, current_user, request.conversation_id, question=question)
    
    routing = classify_query(question)
    classification = routing["classification"]
    model_used = routing["model_used"]
    
    is_greeting = ("greeting_detected" in routing.get("signals", []) and len(question.split()) <= 5)
    
    history = await get_formatted_history(db, conv.id)
    
    if is_greeting:
        retrieved_chunks = []
        chunks_retrieved = 0
        context = "The user is greeting you. Respond warmly."
        llm_result = groq_client.generate(question, context, model_used, conversation_history=history)
        evaluator_flags = []
    else:
        retrieved_chunks = await retriever.retrieve_async(question, user_id=current_user.id)
        chunks_retrieved = len(retrieved_chunks)
        context = retriever.build_context(retrieved_chunks)
        llm_result = groq_client.generate(question, context, model_used, conversation_history=history)
        evaluator_flags = evaluate_response(llm_result["answer"], chunks_retrieved, retrieved_chunks)
    
    answer = llm_result["answer"]
    
    warning = get_warning_message(evaluator_flags)
    if warning:
        answer = f"{warning}\n\n{answer}"
    
    msg_metadata = {
        "model_used": model_used,
        "classification": classification,
        "tokens": {"input": llm_result["tokens_input"], "output": llm_result["tokens_output"]},
        "latency_ms": llm_result["latency_ms"],
        "chunks_retrieved": chunks_retrieved,
        "evaluator_flags": evaluator_flags,
        "sources": [{"document": c["document"], "page": c["page"], "relevance_score": c.get("relevance_score")} for c in retrieved_chunks]
    }
    
    # Save the new turn to the DB
    await crud.add_message(db, conv.id, "user", question)
    await crud.add_message(db, conv.id, "assistant", answer, metadata=msg_metadata)
    
    sources = [Source(document=c["document"], page=c["page"], relevance_score=c.get("relevance_score")) for c in retrieved_chunks]
    
    return QueryResponse(
        answer=answer,
        metadata=Metadata(
            model_used=model_used,
            classification=classification,
            tokens=TokenUsage(input=llm_result["tokens_input"], output=llm_result["tokens_output"]),
            latency_ms=llm_result["latency_ms"],
            chunks_retrieved=chunks_retrieved,
            evaluator_flags=evaluator_flags
        ),
        sources=sources,
        conversation_id=conv.id
    )


@app.post("/query/stream")
async def query_stream(
    request: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Streaming endpoint — returns tokens via Server-Sent Events (SSE)."""
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    
    question = request.question.strip()
    
    conv = await get_or_create_conversation(db, current_user, request.conversation_id, question=question)
    
    routing = classify_query(question)
    classification = routing["classification"]
    model_used = routing["model_used"]
    
    is_greeting = ("greeting_detected" in routing.get("signals", []) and len(question.split()) <= 5)
    
    history = await get_formatted_history(db, conv.id)
    
    if is_greeting:
        retrieved_chunks = []
        context = "The user is greeting you. Respond warmly."
    else:
        retrieved_chunks = await retriever.retrieve_async(question, user_id=current_user.id)
        context = retriever.build_context(retrieved_chunks)
    
    sources = [{"document": c["document"], "page": c["page"], "relevance_score": c.get("relevance_score")} for c in retrieved_chunks]
    
    async def event_generator():
        full_answer = ""
        meta_event = {
            "type": "metadata",
            "classification": classification,
            "model_used": model_used,
            "chunks_retrieved": len(retrieved_chunks),
            "sources": sources,
            "conversation_id": conv.id
        }
        yield f"data: {json.dumps(meta_event)}\n\n"
        
        for chunk in groq_client.generate_stream(question, context, model_used, conversation_history=history):
            if chunk["type"] == "token":
                full_answer += chunk["content"]
                yield f"data: {json.dumps(chunk)}\n\n"
            elif chunk["type"] == "done":
                flags = [] if is_greeting else evaluate_response(full_answer, len(retrieved_chunks), retrieved_chunks)
                
                msg_metadata = {
                    "model_used": model_used,
                    "classification": classification,
                    "tokens": {
                        "input": chunk["tokens_input"],
                        "output": chunk["tokens_output"]
                    },
                    "latency_ms": chunk["latency_ms"],
                    "chunks_retrieved": len(retrieved_chunks),
                    "evaluator_flags": flags,
                    "sources": sources
                }
                # Save to DB inside the generator using its own session context
                async with AsyncSessionLocal() as stream_db:
                    await crud.add_message(stream_db, conv.id, "user", question)
                    await crud.add_message(stream_db, conv.id, "assistant", full_answer, metadata=msg_metadata)
                    await stream_db.commit()
                
                done_event = {
                    "type": "done",
                    "tokens_input": chunk["tokens_input"],
                    "tokens_output": chunk["tokens_output"],
                    "latency_ms": chunk["latency_ms"],
                    "evaluator_flags": flags
                }
                yield f"data: {json.dumps(done_event)}\n\n"
            elif chunk["type"] == "error":
                yield f"data: {json.dumps(chunk)}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- Config Endpoint ---

@app.get("/api/firebase-config")
async def get_firebase_config():
    """Return public Firebase variables from the .env so they aren't hardcoded in JS."""
    return {
        "apiKey": os.getenv("FIREBASE_API_KEY"),
        "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN"),
        "projectId": os.getenv("FIREBASE_PROJECT_ID"),
        "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET"),
        "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID"),
        "appId": os.getenv("FIREBASE_APP_ID"),
        "measurementId": os.getenv("FIREBASE_MEASUREMENT_ID")
    }


# --- CRUD Endpoints for UI ---

@app.get("/conversations")
async def list_conversations(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List all conversations for the authenticated user."""
    convs = await crud.get_user_conversations(db, current_user.id)
    return [{"id": c.id, "title": c.title, "updated_at": c.updated_at} for c in convs]


@app.get("/conversations/{conversation_id}")
async def get_conversation_history_api(
    conversation_id: str, 
    current_user: User = Depends(get_current_user), 
    db: AsyncSession = Depends(get_db)
):
    """Get full message history for a specific conversation."""
    conv = await crud.get_conversation(db, conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    messages = await crud.get_conversation_messages(db, conversation_id)
    return [{"role": m.role, "content": m.content, "created_at": m.created_at, "metadata": m.metadata_json} for m in messages]


@app.put("/conversations/{conversation_id}")
async def rename_conversation_api(
    conversation_id: str,
    update_data: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Rename a conversation."""
    if not update_data.title or not update_data.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
        
    conv = await crud.update_conversation(db, conversation_id, current_user.id, update_data.title.strip())
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "success", "title": conv.title}


@app.delete("/conversations/{conversation_id}")
async def delete_conversation_api(
    conversation_id: str, 
    current_user: User = Depends(get_current_user), 
    db: AsyncSession = Depends(get_db)
):
    """Delete a conversation."""
    success = await crud.delete_conversation(db, conversation_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "success"}


# --- Document Upload (NotebookLM-style) ---

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB per file


@app.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Ingest a user-uploaded PDF or text file: parse → chunk → embed → store."""
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 15 MB limit.")

    lower = filename.lower()
    try:
        if lower.endswith(".pdf"):
            pages = extract_text_from_bytes(data, filename)
        elif lower.endswith(".txt") or lower.endswith(".md"):
            pages = extract_text_from_plain(data, filename)
        else:
            raise HTTPException(status_code=415, detail="Only .pdf, .txt, .md files are supported.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not pages:
        raise HTTPException(status_code=400, detail="No extractable text found in the document.")

    chunks = chunk_pages(pages, CHUNK_SIZE, CHUNK_OVERLAP)
    if not chunks:
        raise HTTPException(status_code=400, detail="Document produced no chunks after splitting.")

    # Replace any prior chunks for the same filename so re-uploads stay clean
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(DocumentChunk).where(
                DocumentChunk.user_id == current_user.id,
                DocumentChunk.document_name == filename,
            )
        )
        await db.commit()

    inserted = await embedding_service.insert_chunks_to_db(chunks, user_id=current_user.id)
    return UploadResponse(document=filename, chunks_indexed=inserted, pages=len(pages))


@app.get("/documents", response_model=List[UserDocument])
async def list_user_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List documents the current user has uploaded, with chunk counts."""
    result = await db.execute(
        select(DocumentChunk.document_name, func.count(DocumentChunk.id))
        .filter(DocumentChunk.user_id == current_user.id)
        .group_by(DocumentChunk.document_name)
        .order_by(DocumentChunk.document_name)
    )
    return [UserDocument(document=name, chunks=count) for name, count in result.all()]


@app.delete("/documents/{document_name}")
async def delete_user_document(
    document_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete all chunks for a single document the current user uploaded."""
    result = await db.execute(
        delete(DocumentChunk).where(
            DocumentChunk.user_id == current_user.id,
            DocumentChunk.document_name == document_name,
        )
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"status": "success", "document": document_name, "chunks_deleted": result.rowcount}


# --- Frontend & Health ---

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def serve_frontend():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "DocChat RAG API is running."}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/debug/status")
async def debug_status():
    """Diagnostic endpoint to check Firebase and DB status on deployment."""
    import firebase_admin
    status = {
        "firebase_initialized": bool(firebase_admin._apps),
        "firebase_app_count": len(firebase_admin._apps),
    }
    
    # Check DB connectivity
    try:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import text
            result = await db.execute(text("SELECT 1"))
            status["db_connected"] = True
            status["db_error"] = None
    except Exception as e:
        status["db_connected"] = False
        status["db_error"] = str(e)
    
    # Check if serviceAccountKey.json paths exist
    import os
    paths_to_check = [
        os.getenv("FIREBASE_CREDENTIALS", "not_set"),
        "/etc/secrets/serviceAccountKey.json",
    ]
    status["credential_paths"] = {p: os.path.exists(p) for p in paths_to_check}
    
    return status

if __name__ == "__main__":
    import uvicorn
    import os

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port)
