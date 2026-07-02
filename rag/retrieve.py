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
import re

import psycopg2
from pgvector.psycopg2 import register_vector
from fastembed import TextEmbedding
from dotenv import load_dotenv

MODEL_NAME = "BAAI/bge-small-en-v1.5"
TOP_K = 3  # lowered from 5 - see ask.py for rationale (vector-match noise ate context budget)
KEYWORD_MATCH_LIMIT = 3  # chunks to pull per exact class/service name match

# bge models expect this exact instruction prefix on QUERIES (not documents)
# for best retrieval accuracy - this is part of how the model was trained.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# Roblox class/service names are CamelCase, e.g. PathfindingService, Humanoid.
# If the question mentions one literally, we guarantee its docs are included -
# pure vector similarity can miss them when the question is phrased generically.
CAMELCASE_PATTERN = re.compile(r"\b[A-Z][a-zA-Z0-9]{3,}\b")

# Matches a return type annotation in a method signature line, e.g.
# "PathfindingService:CreatePath(agentParameters: Dictionary = nil): Path"
# captures "Path". Used to auto-pull in classes that a matched method
# returns, so the model also gets docs for what to *do* with that object,
# not just how to obtain it.
RETURN_TYPE_PATTERN = re.compile(r"\):\s*([A-Z][a-zA-Z0-9]*)")

# Common built-in/structural return types that aren't Roblox classes with
# their own doc pages - skip these when expanding to related classes.
PRIMITIVE_RETURN_TYPES = {
    "Tuple", "Variant", "Dictionary", "Array", "Objects", "Table",
    "Vector2", "Vector3", "CFrame", "Color3", "UDim", "UDim2",
    "BrickColor", "Content", "Function", "Instance",
}

load_dotenv()


def embed_query(model, question):
    prefixed = QUERY_PREFIX + question
    return list(model.embed([prefixed]))[0].tolist()


def keyword_matches(cur, question):
    """Find chunks whose title exactly matches a CamelCase term mentioned in the question."""
    candidates = set(CAMELCASE_PATTERN.findall(question))
    if not candidates:
        return []

    matches = []
    for term in candidates:
        cur.execute(
            """
            select title, section, source_type, text
            from doc_chunks
            where lower(title) = lower(%s)
            order by (section = 'overview') desc, section
            limit %s
            """,
            (term, KEYWORD_MATCH_LIMIT),
        )
        rows = cur.fetchall()
        matches.extend(
            {"title": r[0], "section": r[1], "source_type": r[2], "text": r[3], "distance": 0.0}
            for r in rows
        )
    return matches


# Classes that are almost always needed alongside a matched class, even
# though they're not the return type of any of its methods - e.g. Humanoid
# is the thing you actually call MoveTo()/MoveToFinished on when following
# a Path, but no PathfindingService or Path method returns a Humanoid, so
# return-type expansion alone never pulls it in. Add to this as new gaps
# turn up on new test questions.
COMPANION_TERMS = {
    "PathfindingService": ["Humanoid"],
    "Path": ["Humanoid"],
}


def expand_companion_classes(cur, results, exclude_titles):
    """
    Look at exact-match results and pull in any classes listed as companions
    in COMPANION_TERMS - fixed pairings that return-type expansion can't
    discover on its own.
    """
    companion_types = set()
    for r in results:
        companion_types.update(COMPANION_TERMS.get(r["title"], []))

    companion_types -= exclude_titles
    if not companion_types:
        return []

    expanded = []
    for cls in companion_types:
        cur.execute(
            """
            select title, section, source_type, text
            from doc_chunks
            where lower(title) = lower(%s)
              and section in ('overview', 'methods', 'events')
            """,
            (cls,),
        )
        rows = cur.fetchall()
        expanded.extend(
            {"title": r[0], "section": r[1], "source_type": r[2], "text": r[3], "distance": 0.0}
            for r in rows
        )
    return expanded


def expand_related_classes(cur, results, exclude_titles):
    """
    Look at 'methods' chunks already retrieved and pull in docs for any
    class they return (e.g. PathfindingService:CreatePath() -> Path), so
    the model has the follow-up API too, not just the entry point.
    Only expands one level deep and skips anything already retrieved.
    """
    related_types = set()
    for r in results:
        if r["section"] == "methods":
            for match in RETURN_TYPE_PATTERN.findall(r["text"]):
                if match not in PRIMITIVE_RETURN_TYPES:
                    related_types.add(match)

    related_types -= exclude_titles
    if not related_types:
        return []

    expanded = []
    for cls in related_types:
        cur.execute(
            """
            select title, section, source_type, text
            from doc_chunks
            where lower(title) = lower(%s)
              and section in ('overview', 'methods')
            """,
            (cls,),
        )
        rows = cur.fetchall()
        expanded.extend(
            {"title": r[0], "section": r[1], "source_type": r[2], "text": r[3], "distance": 0.0}
            for r in rows
        )
    return expanded


def vector_matches(cur, query_vector, top_k):
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
    return [
        {"title": r[0], "section": r[1], "source_type": r[2], "text": r[3], "distance": r[4]}
        for r in rows
    ]


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

    # Hybrid retrieval: guaranteed exact-name matches + vector similarity search,
    # merged and deduplicated (exact matches take priority since distance=0).
    kw_results = keyword_matches(cur, question)
    vec_results = vector_matches(cur, query_vector, top_k)

    already_have = {r["title"] for r in kw_results} | {r["title"] for r in vec_results}
    expansion_results = expand_related_classes(cur, kw_results, already_have)
    already_have |= {r["title"] for r in expansion_results}
    companion_results = expand_companion_classes(cur, kw_results, already_have)

    cur.close()
    conn.close()

    seen = set()
    results = []
    for r in kw_results + vec_results + expansion_results + companion_results:
        key = (r["title"], r["section"])
        if key not in seen:
            seen.add(key)
            results.append(r)

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