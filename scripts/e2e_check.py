"""E2E : NL → SKIDL → placement → routage (paires diff enrichies) → DRC →
surrogates β → Gerber. Preuve de fonctionnement de bout en bout."""
import sys, os, traceback

sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")]

def main():
    from services.parser import NLToSkidl
    sk = NLToSkidl(None)
    g = sk.build_graph(sk.translate("carte ESP32 capteur BME680 USB-C"))
    print(f"1. parse : {len(g.components)} composants, {len(g.nets)} nets")

    from services.placement_engine.initial_placement import InitialPlacer
    g = InitialPlacer().place(g)      # retourne une COPIE placée
    print("2. placement initial OK")

    from services.router import RouterEngine
    res = RouterEngine().route_all(g)
    print(f"3. routage : {res.routed} nets, {res.failed} échecs, "
          f"{res.total_length_mm:.1f} mm, {res.vias} vias")
    for q in res.details.get("differential_pairs_quality", []):
        print(f"   paire {q['name']} : skew {q['skew_mm']} mm, "
              f"couplage {int(q['coupling_ratio']*100)} %, matched {q['skew_matched']}")

    from services.verification import DRCEngine
    rep = DRCEngine().run(g)
    print(f"4. DRC : {len(rep.violations)} violations")

    from services.simulator.surrogate_models import FastPredictor, SurrogateManager
    fp = FastPredictor(manager=SurrogateManager())
    preds = fp.predict(g)
    print("5. fast predict β :", {k: (v["source"], v["value"]) for k, v in preds.items()})

    from services.exporter.gerber_generator import GerberGenerator
    out = GerberGenerator(g).generate()
    n = len(out) if isinstance(out, dict) else "ok"
    print(f"6. Gerber : {n} fichiers")
    print("E2E OK")

if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        sys.exit(1)
