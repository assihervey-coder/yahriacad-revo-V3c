"""Loader de standards — data/knowledge/standards (IPC, etc.)."""
from __future__ import annotations

from typing import List

from services.ai_engine.rag_engine import datasheets as _ds


def standards_dir() -> str:
    """Répertoire des standards (créé si absent)."""
    import os

    path = os.path.join(_ds.DATA_DIR, "standards")
    os.makedirs(path, exist_ok=True)
    return path


class StandardsLoader:
    """Loader spécialisé pour les standards de fabrication (IPC-2221, 2581...)."""

    def __init__(self, retriever=None) -> None:
        self.retriever = retriever

    def ingest(self) -> int:
        """Indexe data/knowledge/standards dans le retriever lié."""
        if self.retriever is None:
            raise RuntimeError("StandardsLoader nécessite un retriever")
        return self.retriever.index_dir(standards_dir())


def ensure_sample_corpus(base_dir: str | None = None) -> List[str]:
    """Assure le mini-corpus (délègue au corpus commun)."""
    return _ds.ensure_sample_corpus(base_dir)
