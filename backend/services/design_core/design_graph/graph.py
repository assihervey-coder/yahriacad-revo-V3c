"""DesignGraph — SOURCE DE VÉRITÉ UNIQUE du projet PCB (design core central).

Tous les services (placement, routage, DRC, simulation, export, UI) lisent et
écrivent dans ce graphe ; les révisions (design_versioning) en sont des
snapshots sérialisés via to_dict()/from_dict().
"""
from __future__ import annotations

import copy
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from services.design_core.design_graph.components import (
    Component,
    Pad,
    default_bbox_for_footprint,
    implicit_pad_layout,
)
from services.design_core.design_graph.geometry import (
    Keepout,
    bbox_area,
    component_bbox_mm,
    corners_of,
    make_polygon,
)
from services.design_core.design_graph.layers import Layer, make_default_stackup
from services.design_core.design_graph.nets import Net

log = logging.getLogger(__name__)


@dataclass
class DesignGraph:
    """Graphe complet d'un design PCB : couches, composants, nets, keepouts."""

    project_id: str = ""
    name: str = "untitled"
    board_size: tuple[float, float] = (100.0, 80.0)      # mm (w, h)
    layers: list[Layer] = field(default_factory=make_default_stackup)
    components: dict[str, Component] = field(default_factory=dict)
    nets: dict[str, Net] = field(default_factory=dict)
    keepouts: list[Keepout] = field(default_factory=list)

    # ------------------------------------------------------------------ composants
    def add_component(
        self,
        ref: str,
        value: str = "",
        footprint: str = "",
        mpn: str = "",
        x: float = 0.0,
        y: float = 0.0,
        rotation: float = 0.0,
        side: str = "top",
        bbox: tuple[float, float] | None = None,
        power_w: float = 0.0,
        price_usd: float = 0.0,
        pads: list[Pad] | None = None,
        placed: bool = False,
    ) -> Component:
        """Ajoute (ou remplace) un composant ; bbox déduite du footprint si absente."""
        if bbox is None:
            bbox = default_bbox_for_footprint(footprint)
        comp = Component(
            ref=ref, value=value, footprint=footprint, mpn=mpn,
            x=x, y=y, rotation=rotation, side=side, bbox=bbox,
            power_w=power_w, price_usd=price_usd,
            pads=list(pads) if pads else [], placed=placed,
        )
        self.components[ref] = comp
        return comp

    def get(self, ref: str) -> Component:
        """Renvoie le composant `ref`, KeyError explicite sinon."""
        try:
            return self.components[ref]
        except KeyError:
            raise KeyError(f"composant '{ref}' absent du design graph") from None

    def place(self, ref: str, x: float, y: float, rotation: float | None = None) -> Component:
        """Positionne un composant (placé=True) ; les pads suivent (offsets relatifs)."""
        comp = self.get(ref)
        comp.x, comp.y = float(x), float(y)
        if rotation is not None:
            comp.rotation = float(rotation)
        comp.placed = True
        return comp

    def placed_components(self) -> list[Component]:
        """Composants effectivement placés."""
        return [c for c in self.components.values() if c.placed]

    # ---------------------------------------------------------------------- nets
    def add_net(
        self,
        net_id: str | None = None,
        name: str = "",
        class_name: str = "default",
        pins: list[tuple[str, str]] | None = None,
        impedance_target_ohm: float | None = None,
        max_length_mm: float | None = None,
        matched_group: str | None = None,
    ) -> Net:
        """Ajoute un net ; ID auto "N1", "N2"... si net_id est None."""
        if net_id is None:
            i = 1
            while f"N{i}" in self.nets:
                i += 1
            net_id = f"N{i}"
        net = Net(
            net_id=net_id, name=name or net_id, class_name=class_name,
            pins=list(pins) if pins else [],
            impedance_target_ohm=impedance_target_ohm,
            max_length_mm=max_length_mm, matched_group=matched_group,
        )
        self.nets[net_id] = net
        return net

    def get_net(self, net_id: str) -> Net:
        """Renvoie le net `net_id`, KeyError explicite sinon."""
        try:
            return self.nets[net_id]
        except KeyError:
            raise KeyError(f"net '{net_id}' absent du design graph") from None

    def connect(self, ref: str, pad: str, net_id: str) -> Net:
        """Lie un pad à un net : Pad.net_id + pin (ref, pad) ; crée le net si absent."""
        comp = self.get(ref)
        if net_id not in self.nets:
            self.add_net(net_id=net_id)
        net = self.nets[net_id]
        pin = next((p for p in comp.pads if p.name == pad), None)
        if pin is None:
            # pad implicite (netlist minimale) : layout réaliste par empreinte
            # (jamais empilé au centre — voir implicit_pad_layout)
            x, y, pw, ph = implicit_pad_layout(
                comp.footprint, len(comp.pads), comp.bbox)
            pin = Pad(name=pad, x=x, y=y, w=pw, h=ph)
            comp.pads.append(pin)
            log.debug("pad '%s.%s' créé implicitement (%.2f, %.2f) sur net %s",
                      ref, pad, x, y, net_id)
        pin.net_id = net_id
        if (ref, pad) not in net.pins:
            net.pins.append((ref, pad))
        return net

    def net_of(self, ref: str, pad: str) -> Net | None:
        """Net auquel est rattaché le pad (ref, pad), None si non connecté."""
        comp = self.components.get(ref)
        if comp is None:
            return None
        pin = next((p for p in comp.pads if p.name == pad), None)
        if pin is None or pin.net_id is None:
            return None
        return self.nets.get(pin.net_id)

    def unrouted_nets(self) -> list[Net]:
        """Nets non routés (au moins 2 pins, sans path valide)."""
        return [
            n for n in self.nets.values()
            if not n.routed or n.path is None or len(n.path.points) < 2
        ]

    # ------------------------------------------------------------------ keepouts
    def keepout_add(self, name: str, points: Sequence[Sequence[float]], layer: int = -1) -> Keepout:
        """Ajoute une zone interdite polygonale (points = séquence de (x, y) mm)."""
        keepout = Keepout(name=name, polygon=make_polygon(points, layer), layer=layer)
        self.keepouts.append(keepout)
        return keepout

    def violates_keepouts(self, x: float, y: float, w: float, h: float) -> list[Keepout]:
        """Keepouts violés par une bbox centrée en (x, y) — test 'contains' sur les coins."""
        corners = corners_of(x, y, w, h)
        return [k for k in self.keepouts if any(k.polygon.contains(c) for c in corners)]

    # ------------------------------------------------------------------- métriques
    def total_wire_length(self) -> float:
        """Somme des longueurs des chemins de routage (mm)."""
        return sum(n.path.length() for n in self.nets.values() if n.path is not None)

    def cost_usd(self) -> float:
        """Coût composants du BOM (USD)."""
        return sum(c.price_usd for c in self.components.values())

    def utilization(self) -> float:
        """Densité d'occupation carte : aire bboxes placées / aire carte."""
        board_area = max(1e-9, self.board_size[0] * self.board_size[1])
        used = sum(bbox_area(component_bbox_mm(c)) for c in self.placed_components())
        return used / board_area

    def stats(self) -> dict[str, Any]:
        """Indicateurs synthétiques du design (dashboard, LLM, versioning)."""
        return {
            "components": len(self.components),
            "placed": len(self.placed_components()),
            "nets": len(self.nets),
            "routed": sum(1 for n in self.nets.values() if n.routed),
            "layers": len(self.layers),
            "wire_length_mm": round(self.total_wire_length(), 3),
            "cost_usd": round(self.cost_usd(), 4),
        }

    # ------------------------------------------------------------- sérialisation
    def to_dict(self) -> dict[str, Any]:
        """Snapshot complet JSON-compatible (source des révisions)."""
        return {
            "project_id": self.project_id,
            "name": self.name,
            "board_size": [self.board_size[0], self.board_size[1]],
            "layers": [ly.to_dict() for ly in self.layers],
            "components": [c.to_dict() for c in self.components.values()],
            "nets": [n.to_dict() for n in self.nets.values()],
            "keepouts": [k.to_dict() for k in self.keepouts],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DesignGraph:
        """Reconstruit un DesignGraph depuis un snapshot (clés manquantes = défauts)."""
        board = d.get("board_size", d.get("board_size_mm")) or [100.0, 80.0]
        graph = cls(
            project_id=str(d.get("project_id", "") or ""),
            name=str(d.get("name", "untitled") or "untitled"),
            board_size=(float(board[0]), float(board[1])),
        )
        graph.layers = [Layer.from_dict(ly) for ly in d.get("layers", [])] or make_default_stackup()
        for c in d.get("components", []):
            comp = Component.from_dict(c)
            graph.components[comp.ref] = comp
        for n in d.get("nets", []):
            net = Net.from_dict(n)
            graph.nets[net.net_id] = net
        for k in d.get("keepouts", []):
            graph.keepouts.append(Keepout.from_dict(k))
        return graph

    def copy(self) -> DesignGraph:
        """Copie profonde (le design core reste la seule source de vérité mutable)."""
        return copy.deepcopy(self)

    # ------------------------------------------------- représentation filaire API
    def to_schema(self) -> Any:
        """Convertit vers le DesignSchema pydantic de shared/schemas (API/snapshot filaire)."""
        from shared.schemas.design_schemas import (  # import local (pydantic optionnel ici)
            ComponentSchema,
            DesignSchema,
            LayerSchema,
            LayerType,
            NetSchema,
            PadSchema,
        )

        def _layer_type(ltype: str) -> Any:
            try:
                return LayerType(ltype)
            except ValueError:
                return LayerType.SIGNAL

        return DesignSchema(
            project_id=self.project_id,
            name=self.name,
            board_size_mm=self.board_size,
            layers=[
                LayerSchema(index=ly.index, name=ly.name, type=_layer_type(ly.ltype),
                            thickness_um=ly.thickness_um, er=ly.er)
                for ly in self.layers
            ],
            components=[
                ComponentSchema(
                    ref=c.ref, value=c.value, footprint=c.footprint, mpn=c.mpn,
                    x_mm=c.x, y_mm=c.y, rotation_deg=c.rotation, side=c.side,
                    bbox_mm=c.bbox,
                    pads=[PadSchema(name=p.name, x_mm=p.x, y_mm=p.y,
                                    width_mm=p.w, height_mm=p.h,
                                    net_id=p.net_id, layer=p.layer) for p in c.pads],
                    power_w=c.power_w, price_usd=c.price_usd,
                )
                for c in self.components.values()
            ],
            nets=[
                NetSchema(
                    net_id=n.net_id, name=n.name, class_name=n.class_name, pins=n.pins,
                    impedance_target_ohm=n.impedance_target_ohm,
                    max_length_mm=n.max_length_mm, matched_group=n.matched_group,
                    routed=n.routed,
                )
                for n in self.nets.values()
            ],
            keepouts=[k.to_dict() for k in self.keepouts],
        )

    @classmethod
    def from_schema(cls, schema: Any) -> DesignGraph:
        """Reconstruit le graphe depuis un DesignSchema (model_dump tolérant).

        Note : la représentation filaire ne porte pas `placed` ni `path` ;
        un composant avec une position non nulle est marqué placé (heuristique).
        Le snapshot canonique reste to_dict()/from_dict().
        """
        data = schema.model_dump()
        for comp in data.get("components", []):
            offset = abs(float(comp.get("x_mm") or 0.0)) + abs(float(comp.get("y_mm") or 0.0))
            comp["placed"] = offset > 1e-9
        return cls.from_dict(data)
