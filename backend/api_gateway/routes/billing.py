"""Route billing — crédits par tenant (compteur en mémoire + free tier)."""
from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from shared.utilities import get_logger, get_settings

from api_gateway.deps import get_tenant

log = get_logger("api.billing")

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

_LOCK = threading.Lock()
_CREDITS: dict[str, int] = {}
_LEDGER: dict[str, list] = {}


def _balance(tenant: str) -> int:
    if tenant not in _CREDITS:
        _CREDITS[tenant] = int(get_settings().credits_free_tier)
    return _CREDITS[tenant]


@router.get("/credits/{tenant}")
async def get_credits(tenant: str, request: Request) -> dict[str, Any]:
    """Solde de crédits d'un tenant (free tier depuis Settings)."""
    with _LOCK:
        balance = _balance(tenant)
    return {"tenant": tenant, "credits": balance,
            "free_tier": int(get_settings().credits_free_tier)}


class ConsumeRequest(BaseModel):
    tenant: str = ""
    amount: int = Field(default=1, ge=1, le=1000)
    reason: str = "api_call"


@router.post("/consume")
async def consume_credits(payload: ConsumeRequest, request: Request) -> dict[str, Any]:
    """Débite des crédits — 402 si le solde est insuffisant."""
    tenant = payload.tenant or get_tenant(request)
    with _LOCK:
        balance = _balance(tenant)
        if balance < payload.amount:
            raise HTTPException(status_code=402, detail={
                "code": "insufficient_credits",
                "message": f"solde insuffisant ({balance} < {payload.amount})",
                "tenant": tenant,
            })
        _CREDITS[tenant] = balance - payload.amount
        new_balance = _CREDITS[tenant]
        _LEDGER.setdefault(tenant, []).append({
            "ts": time.time(), "amount": payload.amount,
            "reason": payload.reason, "balance": new_balance,
        })
    return {"tenant": tenant, "credits": new_balance, "consumed": payload.amount,
            "reason": payload.reason}


@router.get("/ledger/{tenant}")
async def get_ledger(tenant: str, request: Request) -> dict[str, Any]:
    """Journal de consommation du tenant."""
    with _LOCK:
        entries = list(_LEDGER.get(tenant, []))
    return {"tenant": tenant, "count": len(entries), "entries": entries[-100:]}
