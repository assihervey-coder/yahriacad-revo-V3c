"""Init STM32 HAL — snippets HAL_GPIO_Init structurés par port."""
from __future__ import annotations

import re

from shared.utilities import get_logger

log = get_logger(__name__)

_STM_PORT_RE = re.compile(r"^P([A-H])(\d{1,2})$")


def _by_port(pin_map: dict[str, dict[str, dict]]) -> dict[str, list[tuple[str, str, str]]]:
    """Port → [(pin, gpio, net)] triés par index, seulement pour des GPIOs STM32."""
    ports: dict[str, list[tuple[str, str, str]]] = {}
    for _ref, pins in pin_map.items():
        for _pin, info in pins.items():
            m = _STM_PORT_RE.match(str(info.get("gpio", "")))
            if m:
                ports.setdefault(m.group(1), []).append(
                    (int(m.group(2)), str(info.get("gpio", "")), str(info.get("net", ""))))
    for entries in ports.values():
        entries.sort(key=lambda e: e[0])
    return ports


def generate_stm32_init(pin_map: dict[str, dict[str, dict]]) -> str:
    """Génère la fonction pcb_gpio_init() avec HAL_GPIO_Init par port."""
    ports = _by_port(pin_map)
    lines: list[str] = [
        "/* stm32_gpio_init.c — généré par PCB_AI_DESIGNER_V3 (firmware_bridge) */",
        '#include "stm32f1xx_hal.h"',
        "",
        "void pcb_gpio_init(void)",
        "{",
        "    GPIO_InitTypeDef GPIO_InitStruct = {0};",
        "",
    ]
    if not ports:
        lines += ["    /* aucun GPIO STM32 mappable dans ce PinMap */", "", "}"]
        return "\n".join(lines) + "\n"

    for port in sorted(ports):
        lines.append(f"    __HAL_RCC_GPIO{port}_CLK_ENABLE();")
    lines.append("")

    for port in sorted(ports):
        entries = ports[port]
        pins_mask = "|".join(f"GPIO_PIN_{idx}" for idx, _g, _n in entries)
        nets = ", ".join(net for _i, _g, net in entries)
        lines += [
            f"    /* Port {port} — nets: {nets} */",
            f"    GPIO_InitStruct.Pin = {pins_mask};",
            "    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;",
            "    GPIO_InitStruct.Pull = GPIO_NOPULL;",
            "    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;",
            f"    HAL_GPIO_Init(GPIO{port}, &GPIO_InitStruct);",
            "",
        ]
    lines.append("}")
    return "\n".join(lines) + "\n"
