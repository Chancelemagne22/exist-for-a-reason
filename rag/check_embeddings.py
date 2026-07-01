import json

with open("chunks_embedded.jsonl", encoding="utf-8") as f:
    lines = [json.loads(l) for l in f]

print(f"Total chunks: {len(lines)}")
print(f"Embedding dim: {len(lines[0]['embedding'])}")
print(f"Sample titles: {[c['title'] for c in lines[:5]]}")

missing = [c for c in lines if not c.get("embedding")]
print(f"Chunks missing embeddings: {len(missing)}")