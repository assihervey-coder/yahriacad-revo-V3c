#!/usr/bin/env python3
"""Construction de l'index de connaissance (RAG) sur data/knowledge/.

Parcourt data/knowledge/ (datasheets, standards, application_notes,
manufacturing), indexe les documents avec le Retriever TF-IDF de
services.ai_engine.rag_engine puis persiste l'index JSON
(data/knowledge/index.json) rechargé au boot par l'API.

Usage :
    python scripts/data/build_knowledge_index.py
    python scripts/data/build_knowledge_index.py --knowledge-dir data/knowledge --smoke
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

DEFAULT_KNOWLEDGE_DIR = REPO_ROOT / "data" / "knowledge"
DEFAULT_INDEX_PATH = REPO_ROOT / "data" / "knowledge" / "index.json"


def main() -> int:
    """Point d'entrée : indexe le corpus, persiste l'index, test optionnel."""
    parser = argparse.ArgumentParser(description="Index RAG du corpus knowledge")
    parser.add_argument("--knowledge-dir", default=str(DEFAULT_KNOWLEDGE_DIR))
    parser.add_argument("--index", default=str(DEFAULT_INDEX_PATH),
                        help="fichier de sortie de l'index TF-IDF")
    parser.add_argument("--smoke", action="store_true",
                        help="après indexation, pose une question de contrôle")
    args = parser.parse_args()

    from services.ai_engine.rag_engine.retrieval import Retriever

    knowledge_dir = Path(args.knowledge_dir)
    if not knowledge_dir.exists():
        print(f"! dossier de connaissance introuvable : {knowledge_dir}", file=sys.stderr)
        return 2

    retriever = Retriever()
    n_chunks = retriever.index_dir(str(knowledge_dir))
    print(f"indexation : {n_chunks} chunks depuis {knowledge_dir.relative_to(REPO_ROOT)}")

    retriever.save(args.index)
    print(f"index persisté : {Path(args.index).relative_to(REPO_ROOT)}")

    if args.smoke:
        # Contrôle qualité : une question doit retrouver le bon document.
        retriever2 = Retriever()
        retriever2.load(args.index)
        hits = retriever2.search("clearance minimale IPC-2221", k=2)
        for hit in hits:
            src = Path(hit.source).name
            print(f"  top hit : {src} (score {hit.score:.3f})")
        if not hits:
            print("  ! aucune réponse — corpus vide ?", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
