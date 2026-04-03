"""
OATS RAG MCP Server
~~~~~~~~~~~~~~~~~~~~
FastMCP server wrapping LightRAG for knowledge-graph-augmented retrieval.
Shared knowledge base for all orchestra agents.

Embeddings: fastembed (ONNX, ~200MB, no PyTorch)
LLM: passthrough by default (instant, no Ollama needed for queries)
     Set RAG_USE_OLLAMA=1 for real entity extraction (builds knowledge graph)

Queries use only_need_context=True — returns raw chunks, no LLM synthesis.
Agents do their own reasoning from the chunks.

Setup:
    pip install lightrag-hku fastembed mcp[cli]

Run:
    python3 tools/rag_server.py                     # stdio transport
    RAG_USE_OLLAMA=1 python3 tools/rag_server.py    # with entity extraction

Config:
    Reads from orchestra/config.json "rag" section:
    {
      "rag": {
        "enabled": true,
        "working_dir": ".rag",
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "use_ollama": false,
        "ollama_model": "qwen2:1.5b"
      }
    }
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
from typing import Optional

import numpy as np
from fastembed import TextEmbedding
from lightrag import LightRAG, QueryParam
from lightrag.utils import wrap_embedding_func_with_attrs
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config — read from orchestra/config.json or environment
# ---------------------------------------------------------------------------

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "orchestra" / "config.json"


def _load_rag_config() -> dict:
    """Load RAG config from orchestra/config.json."""
    defaults = {
        "working_dir": ".rag",
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "use_ollama": False,
        "ollama_model": "qwen2:1.5b",
    }
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH) as f:
                config = json.load(f)
            rag_config = config.get("rag", {})
            defaults.update({k: v for k, v in rag_config.items() if v is not None})
        except (json.JSONDecodeError, KeyError):
            pass
    return defaults


_CONFIG = _load_rag_config()

RAG_DIR = str(_PROJECT_ROOT / _CONFIG["working_dir"])
LLM_MODEL = os.environ.get("RAG_LLM_MODEL", _CONFIG["ollama_model"])
EMBEDDING_MODEL_NAME = _CONFIG["embedding_model"]
EMBEDDING_DIM = 384
EMBEDDING_MAX_TOKENS = 512

os.makedirs(RAG_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Embedding — fastembed (ONNX, ~200MB, no PyTorch dependency)
# ---------------------------------------------------------------------------

_embed_model: TextEmbedding | None = None


def _get_embed_model() -> TextEmbedding:
    global _embed_model
    if _embed_model is None:
        _embed_model = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)
    return _embed_model


@wrap_embedding_func_with_attrs(
    embedding_dim=EMBEDDING_DIM,
    max_token_size=EMBEDDING_MAX_TOKENS,
    model_name=EMBEDDING_MODEL_NAME,
)
async def local_embedding(texts: list[str]) -> np.ndarray:
    model = _get_embed_model()
    return np.array(list(model.embed(texts)))


# ---------------------------------------------------------------------------
# Passthrough LLM — instant, no Ollama needed
# ---------------------------------------------------------------------------


async def _passthrough_llm(prompt, **kwargs):
    """Passthrough LLM for entity extraction during insert.

    Returns the LightRAG extraction delimiter to cleanly signal
    'no entities found'. Chunks still get embedded via fastembed.

    For real entity extraction (builds the knowledge graph):
        RAG_USE_OLLAMA=1 python3 tools/rag_server.py
    """
    return "<|COMPLETE|>"


# ---------------------------------------------------------------------------
# LightRAG instance — created once, initialised lazily
# ---------------------------------------------------------------------------

_rag: LightRAG | None = None
_rag_ready = False
_rag_lock = asyncio.Lock()


def _build_rag() -> LightRAG:
    """Construct (but don't initialise storages for) the LightRAG instance."""
    use_ollama = (
        os.environ.get("RAG_USE_OLLAMA", "0") == "1"
        or _CONFIG.get("use_ollama", False)
    )

    if use_ollama:
        from lightrag.llm.ollama import ollama_model_complete
        llm_func = ollama_model_complete
    else:
        llm_func = _passthrough_llm

    return LightRAG(
        working_dir=RAG_DIR,
        llm_model_func=llm_func,
        llm_model_name=LLM_MODEL,
        embedding_func=local_embedding,
        entity_extract_max_gleaning=0 if not use_ollama else 1,
        cosine_better_than_threshold=0.1,
    )


async def _get_rag() -> LightRAG:
    """Return the initialised LightRAG instance (thread-safe)."""
    global _rag, _rag_ready
    if _rag_ready and _rag is not None:
        return _rag
    async with _rag_lock:
        if _rag_ready and _rag is not None:
            return _rag
        if _rag is None:
            _rag = _build_rag()
        await _rag.initialize_storages()
        _rag_ready = True
        return _rag


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("oats-rag")


@mcp.tool()
async def rag_query(
    question: str,
    scope: str = "",
    max_tokens: int = 4000,
) -> str:
    """Search the shared knowledge base.

    Returns relevant knowledge chunks. Use this instead of reading
    full memory/playbook/gotcha files into your context.

    Args:
        question: What you want to know. Be specific.
        scope: Optional comma-separated tags to filter (e.g. "department:backend,gotcha").
        max_tokens: Approximate max response length.
    """
    try:
        rag = await _get_rag()
        params = QueryParam(
            mode="naive",
            only_need_context=True,
            top_k=10,
            max_total_tokens=max_tokens,
        )
        if scope:
            params.hl_keywords = [t.strip() for t in scope.split(",") if t.strip()]

        result = await rag.aquery(question, param=params)
        text = str(result).strip()

        if not text or len(text) < 20 or "no relevant" in text.lower():
            return f"No relevant knowledge found for: {question}"

        char_limit = max_tokens * 4
        if len(text) > char_limit:
            text = text[:char_limit] + "\n...[truncated]"

        return text
    except Exception as exc:
        return f"[rag_query error] {type(exc).__name__}: {exc}"


@mcp.tool()
async def rag_store(content: str, tags: str = "") -> str:
    """Store new knowledge in the shared knowledge base.

    Use this to persist gotchas, decisions, patterns, and strategic verdicts.

    Args:
        content: The knowledge to store. Be specific and self-contained.
        tags: Comma-separated tags (e.g. "department:backend,domain:database,gotcha").
    """
    try:
        rag = await _get_rag()
        text = content
        if tags:
            tag_list = ", ".join(t.strip() for t in tags.split(",") if t.strip())
            text = f"[Tags: {tag_list}]\n\n{content}"
        await rag.ainsert(text)
        return f"Stored successfully. Tags: {tags or 'none'}"
    except Exception as exc:
        return f"[rag_store error] {type(exc).__name__}: {exc}"


@mcp.tool()
async def rag_store_document(file_path: str, tags: str = "") -> str:
    """Index an entire file into the knowledge base.

    Use for bulk-loading existing knowledge files.

    Args:
        file_path: Absolute path to the file.
        tags: Comma-separated tags for all content in this file.
    """
    try:
        path = pathlib.Path(file_path).expanduser().resolve()
        if not path.is_file():
            return f"File not found: {path}"
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return f"File is empty: {path}"

        header = f"[Source: {path.name}]"
        if tags:
            tag_list = ", ".join(t.strip() for t in tags.split(",") if t.strip())
            header += f" [Tags: {tag_list}]"
        full_content = f"{header}\n\n{text}"

        rag = await _get_rag()
        await rag.ainsert(full_content)
        return f"Indexed {path.name} ({len(text)} chars). Tags: {tags or 'none'}"
    except Exception as exc:
        return f"[rag_store_document error] {type(exc).__name__}: {exc}"


@mcp.tool()
async def rag_delete(entity_name: str) -> str:
    """Remove knowledge about an entity from the knowledge base.

    Args:
        entity_name: Name of the entity to remove.
    """
    try:
        rag = await _get_rag()
        await rag.adelete_by_entity(entity_name)
        return f"Deleted entity: {entity_name}"
    except Exception as exc:
        return f"[rag_delete error] {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def _shutdown() -> None:
    global _rag, _rag_ready
    if _rag is not None and _rag_ready:
        try:
            await _rag.finalize_storages()
        except Exception:
            pass
        _rag_ready = False


import atexit
import signal


def _sync_shutdown(*_args) -> None:
    if _rag is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_shutdown())
            else:
                loop.run_until_complete(_shutdown())
        except Exception:
            pass


atexit.register(_sync_shutdown)
signal.signal(signal.SIGTERM, _sync_shutdown)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
