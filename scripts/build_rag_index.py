"""build_rag_index.py — Chunks and embeds the solar PV knowledge base
(knowledge/solar/*.md plus the non-personal solar rows of site_content.py)
into rag_chunks for the Solara chatbot's retrieval-augmented answers.

Run from the src/ directory so flat imports resolve:
    cd src && ..\\venv\\Scripts\\python.exe ..\\scripts\\build_rag_index.py [--rebuild]
"""
import argparse
import glob
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from _guard import require_local_db
require_local_db()

from db import (count_chunks_by_topic, delete_all_chunks, delete_chunks_by_ids,
                 get_existing_chunks, insert_chunk, update_chunk)
from rag.embeddings import EMBED_MODEL, embed

KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), '..', 'knowledge', 'solar')

# ~300-500 tokens at a rough 4 chars/token, with a small overlap so a split
# section doesn't lose the sentence that explains what came before it.
CHUNK_TARGET_CHARS  = 1800
CHUNK_OVERLAP_CHARS = 150

TOPIC_BY_FILENAME = {
    'pv-basics.md':                          'pv-basics',
    'system-sizing.md':                      'sizing',
    'panels.md':                             'panels',
    'inverters.md':                          'inverters',
    'batteries.md':                          'batteries',
    'grid-tied-vs-off-grid-vs-hybrid.md':    'system-types',
    'net-metering-philippines.md':           'net-metering',
    'installation-and-maintenance.md':       'installation',
    'our-offerings-and-process.md':          'our-offerings',
    'faq.md':                                'faq',
}


def _split_long(content: str, max_chars: int, overlap: int) -> list:
    if len(content) <= max_chars:
        return [content]
    parts, start = [], 0
    while start < len(content):
        end = min(start + max_chars, len(content))
        parts.append(content[start:end])
        if end == len(content):
            break
        start = end - overlap
    return parts


def chunk_markdown(text: str) -> list:
    """Split on H1/H2 headings; further split any oversized section by
    character count. Returns [(title, content), ...]."""
    lines = text.splitlines()
    sections, heading, buf = [], "Untitled", []

    def flush():
        content = "\n".join(buf).strip()
        if content:
            sections.append((heading, content))

    for line in lines:
        if line.startswith("# ") or line.startswith("## "):
            flush()
            heading = line.lstrip("#").strip()
            buf = [line]
        else:
            buf.append(line)
    flush()

    chunks = []
    for heading, content in sections:
        parts = _split_long(content, CHUNK_TARGET_CHARS, CHUNK_OVERLAP_CHARS)
        for i, part in enumerate(parts):
            title = heading if len(parts) == 1 else f"{heading} (part {i + 1})"
            chunks.append((title, part))
    return chunks


def index_chunks(source_type: str, source_ref: str, visibility: str, topic: str,
                  chunks: list, stats: dict):
    """Insert new chunks, update changed ones (by content_hash), skip
    unchanged ones, and delete rows for headings that no longer exist."""
    existing = get_existing_chunks(source_ref)
    seen_titles = set()
    plan = []  # (title, content, hash, action, existing_id)

    for title, content in chunks:
        seen_titles.add(title)
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        prior = existing.get(title)
        if prior and prior["content_hash"] == h:
            stats["skipped"] += 1
            continue
        action = "update" if prior else "insert"
        plan.append((title, content, h, action, prior["id"] if prior else None))

    if plan:
        vectors = embed([c for _, c, _, _, _ in plan], kind="document")
        for (title, content, h, action, existing_id), vec in zip(plan, vectors):
            if action == "insert":
                insert_chunk(source_type, source_ref, title, content, visibility, topic,
                             vec, EMBED_MODEL, h)
                stats["inserted"] += 1
            else:
                update_chunk(existing_id, content, visibility, topic, vec, EMBED_MODEL, h)
                stats["updated"] += 1

    stale_ids = [v["id"] for t, v in existing.items() if t not in seen_titles]
    if stale_ids:
        delete_chunks_by_ids(stale_ids)
        stats["deleted"] += len(stale_ids)


def index_knowledge_files(stats: dict):
    for path in sorted(glob.glob(os.path.join(KNOWLEDGE_DIR, "*.md"))):
        filename = os.path.basename(path)
        topic = TOPIC_BY_FILENAME.get(filename, "general")
        source_ref = f"knowledge/solar/{filename}"
        text = open(path, encoding="utf-8").read()
        chunks = chunk_markdown(text)
        index_chunks("knowledge_md", source_ref, "public", topic, chunks, stats)
        print(f"  {source_ref}: {len(chunks)} chunk(s), topic={topic}")


def index_site_content(stats: dict):
    """Indexes only the non-personal solar capability row of site_content.py —
    never anything from the DB (solar_requests, etc.), per the never-index-
    personal-data rule."""
    import site_content

    row = next((c for c in site_content.CAPABILITIES if c.get("slug") == "renewable-energy"), None)
    if not row:
        print("  site_content.py: no 'renewable-energy' capability found, skipping")
        return

    lines = [f"# {row['title']}", "", row.get("kicker", ""), "", row.get("blurb", ""),
             "", row.get("lede", "")]
    for para in row.get("body", []):
        lines += ["", para]
    lines.append("")
    lines.append("## Offerings")
    for title, desc, _ in row.get("rows", []):
        lines.append(f"- **{title}:** {desc}")

    text = "\n".join(lines)
    chunks = chunk_markdown(text)
    source_ref = "src/site_content.py:renewable-energy"
    index_chunks("site_content", source_ref, "public", "our-offerings", chunks, stats)
    print(f"  {source_ref}: {len(chunks)} chunk(s)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true",
                         help="Wipe rag_chunks and re-embed everything from scratch.")
    args = parser.parse_args()

    if args.rebuild:
        delete_all_chunks()
        print("Rebuild: wiped rag_chunks.")

    stats = {"inserted": 0, "updated": 0, "skipped": 0, "deleted": 0}

    print(f"Embedding model: {EMBED_MODEL}")
    print("Indexing knowledge/solar/*.md ...")
    index_knowledge_files(stats)
    print("Indexing site_content.py solar row ...")
    index_site_content(stats)

    print(f"\nDone. inserted={stats['inserted']} updated={stats['updated']} "
          f"skipped={stats['skipped']} deleted={stats['deleted']}")

    print("\nChunks per source/topic:")
    for row in count_chunks_by_topic():
        print(f"  {row['source_ref']:<55} topic={row['topic']:<15} n={row['n']}")


if __name__ == "__main__":
    main()
