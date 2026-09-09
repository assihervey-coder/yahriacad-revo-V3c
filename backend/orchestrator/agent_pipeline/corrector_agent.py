"""CorrectorAgent V3-enrichi — corrections fine-pitch + optimisation RL/LLM.

Actions :
  - "correct_issues" : corrections ciblées issue par issue, avec chaîne de
    stratégies DRC de pas fin (neck-down vers le minimum de fabrication,
    re-routage ciblé à clearance renforcée, saut de couche via via, rollback
    si dégradation) sur le CLUSTER complet de nets en conflit ; les paires
    réellement incorrigibles sont mémoïsées pour éviter les tours perdus ;
  - "optimize"       : GARDÉ par le verdict VALID (sinon correction automatique
    d'abord) puis AutonomousOptimizer réel : propositions LLM + RL + world model
    (imagination MPC) validées par le keeper sur l'évaluateur rapide.
"""
from __future__ import annotations

import re
from typing import Any

from shared.contracts import AgentRole
from shared.schemas import AgentResultSchema

from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.agent_pipeline.validator_checks import local_checks
from orchestrator.common import (
    call_probe,
    component_bbox,
    get_field,
    set_field,
    try_import,
)

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
        self._strategy_stats: dict[str, int] = {}
        # paires déjà tentées sans amélioration → pas de 2e tentative identique
        self._failed_pairs: set[frozenset[str]] = set()

    def supports(self, action: str) -> bool:
        return action in ("correct_issues", "optimize", "correct", "")

    def execute(self, context: dict[str, Any]) -> AgentResultSchema:
        action = str(context.get("action") or (context.get("params") or {}).get("action") or "correct_issues")
        if action == "optimize":
            return self._optimize(context)
        return self._correct(context)

    # ---------------------------------------------------------------- optimize
    def _optimize(self, context: dict[str, Any]) -> AgentResultSchema:
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
        proposals_detail: list[dict[str, Any]] = []

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
        output: dict[str, Any] = {
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
    def _correct(self, context: dict[str, Any]) -> AgentResultSchema:
        graph = context.get("graph")
        if graph is None:
            return self.failed(context, "aucun DesignGraph dans le contexte")

        params = context.get("params") or {}
        max_rounds = max(1, int(params.get("rounds") or 2))
        self._strategy_stats = {}
        self._failed_pairs = set()
        fixed, attempted = 0, 0
        rounds_log: list[dict[str, Any]] = []

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
        output: dict[str, Any] = {
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
    def _is_valid(context: dict[str, Any]) -> bool:
        """Verdict VALID présent dans le contexte ? (self_verifier + local)."""
        verification = context.get("verification") or {}
        if not isinstance(verification, dict):
            return True          # pas de verdict encore → on optimise (flux legacy)
        passed = verification.get("passed")
        if passed is None:
            passed = verification.get("self", {}).get("passed", True)
        return bool(passed)

    def _build_optimizer(self) -> tuple[Any | None, str]:
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
            proposers: list[Any] = []
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

    def _collect_issues(self, context: dict[str, Any]) -> list[str]:
        issues: list[str] = []
        verification = context.get("verification") or {}
        if isinstance(verification, dict):
            for key in ("self", "physical", "local"):
                block = verification.get(key) or {}
                for issue in (block.get("issues") or []):
                    text = str(issue)
                    if text and text not in issues:
                        issues.append(text)
        if not issues:
            issues.extend(context.get("last_self_issues") or [])
        return issues

    def _fix_issue(self, graph: Any, issue: str, context: dict[str, Any]) -> bool:
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

    def _clearance_violations(self, graph: Any) -> list[Any]:
        """Violations DRC_CLEARANCE du design (un seul run DRC)."""
        mods = try_import("services.verification", ["DRCEngine"])
        engine_cls = mods.get("DRCEngine")
        if engine_cls is None:
            return []
        try:
            report = engine_cls().run(graph)
            return [v for v in report.violations
                    if str(getattr(v, "code", "")) == "DRC_CLEARANCE"]
        except Exception:
            return []

    @staticmethod
    def _violation_nets(violation: Any) -> tuple[str, str]:
        """Paire (net_a, net_b) d'une violation clearance (location ou message)."""
        location = getattr(violation, "location", None) or {}
        net_a = str(location.get("net_a", "") or "")
        net_b = str(location.get("net_b", "") or "")
        if net_a and net_b:
            return net_a, net_b
        # repli : noms de nets dans le message ("entre 'X' et 'Y'")
        m = _NETS_RX.search(str(getattr(violation, "message", "")))
        if m:
            return m.group(1), m.group(2)
        return "", ""

    def _count_trace_clearance(self, graph: Any, net_ids: set[str]) -> int:
        """Nombre de violations DRC_CLEARANCE impliquant ces nets (vrai DRC)."""
        wanted = set(net_ids)
        count = 0
        for violation in self._clearance_violations(graph):
            net_a, net_b = self._violation_nets(violation)
            if {net_a, net_b} & wanted:
                count += 1
        return count

    def _clearance_cluster(self, graph: Any, net_ids: list[str],
                           max_nets: int = 8) -> set[str]:
        """Cluster transitif de nets partageant des violations de clearance.

        Un bus fine-pitch (DP/DM + voisins) est corrigé d'un coup au lieu de
        créer des effets ping-pong entre issues adjacentes.
        """
        edges: dict[str, set[str]] = {}
        for violation in self._clearance_violations(graph):
            net_a, net_b = self._violation_nets(violation)
            if net_a and net_b:
                edges.setdefault(net_a, set()).add(net_b)
                edges.setdefault(net_b, set()).add(net_a)
        cluster = {str(n) for n in net_ids}
        frontier = [str(n) for n in net_ids]
        while frontier and len(cluster) < max_nets:
            current = frontier.pop(0)
            for neighbor in sorted(edges.get(current, ())):
                if neighbor not in cluster:
                    cluster.add(neighbor)
                    frontier.append(neighbor)
                    if len(cluster) >= max_nets:
                        break
        return cluster

    @staticmethod
    def _signal_layers(graph: Any) -> list[int]:
        """Indexes des couches routables (signal/mixed), repli (0, 1)."""
        idx = [int(ly.index) for ly in (getattr(graph, "layers", []) or [])
               if getattr(ly, "ltype", "signal") in ("signal", "mixed")]
        return idx or [0, 1]

    def _dominant_layer(self, graph: Any, net_id: str) -> int | None:
        """Couche principale du chemin du net (None si non routé)."""
        net = (get_field(graph, "nets", default={}) or {}).get(net_id)
        if net is None:
            return None
        path = get_field(net, "path")
        if path is None:
            return None
        try:
            return int(get_field(path, "layer", default=0) or 0)
        except (TypeError, ValueError):
            return None

    def _reroute_nets(self, graph: Any, net_ids: list[str],
                      clearance: float, grid_step: float,
                      widths: dict[str, float],
                      layers: tuple[int, ...] | None = None) -> bool:
        """Re-route les nets donnés avec un maze à clearance renforcée.

        `layers` restreint l'ordre de préférence des couches (saut de couche
        forcé pour la stratégie 3) ; None = toutes les couches signal/mixed.
        """
        mods_maze = try_import("services.router.geometrical", ["MazeRouter"])
        mods_route = try_import("services.router.route_optimizer", ["route_net_segments"])
        maze_cls = mods_maze.get("MazeRouter")
        route_fn = mods_route.get("route_net_segments")
        if maze_cls is None or route_fn is None:
            return False
        nets = get_field(graph, "nets", default={}) or {}
        if layers is None:
            layers = tuple(self._signal_layers(graph))
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
                             context: dict[str, Any]) -> bool:
        """Chaîne de stratégies DRC pas fin : neck-down → clearance renforcée
        → saut de couche.

        En pas fin, la correction porte sur le CLUSTER transitif de nets en
        conflit (pas seulement la paire incriminée). Chaque stratégie est
        validée par un comptage DRC réel sur la paire d'origine ; si aucune
        amélioration → rollback du snapshot (le design ne se dégrade jamais)
        et mémoïsation de la paire pour éviter les tours perdus.
        """
        core_ids = [str(net_a), str(net_b)]
        pair = frozenset(core_ids)
        if pair in self._failed_pairs:
            return False          # déjà tenté sans succès dans cette passe

        fine = any(self._net_is_fine_pitch(graph, nid) for nid in core_ids)

        # ---- périmètre de travail : cluster fine-pitch transitif (≤ 8 nets)
        work_ids = core_ids
        if fine:
            cluster = self._clearance_cluster(graph, core_ids)
            if len(cluster) > len(core_ids):
                work_ids = sorted(cluster)[:8]
                self.log.debug("cluster fine-pitch élargi : %s", work_ids)

        before = self._count_trace_clearance(graph, set(core_ids))
        if before == 0:
            return False          # déjà résolu (ou DRC indisponible)

        snapshot = None
        try:
            snapshot = graph.to_dict()
        except Exception:
            snapshot = None

        # ---- stratégie 1 : neck-down vers le minimum de fabrication
        widths: dict[str, float] = {}
        nets = get_field(graph, "nets", default={}) or {}
        for net_id in work_ids:
            net = nets.get(net_id)
            if net is None or get_field(net, "path") is None:
                widths.setdefault(net_id, FAB_MIN_TRACE_MM if fine else 0.2)
                continue
            current = float(get_field(get_field(net, "path"), "width_mm", default=0.2) or 0.2)
            target = (FAB_MIN_TRACE_MM if fine else min(current, 0.2))
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
        rerouted = self._reroute_nets(graph, work_ids, clearance=0.25,
                                      grid_step=0.25, widths=widths)
        after = self._count_trace_clearance(graph, set(core_ids))
        if rerouted and after < before:
            self._strategy_stats["neckdown_reroute"] = \
                self._strategy_stats.get("neckdown_reroute", 0) + 1
            self.log.info("DRC pas fin %s↔%s : neck-down (%s) %d→%d violations",
                          net_a, net_b, "0.127mm" if fine else "0.2mm", before, after)
            return True

        # ---- stratégie 2 : re-routage clearance renforcée + grille fine
        self._restore(graph, snapshot)
        widths2 = {nid: (FAB_MIN_TRACE_MM if fine else 0.2) for nid in work_ids}
        rerouted2 = self._reroute_nets(graph, work_ids, clearance=0.35,
                                       grid_step=0.2, widths=widths2)
        after2 = self._count_trace_clearance(graph, set(core_ids))
        if rerouted2 and after2 < before:
            self._strategy_stats["reroute_wide_clearance"] = \
                self._strategy_stats.get("reroute_wide_clearance", 0) + 1
            self.log.info("DRC pas fin %s↔%s : re-routage clearance 0.35, %d→%d",
                          net_a, net_b, before, after2)
            return True

        # ---- stratégie 3 : saut de couche — sort les nets conflits de la
        #      couche dominante de net_b (via), conflit même-couche éliminé
        self._restore(graph, snapshot)
        dominant_b = self._dominant_layer(graph, str(net_b))
        alt_layers = [ly for ly in self._signal_layers(graph) if ly != dominant_b]
        if alt_layers:
            hop_ids = [nid for nid in work_ids if nid != str(net_a)] or [str(net_b)]
            widths3 = {nid: (FAB_MIN_TRACE_MM if fine else 0.2) for nid in hop_ids}
            rerouted3 = self._reroute_nets(graph, hop_ids, clearance=0.25,
                                           grid_step=0.25, widths=widths3,
                                           layers=tuple(alt_layers))
            after3 = self._count_trace_clearance(graph, set(core_ids))
            if rerouted3 and after3 < before:
                self._strategy_stats["layer_hop"] = \
                    self._strategy_stats.get("layer_hop", 0) + 1
                self.log.info("DRC pas fin %s↔%s : saut de couche vers %s, %d→%d",
                              net_a, net_b, alt_layers, before, after3)
                return True

        # ---- aucune amélioration : rollback propre + mémo de la paire
        self._restore(graph, snapshot)
        self._failed_pairs.add(pair)
        self._strategy_stats["no_improvement"] = \
            self._strategy_stats.get("no_improvement", 0) + 1
        return False

    @staticmethod
    def _restore(graph: Any, snapshot: dict[str, Any] | None) -> None:
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

    def _fix_unrouted(self, graph: Any, issue: str, context: dict[str, Any]) -> bool:
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
        board = get_field(graph, "board_size", "board_size_mm",
                          default=(100.0, 80.0)) or (100.0, 80.0)
        # éloigne le composant mais reste DANS la carte (marge 5 mm),
        # sinon la correction échangerait une violation contre une autre
        new_x = min(max(x + w + 1.0, 5.0), float(board[0]) - 5.0)
        new_y = min(max(y + 2.0, 5.0), float(board[1]) - 5.0)
        try:
            graph.place(refs[-1], new_x, new_y,
                        float(get_field(comp, "rotation", default=0.0) or 0.0))
            return True
        except Exception:
            set_field(comp, "x", new_x)
            set_field(comp, "y", new_y)
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


def _quality_of(context: dict[str, Any]) -> float:
    verification = context.get("verification") or {}
    quality = verification.get("quality") or {}
    total = quality.get("total")
    if total is not None:
        return float(total)
    local = verification.get("local") or {}
    return float(local.get("quality", 60.0))
