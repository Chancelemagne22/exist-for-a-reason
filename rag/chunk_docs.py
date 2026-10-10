"""
EFAR - Roblox docs chunker

Reads the Roblox/creator-docs repo (already cloned via sparse checkout) and
produces chunked, embedding-ready text for RAG. Handles:

  - Engine API reference (classes, datatypes, enums, globals, libraries) -> YAML
  - Luau/scripting guides (e.g. characters/pathfinding.md)               -> Markdown

Output: chunks.jsonl, one JSON object per line:
  {
    "id": "class:PathfindingService:methods:0",
    "source_type": "class" | "datatype" | "enum" | "global" | "library" | "guide",
    "title": "PathfindingService",
    "section": "methods",
    "text": "..."
  }

This file is the source of truth for the next step (embedding + storing in
Supabase pgvector) - each line here becomes one row/vector.
"""

import glob
import json
import re
import yaml

DOCS_ROOT = "creator-docs/content/en-us"
OUTPUT_FILE = "chunks.jsonl"

MAX_CHARS = 2000       # soft ceiling per chunk (~500 tokens)
GROUP_SIZE = 5          # how many properties/methods/items to bundle per chunk


def clean(text):
    """Strip Roblox's cross-reference markup like `Class.Foo` / `Datatype.Bar` into plain text."""
    if not text:
        return ""
    text = re.sub(r"`Class\.([A-Za-z0-9_.:|]+)`", lambda m: m.group(1).split("|")[-1], text)
    text = re.sub(r"`Datatype\.([A-Za-z0-9_.:|]+)`", lambda m: m.group(1).split("|")[-1], text)
    text = re.sub(r"`Enum\.([A-Za-z0-9_.:|]+)`", lambda m: "Enum." + m.group(1).split("|")[-1], text)
    return text.strip()


def format_params(params):
    if not params:
        return ""
    parts = []
    for p in params:
        seg = f"{p.get('name', '?')}: {p.get('type', 'any')}"
        if p.get("default"):
            seg += f" = {p['default']}"
        parts.append(seg)
    return ", ".join(parts)


def chunk_members(class_name, members, kind, prefix_sep):
    """Group properties/methods/events/callbacks into batches of GROUP_SIZE, formatted as readable text."""
    chunks = []
    if not members:
        return chunks
    for i in range(0, len(members), GROUP_SIZE):
        batch = members[i:i + GROUP_SIZE]
        lines = []
        for m in batch:
            name = m.get("name", "?")
            # Some members (e.g. PathfindingService:CreatePath) keep their
            # real explanatory text in `description` instead of `summary`,
            # with `summary` left as ''. Fall back to description when
            # summary is empty; if both are present and differ, keep both -
            # summary is often a one-liner while description adds detail
            # (e.g. valid keys/values for a parameters table).
            summary = clean(m.get("summary", ""))
            description = clean(m.get("description", ""))
            if description and description != summary:
                summary = f"{summary}\n\n{description}".strip() if summary else description
            deprecated = m.get("deprecation_message")
            if kind == "methods":
                params = format_params(m.get("parameters"))
                returns = m.get("returns", [{}])
                ret_type = returns[0].get("type", "void") if returns else "void"
                sig = f"{class_name}{prefix_sep}{name.split(prefix_sep)[-1] if prefix_sep in name else name}({params}): {ret_type}"
            elif kind == "properties":
                sig = f"{class_name}.{name.split('.')[-1] if '.' in name else name}: {m.get('type', 'any')}"
            elif kind == "events":
                params = format_params(m.get("parameters"))
                sig = f"{class_name}.{name.split('.')[-1] if '.' in name else name}({params}) [event]"
            elif kind == "items":  # enum items
                sig = f"{class_name}.{name} = {m.get('value')}"
            else:
                sig = name
            line = f"- {sig}"
            if summary:
                line += f"\n  {summary}"
            if deprecated:
                line += f"\n  DEPRECATED: {clean(deprecated)}"
            lines.append(line)
        text = f"{class_name} - {kind}:\n" + "\n".join(lines)
        chunks.append({"section": kind, "text": text})
    return chunks


def process_yaml_doc(filepath):
    # encoding="utf-8" is required on Windows: the default charmap codec
    # chokes on non-ASCII bytes (e.g. BasePart.yaml byte 0x81) and silently
    # drops the whole class — BasePart.Touched grounding depends on this.
    with open(filepath, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "name" not in data:
        return []

    name = data["name"]
    doc_type = data.get("type", "unknown")
    out = []

    # Overview chunk: summary + description + inheritance
    overview_parts = [f"{name} ({doc_type})"]
    if data.get("summary"):
        overview_parts.append(clean(data["summary"]))
    if data.get("description"):
        overview_parts.append(clean(data["description"]))
    if data.get("inherits"):
        overview_parts.append(f"Inherits from: {', '.join(data['inherits'])}")
    if data.get("deprecation_message"):
        overview_parts.append(f"DEPRECATED: {clean(data['deprecation_message'])}")
    overview_text = "\n\n".join(overview_parts)[:MAX_CHARS]
    out.append({"section": "overview", "text": overview_text})

    # Member chunks - covers class/datatype/library/global shapes
    member_map = {
        "properties": "properties",
        "methods": "methods",
        "functions": "methods",     # datatypes/libraries call them "functions"
        "events": "events",
        "callbacks": "events",
        "constructors": "methods",
        "items": "items",           # enums
    }
    for key, kind in member_map.items():
        members = data.get(key)
        if members:
            out.extend(chunk_members(name, members, kind, ":" if kind == "methods" else "."))

    for c in out:
        c["title"] = name
        c["source_type"] = doc_type
        c["source_file"] = filepath

    return out


def process_markdown_doc(filepath):
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    # Strip frontmatter if present
    content = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)

    title_match = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else filepath

    # Split on ## headers (keep the header with its section)
    sections = re.split(r"\n(?=##\s+)", content)
    out = []
    for sec in sections:
        sec = sec.strip()
        if len(sec) < 40:  # skip near-empty fragments
            continue
        # Further split if a section is too long
        for i in range(0, len(sec), MAX_CHARS):
            piece = sec[i:i + MAX_CHARS].strip()
            if piece:
                out.append({
                    "section": "guide",
                    "text": piece,
                    "title": title,
                    "source_type": "guide",
                    "source_file": filepath,
                })
    return out


def main():
    all_chunks = []

    # Gather and normalize YAML reference files
    raw_yaml_files = glob.glob(f"{DOCS_ROOT}/reference/engine/**/*.yaml", recursive=True)
    yaml_files = sorted(list(set(fp.replace("\\", "/") for fp in raw_yaml_files)))
    
    for fp in yaml_files:
        try:
            all_chunks.extend(process_yaml_doc(fp))
        except Exception as e:
            print(f"  skip (yaml parse error): {fp} -> {e}")

    # Gather Markdown files across directories
    raw_md_files = glob.glob(f"{DOCS_ROOT}/luau/**/*.md", recursive=True)
    raw_md_files += glob.glob(f"{DOCS_ROOT}/scripting/**/*.md", recursive=True)
    raw_md_files += glob.glob(f"{DOCS_ROOT}/characters/**/*.md", recursive=True)
    # Custom game docs (README promise): rag/custom-docs/**/*.md — e.g. your
    # own kill-brick pattern page. Optional dir; missing = zero files.
    raw_md_files += glob.glob("custom-docs/**/*.md", recursive=True)
    
    # Enforce forward-slashes, eliminate overlaps via set(), and sort for deterministic IDs
    md_files = sorted(list(set(fp.replace("\\", "/") for fp in raw_md_files)))
    
    for fp in md_files:
        try:
            all_chunks.extend(process_markdown_doc(fp))
        except Exception as e:
            print(f"  skip (md parse error): {fp} -> {e}")

    # Generate deterministic sequential IDs
    for idx, c in enumerate(all_chunks):
        safe_title = re.sub(r"[^A-Za-z0-9]+", "_", c["title"])[:50]
        c["id"] = f"{c['source_type']}:{safe_title}:{c['section']}:{idx}"

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"\nWrote {len(all_chunks)} chunks from {len(yaml_files)} YAML docs + {len(md_files)} Markdown guides -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()