"""Embedding provider for the solar RAG pipeline.

Independent of TEXT_PROVIDER/VISION_PROVIDER on purpose: switching which model
answers chat never requires re-indexing, and embeddings must keep working on
CPU even when LM Studio (the GPU-backed chat provider) is not running.

EMBED_PROVIDER=local_cpu (default) — fastembed/ONNX, no GPU, no torch/CUDA.
EMBED_PROVIDER=lmstudio            — LM Studio's /v1/embeddings endpoint.
"""
import os
from typing import Literal

import requests as _http
from dotenv import load_dotenv

load_dotenv()

EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "local_cpu").lower()
EMBED_MODEL    = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

LM_STUDIO_URL  = os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234")

_model = None  # lazy singleton — loaded once per process, not per request


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=EMBED_MODEL)
    return _model


def warm():
    """Load the ONNX model now instead of on the first user request.

    Measured at ~1.5s on this machine (more on a cold HF cache), and it is paid
    per process — so without this the first person to hit Solara after a
    gunicorn worker starts waits it out on top of their reply. Best-effort on
    purpose: a failure here is a slow first request, never a dead app, and
    retrieval would still work (the next embed() call retries the load).
    No-op for EMBED_PROVIDER=lmstudio, which has no local model to load.
    """
    if EMBED_PROVIDER == "lmstudio":
        return
    try:
        embed(["warm"], kind="query")
    except Exception as e:
        print(f"[RAG] embedder pre-warm failed ({type(e).__name__}: {e}) — "
              f"the first query will pay the model load instead.")


def embed(texts: list[str], kind: Literal["document", "query"] = "document") -> list[list[float]]:
    """Embed a batch of texts. kind="query" vs "document" lets fastembed apply
    the model's own asymmetric prefix (BGE wants a query-side instruction
    prefix, not a document-side one) instead of us hand-rolling it."""
    if not texts:
        return []

    if EMBED_PROVIDER == "lmstudio":
        return _embed_lmstudio(texts)

    model = _get_model()
    fn = model.query_embed if kind == "query" else model.passage_embed
    return [vec.tolist() for vec in fn(texts)]


def _embed_lmstudio(texts: list[str]) -> list[list[float]]:
    resp = _http.post(
        f"{LM_STUDIO_URL}/v1/embeddings",
        json={"model": EMBED_MODEL, "input": texts},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    # LM Studio's embeddings endpoint doesn't guarantee response order matches
    # request order across all backends; the "index" field does.
    ordered = sorted(data, key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in ordered]