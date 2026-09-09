"""Retriever TF-IDF maison (numpy) — chunking paragraphe, persistance JSON.

Matrice d'indexation stockée en dictionnaires (sparse logique) et
convertie en numpy dense uniquement au moment du scoring — suffisant
pour un corpus de connaissance (milliers de chunks).
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import re
from dataclasses import dataclass

import numpy as np
from shared.utilities import get_logger

log = get_logger("ai_engine.rag.retrieval")

_TOKEN_RE = re.compile(r"[a-zA-Zàâäéèêëîïôöùûüç0-9]+", re.UNICODE)
_STOPWORDS = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "à", "a",
    "en", "dans", "sur", "pour", "avec", "sans", "est", "sont", "que", "qui",
    "the", "of", "to", "and", "in", "on", "for", "with", "is", "are", "this",
    "that", "it", "as", "by", "be", "at", "or", "from", "par", "au", "aux",
}


@dataclass
class RetrievedChunk:
    """Fragment récupéré avec sa source et son score de pertinence."""

    content: str
    source: str
    score: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {"content": self.content, "source": self.source, "score": self.score}


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)
            if len(t) > 1 and t.lower() not in _STOPWORDS]


def _split_paragraphs(text: str, target_chars: int = 500) -> list[str]:
    """Chunking par paragraphe, fusion des petits, coupure des longs (~500c)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        if len(para) > target_chars * 1.6:
            # coupure par phrases
            sentences = re.split(r"(?<=[.!?])\s+", para)
            sub = ""
            for sent in sentences:
                if len(sub) + len(sent) > target_chars and sub:
                    chunks.append(sub.strip())
                    sub = ""
                sub += " " + sent
            if sub.strip():
                chunks.append(sub.strip())
            buf = ""
            continue
        if len(buf) + len(para) <= target_chars:
            buf = f"{buf}\n\n{para}".strip()
        else:
            if buf:
                chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)
    return chunks


class Retriever:
    """Index TF-IDF (numpy) sur des chunks de documents markdown/texte/json."""

    def __init__(self) -> None:
        self._chunks: list[RetrievedChunk] = []
        self._doc_counts: list[dict[str, int]] = []     # tf par chunk
        self._df: dict[str, int] = {}                   # document frequency
        self._vocab_size = 0

    # -------------------------------------------------------------- indexing
    def add_text(self, text: str, source: str) -> int:
        """Indexe un texte (chunking paragraphe ~500 chars) → nb chunks ajoutés."""
        n_added = 0
        for chunk in _split_paragraphs(text):
            tokens = _tokenize(chunk)
            if not tokens:
                continue
            tf: dict[str, int] = {}
            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1
            self._chunks.append(RetrievedChunk(content=chunk, source=source))
            self._doc_counts.append(tf)
            for tok in tf:
                self._df[tok] = self._df.get(tok, 0) + 1
            n_added += 1
        self._vocab_size = len(self._df)
        return n_added

    def index_dir(self, path: str) -> int:
        """Indexe récursivement les .md/.txt/.json d'un répertoire."""
        total = 0
        if not os.path.isdir(path):
            log.warning("index_dir: %s n'est pas un répertoire", path)
            return 0
        for root, _dirs, files in os.walk(path):
            for fname in sorted(files):
                if not fname.lower().endswith((".md", ".txt", ".json")):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        text = f.read()
                except (OSError, UnicodeDecodeError) as exc:
                    log.warning("lecture impossible %s: %s", fpath, exc)
                    continue
                if fname.lower().endswith(".json"):
                    with contextlib.suppress(ValueError):
                        text = json.dumps(json.loads(text), ensure_ascii=False, indent=1)
                total += self.add_text(text, source=os.path.relpath(fpath, path))
        log.info("index_dir(%s): %d chunks indexés", path, total)
        return total

    # ---------------------------------------------------------------- search
    @property
    def size(self) -> int:
        """Nombre de chunks indexés."""
        return len(self._chunks)

    def search(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        """Recherche cosine TF-IDF — retourne les k meilleurs chunks."""
        if not self._chunks:
            return []
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        q_tf: dict[str, int] = {}
        for tok in q_tokens:
            q_tf[tok] = q_tf.get(tok, 0) + 1

        n_docs = len(self._chunks)
        vocab = list(self._df.keys())
        vocab_idx = {tok: i for i, tok in enumerate(vocab)}

        # vecteur requête
        q_vec = np.zeros(len(vocab), dtype=np.float32)
        for tok, freq in q_tf.items():
            if tok in vocab_idx:
                idf = math.log((1 + n_docs) / (1 + self._df[tok])) + 1.0
                q_vec[vocab_idx[tok]] = (1.0 + math.log(freq)) * idf
        q_norm = float(np.linalg.norm(q_vec)) or 1.0

        # matrice documents (dense — corpus de taille raisonnable)
        d_mat = np.zeros((n_docs, len(vocab)), dtype=np.float32)
        for i, tf in enumerate(self._doc_counts):
            for tok, freq in tf.items():
                idf = math.log((1 + n_docs) / (1 + self._df[tok])) + 1.0
                d_mat[i, vocab_idx[tok]] = (1.0 + math.log(freq)) * idf
        d_norms = np.linalg.norm(d_mat, axis=1)
        d_norms[d_norms == 0] = 1.0

        scores = (d_mat @ q_vec) / (d_norms * q_norm)
        order = np.argsort(scores)[::-1][:max(1, k)]
        results: list[RetrievedChunk] = []
        for idx in order:
            sc = float(scores[idx])
            if sc <= 0.0:
                continue
            chunk = self._chunks[int(idx)]
            results.append(RetrievedChunk(content=chunk.content,
                                          source=chunk.source, score=round(sc, 6)))
        return results

    # ------------------------------------------------------------ persistence
    def save(self, path: str) -> None:
        """Persiste l'index en JSON (portable, lisible)."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        data = {
            "version": 1,
            "chunks": [{"content": c.content, "source": c.source}
                       for c in self._chunks],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def load(self, path: str) -> bool:
        """Recharge un index JSON préalablement sauvegardé."""
        if not os.path.exists(path):
            return False
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            log.warning("load index %s échoué: %s", path, exc)
            return False
        self._chunks, self._doc_counts, self._df = [], [], {}
        for entry in data.get("chunks", []):
            self.add_text(entry["content"], entry["source"])
        log.info("index chargé: %d chunks depuis %s", self.size, path)
        return True
