"""
EFAR - Embed chunks for RAG

Reads chunks.jsonl (produced by chunk_docs.py) and generates an embedding
vector for each chunk using BAAI/bge-small-en-v1.5 (384 dimensions, runs
locally on CPU - no GPU or API costs needed for this step).

Output: chunks_embedded.jsonl - same fields as chunks.jsonl plus "embedding".
This is what gets uploaded to Supabase in the next step.
"""

import json
import os
from fastembed import TextEmbedding
from tqdm import tqdm

INPUT_FILE = "chunks.jsonl"
OUTPUT_FILE = "chunks_embedded.jsonl"
MODEL_NAME = "BAAI/bge-small-en-v1.5"
BATCH_SIZE = 64

# bge models are trained to expect a short instruction prefix on the *query*
# side (not the document side) for best retrieval performance. We apply that
# prefix later, at query time - not here, since these are the documents.


def main():
    with open(INPUT_FILE, encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f]

    print(f"Loaded {len(chunks)} chunks.", flush=True)

    # Resumable: a previous interrupted run leaves a partial OUTPUT_FILE.
    # Skip ids already embedded so a retry continues instead of restarting.
    # NOTE: chunk ids are global-sequential (see chunk_docs.py), so any
    # re-chunk that shifts ids invalidates old partial output — delete
    # chunks_embedded.jsonl first in that case.
    done_ids = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    done_ids.add(json.loads(line)["id"])
                except Exception:
                    pass
    todo = [c for c in chunks if c["id"] not in done_ids]
    print(f"Resume check: {len(done_ids)} already embedded, {len(todo)} remaining.", flush=True)
    if not todo:
        print("Nothing to do — output already complete.", flush=True)
        return

    print(f"Loading embedding model ({MODEL_NAME})...", flush=True)
    model = TextEmbedding(model_name=MODEL_NAME)
    print("Model loaded. Starting embedding pass...", flush=True)

    # Append per batch + flush, so an interrupted run keeps its progress
    # and the next run resumes via the check above.
    dim = None
    with open(OUTPUT_FILE, "a", encoding="utf-8") as out:
        with tqdm(total=len(todo), desc="Embedding chunks", unit="chunk") as pbar:
            for i in range(0, len(todo), BATCH_SIZE):
                batch = todo[i:i + BATCH_SIZE]
                batch_embeddings = list(model.embed([c["text"] for c in batch]))
                for chunk, emb in zip(batch, batch_embeddings):
                    chunk["embedding"] = emb.tolist()
                    out.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                    dim = len(chunk["embedding"])
                out.flush()
                pbar.update(len(batch))

    print(f"Embedding complete -> {OUTPUT_FILE}", flush=True)
    if dim:
        print(f"Embedding dimension: {dim}", flush=True)


if __name__ == "__main__":
    main()