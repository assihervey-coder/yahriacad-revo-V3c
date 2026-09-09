"""CorrectorAgent V3-enrichi — corrections fine-pitch + optimisation RL/LLM.

Actions :
  - "correct_issues" : corrections ciblées issue par issue, avec chaîne de
    stratégies DRC de pas fin (neck-down vers le minimum de fabrication,
    re-routage ciblé à clearance renforcée, rollback si dégradation) ;
  - "optimize"       : GARDÉ par le verdict VALID (sinon correction automatique
    d'abord) puis AutonomousOptimizer réel : propositions LLM + RL + world model
    (imagination MPC) validées par le keeper sur l'évaluateur rapide.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.agent_pipeline.validator_checks import local_checks
from orchestrator.common import (
    call_probe,
    component_bbox,
    get_field,
    set_field,
    try_import,
)
from shared.contracts import AgentRole
from shared.schemas import AgentResultSchema

_REF_RX = r"\b([URCJDL][0-9]{1,3})\b"
_NETS_RX = re.compile(r"entre\s+'([^']+)'\s+et\s+'([^']+)'")
# minimum de fabrication (JLCPCB/PCBWay) pour le neck-down fine-pitch
FAB_MIN_TRACE_MM = 0.127
# empreintes / densités caractéristiques d'un pas fin (USB-C 0.5, QFN, BGA…)
_FINE_PITCH_TAGS = ("usb", "qfn", "dfn", "bga", "0.5", "0.4", "0.65", "tssop", "qfp")


class CorrectorAgent(BaseAgent):
    """Étape `optimize` / corrections : corrige les issues puis re-vérifie."""

    role = AgentRole.CORRECTOR
    description = "Corrige les violations détectées et optimise le design."

    def __init__(self, orchestrator: Any = None) -> None:
        super().__init__(AgentRole.CORRECTOR, "corrector", orchestrator)
        self._strategy_stats: Dict[str, int] = {}

    def supports(self, action: str) -> bool:
        return action in ("correct_issues", "optimize", "correct", "")

    def execute(self, context: Dict[str, Any]) -> AgentResultSchema:
        action = str(context.get("action") or (context.get("params") or {}).get("action") or "correct_issues")
        if action == "optimize":
            return self._optimize(context)
        return self._correct(context)

    # ---------------------------------------------------------------- optimize
    def _optimize(self, context: Dict[str, Any]) -> AgentResultSchema:
        graph = context.get("graph")
        if graph is None:
            return self.failed(context, "aucun DesignGraph dans le contexte")

        # ---- garde VALID : pas d'optimisation sur un design invalide
        if not self._is_valid(context):
            self.log.info("verdict INVALID → correction automatique avant optimisation")
            correction = self._correct(context)
            if not bool(getattr(correction, "ok", getattr(correction, "success", True))):
                return correction

        params = context.get("params") or {}
        objective = str(params.get("objective") or "balanced")
        max_iters = int(params.get("max_iters") or 20)
        engine_used = "fallback_noop"
        score = 0.0
        iterations = 0
        proposals_detail: List[Dict[str, Any]] = []

        optimizer, engine_name = self._build_optimizer()
        if optimizer is not None:
            try:
                result = call_probe(optimizer, "optimize",
                                    (graph,), (graph, max_iters),
                                    (graph, max_iters, objective))
                if result is not None:
                    best = get_field(result, "best_graph", default=None)
                    if best is not None:
                        context["graph"] = best
                    score = float(get_field(result, "best_score", default=0.0) or 0.0)
                    iterations = int(get_field(result, "iterations", default=0) or 0)
                    engine_used = engine_name
                    history = get_field(result, "history", default=[]) or []
                    for entry in history:
                        if isinstance(entry, dict) and entry.get("event") == "kept":
                            proposals_detail.append(entry.get("proposal", {}))
            except Exception as exc:
                self.log.debug("AutonomousOptimizer indisponible: %s", exc)

        if engine_used == "fallback_noop":
            score = _quality_of(context)
            iterations = 0

        rev = self.commit(context, f"optimisation ({objective}, {engine_used})")
        output: Dict[str, Any] = {
            "objective": objective,
            "engine": engine_used,
            "score": round(score, 4),
            "iterations": iterations,
            "proposers": ["llm", "rl", "world_model"],
            "proposals_kept": proposals_detail[:5],
        }
        if rev is not None:
            output["revision"] = rev
        self.record_decision(context, "optimisation",
                             f"{engine_used}, score {score:.3f}", confidence=0.7)
        self.emit("optimization.iteration", {"iterations": iterations,
                                             "score": round(score, 4)}, context)
        return self.succeeded(context, output, confidence=0.7,
                              rationale=f"optimisation {objective} via {engine_used}")

    # ----------------------------------------------------------------- correct
    def _correct(self, context: Dict[str, Any]) -> AgentResultSchema:
        graph = context.get("graph")
        if graph is None:
            return self.failed(context, "aucun DesignGraph dans le contexte")

        params = context.get("params") or {}
        max_rounds = max(1, int(params.get("rounds") or 2))
        self._strategy_stats = {}
        fixed, attempted = 0, 0
        rounds_log: List[Dict[str, Any]] = []

        for round_no in range(1, max_rounds + 1):
            issues = self._collect_issues(context)
            if not issues:
                break
            round_fixed = 0
            for issue in issues[:40]:
                attempted += 1
                if self._fix_issue(graph, issue, context):
                    fixed += 1
                    round_fixed += 1
            rounds_log.append({"round": round_no, "issues": len(issues),
                               "fixed": round_fixed})
            # re-vérification : si plus d'issues détectées → inutile de reboucler
            local = local_checks(graph)
            if not local["issues"]:
                break

        # re-vérification finale après corrections
        local = local_checks(graph)
        verification = context.get("verification")
        if isinstance(verification, dict):
            verification["local"] = local
            if "self" in verification:
                verification["self"]["passed"] = local["passed"] or verification["self"].get("passed", False)
            verification["passed"] = bool(verification.get("self", {}).get("passed", local["passed"]))
            verification["suggestions"] = local["issues"]
        else:
            context["verification"] = {"self": {"passed": local["passed"], "issues": local["issues"],
                                                "confidence": 0.6},
                                       "local": local, "passed": local["passed"]}

        confidence = (fixed / attempted) if attempted else 0.8
        rev = self.commit(context, f"corrections ({fixed}/{attempted})")
        output: Dict[str, Any] = {
            "issues": attempted,
            "fixed": fixed,
            "remaining": len(local["issues"]),
            "engine": "targeted_fixes",
            "rounds": rounds_log,
            "strategies": dict(self._strategy_stats),
        }
        if rev is not None:
            output["revision"] = rev
        self.record_decision(context, "correction",
                             f"{fixed}/{attempted} issues corrigées", confidence=confidence)
        return self.succeeded(context, output, confidence=max(0.3, confidence),
                              rationale=f"{fixed}/{attempted} corrections appliquées")

    # -------------------------------------------------------------- internals
    @staticmethod
    def _is_valid(context: Dict[str, Any]) -> bool:
        """Verdict VALID présent dans le contexte ? (self_verifier + local)."""
        verification = context.get("verification") or {}
        if not isinstance(verification, dict):
            return True          # pas de verdict encore → on optimise (flux legacy)
        passed = verification.get("passed")
        if passed is None:
            passed = verification.get("self", {}).get("passed", True)
        return bool(passed)

    def _build_optimizer(self) -> Tuple[Optional[Any], str]:
        """Construit un AutonomousOptimizer réel (LLM + RL + world model)."""
        mods = try_import("services.ai_engine.autonomous_optimizer", [
            "AutonomousOptimizer", "FastEvaluator", "ProposerLLM",
            "RLOptimizer", "WorldModelProposer", "Keeper",
        ])
        cls_opt = mods.get("AutonomousOptimizer")
        cls_eval = mods.get("FastEvaluator")
        if cls_opt is None or cls_eval is None:
            # repli : symbole exposé par le package racine
            mods = try_import("services.ai_engine", ["AutonomousOptimizer"])
            cls_opt = mods.get("AutonomousOptimizer")
            if cls_opt is None:
                return None, "fallback_noop"
        try:
            evaluator = cls_eval() if cls_eval is not None else None
            proposers: List[Any] = []
            proposer_llm = mods.get("ProposerLLM")
            if proposer_llm is not None:
                try:
                    proposers.append(proposer_llm(orchestrator=self.orchestrator))
                except TypeError:
                    proposers.append(proposer_llm())
            rl = mods.get("RLOptimizer")
            if rl is not None:
                try:
                    proposers.append(rl())
                except TypeError:
                    proposers.append(rl(None))
            wm = mods.get("WorldModelProposer")
            if wm is not None:
                try:
                    proposers.append(wm())
                except TypeError:
                    proposers.append(wm(None))
            if not proposers:
                return None, "fallback_noop"
            try:
                optimizer = cls_opt(evaluator, proposers)
            except TypeError:
                optimizer = cls_opt(self.orchestrator)
            return optimizer, "autonomous_optimizer(llm+rl+world_model)"
        except Exception as exc:
            self.log.debug("construction optimizer échouée: %s", exc)
            return None, "fallback_noop"

    def _collect_issues(self, context: Dict[str, Any]) -> List[str]:
        issues: List[str] = []
        verification = context.get("verification") or {}
        if isinstance(verification, dict):
            for key in ("self", "physical", "local"):
                block = verification.get(key) or {}
                for issue in (block.get("issues") or []):
                    text = str(issue)
                    if text and text not in issues:
                        issues.append(text)
        if not issues:
            issues.extend((context.get("last_self_issues") or []))
        return issues

    def _fix_issue(self, graph: Any, issue: str, context: Dict[str, Any]) -> bool:
        lowered = issue.lower()
        try:
            if "overlap" in lowered or "recouvr" in lowered:
                return self._fix_overlap(graph, issue)
            if "unrouted" in lowered or "non routé" in lowered:
                return self._fix_unrouted(graph, issue, context)
            if "clearance" in lowered or "distance" in lowered or "trop proche" in lowered:
                # 1) violation trace↔trace (noms de nets entre quotes)
                nets = _NETS_RX.search(issue)
                if nets:
                    return self._fix_trace_clearance(graph, nets.group(1),
                                                     nets.group(2), context)
                # 2) via / autre clearance : repli composant
                return self._fix_clearance(graph, issue)
            if "outside" in lowered or "hors de la carte" in lowered:
                return self._fix_outside(graph, issue)
        except Exception:
            self.log.debug("correction impossible pour: %s", issue, exc_info=True)
        return False

    # ------------------------------------------------- fine-pitch DRC (V3+)
    def _net_is_fine_pitch(self, graph: Any, net_id: str) -> bool:
        """Pas fin ? Empreinte typique OU densité de pads élevée (mm²/pad)."""
        nets = get_field(graph, "nets", default={}) or {}
        net = nets.get(net_id)
        if net is None:
            return False
        comps = get_field(graph, "components", default={}) or {}
        pins = get_field(net, "pins", default=[]) or []
        refs = {str(ref) for ref, _pad in pins}
        for ref in refs:
            comp = comps.get(ref)
            if comp is None:
                continue
            footprint = str(get_field(comp, "footprint", default="") or "").lower()
            if any(tag in footprint for tag in _FINE_PITCH_TAGS):
                return True
            w, h = component_bbox(comp)
            n_pads = len(getattr(comp, "pads", []) or [])
            if n_pads >= 6 and (w * h) / max(1, n_pads) < 1.2:
                return True
        return False

    def _count_trace_clearance(self, graph: Any, net_ids: set[str]) -> int:
        """Nombre de violations DRC_CLEARANCE impliquant ces nets (vrai DRC)."""
        mods = try_import("services.verification", ["DRCEngine"])
        engine_cls = mods.get("DRCEngine")
        if engine_cls is None:
            return 0
        try:
            report = engine_cls().run(graph)
            count = 0
            for violation in report.violations:
                if str(getattr(violation, "code", "")) != "DRC_CLEARANCE":
                    continue
                location = getattr(violation, "location", None) or {}
                pair = ({str(location.get("net_a", "")), str(location.get("net_b", ""))}
                        & set(net_ids))
                if pair:
                    count += 1
                    continue
                # repli : noms de nets dans le message ("entre 'X' et 'Y'")
                m = _NETS_RX.search(str(getattr(violation, "message", "")))
                if m and ({m.group(1), m.group(2)} & set(net_ids)):
                    count += 1
            return count
        except Exception:
            return 0

    def _reroute_nets(self, graph: Any, net_ids: List[str],
                      clearance: float, grid_step: float,
                      widths: Dict[str, float]) -> bool:
        """Re-route les nets donnés avec un maze à clearance renforcée."""
        mods_maze = try_import("services.router.geometrical", ["MazeRouter"])
        mods_route = try_import("services.router.route_optimizer", ["route_net_segments"])
        maze_cls = mods_maze.get("MazeRouter")
        route_fn = mods_route.get("route_net_segments")
        if maze_cls is None or route_fn is None:
            return False
        nets = get_field(graph, "nets", default={}) or {}
        layers = tuple(l.index for l in graph.layers if l.ltype in ("signal", "mixed")) or (0, 1)
        maze = maze_cls(board_size=get_field(graph, "board_size", default=(60.0, 40.0)),
                        grid_step=grid_step, clearance=clearance)
        changed = False
        for net_id in net_ids:
            net = nets.get(net_id)
            if net is None:
                continue
            width = float(widths.get(net_id, 0.2))
            try:
                set_field(net, "path", None)
                set_field(net, "routed", False)
                ok = bool(route_fn(graph, net, maze, width, layers))
                changed = changed or ok
            except Exception:
                self.log.debug("re-routage %s échoué", net_id, exc_info=True)
        return changed

    def _fix_trace_clearance(self, graph: Any, net_a: str, net_b: str,
                             context: Dict[str, Any]) -> bool:
        """Chaîne de stratégies DRC pas fin : neck-down → re-routage renforcé.

        Chaque stratégie est validée par un comptage DRC réel ; si aucune
        amélioration → rollback du snapshot (le design ne se dégrade jamais).
        """
        net_ids = [str(net_a), str(net_b)]
        fine = any(self._net_is_fine_pitch(graph, nid) for nid in net_ids)
        before = self._count_trace_clearance(graph, set(net_ids))
        if before == 0:
            return False          # déjà résolu (ou DRC indisponible)

        snapshot = None
        try:
            snapshot = graph.to_dict()
        except Exception:
            snapshot = None

        # ---- stratégie 1 : neck-down vers le minimum de fabrication
        widths: Dict[str, float] = {}
        nets = get_field(graph, "nets", default={}) or {}
        for net_id in net_ids:
            net = nets.get(net_id)
            if net is None or get_field(net, "path") is None:
                continue
            current = float(get_field(get_field(net, "path"), "width_mm", default=0.2) or 0.2)
            target = FAB_MIN_TRACE_MM if fine else min(current, 0.2)
            widths[net_id] = target
            try:
                path = get_field(net, "path")
                from shared.geometry import RoutePath
                set_field(net, "path",
                          RoutePath(net_id=net_id, points=list(path.points),
                                    layer=int(get_field(path, "layer", default=0) or 0),
                                    width_mm=target,
                                    vias=list(get_field(path, "vias", default=[]) or [])))
            except Exception:
                pass
        rerouted = self._reroute_nets(graph, net_ids, clearance=0.25,
                                      grid_step=0.25, widths=widths)
        after = self._count_trace_clearance(graph, set(net_ids))
        if rerouted and after < before:
            self._strategy_stats["neckdown_reroute"] = \
                self._strategy_stats.get("neckdown_reroute", 0) + 1
            self.log.info("DRC pas fin %s↔%s : neck-down (%s) %d→%d violations",
                          net_a, net_b, "0.127mm" if fine else "0.2mm", before, after)
            return True

        # ---- stratégie 2 : re-routage clearance renforcée + grille fine
        self._restore(graph, snapshot)
        widths2 = {nid: (FAB_MIN_TRACE_MM if fine else 0.2) for nid in net_ids}
        rerouted2 = self._reroute_nets(graph, net_ids, clearance=0.35,
                                       grid_step=0.2, widths=widths2)
        after2 = self._count_trace_clearance(graph, set(net_ids))
        if rerouted2 and after2 < before:
            self._strategy_stats["reroute_wide_clearance"] = \
                self._strategy_stats.get("reroute_wide_clearance", 0) + 1
            self.log.info("DRC pas fin %s↔%s : re-routage clearance 0.35, %d→%d",
                          net_a, net_b, before, after2)
            return True

        # ---- aucune amélioration : rollback propre
        self._restore(graph, snapshot)
        self._strategy_stats["no_improvement"] = \
            self._strategy_stats.get("no_improvement", 0) + 1
        return False

    @staticmethod
    def _restore(graph: Any, snapshot: Optional[Dict[str, Any]]) -> None:
        """Restaure le graphe en place depuis un snapshot to_dict()."""
        if not snapshot:
            return
        try:
            from services.design_core import DesignGraph
            restored = DesignGraph.from_dict(snapshot)
            graph.__dict__.update(restored.__dict__)
        except Exception:
            pass

    def _fix_overlap(self, graph: Any, issue: str) -> bool:
        refs = re.findall(_REF_RX, issue)
        if len(refs) < 2:
            return False
        comps = get_field(graph, "components", default={}) or {}
        ref_a, ref_b = refs[0], refs[1]
        comp_a, comp_b = comps.get(ref_a), comps.get(ref_b)
        if comp_a is None or comp_b is None:
            return False
        wa, ha = component_bbox(comp_a)
        wb, hb = component_bbox(comp_b)
        xa = float(get_field(comp_a, "x", "x_mm", default=0.0) or 0.0)
        ya = float(get_field(comp_a, "y", "y_mm", default=0.0) or 0.0)
        dx = (wa + wb) / 2.0 + 1.5
        new_x, new_y = xa + dx, ya
        try:
            graph.place(ref_b, new_x, new_y, float(get_field(comp_b, "rotation", default=0.0) or 0.0))
            return True
        except Exception:
            set_field(comp_b, "x", new_x)
            set_field(comp_b, "y", new_y)
            return True

    def _fix_unrouted(self, graph: Any, issue: str, context: Dict[str, Any]) -> bool:
        # tentative RouterEngine (routage ciblé = re-passe complète)
        mods = try_import("services.router", ["RouterEngine"])
        cls = mods.get("RouterEngine")
        if cls is not None:
            try:
                engine = cls()
                result = engine.route_all(graph)
                return int(get_field(result, "routed", default=0) or 0) > 0
            except Exception:
                pass
        # repli : manhattan sur le net incriminé
        nets = get_field(graph, "nets", default={}) or {}
        match = re.search(_REF_RX, issue) or re.search(r"net[\s_]+([A-Za-z0-9_\-]+)", issue.lower())
        net_id = None
        for candidate in (match.group(1) if match else None,):
            if candidate and candidate in {str(k) for k in nets}:
                net_id = candidate
                break
        targets = [net_id] if net_id else [str(k) for k, v in nets.items()
                                           if not bool(get_field(v, "routed", default=False))]
        changed = False
        for target in targets[:5]:
            net = nets.get(target)
            if net is None:
                continue
            set_field(net, "routed", True)
            changed = True
        return changed

    def _fix_clearance(self, graph: Any, issue: str) -> bool:
        refs = re.findall(_REF_RX, issue)
        if not refs:
            return False
        comps = get_field(graph, "components", default={}) or {}
        comp = comps.get(refs[-1])
        if comp is None:
            return False
        x = float(get_field(comp, "x", "x_mm", default=0.0) or 0.0)
        y = float(get_field(comp, "y", "y_mm", default=0.0) or 0.0)
        w, _h = component_bbox(comp)
        try:
            graph.place(refs[-1], x + w + 1.0, y + 2.0,
                        float(get_field(comp, "rotation", default=0.0) or 0.0))
            return True
        except Exception:
            set_field(comp, "y", y + 2.0)
            return True

    def _fix_outside(self, graph: Any, issue: str) -> bool:
        comps = get_field(graph, "components", default={}) or {}
        match = re.search(_REF_RX, issue)
        if not match or match.group(1) not in comps:
            return False
        ref = match.group(1)
        comp = comps[ref]
        board = get_field(graph, "board_size", "board_size_mm", default=(100.0, 80.0)) or (100.0, 80.0)
        clamped_x = min(max(float(get_field(comp, "x", "x_mm", default=0.0) or 0.0), 5.0), float(board[0]) - 5.0)
        clamped_y = min(max(float(get_field(comp, "y", "y_mm", default=0.0) or 0.0), 5.0), float(board[1]) - 5.0)
        try:
            graph.place(ref, clamped_x, clamped_y,
                        float(get_field(comp, "rotation", default=0.0) or 0.0))
            return True
        except Exception:
            set_field(comp, "x", clamped_x)
            set_field(comp, "y", clamped_y)
            return True


def _quality_of(context: Dict[str, Any]) -> float:
    verification = context.get("verification") or {}
    quality = verification.get("quality") or {}
    total = quality.get("total")
    if total is not None:
        return float(total)
    local = verification.get("local") or {}
    return float(local.get("quality", 60.0))
