from typing import List, Dict
import numpy as np
import logging
from fastembed import TextEmbedding
from sqlalchemy.future import select
from sqlalchemy import text
from backend.db.database import AsyncSessionLocal
from backend.db.models import DocumentChunk
from backend.config import EMBEDDING_MODEL

logger = logging.getLogger(__name__)

class EmbeddingService:
    """Manages document chunking, embedding generation and inserting to DB."""
    
    def __init__(self, model_name: str = None):
        """Initialize the embedding model."""
        # FastEmbed uses a slightly different default model name string
        model_name = "sentence-transformers/all-MiniLM-L6-v2"
        logger.info(f"Loading fastembed model: {model_name}...")
        self.model = TextEmbedding(model_name=model_name)
        logger.info("Embedding model loaded.")
        
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate normalized vector embeddings for a list of strings."""
        logger.info(f"Generating embeddings for {len(texts)} chunks...")
        # fastembed returns a generator of numpy arrays
        embeddings = list(self.model.embed(texts))
        
        # Convert numpy floats to standard python floats for pgvector
        embeddings_list = [emb.tolist() for emb in embeddings]
        return embeddings_list

    async def insert_chunks_to_db(self, chunks: List[Dict], user_id: str = None):
        """
        Embed and save chunks to the PostgreSQL database via SQLAlchemy.

        Args:
            chunks: List of chunk dicts from chunker.py:
                   [{'document': 'pricing.pdf', 'page': 1, 'text': '...'}]
            user_id: If provided, scopes these chunks to a specific user
                     (so retrieval can isolate per-user uploads).
        """
        if not chunks:
            return 0

        texts = [chunk["text"] for chunk in chunks]
        embeddings = self.generate_embeddings(texts)

        chunk_objects = []
        for i, chunk in enumerate(chunks):
            chunk_obj = DocumentChunk(
                user_id=user_id,
                document_name=chunk["document"],
                page=chunk["page"],
                text_content=chunk["text"],
                embedding=embeddings[i]
            )
            chunk_objects.append(chunk_obj)

        async with AsyncSessionLocal() as db:
            logger.info(f"Saving {len(chunk_objects)} chunks to database (user_id={user_id})...")
            db.add_all(chunk_objects)
            await db.commit()
            logger.info("Chunks successfully saved to PostgreSQL + pgvector.")
        return len(chunk_objects)

# Optional: Keep a script entry point to easily index files from CLI
if __name__ == "__main__":
    import asyncio
    from backend.config import DOCS_DIR, CHUNK_SIZE, CHUNK_OVERLAP
    from backend.rag.pdf_parser import extract_all_pdfs
    from backend.rag.chunker import chunk_pages
    
    async def run_ingestion():
        print(f"Reading PDFs from {DOCS_DIR}")
        pages = extract_all_pdfs(DOCS_DIR)
        chunks = chunk_pages(pages, CHUNK_SIZE, CHUNK_OVERLAP)
        
        svc = EmbeddingService()
        await svc.insert_chunks_to_db(chunks)
        
    asyncio.run(run_ingestion())
