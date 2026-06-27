"""
Output Evaluator — Post-generation quality check.

Scans LLM responses for reliability issues and returns evaluator flags.

Flags:
1. "no_context"       — LLM answered but no relevant chunks were retrieved
2. "refusal"          — LLM explicitly refused to answer or said it doesn't know
3. "conflicting_info" — Answer indicates conflicting information across documents
"""

import re
from typing import List, Dict


# Refusal phrases indicating the model couldn't answer
REFUSAL_PHRASES = [
    "i don't have",
    "i do not have",
    "not mentioned",
    "cannot find",
    "can't find",
    "no information",
    "i'm not sure",
    "i am not sure",
    "don't know",
    "do not know",
    "not available",
    "no relevant",
    "unable to find",
    "unable to answer",
    "not enough information",
    "not provided in",
    "doesn't contain",
    "does not contain",
    "not in the documentation",
    "context doesn't",
    "context does not",
    "no documentation",
    "i cannot",
    "i can't",
]

# Phrases indicating conflicting or uncertain information
CONFLICT_PHRASES = [
    "conflicting",
    "contradictory",
    "inconsistent",
    "discrepancy",
    "differs from",
    "different from what",
    "varies depending",
    "unclear from the documentation",
    "multiple sources suggest different",
    "appears to conflict",
    "however, another",
    "on the other hand",
    "but the documentation also states",
    "note that there may be",
]


def evaluate_response(
    answer: str,
    chunks_retrieved: int,
    retrieved_chunks: List[Dict] = None
) -> List[str]:
    """
    Evaluate an LLM response for reliability issues.
    
    Args:
        answer: The LLM's generated response
        chunks_retrieved: Number of chunks that were retrieved
        retrieved_chunks: List of retrieved chunk dicts (for conflict detection)
    
    Returns:
        List of flag strings (empty if no issues detected)
    """
    flags = []
    answer_lower = answer.lower()
    
    # Flag 1: no_context — No relevant chunks were retrieved
    # pgvector always returns top-k results even if irrelevant, so we also
    # check if all chunks have very low relevance scores. Threshold is intentionally
    # low (0.25) because short structured docs (CVs, etc.) often max out around 0.35–0.45.
    # Web chunks from CRAG fallback carry relevance_score=None — treat them as valid
    # context so they don't trigger a false no_context flag or a TypeError in max().
    effectively_no_context = False
    if chunks_retrieved == 0:
        effectively_no_context = True
    elif retrieved_chunks:
        has_web_chunks = any(c.get("source_type") == "web" for c in retrieved_chunks)
        if has_web_chunks:
            effectively_no_context = False
        else:
            max_score = max((c.get("relevance_score") or 0 for c in retrieved_chunks), default=0)
            if max_score < 0.25:
                effectively_no_context = True
    
    if effectively_no_context:
        flags.append("no_context")
    
    # Flag 2: refusal — LLM explicitly refused or said it doesn't know
    # Only add refusal if we had relevant context but the LLM still refused
    if _check_refusal(answer_lower) and not effectively_no_context:
        flags.append("refusal")
    
    # Flag 3: conflicting_info — Answer indicates conflicting information
    if _check_conflicting_info(answer_lower, retrieved_chunks):
        flags.append("conflicting_info")
    
    return flags


def _check_refusal(answer_lower: str) -> bool:
    """Check if the answer contains refusal phrases."""
    for phrase in REFUSAL_PHRASES:
        if phrase in answer_lower:
            return True
    return False


def _check_conflicting_info(answer_lower: str, retrieved_chunks: List[Dict] = None) -> bool:
    """
    Check if the answer indicates conflicting information.
    
    Two checks:
    1. The answer text contains conflict-indicating phrases
    2. Retrieved chunks come from 3+ different documents on similar content
    """
    # Check for conflict phrases in the answer
    for phrase in CONFLICT_PHRASES:
        if phrase in answer_lower:
            return True
    
    # Check if retrieved chunks span many different documents
    if retrieved_chunks and len(retrieved_chunks) >= 3:
        unique_docs = set(chunk.get("document", "") for chunk in retrieved_chunks)
        if len(unique_docs) >= 3:
            # Additional heuristic: if the answer is long and mentions "however" or "but"
            transition_words = ["however", "but", "although", "whereas", "nevertheless"]
            transition_count = sum(1 for w in transition_words if w in answer_lower)
            if transition_count >= 2:
                return True
    
    return False


def get_warning_message(flags: List[str]) -> str:
    """
    Generate a user-facing warning message based on evaluator flags.
    
    Args:
        flags: List of evaluator flag strings
    
    Returns:
        Warning message string, or empty string if no flags
    """
    if not flags:
        return ""
    
    warnings = []
    if "no_context" in flags:
        warnings.append("no relevant documentation was found for this query")
    if "refusal" in flags:
        warnings.append("the assistant could not find a definitive answer")
    if "conflicting_info" in flags:
        warnings.append("the documentation may contain conflicting information")
    
    warning_text = " and ".join(warnings)
    return f"⚠️ Low confidence — {warning_text}."
