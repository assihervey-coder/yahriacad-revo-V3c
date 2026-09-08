"""Overlay devicetree Zephyr — &{/dev/gpioX} avec zephyr,gpios."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from shared.utilities import get_logger

log = get_logger(__name__)

_STM_PORT_RE = re.compile(r"^P([A-H])(\d{1,2})$")
_GPIO_RE = re.compile(r"^GPIO(\d{1,2})$")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9_]+")


def _gpio_ref(gpio: str) -> Optional[Tuple[str, int]]:
    """'PA9' → ('gpioa', 9) ; 'GPIO5' → ('gpio0', 5). None si non reconnu."""
    m = _STM_PORT_RE.match(gpio or "")
    if m:
        return f"gpio{m.group(1).lower()}", int(m.group(2))
    m = _GPIO_RE.match(gpio or "")
    if m:
        pin = int(m.group(1))
        return ("gpio0", pin) if pin < 32 else ("gpio1", pin - 32)
    return None


def _label(net_name: str, used: Dict[str, int]) -> str:
    base = "net_" + (_NON_ALNUM.sub("_", (net_name or "unknown")).strip("_").lower() or "unknown")
    if base in used:
        used[base] += 1
        return f"{base}_{used[base]}"
    used[base] = 1
    return base


def generate_zephyr_overlay(pin_map: Dict[str, Dict[str, dict]],
                            board: str = "nucleo_f103rb") -> str:
    """Génère un overlay devicetree Zephyr : un nœud par net avec `gpios`."""
    lines: List[str] = [
        f"/* Overlay devicetree généré par PCB_AI_DESIGNER_V3 — cible {board} */",
        "#include <dt-bindings/gpio/gpio.h>",
        "",
        "/ {",
        "\tpcb_pins {",
        '\t\tcompatible = "pcb-ai,pin-map";',
        '\t\tstatus = "okay";',
        "",
    ]
    used: Dict[str, int] = {}
    for ref in sorted(pin_map):
        lines.append(f"\t\t/* {ref} */")
        for pin in sorted(pin_map[ref]):
            info = pin_map[ref][pin]
            ref_node = _gpio_ref(str(info.get("gpio", "")))
            label = _label(str(info.get("net", "")), used)
            if ref_node is None:
                lines.append(f"\t\t/* {label}: GPIO {info.get('gpio')} non mappable en devicetree */")
                continue
            controller, index = ref_node
            lines.append(
                f"\t\t{label}: {label} {{\n"
                f"\t\t\tgpios = <&{controller} {index} GPIO_ACTIVE_HIGH>;"
                f" /* net {info.get('net')} ({ref}.{pin}) */\n"
                f"\t\t}};"
            )
        lines.append("")
    lines.append("\t};")
    lines.append("};")
    return "\n".join(lines) + "\n"
