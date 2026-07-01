"""
EFAR - Upload embedded chunks to Supabase

Reads chunks_embedded.jsonl and bulk-inserts every row into the `doc_chunks`
table in your Supabase project (pgvector-backed).

Requires:
  pip install psycopg2-binary python-dotenv pgvector

Requires SUPABASE_DB_URL to be set in your .env file
(see docs_supabase_setup.md for how to get this).
"""

import json
import os

import psycopg2
from psycopg2.extras import execute_values
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv

INPUT_FILE = "chunks_embedded.jsonl"
BATCH_SIZE = 200

load_dotenv()


def main():
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit(
            "SUPABASE_DB_URL not found. Add it to your .env file - "
            "see docs_supabase_setup.md for how to get your connection string."
        )

    with open(INPUT_FILE, encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f]

    print(f"Loaded {len(chunks)} embedded chunks. Connecting to Supabase...")
    conn = psycopg2.connect(db_url)
    register_vector(conn)  # teaches psycopg2 how to send Python lists as pgvector 'vector' values
    cur = conn.cursor()

    insert_query = """
        insert into doc_chunks (id, title, section, source_type, source_file, text, embedding)
        values %s
        on conflict (id) do update set
            title = excluded.title,
            section = excluded.section,
            source_type = excluded.source_type,
            source_file = excluded.source_file,
            text = excluded.text,
            embedding = excluded.embedding
    """

    rows = [
        (
            c["id"],
            c["title"],
            c["section"],
            c["source_type"],
            c["source_file"],
            c["text"],
            c["embedding"],  # psycopg2 + pgvector adapter handles list -> vector
        )
        for c in chunks
    ]

    print(f"Uploading in batches of {BATCH_SIZE}...")
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        execute_values(cur, insert_query, batch, template=None)
        conn.commit()
        print(f"  uploaded {min(i + BATCH_SIZE, len(rows))}/{len(rows)}")

    cur.close()
    conn.close()
    print("Done. Verify in Supabase SQL Editor with: select count(*) from doc_chunks;")


if __name__ == "__main__":
    main()