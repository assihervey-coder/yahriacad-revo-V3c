"""Générateur de header C — #define PIN_xxx + enum, commentés avec les nets."""
from __future__ import annotations

import re
from typing import Dict, List

from shared.utilities import get_logger

log = get_logger(__name__)

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def _macro(net_name: str, used: Dict[str, int]) -> str:
    """Nom de macro stable : /SDA → PIN_SDA (dédupliqué si collision)."""
    base = "PIN_" + (_NON_ALNUM.sub("_", (net_name or "NET")).strip("_").upper() or "NET")
    if base in used:
        used[base] += 1
        return f"{base}_{used[base]}"
    used[base] = 1
    return base


def generate_c_header(pin_map: Dict[str, Dict[str, dict]], name: str = "pins") -> str:
    """Génère un header C complet : garde d'inclusion, #define, enum des nets."""
    guard = _NON_ALNUM.sub("_", name).strip("_").upper() or "PINS"
    lines: List[str] = [
        "/*",
        " * pins.h — généré par PCB_AI_DESIGNER_V3 (firmware_bridge)",
        " * NE PAS ÉDITER À LA MAIN — régénéré à chaque export firmware.",
        " */",
        f"#ifndef {guard}_H",
        f"#define {guard}_H",
        "",
        "#include <stdint.h>",
        "",
    ]
    used: Dict[str, int] = {}
    enum_entries: List[str] = []
    for ref in sorted(pin_map):
        pins = pin_map[ref]
        lines.append(f"/* ---- {ref} ---- */")
        for pin in sorted(pins):
            info = pins[pin]
            macro = _macro(str(info.get("net", "")), used)
            gpio = str(info.get("gpio", ""))
            functions = ", ".join(info.get("functions", []))
            lines.append(f"#define {macro:<24} {gpio:<10} "
                         f"/* {ref}.{pin} — net {info.get('net')} [{functions}] */")
            enum_entries.append(f"    {macro[4:]} = {len(enum_entries)},")
        lines.append("")
    if enum_entries:
        lines.append("/* index symboliques des nets pilotés */")
        lines.append("typedef enum {")
        lines.extend(enum_entries)
        lines.append(f"    {guard}_PIN_COUNT = {len(enum_entries)}")
        lines.append("} pcb_pin_index_t;")
        lines.append("")
    lines.append(f"#endif /* {guard}_H */")
    return "\n".join(lines) + "\n"
