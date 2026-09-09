"""Formats Altium natifs — vocabulaire de records partagé ASCII / binaire.

Le format PCB d'Altium (PCB 5.0 ASCII et .PcbDoc binaire) repose sur le même
vocabulaire de records `|CLE=VALEUR|CLE=VALEUR|...` :

    RECORD=1  Board          RECORD=8   Pad (enfant d'un composant)
    RECORD=2  Component      RECORD=10  Region
    RECORD=3  Track          RECORD=12  Polygon (pour)
    RECORD=4  Via            RECORD=27  Net
    RECORD=7  Text (designator/commentaire enfants)

Les coordonnées Altium sont exprimées en 1/10000 de pouce ; la conversion vers
les millimètres du design_core est  mm = unités * 25.4 / 10000.

Ce module fournit le tokenizer (texte → dict) et les conversions d'unités ;
`ascii_pcb.py` et `pcbdoc.py` s'appuient dessus.
"""
from __future__ import annotations

from typing import Any

# Altium : 1 unité = 1/10000 pouce → 25.4 mm / 10000
ALTIUM_TO_MM = 25.4 / 10000.0
MM_TO_ALTIUM = 10000.0 / 25.4

# Signature OLE Compound File (documents .PcbDoc binaires)
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# Couches Altium → (index design_core, side)
_LAYER_MAP = {
    "TOPLAYER": (0, "top"),
    "TOP LAYER": (0, "top"),
    "BOTTOMLAYER": (1, "bottom"),
    "BOTTOM LAYER": (1, "bottom"),
    "MIDPLAYER1": (0, "top"),
    "MIDLAYER1": (0, "top"),
}


def is_ole_document(data: bytes) -> bool:
    """True si les octets commencent par la signature OLE (Compound File)."""
    return data[:8] == OLE_MAGIC


def parse_record(text: str) -> dict[str, str]:
    """`|RECORD=2|DESIGNATOR=U1|X=11811|` → {"RECORD": "2", "DESIGNATOR": "U1", ...}.

    Tolérant : doublons (dernier gagne), clés vides ignorées, `*` final retiré.
    """
    out: dict[str, str] = {}
    if not text:
        return out
    stripped = text.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") or stripped.endswith("*"):
        stripped = stripped[:-1]
    for part in stripped.split("|"):
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip().upper()
        if key:
            out[key] = value.strip()
    return out


def parse_records_binary(data: bytes) -> list[dict[str, str]]:
    """Décode un flux binaire de records PcbDoc ([2 octets BE longueur][texte record]).

    Le préfixe de longueur permet de sauter proprement tout record inconnu ou
    corrompu sans désynchroniser le reste du flux.
    """
    import struct

    records: list[dict[str, str]] = []
    offset = 0
    total = len(data)
    while offset + 2 <= total:
        (length,) = struct.unpack_from(">H", data, offset)
        offset += 2
        if length == 0 or offset + length > total:
            break  # flux tronqué ou padding — on s'arrête proprement
        raw = data[offset:offset + length]
        offset += length
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")
        record = parse_record(text)
        if record:
            records.append(record)
    return records


def to_int(value: str | None, default: int = 0) -> int:
    """Entier Altium tolérant (valeurs vides/flottantes acceptées)."""
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def to_float(value: str | None, default: float = 0.0) -> float:
    """Flottant Altium tolérant."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def to_mm(value: str | None, default: float = 0.0) -> float:
    """Coordonnée/taille Altium (1/10000 in) → millimètres."""
    return round(to_float(value, default) * ALTIUM_TO_MM, 4)


def to_deg(value: str | None, default: float = 0.0) -> float:
    """Champ de rotation (déjà en degrés dans le fichier, pas une coordonnée)."""
    return to_float(value, default)


def mm_to_altium(mm: float) -> int:
    """Millimètres → coordonnée entière Altium (1/10000 in)."""
    return int(round(mm * MM_TO_ALTIUM))


def layer_info(layer_str: str | None) -> tuple[int, str]:
    """Nom de couche Altium → (index, side) design_core ; défaut (0, 'top')."""
    key = str(layer_str or "").strip().upper()
    return _LAYER_MAP.get(key, (0, "top"))


def collect_text_fields(records: list[dict[str, str]]) -> dict[int, dict[str, str]]:
    """Indexe les records TEXT (RECORD=7) par OWNERINDEX.

    Dans un vrai fichier Altium, le designator et le commentaire d'un
    composant sont des records enfants `|RECORD=7|OWNERINDEX=n|NAME=Designator|
    TEXTSTRING=U1|`. Retourne {owner_index: {"designator": ..., "comment": ...}}.
    """
    out: dict[int, dict[str, str]] = {}
    for rec in records:
        if rec.get("RECORD") != "7":
            continue
        owner = to_int(rec.get("OWNERINDEX"), -1)
        if owner < 0:
            continue
        slot = out.setdefault(owner, {})
        label = rec.get("NAME", "").strip().lower()
        value = rec.get("TEXTSTRING", "").strip()
        if not value:
            continue
        if label == "designator":
            slot["designator"] = value
        elif label == "comment":
            slot["comment"] = value
        elif label not in ("comment", "designator") and "comment" not in slot:
            # texte principal sans label explicite → commentaire par défaut
            slot.setdefault("comment", value)
    return out


def payload_to_graph_dict(payload: dict[str, Any], name: str) -> dict[str, Any]:
    """Payload formats Altium → dict compatible AltiumBridge.from_dict.

    Le payload intermédiaire utilise déjà le vocabulaire design_core
    (components/nets/pads en mm) ; cette étape applique les valeurs par défaut
    attendues par le pont (pads listes, board_size tuple, etc.).
    """
    board = payload.get("board_size") or (50.0, 40.0)
    if isinstance(board, dict):
        board = (float(board.get("w", 50.0)), float(board.get("h", 40.0)))
    return {
        "project_id": str(payload.get("project_id", "altium-import")),
        "name": name,
        "board_size": [round(float(board[0]), 3), round(float(board[1]), 3)],
        "components": payload.get("components") or [],
        "nets": payload.get("nets") or [],
        "layers": payload.get("layers") or [],
    }
