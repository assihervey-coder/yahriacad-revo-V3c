"""RollbackManager — retour à la dernière révision valide (event bus)."""
from __future__ import annotations

from typing import Any

from shared.events import EventTypes, make_event
from shared.utilities import get_logger

from services.ai_engine._event_helpers import publish_nowait
from services.ai_engine.self_verifier.verifier import SelfVerifier

log = get_logger("ai_engine.verify.rollback")


class RollbackManager:
    """Gère le registre valide/invalide et le rollback aux révisions.

    - `mark_valid(rev)` / `mark_invalid(rev)` : registre interne ;
    - `rollback_to_last_valid(current_rev)` : re-walk les révisions en arrière,
      re-vérifie chacune (SelfVerifier), restaure la première valide.
    """

    def __init__(self, versioning,  # noqa: ANN001 — DesignVersioning
                 verifier: SelfVerifier | None = None) -> None:
        self.versioning = versioning
        self.verifier = verifier or SelfVerifier(emit_events=False)
        self._valid: dict[str, dict[str, Any]] = {}
        self._invalid: dict[str, dict[str, Any]] = {}

    # -------------------------------------------------------------- registre
    def mark_valid(self, rev: str, info: dict[str, Any] | None = None) -> None:
        """Marque une révision comme valide."""
        self._valid[rev] = info or {}
        self._invalid.pop(rev, None)

    def mark_invalid(self, rev: str, info: dict[str, Any] | None = None) -> None:
        """Marque une révision comme invalide."""
        self._invalid[rev] = info or {}
        self._valid.pop(rev, None)

    def is_valid(self, rev: str) -> bool:
        return rev in self._valid

    # -------------------------------------------------------------- rollback
    def _revision_list_backwards(self) -> list[str]:
        """Liste des révisions de la plus récente à la plus ancienne."""
        try:
            revisions = self.versioning.list()
        except Exception as exc:
            log.warning("versioning.list() échoué: %s", exc)
            return []
        revs: list[str] = []
        for item in revisions:
            rev = getattr(item, "rev", None)
            if rev is None and isinstance(item, dict):
                rev = item.get("rev")
            if rev is not None:
                revs.append(str(rev))
        return list(reversed(revs))

    def _reverify(self, rev: str) -> tuple[bool, object | None]:
        """Restaure temporairement une révision et la re-vérifie."""
        try:
            graph = self.versioning.restore(rev)
        except Exception as exc:
            log.warning("restore(%s) échoué: %s", rev, exc)
            return False, None
        try:
            report = self.verifier.verify(graph)
            return bool(report.passed), graph
        except Exception as exc:
            log.warning("re-vérification de %s échouée: %s", rev, exc)
            return False, graph

    def rollback_to_last_valid(self, current_rev: str | None = None
                               ) -> tuple[bool, int | None]:
        """Restaure la première révision valide en remontant le temps.

        Retourne (success, rev_index | None) — rev_index = position dans la
        liste chronologique des révisions.
        """
        self.mark_invalid(current_rev) if current_rev else None
        revs = self._revision_list_backwards()
        if not revs:
            log.warning("rollback: aucune révision connue")
            return False, None

        for pos, rev in enumerate(revs):
            if rev == current_rev and pos == 0:
                continue  # la révision courante est déjà connue comme invalide
            ok, graph = self._reverify(rev)
            if ok:
                self.mark_valid(rev, {"verified_at": "rollback"})
                self._emit_rollback(rev, pos)
                log.info("rollback vers %s (index %d) — valide", rev, pos)
                return True, pos
            self.mark_invalid(rev, {"reason": "re-vérification échouée"})

        log.error("rollback: aucune révision valide trouvée (%d testées)", len(revs))
        return False, None

    # ------------------------------------------------------------- events
    def _emit_rollback(self, rev: str, pos: int) -> None:
        try:
            publish_nowait(make_event(
                EventTypes.ROLLBACK_EXECUTED,
                payload={"target_rev": str(rev), "position": pos},
                source="ai_engine.rollback_manager",
            ))
        except Exception as exc:
            log.warning("émission ROLLBACK_EXECUTED échouée: %s", exc)
