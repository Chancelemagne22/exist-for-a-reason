"""
EFAR - Embed chunks for RAG

Reads chunks.jsonl (produced by chunk_docs.py) and generates an embedding
vector for each chunk using BAAI/bge-small-en-v1.5 (384 dimensions, runs
locally on CPU - no GPU or API costs needed for this step).

Output: chunks_embedded.jsonl - same fields as chunks.jsonl plus "embedding".
This is what gets uploaded to Supabase in the next step.
"""

import json
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
    print(f"Loading embedding model ({MODEL_NAME})...", flush=True)
    model = TextEmbedding(model_name=MODEL_NAME)
    print("Model loaded. Starting embedding pass...", flush=True)

    texts = [c["text"] for c in chunks]

    # Process in visible batches instead of one silent bulk call, so progress
    # is always visible and never looks frozen.
    all_embeddings = []
    with tqdm(total=len(texts), desc="Embedding chunks", unit="chunk") as pbar:
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            batch_embeddings = list(model.embed(batch))
            all_embeddings.extend(batch_embeddings)
            pbar.update(len(batch))

    print("Embedding complete. Writing output file...", flush=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for chunk, emb in zip(chunks, all_embeddings):
            chunk["embedding"] = emb.tolist()
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    print(f"Wrote {len(chunks)} embedded chunks -> {OUTPUT_FILE}", flush=True)
    print(f"Embedding dimension: {len(all_embeddings[0])}", flush=True)


if __name__ == "__main__":
    main()