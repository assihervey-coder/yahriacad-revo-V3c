"""Arbitrator — résolution de conflits entre agents selon les 4 politiques.

Cas d'usage typiques :
  - placement vs thermique (le simulateur physique a toujours raison),
  - routing vs intégrité signal (idem),
  - conflits de confiance (vote pondéré),
  - blocage récurrent (escalade humaine / rollback dernière révision valide).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.contracts import ArbitrationPolicy
from shared.utilities import get_logger

log = get_logger("super_agent.arbitration")

# Rôles dont le rapport fait autorité physique (cerveau PHYSICAL)
PHYSICAL_ROLES = {"validator", "simulation", "manufacturing"}


@dataclass
class ArbitrationResult:
    """Issue d'un arbitrage : gagnant, justification et votes pondérés."""

    winner: dict[str, Any]
    rationale: str
    votes: dict[str, float] = field(default_factory=dict)
    policy: ArbitrationPolicy = ArbitrationPolicy.CONSENSUS_CONFIDENCE
    resolved: list[dict[str, Any]] = field(default_factory=list)


class Arbitrator:
    """Applique une ArbitrationPolicy sur une liste de conflits."""

    def resolve(self, conflicts: list[dict[str, Any]],
                policy: ArbitrationPolicy = ArbitrationPolicy.CONSENSUS_CONFIDENCE,
                context: dict[str, Any] | None = None) -> ArbitrationResult:
        """Résout les conflits (le premier conflit détermine le gagnant global)."""
        context = context or {}
        if not conflicts:
            return ArbitrationResult(winner={}, rationale="aucun conflit à arbitrer",
                                     votes={}, policy=policy, resolved=[])

        votes: dict[str, float] = {}
        resolved: list[dict[str, Any]] = []
        primary: dict[str, Any] | None = None

        for conflict in conflicts:
            candidates = self._candidates(conflict)
            outcome = self._resolve_one(conflict, candidates, policy, context)
            resolved.append(outcome)
            for name, weight in outcome.get("votes", {}).items():
                votes[name] = votes.get(name, 0.0) + float(weight)
            if primary is None:
                primary = outcome

        assert primary is not None
        return ArbitrationResult(
            winner=primary.get("winner", {}),
            rationale=primary.get("rationale", ""),
            votes=votes,
            policy=policy,
            resolved=resolved,
        )

    # ------------------------------------------------------------ internals
    def _resolve_one(self, conflict: dict[str, Any], candidates: list[dict[str, Any]],
                     policy: ArbitrationPolicy, context: dict[str, Any]) -> dict[str, Any]:
        subject = str(conflict.get("subject") or conflict.get("topic") or "conflit")
        if policy == ArbitrationPolicy.HUMAN_FIRST:
            return {
                "subject": subject, "policy": policy.value,
                "winner": {"action": "escalate", "subject": subject,
                           "reason": "politique HUMAN_FIRST — décision humaine requise"},
                "rationale": "HUMAN_FIRST: escalade vers l'opérateur humain",
                "votes": {},
            }

        if policy == ArbitrationPolicy.LAST_VALID_REVISION:
            revisions = [int(c.get("revision")) for c in candidates
                         if c.get("revision") is not None]
            last_valid = context.get("last_valid_rev")
            if last_valid is not None:
                revisions.append(int(last_valid))
            target = min(revisions) if revisions else None
            return {
                "subject": subject, "policy": policy.value,
                "winner": {"action": "rollback", "revision": target, "subject": subject},
                "rationale": (f"LAST_VALID_REVISION: rollback vers la révision {target}"
                              if target is not None else
                              "LAST_VALID_REVISION: aucune révision valide connue"),
                "votes": {},
            }

        if policy == ArbitrationPolicy.PHYSICAL_WINS:
            physical = [c for c in candidates if c.get("physical")]
            if physical:
                winner = max(physical, key=lambda c: float(c.get("confidence", 0.0)))
                return {
                    "subject": subject, "policy": policy.value,
                    "winner": winner,
                    "rationale": (f"PHYSICAL_WINS: le rapport physique de "
                                  f"{winner.get('agent', '?')} prime sur {subject}"),
                    "votes": {str(c.get("agent", f"cand#{i}")): float(c.get("confidence", 0.0))
                              for i, c in enumerate(candidates)},
                }
            log.debug("PHYSICAL_WINS sans candidat physique — repli consensus (%s)", subject)

        # CONSENSUS_CONFIDENCE (et repli de PHYSICAL_WINS)
        votes = {str(c.get("agent", f"cand#{i}")): float(c.get("confidence", 0.0))
                 for i, c in enumerate(candidates)}
        if votes:
            winner_name = max(votes, key=lambda k: votes[k])
            winner = next(c for i, c in enumerate(candidates)
                          if str(c.get("agent", f"cand#{i}")) == winner_name)
            return {
                "subject": subject, "policy": ArbitrationPolicy.CONSENSUS_CONFIDENCE.value,
                "winner": winner,
                "rationale": (f"CONSENSUS_CONFIDENCE: {winner_name} l'emporte "
                              f"(confiance {votes[winner_name]:.2f}) sur {subject}"),
                "votes": votes,
            }
        return {
            "subject": subject, "policy": ArbitrationPolicy.CONSENSUS_CONFIDENCE.value,
            "winner": {"action": "escalate", "subject": subject,
                       "reason": "aucun candidat évaluable"},
            "rationale": "aucun candidat — escalade par défaut",
            "votes": {},
        }

    def _candidates(self, conflict: dict[str, Any]) -> list[dict[str, Any]]:
        raw = conflict.get("candidates") or conflict.get("parties") or []
        if isinstance(raw, dict):
            raw = [dict(value, agent=str(key)) for key, value in raw.items()]
        candidates: list[dict[str, Any]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                item = {"agent": str(item)}
            agent = str(item.get("agent") or item.get("role") or f"cand#{index}")
            physical = bool(item.get("physical") or item.get("is_physical")
                            or agent.lower() in PHYSICAL_ROLES
                            or str(item.get("brain") or "").lower() == "physical")
            candidates.append({
                "agent": agent,
                "confidence": _as_float(item.get("confidence"), 0.5),
                "physical": physical,
                "revision": item.get("revision"),
                "proposal": item.get("proposal") or item.get("position") or {},
                "report": item.get("report") or {},
            })
        return candidates


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
