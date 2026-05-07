"""
Chunker — Splits extracted PDF text into smaller overlapping chunks.

Strategy: Recursive character-based splitting.
1. Split on paragraph breaks (\n\n)
2. If a paragraph is still too long, split on sentence boundaries (. )
3. If still too long, split on word boundaries
4. Apply overlap to preserve context across chunk boundaries.
"""

import json
import os
from typing import List, Dict


def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 100) -> List[str]:
    """
    Split text into overlapping chunks using recursive splitting.
    
    Args:
        text: The text to split
        chunk_size: Target maximum chunk size in characters
        chunk_overlap: Number of overlapping characters between chunks
    
    Returns:
        List of text chunks
    """
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    
    # First try splitting on paragraph breaks
    paragraphs = text.split("\n\n")
    
    current_chunk = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # If adding this paragraph exceeds chunk size
        if len(current_chunk) + len(para) + 2 > chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
                # Keep overlap from end of current chunk
                overlap_text = current_chunk[-chunk_overlap:] if len(current_chunk) > chunk_overlap else current_chunk
                current_chunk = overlap_text + " " + para
            else:
                # Single paragraph is too long — split on sentences
                sentence_chunks = _split_on_sentences(para, chunk_size, chunk_overlap)
                chunks.extend(sentence_chunks[:-1])
                current_chunk = sentence_chunks[-1] if sentence_chunks else ""
        else:
            current_chunk = (current_chunk + "\n\n" + para).strip()
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks


def _split_on_sentences(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """Split text on sentence boundaries when paragraphs are too long."""
    # Split on common sentence endings
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    chunks = []
    current_chunk = ""
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 > chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
                overlap_text = current_chunk[-chunk_overlap:] if len(current_chunk) > chunk_overlap else current_chunk
                current_chunk = overlap_text + " " + sentence
            else:
                # Single sentence too long — split on words
                word_chunks = _split_on_words(sentence, chunk_size, chunk_overlap)
                chunks.extend(word_chunks[:-1])
                current_chunk = word_chunks[-1] if word_chunks else ""
        else:
            current_chunk = (current_chunk + " " + sentence).strip()
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks


def _split_on_words(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """Last resort: split on word boundaries."""
    words = text.split()
    chunks = []
    current_chunk = ""
    
    for word in words:
        if len(current_chunk) + len(word) + 1 > chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
                overlap_text = current_chunk[-chunk_overlap:] if len(current_chunk) > chunk_overlap else current_chunk
                current_chunk = overlap_text + " " + word
            else:
                current_chunk = word
        else:
            current_chunk = (current_chunk + " " + word).strip()
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks


def chunk_pages(pages: List[Dict], chunk_size: int = 500, chunk_overlap: int = 100) -> List[Dict]:
    """
    Chunk all extracted pages into smaller pieces.
    
    Args:
        pages: List of page dicts from pdf_parser
        chunk_size: Target max chunk size
        chunk_overlap: Overlap between chunks
    
    Returns:
        List of chunk dicts with metadata:
        [{ "text": "...", "document": "...", "page": 1, "chunk_id": 0 }]
    """
    all_chunks = []
    chunk_id = 0
    
    for page in pages:
        text_chunks = chunk_text(page["text"], chunk_size, chunk_overlap)
        
        for text in text_chunks:
            all_chunks.append({
                "text": text,
                "document": page["document"],
                "page": page["page"],
                "chunk_id": chunk_id
            })
            chunk_id += 1
    
    print(f"Created {len(all_chunks)} chunks from {len(pages)} pages")
    return all_chunks


def save_chunks(chunks: List[Dict], output_path: str):
    """Save chunks to a JSON file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(chunks)} chunks to {output_path}")


def load_chunks(chunks_path: str) -> List[Dict]:
    """Load chunks from a JSON file."""
    with open(chunks_path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    import sys
    import os
    from backend.config import CHUNKS_FILE, CHUNK_SIZE, CHUNK_OVERLAP
    from backend.rag.pdf_parser import extract_all_pdfs

    if len(sys.argv) < 2:
        print("Usage: python -m backend.rag.chunker <path-to-pdf-folder>")
        sys.exit(1)
    folder = sys.argv[1]
    if not os.path.isdir(folder):
        print(f"Folder not found: {folder}")
        sys.exit(1)

    pages = extract_all_pdfs(folder)
    chunks = chunk_pages(pages, CHUNK_SIZE, CHUNK_OVERLAP)
    save_chunks(chunks, CHUNKS_FILE)

    for c in chunks[:3]:
        print(f"\n--- Chunk {c['chunk_id']} ({c['document']}, p{c['page']}) ---")
        print(c['text'][:200] + "...")
