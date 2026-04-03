"""
OATS RAG Seed Script
~~~~~~~~~~~~~~~~~~~~~
Indexes existing knowledge files into the LightRAG knowledge base.
Auto-discovers files from standard OATS locations.

Usage:
    python3 tools/rag_seed.py              # index everything discovered
    python3 tools/rag_seed.py --dry-run    # list files without indexing
    python3 tools/rag_seed.py --paths playbook.md memory/  # index specific files/dirs
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import os
import pathlib
import sys

# ---------------------------------------------------------------------------
# Reuse the exact same RAG config from rag_server.py
# ---------------------------------------------------------------------------

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rag_server import _build_rag  # noqa: E402


# ---------------------------------------------------------------------------
# Auto-discovery — finds knowledge files from standard OATS locations
# ---------------------------------------------------------------------------

PROJECT_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _tag_for_file(filepath: str) -> str:
    """Infer tags from file path and name."""
    parts = pathlib.Path(filepath).parts
    name = pathlib.Path(filepath).stem.lower()
    tags = []

    # Department detection
    dept_names = {"frontend", "backend", "devops", "content", "mcp", "strategy", "integration"}
    for part in parts:
        if part.lower() in dept_names:
            tags.append(f"department:{part.lower()}")
            break

    # Content type detection
    if "memory" in parts or "memory" in name:
        tags.append("memory")
    if "playbook" in name:
        tags.append("playbook")
    if "gotcha" in name:
        tags.append("gotcha")
    if "decision" in name:
        tags.append("decision")
    if "sprint" in name:
        tags.append("sprint")
    if "feedback" in name:
        tags.append("feedback")
    if "directive" in name:
        tags.append("directive")
    if "research" in name or "log" in parts:
        tags.append("research")
    if "rule" in parts or "rules" in parts:
        tags.append("rules")

    # Shared if it's in orchestra/memory or top-level
    if "orchestra" in parts and "memory" in parts:
        tags.append("shared")

    return ",".join(tags) if tags else "knowledge"


def discover_files() -> list[tuple[str, str]]:
    """Auto-discover knowledge files from standard OATS locations.

    Scans:
    - .orchestra/memory/*.md
    - .orchestra/departments/*/memory.md
    - .orchestra/departments/*/CLAUDE.md
    - .claude/rules/*.md
    - .claude/projects/*/memory/*.md (Claude Code user memory)

    Returns list of (filepath, tags) tuples.
    """
    manifest: list[tuple[str, str]] = []
    seen = set()

    search_patterns = [
        # Orchestra memory
        os.path.join(PROJECT_ROOT, ".orchestra", "memory", "*.md"),
        # Department memories
        os.path.join(PROJECT_ROOT, ".orchestra", "departments", "*", "memory.md"),
        # Department rules
        os.path.join(PROJECT_ROOT, ".orchestra", "departments", "*", "CLAUDE.md"),
        # Claude Code rules
        os.path.join(PROJECT_ROOT, ".claude", "rules", "*.md"),
        # Directives (completed)
        os.path.join(PROJECT_ROOT, ".orchestra", "directives", "done", "*.md"),
    ]

    # Claude Code user memory (find the right project dir)
    home = str(pathlib.Path.home())
    claude_memory_pattern = os.path.join(home, ".claude", "projects", "*", "memory", "*.md")
    search_patterns.append(claude_memory_pattern)

    for pattern in search_patterns:
        for filepath in sorted(glob.glob(pattern)):
            real = os.path.realpath(filepath)
            if real not in seen:
                seen.add(real)
                tags = _tag_for_file(filepath)
                manifest.append((filepath, tags))

    return manifest


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------


async def seed(
    dry_run: bool = False,
    paths: list[str] | None = None,
) -> None:
    if paths:
        # Manual paths — files or directories
        manifest = []
        for p in paths:
            path = pathlib.Path(p).resolve()
            if path.is_dir():
                for md in sorted(path.glob("**/*.md")):
                    manifest.append((str(md), _tag_for_file(str(md))))
            elif path.is_file():
                manifest.append((str(path), _tag_for_file(str(path))))
            else:
                print(f"SKIP: {p} (not found)")
    else:
        manifest = discover_files()

    print(f"RAG seed: {len(manifest)} files discovered\n")

    rag = _build_rag()

    if not dry_run:
        print("Initialising RAG storages...")
        await rag.initialize_storages()
        print()

    ok_count = 0
    skip_count = 0

    for filepath, tags in manifest:
        p = pathlib.Path(filepath)
        name = p.name

        if not p.exists():
            print(f"SKIP: {name} (file not found)")
            skip_count += 1
            continue

        text = p.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            print(f"SKIP: {name} (empty)")
            skip_count += 1
            continue

        char_count = len(text)

        if dry_run:
            print(f"  OK: {name} ({char_count} chars) [{tags}]")
            ok_count += 1
            continue

        tag_list = ", ".join(t.strip() for t in tags.split(",") if t.strip())
        document = f"[Source: {name}] [Tags: {tag_list}]\n\n{text}"

        try:
            await rag.ainsert(document)
            print(f"  OK: {name} ({char_count} chars) [{tags}]")
            ok_count += 1
        except Exception as exc:
            print(f"SKIP: {name} (error: {type(exc).__name__}: {exc})")
            skip_count += 1

    if not dry_run:
        print("\nFinalising RAG storages...")
        await rag.finalize_storages()

    print(f"\nDone. OK: {ok_count}  Skipped: {skip_count}  Total: {ok_count + skip_count}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the OATS RAG knowledge base with existing knowledge files."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files and sizes without actually indexing.",
    )
    parser.add_argument(
        "--paths",
        nargs="+",
        help="Specific files or directories to index (default: auto-discover).",
    )
    args = parser.parse_args()
    asyncio.run(seed(dry_run=args.dry_run, paths=args.paths))


if __name__ == "__main__":
    main()
