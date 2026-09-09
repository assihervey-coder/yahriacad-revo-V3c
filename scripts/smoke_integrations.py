"""Smoke test — intégrations EDA fonctionnelles + voie β + optimizer VALID.

Démonstration de bout en bout sans serveur :
  1. KiCad     : netlist s-expr → DesignGraph → .kicad_pcb → ré-import (round-trip) ;
  2. Altium    : JSON pont → DesignGraph → export symétrique → sync (conflits) ;
  3. Sessions  : save atomique → restore (graphe + versioning) ;
  4. Surrogates β : solveur complet enregistre → entraînement → voie β (µs) ;
  5. Optimiseur: propositions RL/LLM après verdict VALID (keeper conservatif).

Lancement : make smoke-integrations  (ou python3 scripts/smoke_integrations.py)
"""
import os
import sys
import tempfile
import time
import traceback

sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")]

# données isolées pour le smoke (aucun impact sur data/ réel)
os.environ.setdefault("PCB3_DATA_DIR", tempfile.mkdtemp(prefix="pcb3_smoke_data_"))
os.environ.setdefault("SURROGATE_DATA_DIR", tempfile.mkdtemp(prefix="pcb3_smoke_surr_"))

NETLIST = '''(export (version "E")
  (components
    (comp (ref "U1") (value "ESP32") (footprint "ESP32-WROOM-32E"))
    (comp (ref "R1") (value "10k") (footprint "R_0603_1608Metric")))
  (nets
    (net (code 1) (name "PWR")
      (node (ref "U1") (pin "1")) (node (ref "R1") (pin "2")))
    (net (code 2) (name "GND")
      (node (ref "U1") (pin "2")) (node (ref "R1") (pin "1")))))'''


def main() -> None:
    from services.pcb_plugin.kicad import import_kicad_netlist, export_kicad_pcb, export_kicad_netlist
    from services.pcb_plugin.altium import AltiumBridge, AltiumSynchronizer
    from services.pcb_plugin.session_restorer import SessionRestorer
    from services.simulator.surrogate_models.beta_path import run_sim_smart
    from services.simulator.surrogate_models.manager import SurrogateManager
    from services.simulator.thermal_sim import ThermalSim
    from services.design_core import DesignGraph

    # ---- 1) KiCad round-trip
    g = import_kicad_netlist(NETLIST)
    assert len(g.components) == 2 and len(g.nets) == 2, "netlist KiCad mal parsée"
    pcb = export_kicad_pcb(g)
    assert pcb.startswith("(kicad_pcb") and "(segment" not in pcb
    nl = export_kicad_netlist(g)
    g2 = import_kicad_netlist(nl)
    assert len(g2.components) == 2 and len(g2.nets) == 2
    print(f"1. KiCad : import 2 comp / 2 nets, export .kicad_pcb ({len(pcb)} o) "
          f"+ netlist ({len(nl)} o), ré-import netlist OK")

    # ---- 2) Altium import → export → sync
    bridge = AltiumBridge()
    ga = bridge.from_dict({
        "components": [
            {"ref": "U1", "value": "MCU", "footprint": "QFN-16_0.5mm", "x": 10, "y": 10,
             "pads": [{"name": "1", "x": -1.5, "y": 0, "net_id": "PWR"},
                      {"name": "2", "x": 1.5, "y": 0, "net_id": "GND"}]},
        ],
        "nets": [{"net_id": "PWR"}, {"net_id": "GND"}],
        "board_size": {"w": 40, "h": 30},
    })
    out = bridge.export_altium(ga)
    assert out["components"][0]["ref"] == "U1"
    ga_local = bridge.from_dict(out)          # round-trip
    sync = AltiumSynchronizer(bridge)
    rep = sync.sync(ga_local)                 # 2e passe sans changement distant
    print(f"2. Altium : import/export/round-trip OK, sync résolution={rep.resolution}, "
          f"conflits={len(rep.conflicts)}")

    # ---- 3) Sessions save → restore
    tenant, user, project = "default", "smoke", "proj_smoke"
    restorer = SessionRestorer(base_dir=os.environ["PCB3_DATA_DIR"])
    restorer.save_session(tenant, user, project, g, versioning=None)
    restored = restorer.restore_session(tenant, user, project)
    assert restored is not None and len(restored[0].components) == 2
    sessions = restorer.list_sessions(tenant)
    assert len(sessions) == 1
    print(f"3. Sessions : save atomique → restore ({len(restored[0].components)} comp), "
          f"listing OK ({len(sessions)} session)")

    # ---- 4) Surrogates β : collecte → entraînement → voie β
    mgr = SurrogateManager(min_samples=8)
    gt = DesignGraph(project_id="s", name="s", board_size=(40.0, 30.0))
    gt.add_component("U1", footprint="soic-8", x=10, y=10, power_w=1.0)
    gt.place("U1", 10, 10)
    res_full, beta_used = run_sim_smart(ThermalSim(), gt, manager=mgr)
    assert not beta_used
    feats = {"n_comp": 1.0, "density": 0.02, "power_sum": 1.0, "wire_length": 0.0}
    for i in range(30):
        f = dict(feats)
        f["power_sum"] = 0.5 + i * 0.05
        mgr.record("thermal", f, 25.0 + 8.0 * f["power_sum"])
    mgr.maybe_train("thermal")
    t0 = time.perf_counter()
    res_beta, beta_used = run_sim_smart(ThermalSim(), gt, manager=mgr)
    beta_ms = (time.perf_counter() - t0) * 1000.0
    assert beta_used and res_beta.metrics.get("beta") is True
    print(f"4. Surrogates β : solveur complet enregistré puis entraîné → "
          f"voie β {beta_ms:.3f} ms (source={res_beta.metrics['source']}), "
          f"échantillons={len(mgr.dataset('thermal').load()[1])}")

    # ---- 5) Optimiseur autonome après verdict VALID
    from services.parser import NLToSkidl
    from services.placement_engine.initial_placement import InitialPlacer
    from services.router.engine import RouterEngine
    from orchestrator.agent_pipeline.corrector_agent import CorrectorAgent
    from orchestrator.common import call_probe, get_field

    sk = NLToSkidl(None)
    gd = sk.build_graph(sk.translate("carte ESP32 capteur BME680 USB-C"))
    gd = InitialPlacer().place(gd)
    rr = RouterEngine().route_all(gd)
    gd = rr.graph if rr.graph is not None else gd

    optimizer, engine = CorrectorAgent(None)._build_optimizer()
    assert optimizer is not None, "optimizer non construit"
    t0 = time.perf_counter()
    result = optimizer.optimize(gd.copy(), max_iters=6, objective="balanced")
    dt = time.perf_counter() - t0
    best = float(get_field(result, "best_score", default=0.0) or 0.0)
    kept = sum(1 for h in (get_field(result, "history", default=[]) or [])
               if isinstance(h, dict) and h.get("event") == "kept")
    print(f"5. Optimiseur : moteur={engine}, {get_field(result, 'iterations', default=0)} itérations "
          f"en {dt:.2f} s, meilleur score {best:.4f}, propositions gardées {kept} "
          f"(keeper conservatif : rien appliqué sans amélioration stricte)")

    print("SMOKE_INTEGRATIONS OK")


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        sys.exit(1)
