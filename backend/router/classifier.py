"""
Query Classifier (Model Router) — Deterministic, rule-based query classification.

Classifies queries as "simple" or "complex" using explicit rules based on:
- Query length (word count)
- Presence of complexity-indicating keywords
- Number of question marks (multi-part questions)
- Greeting/farewell patterns
- Complaint/urgency indicators

Routes:
  simple  → llama-3.1-8b-instant
  complex → llama-3.3-70b-versatile
"""

import re
import time
from typing import Dict
from backend.config import MODEL_SIMPLE, MODEL_COMPLEX


# Greeting/farewell patterns (simple)
GREETING_PATTERNS = [
    r'\b(hi|hello|hey|howdy|greetings|good\s+(morning|afternoon|evening))\b',
    r'\b(thanks|thank\s+you|bye|goodbye|see\s+you|cheers)\b',
]

# Keywords that indicate complexity
COMPLEX_KEYWORDS = [
    "how", "why", "explain", "compare", "comparison", "difference",
    "differences", "between", "steps", "troubleshoot", "troubleshooting",
    "configure", "configuration", "integrate", "integration",
    "setup", "set up", "multi", "multiple", "detailed", "describe",
    "walk me through", "guide", "process", "workflow", "migrate",
    "migration", "architecture", "implement", "implementation"
]

# Complaint/urgency indicators (complex)
COMPLAINT_KEYWORDS = [
    "not working", "broken", "issue", "problem", "bug", "error",
    "frustrated", "urgent", "critical", "failing", "failed",
    "can't", "cannot", "unable", "doesn't work", "won't",
    "help me", "stuck", "confused"
]


def classify_query(query: str) -> Dict:
    """
    Classify a query as 'simple' or 'complex' using deterministic rules.
    
    Returns:
        {
            "classification": "simple" | "complex",
            "model_used": "<model_name>",
            "signals": ["list of triggered signals"]
        }
    """
    query_lower = query.lower().strip()
    words = query_lower.split()
    word_count = len(words)
    signals = []
    complexity_score = 0
    
    # Rule 1: Check for greetings/farewells (→ simple)
    is_greeting = False
    for pattern in GREETING_PATTERNS:
        if re.search(pattern, query_lower):
            is_greeting = True
            signals.append("greeting_detected")
            break
    
    # If it's purely a greeting (short), classify as simple immediately
    if is_greeting and word_count <= 5:
        return {
            "classification": "simple",
            "model_used": MODEL_SIMPLE,
            "signals": signals
        }
    
    # Rule 2: Word count
    if word_count >= 15:
        complexity_score += 2
        signals.append(f"long_query ({word_count} words)")
    elif word_count >= 10:
        complexity_score += 1
        signals.append(f"moderate_length ({word_count} words)")
    
    # Rule 3: Complex keywords
    complex_keywords_found = []
    for keyword in COMPLEX_KEYWORDS:
        if keyword in query_lower:
            complex_keywords_found.append(keyword)
    
    if len(complex_keywords_found) >= 2:
        complexity_score += 2
        signals.append(f"multiple_complex_keywords: {complex_keywords_found}")
    elif len(complex_keywords_found) == 1:
        complexity_score += 1
        signals.append(f"complex_keyword: {complex_keywords_found[0]}")
    
    # Rule 4: Multiple question marks (multi-part question)
    question_marks = query.count("?")
    if question_marks >= 2:
        complexity_score += 2
        signals.append(f"multi_question ({question_marks} question marks)")
    
    # Rule 5: Complaint/urgency indicators
    complaint_found = []
    for keyword in COMPLAINT_KEYWORDS:
        if keyword in query_lower:
            complaint_found.append(keyword)
    
    if complaint_found:
        complexity_score += 1
        signals.append(f"complaint_indicators: {complaint_found}")
    
    # Rule 6: Contains subordinate clauses (and, but, or, because, while, when)
    subordinate_conjunctions = ["and", "but", "because", "while", "when", "although", "however"]
    conj_found = [c for c in subordinate_conjunctions if f" {c} " in f" {query_lower} "]
    if len(conj_found) >= 2:
        complexity_score += 1
        signals.append(f"subordinate_clauses: {conj_found}")
    
    # Decision: threshold of 2 → complex
    if complexity_score >= 2:
        classification = "complex"
        model = MODEL_COMPLEX
    else:
        classification = "simple"
        model = MODEL_SIMPLE
    
    if not signals:
        signals.append("no_special_signals")
    
    return {
        "classification": classification,
        "model_used": model,
        "signals": signals
    }


def create_routing_log(query: str, classification: str, model_used: str,
                       tokens_input: int, tokens_output: int, latency_ms: int) -> Dict:
    """
    Create a structured routing decision log entry.
    
    This is the format required by the assignment.
    """
    return {
        "query": query,
        "classification": classification,
        "model_used": model_used,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "latency_ms": latency_ms
    }


if __name__ == "__main__":
    # Sanity-check the router with a mix of simple/complex/greeting queries.
    test_queries = [
        "Hi!",
        "Hello, how are you?",
        "What is the main topic of this document?",
        "Summarize the key points in one sentence.",
        "How do I configure webhook integrations and what are the rate limits?",
        "The system is throwing an error when I export reports — can you help me debug it?",
        "Thanks!",
        "Compare the two approaches described and explain when each is appropriate.",
        "Why is the API returning 403 errors? I've tried multiple times and it's still broken.",
    ]

    for q in test_queries:
        result = classify_query(q)
        print(f"\nQuery: \"{q}\"")
        print(f"  → {result['classification'].upper()} → {result['model_used']}")
        print(f"  Signals: {result['signals']}")
