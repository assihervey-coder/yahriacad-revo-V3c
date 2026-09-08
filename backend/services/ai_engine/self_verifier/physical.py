"""Vérifications physiques — proxies thermique/SI (simulator si dispo).

Si `services.simulator` est importable → utilise ses runners thermal/SI ;
sinon estimations analytiques inline :
- crosstalk proxy par proximité des composants de nets adjacents ;
- IR drop proxy par courant/puissance et distance d'alimentation.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from shared.utilities import get_logger

log = get_logger("ai_engine.verify.physical")

# seuils heuristiques (plate-forme)
_THERMAL_WARNING_W_PER_CM2 = 0.8     # densité de puissance locale (W/cm²)
_THERMAL_ERROR_W_PER_CM2 = 2.0
_CROSSTALK_WARN_DIST_MM = 3.0
_IR_DROP_WARN_V = 0.15


def _try_simulator(graph, nets_hs: List[str]) -> List[Dict[str, Any]]:
    """Délègue aux simulateurs si services.simulator est disponible."""
    try:
        from services import simulator  # type: ignore
    except ImportError:
        return []
    issues: List[Dict[str, Any]] = []
    for fn_name, kind in (("run_thermal", "thermal_proxy"),
                          ("thermal_proxy", "thermal_proxy"),
                          ("run_si", "si_proxy"),
                          ("si_proxy", "si_proxy")):
        fn = getattr(simulator, fn_name, None)
        if fn is None:
            continue
        try:
            result = fn(graph) if fn_name.startswith("run_") else fn(graph)
            issues.extend(_normalize_simulator_output(result, kind))
        except Exception as exc:
            log.warning("simulator.%s a échoué: %s", fn_name, exc)
        break
    return issues


def _normalize_simulator_output(result: Any, kind: str) -> List[Dict[str, Any]]:
    """Normalise divers formats de sortie simulateur en liste d'issues."""
    out: List[Dict[str, Any]] = []
    if isinstance(result, dict):
        if "issues" in result and isinstance(result["issues"], list):
            out.extend(result["issues"])
        elif "max_temp_c" in result:
            temp = float(result["max_temp_c"])
            sev = "error" if temp > 105 else ("warning" if temp > 85 else "info")
            out.append({"kind": kind, "severity": sev,
                        "message": f"température max simulée {temp:.1f} °C",
                        "location": {"ref": result.get("hotspot_ref", "")}})
    return out


def _high_speed_nets(graph) -> List[str]:  # noqa: ANN001
    """Nets à haut débit (impédance cible définie ou classe high_speed)."""
    out: List[str] = []
    for net_id, net in dict(getattr(graph, "nets", {}) or {}).items():
        if getattr(net, "impedance_target_ohm", None) or \
                str(getattr(net, "class_name", "")).lower() in ("high_speed", "hs"):
            out.append(str(net_id))
    return out


def _component_position(graph, ref: str) -> Tuple[float, float] | None:  # noqa: ANN001
    comp = graph.components.get(ref)
    return (comp.x, comp.y) if comp else None


def check_physical(graph, quick: bool = True) -> List[Dict[str, Any]]:  # noqa: ANN001
    """Proxies physiques : thermique, crosstalk (SI), IR drop."""
    issues = _try_simulator(graph, _high_speed_nets(graph))
    if issues or not quick:
        pass  # en mode complet on ajoute quand même les proxies inline ci-dessous

    components = dict(getattr(graph, "components", {}) or {})
    nets = dict(getattr(graph, "nets", {}) or {})

    # ---- 1) thermique proxy : densité de puissance locale -----------------
    for ref, comp in components.items():
        power = float(getattr(comp, "power_w", 0.0) or 0.0)
        if power <= 0.05:
            continue
        w, h = comp.bbox
        area_cm2 = max(1e-3, (w / 10.0) * (h / 10.0))
        density = power / area_cm2
        if density >= _THERMAL_ERROR_W_PER_CM2:
            issues.append({
                "kind": "thermal_proxy", "severity": "error",
                "message": f"{ref}: densité de puissance {density:.2f} W/cm² "
                           f"(seuil erreur {_THERMAL_ERROR_W_PER_CM2}) — vias "
                           "thermiques / plan cuivre requis",
                "location": {"ref": ref, "x": comp.x, "y": comp.y},
            })
        elif density >= _THERMAL_WARNING_W_PER_CM2:
            issues.append({
                "kind": "thermal_proxy", "severity": "warning",
                "message": f"{ref}: densité de puissance {density:.2f} W/cm² "
                           "— surveiller la thermique",
                "location": {"ref": ref, "x": comp.x, "y": comp.y},
            })

    # ---- 2) SI proxy : crosstalk par proximité ----------------------------
    hs_net_ids = set(_high_speed_nets(graph))
    hs_refs: set[str] = set()
    for net_id in hs_net_ids:
        net = nets.get(net_id)
        for pin in (getattr(net, "pins", []) or []):
            try:
                hs_refs.add(str(pin[0]))
            except (TypeError, IndexError):
                continue

    hs_list = sorted(hs_refs)
    for i, ra in enumerate(hs_list):
        pa = _component_position(graph, ra)
        if pa is None:
            continue
        for rb in hs_list[i + 1:]:
            pb = _component_position(graph, rb)
            if pb is None:
                continue
            dist = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
            if dist < _CROSSTALK_WARN_DIST_MM:
                issues.append({
                    "kind": "si_proxy", "severity": "warning",
                    "message": f"crosstalk proxy : {ra} et {rb} à "
                               f"{dist:.2f} mm (paires rapides trop proches)",
                    "location": {"ref": ra, "ref2": rb, "distance_mm": round(dist, 3)},
                })

    # ---- 3) IR drop proxy --------------------------------------------------
    total_power = sum(float(getattr(c, "power_w", 0.0) or 0.0)
                      for c in components.values())
    # hypothèse 3.3 V ; distance max au point d'alimentation = coin 0,0
    if total_power > 0.5:
        current = total_power / 3.3
        max_dist = max(math.hypot(c.x, c.y) for c in components.values()) \
            if components else 0.0
        # résistance proxy 1 Ω/m pour un plan continu (ordre de grandeur)
        ir_drop = current * (max_dist / 1000.0) * 1.0
        if ir_drop > _IR_DROP_WARN_V:
            issues.append({
                "kind": "ir_drop_proxy", "severity": "warning",
                "message": f"IR drop proxy {ir_drop:.3f} V (> "
                           f"{_IR_DROP_WARN_V} V) — épaissir les rails / "
                           "rapprocher le régulateur",
                "location": {"max_distance_mm": round(max_dist, 1)},
            })

    log.debug("physical checks: %d issues", len(issues))
    return issues
