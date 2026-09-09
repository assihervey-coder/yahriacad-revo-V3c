"""Définitions Arduino — #define + commentaires nets."""
from __future__ import annotations

import re

from shared.utilities import get_logger

log = get_logger(__name__)

_NON_ALNUM = re.compile(r"[^A-Za-z0-9_]+")


def _pin_number(gpio: str) -> str:
    """'GPIO5'/'GP5' → '5' ; 'PA9' → '9' ; inchangé si pas de numéro."""
    m = re.search(r"(\d+)$", gpio or "")
    return m.group(1) if m else gpio


def generate_arduino_defs(pin_map: dict[str, dict[str, dict]]) -> str:
    """Génère un header Arduino : #define PIN_xxx <numéro> // net."""
    lines: list[str] = [
        "// pins_arduino.h — généré par PCB_AI_DESIGNER_V3 (firmware_bridge)",
        "#pragma once",
        "",
    ]
    used: dict[str, int] = {}
    for ref in sorted(pin_map):
        lines.append(f"// ---- {ref} ----")
        for pin in sorted(pin_map[ref]):
            info = pin_map[ref][pin]
            net = str(info.get("net", ""))
            macro = "PIN_" + (_NON_ALNUM.sub("_", net.lstrip("/")).strip("_").upper() or "NET")
            if macro in used:
                used[macro] += 1
                macro = f"{macro}_{used[macro]}"
            else:
                used[macro] = 1
            lines.append(f"#define {macro:<24} {_pin_number(str(info.get('gpio', ''))):<4} "
                         f"// net {net} ({ref}.{pin})")
        lines.append("")
    return "\n".join(lines) + "\n"
