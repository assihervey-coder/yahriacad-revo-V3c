"""Loader de notes d'application — data/knowledge/application_notes."""
from __future__ import annotations

from typing import List

from services.ai_engine.rag_engine.datasheets import ensure_sample_corpus as _ensure


def application_notes_dir() -> str:
    """Répertoire des notes d'application (créé si absent)."""
    import os

    path = os.path.join(_ds.DATA_DIR, "application_notes")
    os.makedirs(path, exist_ok=True)
    return path


class ApplicationNotesLoader:
    """Loader spécialisé pour les notes d'application (USB-C, I2C, PDN...)."""

    def __init__(self, retriever=None) -> None:
        self.retriever = retriever

    def ingest(self) -> int:
        """Indexe data/knowledge/application_notes dans le retriever lié."""
        if self.retriever is None:
            raise RuntimeError("ApplicationNotesLoader nécessite un retriever")
        return self.retriever.index_dir(application_notes_dir())


def ensure_sample_corpus(base_dir: str | None = None) -> List[str]:
    """Assure le mini-corpus (délègue au corpus commun)."""
    return _ensure(base_dir)
