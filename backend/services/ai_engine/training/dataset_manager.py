"""DatasetManager — persistance d'épisodes (JSONL) + splits train/val/test."""
from __future__ import annotations

import json
import os
import random
from collections.abc import Iterable
from typing import Any

from shared.utilities import get_logger

log = get_logger("ai_engine.training.dataset")


def save_episode(path: str, graph_dict: dict[str, Any],
                 actions: list[dict[str, Any]], reward: float) -> None:
    """Sauvegarde un épisode en JSONL (append) : graph, actions, reward."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    record = {"graph": graph_dict, "actions": actions, "reward": float(reward)}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def to_jsonl(records: Iterable[dict[str, Any]], path: str) -> int:
    """Écrit des records en JSONL — retourne le nombre écrit."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            n += 1
    return n


def load_jsonl(path: str) -> list[dict[str, Any]]:
    """Charge un fichier JSONL en liste de dicts."""
    out: list[dict[str, Any]] = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("ligne JSONL invalide ignorée dans %s", path)
    return out


class DatasetManager:
    """Gestion de dataset : JSONL, splits 80/10/10, stats."""

    def __init__(self, root: str = "data/training") -> None:
        self.root = root
        os.makedirs(root, exist_ok=True)

    # ------------------------------------------------------------ episodes
    def save_episode(self, name: str, graph_dict: dict[str, Any],
                     actions: list[dict[str, Any]], reward: float) -> str:
        """Sauvegarde un épisode dans root/episodes/<name>.jsonl."""
        path = os.path.join(self.root, "episodes", f"{name}.jsonl")
        save_episode(path, graph_dict, actions, reward)
        return path

    def load(self, name: str) -> list[dict[str, Any]]:
        """Charge un dataset d'épisodes."""
        return load_jsonl(os.path.join(self.root, "episodes", f"{name}.jsonl"))

    # --------------------------------------------------------------- split
    @staticmethod
    def split(records: list[dict[str, Any]], seed: int = 42,
              ratios: tuple[float, float, float] = (0.8, 0.1, 0.1)
              ) -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                         list[dict[str, Any]]]:
        """Split déterministe train/val/test (80/10/10 par défaut)."""
        data = list(records)
        rng = random.Random(seed)
        rng.shuffle(data)
        n = len(data)
        n_train = int(n * ratios[0])
        n_val = int(n * ratios[1])
        return (data[:n_train],
                data[n_train:n_train + n_val],
                data[n_train + n_val:])

    def write_splits(self, name: str, records: list[dict[str, Any]],
                     seed: int = 42) -> dict[str, int]:
        """Split + écriture train/val/test — retourne les tailles."""
        train, val, test = self.split(records, seed=seed)
        counts = {
            "train": to_jsonl(train, os.path.join(self.root, "splits",
                                                  f"{name}_train.jsonl")),
            "val": to_jsonl(val, os.path.join(self.root, "splits",
                                              f"{name}_val.jsonl")),
            "test": to_jsonl(test, os.path.join(self.root, "splits",
                                                f"{name}_test.jsonl")),
        }
        log.info("splits écrits: %s", counts)
        return counts

    def stats(self, records: list[dict[str, Any]]) -> dict[str, float]:
        """Statistiques rapides du dataset."""
        rewards = [float(r.get("reward", 0.0)) for r in records]
        if not rewards:
            return {"n": 0.0}
        mean = sum(rewards) / len(rewards)
        var = sum((x - mean) ** 2 for x in rewards) / len(rewards)
        return {"n": float(len(rewards)), "reward_mean": mean,
                "reward_std": var ** 0.5,
                "reward_min": min(rewards), "reward_max": max(rewards)}
