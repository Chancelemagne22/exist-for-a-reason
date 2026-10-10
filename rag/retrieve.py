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
TOP_K = 3  # default for single-concept queries; tutorial queries auto-bump (see TUTORIAL_TOP_K)
TUTORIAL_TOP_K = 8  # multi-concept builds (touch + kill + debounce + placement) need 2-3 API families
KEYWORD_MATCH_LIMIT = 3  # chunks to pull per exact class/service name match

# Slang -> Roblox API terms. Creator-docs never says "deathtile"; it says
# BasePart.Touched + Humanoid.Health + Players:GetPlayerFromCharacter.
# Without this map a lowercase slang query yields zero keyword hits and a
# pure-vector TOP_K=3 miss (see evals/killbrick/). Keys are lowercase
# substrings matched against question.lower().
SLANG_TO_API_TERMS = {
    "deathtile": ["BasePart", "Humanoid", "Players", "Model"],
    "death tile": ["BasePart", "Humanoid", "Players", "Model"],
    "death-tile": ["BasePart", "Humanoid", "Players", "Model"],
    "kill brick": ["BasePart", "Humanoid", "Players", "Model"],
    "killbrick": ["BasePart", "Humanoid", "Players", "Model"],
    "kill brick": ["BasePart", "Humanoid", "Players", "Model"],
    "lava brick": ["BasePart", "Humanoid", "Players"],
    "lava tile": ["BasePart", "Humanoid", "Players"],
    "damage brick": ["BasePart", "Humanoid", "Players"],
    "obby kill": ["BasePart", "Humanoid", "Players"],
    "touch kill": ["BasePart", "Humanoid", "Players"],
    "touch damage": ["BasePart", "Humanoid", "Players"],
}

# Extra API sentence appended to the embedded query so bge-small (384d,
# 512tok, weak on slang synonyms) lands near Touched/Humanoid/Players docs.
QUERY_EXPANSION_SUFFIX = (
    " Roblox BasePart Touched event Humanoid Health "
    "Players GetPlayerFromCharacter server Script debounce"
)

# Kill-brick task router patterns (lowercase substrings). Used by ask.py /
# app.py to swap Pathfinding CRITICAL LAWS for kill-brick laws, and by
# is_tutorial_query() to bump TOP_K without a re-embed.
KILLBRICK_PATTERNS = (
    "deathtile", "death tile", "death-tile", "kill brick", "killbrick",
    "kill-brick", "lava brick", "damage brick", "touch kill", "obby kill",
)


def is_killbrick_query(question: str) -> bool:
    """True if the question is a kill-brick/deathtile build (slang-tolerant)."""
    q = (question or "").lower()
    return any(p in q for p in KILLBRICK_PATTERNS)


def get_slang_api_terms(question: str) -> list:
    """Return deduped Roblox API terms implied by slang in the question."""
    q = (question or "").lower()
    terms: list = []
    for slang, api_terms in SLANG_TO_API_TERMS.items():
        if slang in q:
            for t in api_terms:
                if t not in terms:
                    terms.append(t)
    return terms


def is_tutorial_query(question: str) -> bool:
    """
    Multi-concept build (e.g. touch + kill + debounce + placement) needs
    more than TOP_K=3: it spans BasePart + Humanoid + Players docs.
    Triggers on slang match OR 2+ tutorial signals.
    """
    if get_slang_api_terms(question):
        return True
    q = (question or "").lower()
    signals = ("touch", "kill", "die", "debounce", "where to put",
               "how do i make", "script", "lava", "debounce")
    return sum(1 for s in signals if s in q) >= 2


def effective_top_k(question: str, requested: int) -> int:
    """Auto-bump TOP_K for tutorial queries unless caller overrode it."""
    if requested == TOP_K and is_tutorial_query(question):
        return TUTORIAL_TOP_K
    return requested


def expand_query_for_embedding(question: str) -> str:
    """Append API terms so the embed lands near Touched/Humanoid/Players docs."""
    terms = get_slang_api_terms(question)
    if not terms:
        return question
    return question + QUERY_EXPANSION_SUFFIX

# Lazy singleton so Streamlit reruns / CLI loops don't reload FastEmbed (1-3s + ~200MB) per query.
# P0 fix for B6 — full pooling (psycopg_pool) deferred to P1 FastAPI layer.
_EMBED_MODEL_CACHE = {}


def get_embedding_model(model_name=MODEL_NAME):
    if model_name not in _EMBED_MODEL_CACHE:
        _EMBED_MODEL_CACHE[model_name] = TextEmbedding(model_name=model_name)
    return _EMBED_MODEL_CACHE[model_name]

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
    prefixed = QUERY_PREFIX + expand_query_for_embedding(question)
    return list(model.embed([prefixed]))[0].tolist()


def keyword_matches(cur, question):
    """Find chunks whose title exactly matches a CamelCase term mentioned in the question.

    Also includes slang-implied API terms (e.g. "deathtile" -> BasePart,
    Humanoid, Players) so lowercase slang queries still get guaranteed hits.
    """
    candidates = set(CAMELCASE_PATTERN.findall(question))
    candidates.update(get_slang_api_terms(question))
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
    # Kill-brick triad: Touched entry point is useless without the follow-up
    # APIs (what is the character? is it a real player? how to kill it?).
    # Return-type expansion can't discover these pairings on its own.
    "BasePart": ["Humanoid", "Players", "Model"],
    "Humanoid": ["Players", "BasePart"],
    "Players": ["Humanoid", "BasePart", "Model"],
    "Model": ["Humanoid", "Players"],
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

    top_k = effective_top_k(question, top_k)
    slang_terms = get_slang_api_terms(question)
    if slang_terms:
        print(f"Slang expansion: {slang_terms} (TOP_K={top_k})", flush=True)

    print(f"Loading embedding model ({MODEL_NAME})...", flush=True)
    model = get_embedding_model(MODEL_NAME)

    print(f"Embedding question: {question!r}", flush=True)
    query_vector = embed_query(model, question)

    print("Connecting to Supabase (10s timeout)...", flush=True)
    try:
        conn = psycopg2.connect(db_url, connect_timeout=10, options="-c statement_timeout=30000")
    except Exception as e:
        msg = str(e)
        # Supabase pooler vs direct mix-up is the #1 cause of ENOTFOUND/tenant errors on Windows.
        # Pooler host (aws-*.pooler.supabase.com) MUST use port 6543; direct db host (db.*.supabase.co) uses 5432.
        if "pooler.supabase.com" in (db_url or "") and ":5432" in db_url:
            raise SystemExit(
                "Supabase connection failed: you are using a pooler host with port 5432. "
                "Change :5432 to :6543 in SUPABASE_DB_URL, e.g. "
                "postgresql://postgres.<ref>@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres\n"
                f"Original error: {msg}"
            )
        if "tenant/user" in msg and "not found" in msg:
            raise SystemExit(
                "Supabase connection failed: tenant/user not found. Check SUPABASE_DB_URL format:\n"
                "  Pooler: postgresql://postgres.<project-ref>@aws-1-...pooler.supabase.com:6543/postgres\n"
                "  Direct: postgresql://postgres@db.<project-ref>.supabase.co:5432/postgres\n"
                f"Original error: {msg}"
            )
        raise
    try:
        register_vector(conn)
        cur = conn.cursor()
        try:
            # Hybrid retrieval: guaranteed exact-name matches + vector similarity search,
            # merged and deduplicated (exact matches take priority since distance=0).
            kw_results = keyword_matches(cur, question)
            vec_results = vector_matches(cur, query_vector, top_k)

            already_have = {r["title"] for r in kw_results} | {r["title"] for r in vec_results}
            expansion_results = expand_related_classes(cur, kw_results, already_have)
            already_have |= {r["title"] for r in expansion_results}
            companion_results = expand_companion_classes(cur, kw_results, already_have)
        finally:
            cur.close()
    finally:
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