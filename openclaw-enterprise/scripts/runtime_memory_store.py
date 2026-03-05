#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import psycopg2


@dataclass
class EmbeddingConfig:
    provider: str
    model: str
    dim: int


def load_embedding_config() -> EmbeddingConfig:
    """Decision explicita de embeddings.

    EMBEDDING_PROVIDER:
    - openai  -> text-embedding-3-small
    - ollama  -> nomic-embed-text (via OLLAMA_BASE_URL)
    """
    provider = os.getenv("EMBEDDING_PROVIDER", "ollama").strip().lower()
    if provider == "openai":
        model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        return EmbeddingConfig(provider=provider, model=model, dim=768)
    model = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    return EmbeddingConfig(provider="ollama", model=model, dim=768)


class MemoryStore:
    """Vector memory con almacenamiento en PostgreSQL + pgvector."""

    def __init__(self) -> None:
        self.cfg = load_embedding_config()
        self.db_url = self._db_url()
        self.vector_enabled = False
        self._ensure_tables()

    @staticmethod
    def _db_url() -> str:
        env_url = os.getenv("OPENCLAW_DB_URL", "").strip()
        if env_url:
            return env_url
        env_file = Path.home() / "apps" / ".env.production"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENCLAW_DB_URL="):
                    return line.split("=", 1)[1].strip()
        raise RuntimeError("OPENCLAW_DB_URL no configurado")

    @staticmethod
    def _vector_literal(values: list[float]) -> str:
        return "[" + ",".join(f"{v:.8f}" for v in values) + "]"

    def _normalize_dim(self, embedding: list[float]) -> list[float]:
        dim = self.cfg.dim
        if len(embedding) == dim:
            return embedding
        if len(embedding) > dim:
            return embedding[:dim]
        return embedding + [0.0] * (dim - len(embedding))

    def _embed(self, text: str) -> list[float]:
        if self.cfg.provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY no configurada para embeddings OpenAI")
            payload = {"model": self.cfg.model, "input": text}
            req = urllib.request.Request(
                "https://api.openai.com/v1/embeddings",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310
                data = json.loads(r.read().decode("utf-8"))
            emb = data["data"][0]["embedding"]
            return self._normalize_dim([float(x) for x in emb])

        ollama_base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        payload = {"model": self.cfg.model, "prompt": text}
        req = urllib.request.Request(
            f"{ollama_base}/api/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310
            data = json.loads(r.read().decode("utf-8"))
        emb = data.get("embedding", [])
        return self._normalize_dim([float(x) for x in emb])

    def _ensure_tables(self) -> None:
        ddl_text_tmpl = """
        CREATE TABLE IF NOT EXISTS {schema}.memory_entries (
          id BIGSERIAL PRIMARY KEY,
          execution_id TEXT NOT NULL,
          agent_id TEXT NOT NULL,
          content TEXT NOT NULL,
          metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """

        ddl_vector_tmpl = """
        CREATE TABLE IF NOT EXISTS {schema}.memory_vectors (
          id BIGSERIAL PRIMARY KEY,
          execution_id TEXT NOT NULL,
          agent_id TEXT NOT NULL,
          content TEXT NOT NULL,
          metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
          embedding vector(768) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
        with psycopg2.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM pg_extension WHERE extname='vector';"
                )
                self.vector_enabled = cur.fetchone() is not None
                for schema in ("mem_finance", "mem_tech"):
                    cur.execute(ddl_text_tmpl.format(schema=schema))
                    if self.vector_enabled:
                        cur.execute(ddl_vector_tmpl.format(schema=schema))

    def save_execution_artifact(self, domain: str, text: str, metadata: dict) -> None:
        schema = domain if domain in ("mem_finance", "mem_tech") else "mem_tech"
        with psycopg2.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(  # nosec B608
                    f"""
                    INSERT INTO {schema}.memory_entries
                    (execution_id, agent_id, content, metadata)
                    VALUES (%s, %s, %s, %s::jsonb)
                    """,
                    (
                        str(metadata.get("execution_id", "")),
                        str(metadata.get("agent_id", "")),
                        text,
                        json.dumps(metadata),
                    ),
                )
                if not self.vector_enabled:
                    return

                embedding = self._embed(text)
                v = self._vector_literal(embedding)
                cur.execute(  # nosec B608
                    f"""
                    INSERT INTO {schema}.memory_vectors
                    (execution_id, agent_id, content, metadata, embedding)
                    VALUES (%s, %s, %s, %s::jsonb, %s::vector)
                    """,
                    (
                        str(metadata.get("execution_id", "")),
                        str(metadata.get("agent_id", "")),
                        text,
                        json.dumps(metadata),
                        v,
                    ),
                )

    def retrieve_context(self, domain: str, query: str, k: int = 5) -> list[dict]:
        schema = domain if domain in ("mem_finance", "mem_tech") else "mem_tech"
        with psycopg2.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                if self.vector_enabled:
                    embedding = self._embed(query)
                    v = self._vector_literal(embedding)
                    cur.execute(  # nosec B608
                        f"""
                        SELECT content, metadata, (embedding <=> %s::vector) AS distance
                        FROM {schema}.memory_vectors
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (v, v, int(k)),
                    )
                    rows = cur.fetchall()
                else:
                    cur.execute(  # nosec B608
                        f"""
                        SELECT content, metadata, NULL::float8 AS distance
                        FROM {schema}.memory_entries
                        WHERE content ILIKE %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (f"%{query[:64]}%", int(k)),
                    )
                    rows = cur.fetchall()
        return [
            {"content": r[0], "metadata": r[1], "distance": float(r[2]) if r[2] is not None else None}
            for r in rows
        ]
