"""firmware_bridge — PinMap MCU + génération header C / Zephyr / Arduino / STM32."""
import json
from typing import Any, Dict, Optional

from shared.utilities import get_logger

from services.firmware_bridge.arduino import generate_arduino_defs
from services.firmware_bridge.header_generator import generate_c_header
from services.firmware_bridge.pin_exporter import PinExporter, PinMap, is_power_net
from services.firmware_bridge.pin_validator import PinIssue, validate
from services.firmware_bridge.stm32 import generate_stm32_init
from services.firmware_bridge.zephyr import generate_zephyr_overlay

__all__ = [
    "FirmwareBridge",
    "PinExporter",
    "PinIssue",
    "PinMap",
    "generate_all",
    "generate_arduino_defs",
    "generate_c_header",
    "generate_stm32_init",
    "generate_zephyr_overlay",
    "is_power_net",
    "validate",
]

log = get_logger(__name__)


class FirmwareBridge:
    """Façade : DesignGraph → fichiers firmware virtuels (dict chemin → contenu)."""

    def generate_all(self, graph: Any, mcu_ref: Optional[str] = None) -> Dict[str, str]:
        """Génère tous les artefacts firmware (header C, overlay, Arduino, STM32)."""
        pin_map = PinExporter().export(graph, mcu_ref=mcu_ref)
        issues = validate(pin_map)
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            log.warning("PinMap avec %d erreur(s) — artefacts générés malgré tout",
                        len(errors))
        return {
            "firmware/pins.h": generate_c_header(pin_map),
            "firmware/pin_map.json": json.dumps(pin_map, indent=2, sort_keys=True),
            "firmware/app.overlay": generate_zephyr_overlay(pin_map),
            "firmware/pins_arduino.h": generate_arduino_defs(pin_map),
            "firmware/stm32_gpio_init.c": generate_stm32_init(pin_map),
        }


def generate_all(graph: Any, mcu_ref: Optional[str] = None) -> Dict[str, str]:
    """Raccourci module-level : FirmwareBridge().generate_all(graph, mcu_ref)."""
    return FirmwareBridge().generate_all(graph, mcu_ref=mcu_ref)
