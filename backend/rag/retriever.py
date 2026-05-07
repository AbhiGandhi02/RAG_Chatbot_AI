import logging
from typing import List, Dict
from sqlalchemy.future import select
from sqlalchemy import text, or_
from fastembed import TextEmbedding

from backend.db.database import AsyncSessionLocal
from backend.db.models import DocumentChunk
from backend.config import TOP_K, SIMILARITY_THRESHOLD, EMBEDDING_MODEL

logger = logging.getLogger(__name__)

class Retriever:
    """Retrieves relevant document chunks from PostgreSQL using pgvector."""
    
    def __init__(self, model_name: str = None):
        """Initialize retriever with the fastembed model."""
        model_name = "sentence-transformers/all-MiniLM-L6-v2"
        logger.info(f"Retriever loading fastembed model: {model_name}...")
        self.model = TextEmbedding(model_name=model_name)
    
    def embed_query(self, query: str) -> List[float]:
        """Embed a query string into a vector."""
        # fastembed returns a generator, so we wrap in list
        embedding = list(self.model.embed([query]))
        return embedding[0].tolist()
        
    async def retrieve_async(self, query: str, top_k: int = None, threshold: float = None, user_id: str = None) -> List[Dict]:
        """
        Asynchronously retrieve the most relevant chunks.

        Search scope:
          - Always include the default/global corpus (chunks with user_id IS NULL),
            i.e. the pre-loaded ClearPath PDFs from `python -m backend.rag.embeddings`.
          - If `user_id` is provided, also include chunks owned by that user
            (their uploaded documents).
        """
        top_k = top_k or TOP_K
        threshold = threshold or SIMILARITY_THRESHOLD

        query_embedding = self.embed_query(query)

        relevant_chunks = []
        async with AsyncSessionLocal() as db:
            stmt = (
                select(DocumentChunk, DocumentChunk.embedding.cosine_distance(query_embedding).label("cos_dist"))
                .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
                .limit(top_k)
            )
            if user_id is not None:
                stmt = stmt.filter(
                    or_(
                        DocumentChunk.user_id == user_id,
                        DocumentChunk.user_id.is_(None),
                    )
                )
            result = await db.execute(stmt)
            
            rows = result.all()
            for chunk_obj, dist in rows:
                # Recover original cosine similarity from the pgvector distance
                # Cosine Similarity = 1.0 - cosine_distance
                # E.g., if dist is 0.15, similarity is 0.85
                similarity = 1.0 - float(dist)
                
                if similarity >= threshold:
                    chunk_dict = {
                        "document": chunk_obj.document_name,
                        "page": chunk_obj.page,
                        "text": chunk_obj.text_content,
                        "relevance_score": round(similarity, 4)
                    }
                    relevant_chunks.append(chunk_dict)
                    
        return relevant_chunks
        
    def retrieve(self, query: str, top_k: int = None, threshold: float = None, user_id: str = None) -> List[Dict]:
        """Synchronous wrapper for retrieve_async."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return asyncio.run(self.retrieve_async(query, top_k, threshold, user_id))
        else:
            return asyncio.run(self.retrieve_async(query, top_k, threshold, user_id))
            
    def build_context(self, chunks: List[Dict]) -> str:
        """Build context string from retrieved chunks for the LLM prompt."""
        if not chunks:
            return "No relevant documentation found for this query."
        
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            source = f"[Source: {chunk['document']}, Page {chunk['page']}]"
            context_parts.append(f"--- Context {i} {source} ---\n{chunk['text']}")
        
        return "\n\n".join(context_parts)
