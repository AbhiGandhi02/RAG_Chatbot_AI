"""
PDF Parser — Extracts text from PDF documents (default corpus or user uploads).
Preserves page numbers and document filenames for source tracking.
"""

import os
from io import BytesIO
from typing import List, Dict, Union
from PyPDF2 import PdfReader


def extract_text_from_bytes(data: bytes, document_name: str) -> List[Dict]:
    """
    Extract text from raw PDF bytes (e.g., an uploaded file).

    Returns a list of dicts, one per page:
    [{ "text": "...", "page": 1, "document": document_name }]
    """
    pages = []
    try:
        reader = PdfReader(BytesIO(data))
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                pages.append({
                    "text": text.strip(),
                    "page": i + 1,
                    "document": document_name
                })
    except Exception as e:
        raise ValueError(f"Failed to parse PDF '{document_name}': {e}")
    return pages


def extract_text_from_plain(data: bytes, document_name: str) -> List[Dict]:
    """Treat the file as a single-page text document."""
    try:
        text = data.decode("utf-8", errors="ignore").strip()
    except Exception as e:
        raise ValueError(f"Failed to decode '{document_name}' as text: {e}")
    if not text:
        return []
    return [{"text": text, "page": 1, "document": document_name}]


def extract_text_from_pdf(pdf_path: str) -> List[Dict]:
    """
    Extract text from a single PDF file.
    
    Returns a list of dicts, one per page:
    [{ "text": "...", "page": 1, "document": "filename.pdf" }]
    """
    filename = os.path.basename(pdf_path)
    pages = []
    
    try:
        reader = PdfReader(pdf_path)
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                pages.append({
                    "text": text.strip(),
                    "page": i + 1,
                    "document": filename
                })
    except Exception as e:
        print(f"Error reading {filename}: {e}")
    
    return pages


def extract_all_pdfs(docs_dir: str) -> List[Dict]:
    """
    Extract text from all PDFs in the given directory.
    
    Returns a flat list of page dicts from all documents.
    """
    all_pages = []
    
    pdf_files = sorted([
        f for f in os.listdir(docs_dir) 
        if f.endswith(".pdf")
    ])
    
    print(f"Found {len(pdf_files)} PDF files in {docs_dir}")
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join(docs_dir, pdf_file)
        pages = extract_text_from_pdf(pdf_path)
        all_pages.extend(pages)
        print(f"  ✓ {pdf_file}: {len(pages)} pages extracted")
    
    print(f"\nTotal: {len(all_pages)} pages extracted from {len(pdf_files)} PDFs")
    return all_pages


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m backend.rag.pdf_parser <path-to-pdf-folder>")
        sys.exit(1)
    pages = extract_all_pdfs(sys.argv[1])
    for p in pages[:3]:
        print(f"\n--- {p['document']} (page {p['page']}) ---")
        print(p['text'][:200] + "...")
