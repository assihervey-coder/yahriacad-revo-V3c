"""Génération d'identifiants uniques (jobs, révisions, événements)."""
from __future__ import annotations

import time
import uuid


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex
    return f"{prefix}_{raw}" if prefix else raw


def short_id(prefix: str = "") -> str:
    raw = f"{time.time_ns():x}"[-8:] + uuid.uuid4().hex[:4]
    return f"{prefix}{raw}" if prefix else raw
