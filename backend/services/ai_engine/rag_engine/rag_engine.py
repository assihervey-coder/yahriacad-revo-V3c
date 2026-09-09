"""RAGEngine — question/réponse sur le corpus avec synthèse LLM ou extractif."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from shared.utilities import get_logger, new_id

from services.ai_engine.llm_orchestrator.orchestrator import LLMOrchestrator
from services.ai_engine.rag_engine.retrieval import RetrievedChunk, Retriever

log = get_logger("ai_engine.rag.engine")

_UNANSWERED_FILE = "data/knowledge/unanswered_questions.jsonl"


@dataclass
class RAGAnswer:
    """Réponse RAG : texte, sources utilisées, confiance estimée."""

    text: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0


class RAGEngine:
    """Moteur RAG : retriever TF-IDF + synthèse LLM (sinon mode extractif)."""

    def __init__(self, retriever: Retriever | None = None,
                 orchestrator: LLMOrchestrator | None = None,
                 unanswered_path: str = _UNANSWERED_FILE) -> None:
        self.retriever = retriever or Retriever()
        self.orchestrator = orchestrator
        self.unanswered_path = unanswered_path
        self._history: list[dict[str, Any]] = []

    # -------------------------------------------------------------- ingest
    def ingest_dir(self, path: str) -> int:
        """Indexe un répertoire de connaissance (.md/.txt/.json)."""
        return self.retriever.index_dir(path)

    def ingest_text(self, text: str, source: str) -> int:
        """Indexe un texte direct."""
        return self.retriever.add_text(text, source)

    # -------------------------------------------------------------- answer
    def answer(self, question: str, k: int = 5) -> RAGAnswer:
        """Répond à une question à partir du corpus indexé."""
        chunks = self.retriever.search(question, k=k)
        if not chunks:
            self._save_unanswered(question, reason="aucun_chunk")
            return RAGAnswer(
                text="Je n'ai pas trouvé d'information pertinente dans le "
                     "corpus de connaissance pour cette question.",
                sources=[], confidence=0.05)

        top_score = chunks[0].score
        if self.orchestrator is not None:
            try:
                text = self._synthesize(question, chunks)
                mode = "llm"
            except Exception as exc:
                log.warning("synthèse LLM échouée (%s) → extractif", exc)
                text, mode = self._extractive(chunks), "extractive"
        else:
            text, mode = self._extractive(chunks), "extractive"

        # confiance : score du meilleur chunk + quantité de support
        confidence = min(0.95, 0.3 + 0.5 * min(1.0, top_score) + 0.05 * (len(chunks) - 1))
        if mode == "extractive" and top_score < 0.35:
            confidence *= 0.6
            self._save_unanswered(question, reason="score_faible")

        ans = RAGAnswer(
            text=text,
            sources=[{"source": c.source, "score": c.score,
                      "excerpt": c.content[:160]} for c in chunks],
            confidence=round(confidence, 3),
        )
        self._history.append({"ts": time.time(), "question": question,
                              "mode": mode, "n_sources": len(chunks)})
        return ans

    # ------------------------------------------------------------ internals
    @staticmethod
    def _extractive(chunks: list[RetrievedChunk]) -> str:
        """Mode extractif (mock) : meilleurs passages concaténés + sources."""
        parts = ["Passages les plus pertinents du corpus :"]
        for i, c in enumerate(chunks, 1):
            parts.append(f"[{i}] ({c.source}) {c.content.strip()}")
        return "\n\n".join(parts)

    def _synthesize(self, question: str, chunks: list[RetrievedChunk]) -> str:
        assert self.orchestrator is not None
        context = "\n\n".join(
            f"--- Source: {c.source} ---\n{c.content}" for c in chunks)
        return self.orchestrator.ask(
            question=(
                f"Question : {question}\n\nContexte (extraits du corpus) :\n{context}\n\n"
                "Réponds en te basant UNIQUEMENT sur le contexte, cite les "
                "sources entre crochets [source]."
            ),
            system=(
                "Tu es l'agent RESEARCHER. Tu réponds à partir des extraits "
                "fournis, sans inventer. Si l'information manque, dis-le."
            ),
            temperature=0.2,
        )

    def _save_unanswered(self, question: str, reason: str) -> None:
        """Sauvegarde les questions sans réponse pour enrichissement futur."""
        try:
            os.makedirs(os.path.dirname(self.unanswered_path) or ".", exist_ok=True)
            with open(self.unanswered_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "id": new_id("q"), "ts": time.time(),
                    "question": question, "reason": reason,
                }, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.debug("sauvegarde unanswered impossible: %s", exc)


def get_rag_engine() -> RAGEngine:
    """RAGEngine singleton (retriever neuf, orchestrateur mock par défaut)."""
    return RAGEngine(orchestrator=None)
