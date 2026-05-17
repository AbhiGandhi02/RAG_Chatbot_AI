"""
Corrective RAG (CRAG) — Self-correcting retrieval pipeline.

Reference: Yan et al., "Corrective Retrieval Augmented Generation" (2024).

Pipeline:
    1. Retrieve candidate chunks from the local vector store.
    2. Grade each chunk's relevance to the query (yes / partial / no)
       using a fast LLM in a single batched call.
    3. Decide an action based on the grades:
         - "use"   → confident in local retrieval; use the graded-relevant chunks.
         - "mix"   → partial coverage; supplement local chunks with web results.
         - "search"→ local retrieval is poor; fall back to web search only.
    4. For "mix" / "search", rewrite the query and run a DuckDuckGo web search.
    5. Return the final chunk list (same shape as retriever output) plus
       debug metadata describing what CRAG did.

Web search uses `duckduckgo-search` if installed. If the dependency is missing
or the call fails, CRAG degrades gracefully to whatever local chunks exist.
"""

import json
import logging
from typing import Dict, List, Optional

from backend.config import CRAG_GRADER_MODEL, CRAG_WEB_MAX_RESULTS

logger = logging.getLogger(__name__)


GRADER_SYSTEM_PROMPT = """You are a strict relevance grader for a retrieval system.

You will receive a user question and a numbered list of document chunks. For each chunk, decide whether it contains information that helps answer the question.

Respond with ONLY a single JSON object. No prose, no markdown fences.

Schema:
{"grades": [{"i": <chunk_number>, "relevance": "yes" | "partial" | "no"}, ...]}

Definitions:
- "yes"     — the chunk directly answers or strongly supports answering the question.
- "partial" — the chunk is on-topic but does not fully answer the question.
- "no"      — the chunk is off-topic or unrelated.

Output exactly one grade per chunk in the same order."""


REWRITER_SYSTEM_PROMPT = """You rewrite a user question into a concise web search query.

Rules:
- 4 to 10 words, no punctuation other than spaces.
- Strip pronouns, filler words, and chat phrasing.
- Keep proper nouns, technical terms, and entities verbatim.
- Output ONLY the search query. No quotes, no preamble, no explanation."""


def _format_chunks_for_grader(chunks: List[Dict]) -> str:
    """Render chunks as a numbered list for the grader prompt."""
    parts = []
    for i, chunk in enumerate(chunks, 1):
        # Truncate long chunks so the grader prompt stays cheap and fast.
        text = (chunk.get("text") or "").strip().replace("\n", " ")
        if len(text) > 800:
            text = text[:800] + "…"
        parts.append(f"[{i}] {text}")
    return "\n\n".join(parts)


def grade_chunks(groq_client, query: str, chunks: List[Dict]) -> List[Dict]:
    """
    Grade each chunk's relevance to the query in a single batched LLM call.

    Returns a new list of chunks with a `grade` field added
    (one of "yes" / "partial" / "no"). On failure the chunks are
    returned with `grade="partial"` as a safe default.
    """
    if not chunks:
        return []

    user_msg = (
        f"Question: {query}\n\n"
        f"Chunks:\n{_format_chunks_for_grader(chunks)}\n\n"
        "Return JSON only."
    )

    grades_by_index: Dict[int, str] = {}
    try:
        response = groq_client.client.chat.completions.create(
            model=CRAG_GRADER_MODEL,
            messages=[
                {"role": "system", "content": GRADER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)
        for entry in data.get("grades", []):
            idx = entry.get("i")
            rel = (entry.get("relevance") or "").lower()
            if isinstance(idx, int) and rel in ("yes", "partial", "no"):
                grades_by_index[idx] = rel
    except Exception as e:
        logger.warning(f"CRAG grader failed, defaulting to 'partial': {e}")

    graded = []
    for i, chunk in enumerate(chunks, 1):
        new_chunk = dict(chunk)
        new_chunk["grade"] = grades_by_index.get(i, "partial")
        graded.append(new_chunk)
    return graded


def decide_action(graded_chunks: List[Dict]) -> str:
    """
    Decide what CRAG should do next based on grader output.

    Returns one of:
        "use"    — confident in local context; keep graded-relevant chunks.
        "mix"    — partial coverage; pull in web results to fill the gap.
        "search" — local retrieval insufficient; fall back to web only.
    """
    if not graded_chunks:
        return "search"

    yes_count = sum(1 for c in graded_chunks if c.get("grade") == "yes")
    partial_count = sum(1 for c in graded_chunks if c.get("grade") == "partial")

    if yes_count >= 2:
        return "use"
    if yes_count == 1 or partial_count >= 2:
        return "mix"
    return "search"


def filter_relevant(graded_chunks: List[Dict]) -> List[Dict]:
    """Drop chunks graded `no`. Keep order from the retriever."""
    return [c for c in graded_chunks if c.get("grade") in ("yes", "partial")]


def rewrite_query(groq_client, query: str) -> str:
    """Rewrite the user's query into a concise web search query."""
    try:
        response = groq_client.client.chat.completions.create(
            model=CRAG_GRADER_MODEL,
            messages=[
                {"role": "system", "content": REWRITER_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0,
            max_tokens=40,
        )
        rewritten = response.choices[0].message.content.strip().strip('"\'')
        if rewritten:
            return rewritten
    except Exception as e:
        logger.warning(f"CRAG query rewriter failed, using original query: {e}")
    return query


def web_search(query: str, max_results: int = CRAG_WEB_MAX_RESULTS) -> List[Dict]:
    """
    Web search fallback via DuckDuckGo. Returns chunks in the same shape as
    `Retriever.retrieve_async` so they slot directly into `build_context`.

    Gracefully returns [] if `duckduckgo-search` is not installed or the
    call fails — CRAG then falls back to whatever local chunks remain.
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.warning(
            "CRAG: duckduckgo-search not installed; skipping web fallback. "
            "Run `pip install duckduckgo-search` to enable."
        )
        return []

    results: List[Dict] = []
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=max_results))
        for i, h in enumerate(hits, 1):
            title = (h.get("title") or "").strip()
            snippet = (h.get("body") or "").strip()
            url = (h.get("href") or "").strip()
            if not snippet and not title:
                continue
            text = f"{title}\n{snippet}" if title else snippet
            results.append({
                "document": url or f"web-result-{i}",
                "page": 0,
                "text": text,
                "relevance_score": None,
                "source_type": "web",
            })
    except Exception as e:
        logger.warning(f"CRAG web search failed: {e}")
    return results


async def corrective_retrieve(
    retriever,
    groq_client,
    query: str,
    user_id: Optional[str] = None,
) -> Dict:
    """
    Run the full CRAG pipeline and return final chunks + debug metadata.

    Returns:
        {
            "chunks":          List[Dict],   # chunks to pass to the generator
            "action":          str,          # "use" | "mix" | "search"
            "graded_chunks":   List[Dict],   # original chunks with grades
            "rewritten_query": Optional[str],
            "web_results":     int,          # count of web results pulled in
        }
    """
    initial_chunks = await retriever.retrieve_async(query, user_id=user_id)

    # No retrieval at all → straight to web search.
    if not initial_chunks:
        rewritten = rewrite_query(groq_client, query)
        web = web_search(rewritten)
        return {
            "chunks": web,
            "action": "search",
            "graded_chunks": [],
            "rewritten_query": rewritten,
            "web_results": len(web),
        }

    graded = grade_chunks(groq_client, query, initial_chunks)
    action = decide_action(graded)
    relevant = filter_relevant(graded)

    if action == "use":
        return {
            "chunks": relevant or initial_chunks,
            "action": action,
            "graded_chunks": graded,
            "rewritten_query": None,
            "web_results": 0,
        }

    # "mix" or "search" → rewrite + web search.
    rewritten = rewrite_query(groq_client, query)
    web = web_search(rewritten)

    if action == "search":
        final = web if web else (relevant or initial_chunks)
    else:  # "mix"
        # Cap each source so the context prompt stays balanced.
        final = (relevant or [])[:4] + web[:4]

    return {
        "chunks": final,
        "action": action,
        "graded_chunks": graded,
        "rewritten_query": rewritten,
        "web_results": len(web),
    }
