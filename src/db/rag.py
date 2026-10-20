import psycopg2.extras

from .core import get_db


def get_existing_chunks(source_ref: str) -> dict:
    """{title: {"id": int, "content_hash": str}} for one source file — lets the
    indexer skip unchanged chunks and detect removed headings."""
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, title, content_hash FROM rag_chunks WHERE source_ref=%s", (source_ref,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {r["title"]: {"id": r["id"], "content_hash": r["content_hash"]} for r in rows}


def insert_chunk(source_type: str, source_ref: str, title: str, content: str,
                  visibility: str, topic: str | None, embedding: list, embed_model: str,
                  content_hash: str) -> int:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO rag_chunks (source_type, source_ref, title, content, visibility,
                                 topic, embedding, embed_model, content_hash)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (source_type, source_ref, title, content, visibility, topic,
          embedding, embed_model, content_hash))
    conn.commit()
    chunk_id = cur.fetchone()[0]
    cur.close(); conn.close()
    return chunk_id


def update_chunk(chunk_id: int, content: str, visibility: str, topic: str | None,
                  embedding: list, embed_model: str, content_hash: str):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        UPDATE rag_chunks
        SET content=%s, visibility=%s, topic=%s, embedding=%s, embed_model=%s,
            content_hash=%s, updated_at=CURRENT_TIMESTAMP
        WHERE id=%s
    """, (content, visibility, topic, embedding, embed_model, content_hash, chunk_id))
    conn.commit()
    cur.close(); conn.close()


def delete_chunks_by_ids(ids: list):
    if not ids:
        return
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM rag_chunks WHERE id = ANY(%s)", (ids,))
    conn.commit()
    cur.close(); conn.close()


def delete_all_chunks():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM rag_chunks")
    conn.commit()
    cur.close(); conn.close()


def count_chunks_by_topic() -> list:
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT source_ref, topic, COUNT(*) AS n
        FROM rag_chunks GROUP BY source_ref, topic ORDER BY source_ref, topic
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def fetch_chunks(embed_model: str, visibilities: tuple = ("public",)) -> list:
    """Candidate chunks for retrieval. Rows whose embed_model doesn't match the
    configured model are excluded — mixing vector spaces silently would rank
    garbage as if it were relevant — and logged once so a stale index is
    obvious instead of quietly wrong."""
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT id, source_type, source_ref, title, content, visibility, topic, "
        "embedding, embed_model FROM rag_chunks WHERE visibility = ANY(%s)",
        (list(visibilities),)
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()

    matching = [r for r in rows if r["embed_model"] == embed_model]
    stale    = len(rows) - len(matching)
    if stale:
        print(f"[RAG] WARNING: {stale} indexed chunk(s) were embedded with a different "
              f"model than the configured EMBED_MODEL={embed_model!r}. They are being "
              f"skipped, not mixed in — re-run scripts/build_rag_index.py --rebuild.")
    return matching
