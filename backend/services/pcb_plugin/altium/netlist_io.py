"""Netlist Protel / Altium — lecture et écriture.

Format historique (ASCII, stable depuis Protel DOS, importable dans Altium
Designer via l'assistant d'import, KiCad, Eagle, ...) :

    [                 # bloc composant
    U1                # designator
    LQFP-48           # empreinte
    STM32F103C8T6     # commentaire / valeur
    ]
    (                 # bloc net
    GND               # nom du net
    U1-44             # noeud ref-pin
    C1-2
    )

C'est le canal le plus fiable pour la **connectivité** entre Altium et la
plateforme (le PCB ASCII porte la géométrie, la netlist porte les réseaux).
"""
from __future__ import annotations

from typing import Any

from shared.utilities import get_logger

log = get_logger(__name__)


def parse_netlist(text: str) -> dict[str, Any]:
    """Netlist Protel → payload intermédiaire (components/nets, pas de géométrie).

    Les pads sont reconstruits depuis les nœuds des nets (net_id rempli,
    position 0) — le placement reste à faire côté plateforme.
    """
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]

    components: list[dict[str, Any]] = []
    nets: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line == "[":
            block: list[str] = []
            i += 1
            while i < len(lines) and lines[i] != "]":
                block.append(lines[i])
                i += 1
            components.append(_component_from_block(block))
        elif line == "(":
            block = []
            i += 1
            while i < len(lines) and lines[i] != ")":
                block.append(lines[i])
                i += 1
            net = _net_from_block(block)
            if net:
                nets.append(net)
        i += 1

    refs = {c["ref"] for c in components}
    for net in nets:
        for ref, _pin in net.get("pins", []):
            if ref not in refs:
                refs.add(ref)
                components.append({"ref": ref, "value": "", "footprint": "",
                                   "x": 0.0, "y": 0.0, "rotation": 0.0,
                                   "side": "top", "pads": []})
    # pads depuis les nœuds de nets
    pads_by_ref: dict[str, list[dict[str, Any]]] = {}
    for net in nets:
        for ref, pin in net.get("pins", []):
            pads_by_ref.setdefault(ref, []).append(
                {"name": pin, "x": 0.0, "y": 0.0, "size": 1.2,
                 "layer": 0, "net_id": net["net_id"]})
    for comp in components:
        seen: set[str] = set()
        comp_pads: list[dict[str, Any]] = []
        for pad in pads_by_ref.get(comp["ref"], []):
            if pad["name"] not in seen:
                seen.add(pad["name"])
                comp_pads.append(pad)
        comp["pads"] = comp_pads

    log.info("netlist Protel: %d composants, %d nets", len(components), len(nets))
    return {"components": components, "nets": nets, "board_size": [50.0, 40.0]}


def _component_from_block(block: list[str]) -> dict[str, Any]:
    """Bloc `[ ... ]` → composant (designator, empreinte, valeur)."""
    ref = block[0] if block else "U?"
    if len(block) >= 3:
        footprint, value = block[1], block[2]
    elif len(block) == 2:
        footprint, value = "", block[1]
    else:
        footprint, value = "", ""
    return {"ref": ref, "value": value, "footprint": footprint,
            "x": 0.0, "y": 0.0, "rotation": 0.0, "side": "top", "pads": []}


def _net_from_block(block: list[str]) -> dict[str, Any] | None:
    """Bloc `( ... )` → net nommé + pins [[ref, pin], ...]."""
    if not block:
        return None
    name = block[0]
    pins: list[list[str]] = []
    for node in block[1:]:
        ref, _, pin = str(node).partition("-")
        if ref and pin:
            pins.append([ref, pin])
    return {"net_id": name, "name": name, "pins": pins, "routed": False}


def write_netlist(payload: dict[str, Any]) -> str:
    """Payload design_core → netlist Protel texte.

    Les nets sont dérivés des `net_id` des pads ; les composants sans pad
    restent listés (blocs `[`...`]`).
    """
    components = payload.get("components") or []
    nets_payload = payload.get("nets") or []

    nets_by_name: dict[str, list[list[str]]] = {}
    for net in nets_payload:
        name = str(net.get("net_id", net.get("name", "")) or "")
        if name:
            nets_by_name.setdefault(name, [])
            for pin in net.get("pins") or []:
                if isinstance(pin, (list, tuple)) and len(pin) >= 2:
                    nets_by_name[name].append([str(pin[0]), str(pin[1])])
    for comp in components:
        for pad in comp.get("pads") or []:
            net_id = str(pad.get("net_id", "") or "")
            if net_id:
                nets_by_name.setdefault(net_id, [])
                entry = [str(comp.get("ref", "?")), str(pad.get("name", "?"))]
                if entry not in nets_by_name[net_id]:
                    nets_by_name[net_id].append(entry)

    lines: list[str] = ["Protel netlist (généré par PCB_AI_DESIGNER_V3)", ""]
    for comp in components:
        lines.extend([
            "[",
            str(comp.get("ref", "U?")),
            str(comp.get("footprint", "") or ""),
            str(comp.get("value", "") or ""),
            "]",
        ])
    if components:
        lines.append("")
    for name in sorted(nets_by_name):
        lines.append("(")
        lines.append(name)
        for ref, pin in nets_by_name[name]:
            lines.append(f"{ref}-{pin}")
        lines.append(")")
    return "\n".join(lines) + "\n"
