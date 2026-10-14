"""Retrieval for the solar RAG pipeline — cosine similarity over
`rag_chunks.embedding` (REAL[] + numpy), against a normalized matrix cached in
process. Fine at this corpus size; see the pgvector note in docs/RAG_SETUP.md
if the knowledge base ever grows enough to need an ANN index instead.
"""
import os
import threading
import time

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

# Seconds to reuse the fetched+normalized chunk matrix before re-reading
# rag_chunks. Opening a fresh psycopg2 connection and re-parsing every REAL[]
# was measured at ~62ms of a ~62ms retrieve() — the cosine ranking itself is
# 0.003ms — and _retrieve_multi() in solar_bp.py pays it once per
# sub-question, so a 3-question message spent ~194ms refetching rows that
# cannot have changed between fragments.
#
# The cost of caching is staleness: build_rag_index.py runs as a separate
# process, so a live app keeps serving the old vectors until the TTL lapses.
# That is why this is a short TTL and not a permanent memo — re-indexing is a
# manual terminal step anyway (docs/RAG_SETUP.md), so waiting out one TTL (or
# restarting) is an acceptable price. RAG_CACHE_TTL=0 disables caching, which
# is what you want when hand-checking an index you are actively rebuilding.
RAG_CACHE_TTL = float(os.getenv("RAG_CACHE_TTL", "300"))

# {visibilities: (expires_at, chunks, row-normalized matrix)}. Keyed by
# visibility tuple because an admin/employee session ranks over a strictly
# larger candidate set than the public chat does, and the two must not share
# a matrix. Guarded by a lock so a cold cache under concurrent requests costs
# one fetch rather than one per thread.
_cache: dict = {}
_cache_lock = threading.Lock()


def _normalized(visibilities: tuple):
    """(chunks, matrix) where matrix[i] is chunks[i]'s unit-length embedding."""
    now = time.monotonic()
    if RAG_CACHE_TTL > 0:
        hit = _cache.get(visibilities)
        if hit and hit[0] > now:
            return hit[1], hit[2]

    with _cache_lock:
        # Re-check: another thread may have populated it while we waited.
        if RAG_CACHE_TTL > 0:
            hit = _cache.get(visibilities)
            if hit and hit[0] > time.monotonic():
                return hit[1], hit[2]

        chunks = fetch_chunks(EMBED_MODEL, visibilities)
        if not chunks:
            # Not cached — an empty table usually means the index hasn't been
            # built yet, and pinning that for a full TTL would outlast the
            # build_rag_index.py run that fixes it.
            return [], None

        matrix = np.asarray([c["embedding"] for c in chunks], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0          # same zero-guard as the query vector
        matrix /= norms

        if RAG_CACHE_TTL > 0:
            _cache[visibilities] = (time.monotonic() + RAG_CACHE_TTL, chunks, matrix)
        return chunks, matrix


def retrieve(query: str, user_role: str | None = None, k: int = 5) -> list:
    """Top-k chunks above RAG_MIN_SCORE, filtered by visibility BEFORE ranking.
    visibility='admin' chunks are only ever candidates for admin/employee
    sessions — the public solar chat never passes that role."""
    visibilities = ("public", "admin") if user_role in ("admin", "employee") else ("public",)
    chunks, matrix = _normalized(visibilities)
    if not chunks:
        return []

    q_vec = np.asarray(embed([query], kind="query")[0], dtype=np.float32)
    q_vec = q_vec / (np.linalg.norm(q_vec) or 1.0)

    scores = matrix @ q_vec
    # kind="stable" so chunks tying on score keep the order the rows came back
    # in, which is what the previous list.sort() did — argsort's default
    # quicksort would reorder them arbitrarily. Threshold is applied AFTER the
    # top-k slice, not before it, also matching the previous behaviour.
    order = np.argsort(-scores, kind="stable")[:k]

    results = []
    for i in order:
        score = float(scores[i])
        if score < RAG_MIN_SCORE:
            continue
        c = chunks[i]
        results.append({
            "title": c["title"], "source_ref": c["source_ref"],
            "topic": c["topic"], "content": c["content"],
            "score": round(score, 4),
        })
    return results
