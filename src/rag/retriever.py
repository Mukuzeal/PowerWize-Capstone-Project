"""Retrieval for the solar RAG pipeline — brute-force cosine similarity over
`rag_chunks.embedding` (REAL[] + numpy). Fine at this corpus size; see the
pgvector note in docs/RAG_SETUP.md if the knowledge base ever grows enough to
need an ANN index instead.
"""
import os

import numpy as np
from dotenv import load_dotenv

from db import fetch_chunks

from .embeddings import EMBED_MODEL, embed

load_dotenv()

# Tuned from scripts/rag_eval.py's output against the actual indexed corpus
# (2026-09-19): off-topic questions' best top-1 cosine score was 0.5275
# ("capital of France" scored 0 candidates above even 0.45; "chicken adobo"
# topped out at 0.5275). The weakest top-1 score among every genuinely
# solar-related question (in-KB, not-in-KB-but-on-topic, numeric, Taglish) was
# 0.6581. 0.55 sits in that gap with margin on both sides. Re-run rag_eval.py
# and revisit this if the knowledge base changes meaningfully in size or topic
# spread. See docs/RAG_SETUP.md.
RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.55"))


def retrieve(query: str, user_role: str | None = None, k: int = 5) -> list:
    """Top-k chunks above RAG_MIN_SCORE, filtered by visibility BEFORE ranking.
    visibility='admin' chunks are only ever candidates for admin/employee
    sessions — the public solar chat never passes that role."""
    visibilities = ("public", "admin") if user_role in ("admin", "employee") else ("public",)
    chunks = fetch_chunks(EMBED_MODEL, visibilities)
    if not chunks:
        return []

    q_vec = np.asarray(embed([query], kind="query")[0], dtype=np.float32)
    q_vec = q_vec / (np.linalg.norm(q_vec) or 1.0)

    scored = []
    for c in chunks:
        v = np.asarray(c["embedding"], dtype=np.float32)
        v = v / (np.linalg.norm(v) or 1.0)
        scored.append((float(np.dot(q_vec, v)), c))
    scored.sort(key=lambda t: t[0], reverse=True)

    results = []
    for score, c in scored[:k]:
        if score < RAG_MIN_SCORE:
            continue
        results.append({
            "title": c["title"], "source_ref": c["source_ref"],
            "topic": c["topic"], "content": c["content"],
            "score": round(score, 4),
        })
    return results
