"""SimulationWorker — boucle asyncio sur l'event bus.

Écoute le topic "sim.requested", exécute les simulations (hors thread pour ne
pas bloquer la boucle) et publie SIMULATION_COMPLETED avec les résultats.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence

from shared.events import Event, EventTypes, EventBus, get_event_bus, make_event
from shared.utilities import get_logger, new_id

from services.simulator.base import BaseSim
from services.simulator.em_sim import EMIProxySim
from services.simulator.mechanical_sim import MechanicalSim
from services.simulator.power_integrity import PowerIntegritySim
from services.simulator.signal_integrity import SignalIntegritySim
from services.simulator.thermal_sim import ThermalSim

log = get_logger("simulator.worker")

SIM_REQUEST_TOPIC = "sim.requested"


def default_worker_sims() -> List[BaseSim]:
    """Jeu complet de sims exécutées par le worker."""
    return [ThermalSim(), EMIProxySim(), SignalIntegritySim(),
            PowerIntegritySim(), MechanicalSim()]


class SimulationWorker:
    """Consomme les demandes de simulation et publie les résultats."""

    def __init__(self, bus: Optional[EventBus] = None,
                 sims: Optional[Sequence[BaseSim]] = None) -> None:
        self.bus = bus or get_event_bus()
        self.sims: List[BaseSim] = list(sims) if sims else default_worker_sims()
        self._running = False

    # ------------------------------------------------------------------ cycle
    async def start(self) -> None:
        """Souscrit au topic de demande de simulation."""
        self.bus.subscribe(SIM_REQUEST_TOPIC, self._on_request)
        self._running = True
        log.info("SimulationWorker démarré (topic '%s', %d sims)",
                 SIM_REQUEST_TOPIC, len(self.sims))

    async def stop(self) -> None:
        """Se désouscrit et marque le worker arrêté."""
        self.bus.unsubscribe(SIM_REQUEST_TOPIC, self._on_request)
        self._running = False
        log.info("SimulationWorker arrêté")

    @property
    def running(self) -> bool:
        return self._running

    async def run_forever(self, poll_s: float = 0.5) -> None:
        """Boucle veille-active pour un process worker dédié."""
        await self.start()
        try:
            while self._running:
                await asyncio.sleep(poll_s)
        finally:
            await self.stop()

    # ---------------------------------------------------------------- handler
    async def _on_request(self, event: Event) -> None:
        """Exécute les sims en thread (CPU/numpy) et publie SIMULATION_COMPLETED."""
        payload: Dict[str, Any] = dict(event.payload or {})
        graph = payload.get("graph")
        if graph is None:
            log.warning("sim.requested sans 'graph' (event %s) — ignoré", event.event_id)
            return
        log.info("simulation demandée (projet %s, %d sims)",
                 payload.get("project_id") or event.project_id, len(self.sims))
        results = await asyncio.to_thread(self._run_sims, graph)
        await self.bus.publish(make_event(
            EventTypes.SIMULATION_COMPLETED,
            {"results": results, "requested_by": payload.get("requested_by", "")},
            project_id=payload.get("project_id") or event.project_id,
            tenant_id=event.tenant_id,
            source="simulator",
            correlation_id=event.correlation_id or new_id("sim"),
        ))

    def _run_sims(self, graph) -> Dict[str, Any]:
        """Exécution synchrone des sims → dict sérialisable."""
        out: Dict[str, Any] = {}
        for sim in self.sims:
            try:
                out[sim.sim_kind] = sim.run(graph).to_dict()
            except Exception:
                log.exception("simulation %s en échec", sim.sim_kind)
                out[sim.sim_kind] = {"passed": False, "metrics": {},
                                     "notes": ["exception"], "runtime_s": 0.0,
                                     "sim_kind": sim.sim_kind}
        return out
