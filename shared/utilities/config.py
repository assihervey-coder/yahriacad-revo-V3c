"""Configuration centralisée (12-factor) — surcharge par variables d'env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/pcb_ai_v3.db"))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    jwt_secret: str = field(default_factory=lambda: os.getenv("JWT_SECRET_KEY", "dev-secret"))
    # IA
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "mock"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o"))
    llm_temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.2")))
    # RL
    rl_device: str = field(default_factory=lambda: os.getenv("RL_DEVICE", "cpu"))
    checkpoint_dir: str = field(default_factory=lambda: os.getenv("RL_CHECKPOINT_DIR", "data/trained_models/policies"))
    # Manufacturing
    pcbway_api_key: str = field(default_factory=lambda: os.getenv("PCBWAY_API_KEY", ""))
    jlcpcb_api_key: str = field(default_factory=lambda: os.getenv("JLCPCB_API_KEY", ""))
    # Crédits
    credits_free_tier: int = field(default_factory=lambda: int(os.getenv("CREDITS_FREE_TIER", "100")))


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
