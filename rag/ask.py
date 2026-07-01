"""
EFAR - Ask (full RAG pipeline, end to end)

Question -> retrieve relevant Roblox doc chunks from Supabase -> build a
grounded prompt -> send to your Modal endpoint -> print the answer.

This is the same logic that will eventually live in the Next.js API route -
this script just lets us test and tune it before wiring up a frontend.

Requires:
  pip install fastembed psycopg2-binary python-dotenv pgvector requests

Requires in .env:
  SUPABASE_DB_URL=...
  MODAL_ENDPOINT_URL=...   (e.g. https://your-workspace--efar-serve.modal.run)
"""

import os
import sys

import requests
from dotenv import load_dotenv

from retrieve import retrieve, build_context_block

load_dotenv()

SYSTEM_PROMPT_FILE = "../system_prompt.md"  # adjust path if your layout differs
TOP_K = 5
MAX_TOKENS = 900
TEMPERATURE = 0.3
REPETITION_PENALTY = 1.15


def load_game_context():
    try:
        with open(SYSTEM_PROMPT_FILE, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""  # fine to run without it, just less personalized


def build_messages(question, context_block, game_context):
    system_parts = [
        "You are EFAR, a coding assistant specialized in Roblox development (Luau, Studio APIs, game architecture).",
        "Answer using the reference documentation provided below whenever it's relevant. "
        "If the documentation doesn't cover something, say so rather than guessing or inventing API details.",
    ]
    if game_context.strip():
        system_parts.append("Project context:\n" + game_context)
    if context_block.strip():
        system_parts.append("Reference documentation:\n" + context_block)

    system_message = "\n\n".join(system_parts)

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": question},
    ]


def ask_modal(messages):
    endpoint = os.environ.get("MODAL_ENDPOINT_URL")
    if not endpoint:
        raise SystemExit("MODAL_ENDPOINT_URL not found in .env")

    url = endpoint.rstrip("/")
    if not url.endswith("/v1/chat/completions"):
        url += "/v1/chat/completions"
    payload = {
        "model": "roblox-coder",
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "repetition_penalty": REPETITION_PENALTY,
    }

    print("Sending to Modal (cold start may take 15-40s if idle)...")
    resp = requests.post(url, json=payload, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"], data.get("usage", {})


def main():
    question = " ".join(sys.argv[1:]) or "How do I use PathfindingService to move an NPC?"

    print(f"Question: {question}\n")
    print("Retrieving relevant docs...")
    results = retrieve(question, top_k=TOP_K)
    context_block = build_context_block(results)

    print(f"Retrieved {len(results)} chunks: {[r['title'] for r in results]}\n")

    game_context = load_game_context()
    messages = build_messages(question, context_block, game_context)

    answer, usage = ask_modal(messages)

    print("\n" + "=" * 60)
    print("ANSWER:")
    print("=" * 60)
    print(answer)
    print("\n" + "=" * 60)
    print(f"Tokens used: {usage}")


if __name__ == "__main__":
    main()