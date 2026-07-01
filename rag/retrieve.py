"""
EFAR - Retrieve relevant doc chunks for a question (RAG retrieval step)

Given a question, this:
  1. Embeds it using the same model used for the docs (BAAI/bge-small-en-v1.5)
  2. Searches Supabase (pgvector) for the closest matching chunks
  3. Prints them, and builds a "context block" string ready to inject into
     a system/user prompt sent to your Modal endpoint

Requires:
  pip install fastembed psycopg2-binary python-dotenv pgvector

Requires SUPABASE_DB_URL in your .env (same one used by upload_chunks.py).
"""

import os
import sys

import psycopg2
from pgvector.psycopg2 import register_vector
from fastembed import TextEmbedding
from dotenv import load_dotenv

MODEL_NAME = "BAAI/bge-small-en-v1.5"
TOP_K = 5

# bge models expect this exact instruction prefix on QUERIES (not documents)
# for best retrieval accuracy - this is part of how the model was trained.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

load_dotenv()


def embed_query(model, question):
    prefixed = QUERY_PREFIX + question
    return list(model.embed([prefixed]))[0].tolist()


def retrieve(question, top_k=TOP_K):
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL not found in .env")

    print(f"Loading embedding model ({MODEL_NAME})...")
    model = TextEmbedding(model_name=MODEL_NAME)

    print(f"Embedding question: {question!r}")
    query_vector = embed_query(model, question)

    conn = psycopg2.connect(db_url)
    register_vector(conn)
    cur = conn.cursor()

    # <=> is pgvector's cosine distance operator - smaller = more similar.
    # We order by distance ascending and take the top_k closest chunks.
    cur.execute(
        """
        select title, section, source_type, text, embedding <=> %s::vector as distance
        from doc_chunks
        order by embedding <=> %s::vector
        limit %s
        """,
        (query_vector, query_vector, top_k),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    results = [
        {"title": r[0], "section": r[1], "source_type": r[2], "text": r[3], "distance": r[4]}
        for r in rows
    ]
    return results


def build_context_block(results):
    """Format retrieved chunks into a block ready to inject into a prompt."""
    parts = []
    for r in results:
        parts.append(f"[{r['title']} - {r['section']}]\n{r['text']}")
    return "\n\n---\n\n".join(parts)


def main():
    question = " ".join(sys.argv[1:]) or "How do I use PathfindingService to move an NPC?"

    results = retrieve(question)

    print(f"\nTop {len(results)} matches:\n")
    for r in results:
        print(f"- {r['title']} [{r['section']}]  (distance: {r['distance']:.4f})")

    context_block = build_context_block(results)
    print("\n" + "=" * 60)
    print("CONTEXT BLOCK (ready to inject into your Modal prompt):")
    print("=" * 60)
    print(context_block)


if __name__ == "__main__":
    main()