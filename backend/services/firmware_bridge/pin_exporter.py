"""Export des pins MCU — mapping nets → GPIO depuis le DesignGraph.

Détection du MCU (ref U* avec le plus de pads), allocation GPIO séquentielle
pour les nets non-alimentation (PA0.. pour STM32, GPIO0.. pour ESP32).
"""
from __future__ import annotations

import re
from typing import Any

from shared.utilities import get_logger

log = get_logger(__name__)

PinMap = dict[str, dict[str, dict[str, Any]]]  # ref → pin → {net, gpio, functions}

_POWER_RE = re.compile(
    r"^(GND|AGND|PGND|DGND|VCC|VDD|VSS|AVDD|AVCC|DVDD|VBAT|VBUS|VIN|VOUT|"
    r"3V3|5V|1V8|2V5|12V|24V|V\+|V-|NRST|RESET)$", re.IGNORECASE)


def is_power_net(net_name: str | None) -> bool:
    """True si le net est un net d'alimentation/reset (exclu de l'allocation GPIO)."""
    up = (net_name or "").strip().lstrip("/").upper()
    if not up:
        return True
    if _POWER_RE.match(up):
        return True
    if up.startswith("+") and any(c.isdigit() for c in up):  # +3V3, +5V, +12V…
        return True
    return "POWER" in up or "SUPPLY" in up


def _detect_family(comp: Any) -> str:
    """Famille MCU devinée depuis footprint/value/mpn."""
    blob = " ".join(str(getattr(comp, f, "") or "")
                    for f in ("footprint", "value", "mpn", "ref")).lower()
    if "esp32" in blob or "esp-" in blob:
        return "esp32"
    if "stm32" in blob:
        return "stm32"
    if "nrf5" in blob:
        return "nrf52"
    if "rp2040" in blob:
        return "rp2040"
    return "generic"


def _gpio_sequence(family: str) -> list[str]:
    """Séquence de GPIOs disponibles par famille."""
    if family == "esp32":
        # 20, 24, 28-31 réservés flash ; 34-39 input-only (gardés en secours)
        return [f"GPIO{i}" for i in list(range(0, 20)) + list(range(21, 24)) + list(range(32, 40))]
    if family == "stm32":
        return [f"{port}{i}" for port in "ABCDEFGH" for i in range(16)]
    if family == "nrf52":
        return [f"P{i:02d}" for i in range(32)]
    if family == "rp2040":
        return [f"GP{i}" for i in range(30)]
    return [f"GPIO{i}" for i in range(32)]


def _functions_for(net_name: str) -> list[str]:
    """Indices de fonction déduits du nom du net."""
    low = (net_name or "").lower()
    funcs = ["GPIO"]
    if any(k in low for k in ("sda", "scl")):
        funcs.append("I2C")
    if any(k in low for k in ("mosi", "miso", "sck", "spi", "cs")):
        funcs.append("SPI")
    if any(k in low for k in ("tx", "rx", "uart")):
        funcs.append("UART")
    if any(k in low for k in ("pwm", "led", "servo", "fan")):
        funcs.append("PWM")
    if "adc" in low or "analog" in low or "sense" in low:
        funcs.append("ADC")
    return funcs


class PinExporter:
    """Construit le PinMap (ref → pin → net/gpio/fonctions) d'un DesignGraph."""

    def export(self, graph: Any, mcu_ref: str | None = None) -> PinMap:
        """Exporte le mapping des pins du MCU détecté (ou de mcu_ref)."""
        candidates = [
            (ref, comp) for ref, comp in graph.components.items()
            if ref.upper().startswith("U")
        ]
        if mcu_ref:
            if mcu_ref not in graph.components:
                raise KeyError(f"MCU {mcu_ref!r} absent du design")
            mcu_ref, mcu = mcu_ref, graph.components[mcu_ref]
        elif candidates:
            mcu_ref, mcu = max(candidates, key=lambda rc: len(rc[1].pads or []))
        else:
            log.warning("aucun composant U* — PinMap vide")
            return {}

        family = _detect_family(mcu)
        sequence = _gpio_sequence(family)
        total_pads = len(list(getattr(mcu, "pads", []) or []))
        if total_pads > len(sequence):
            log.warning("MCU %s: %d pads > %d GPIOs disponibles (%s)",
                        mcu_ref, total_pads, len(sequence), family)

        # nets déjà alloués (partagés entre plusieurs pads du MCU)
        allocated: dict[str, str] = {}
        pin_map: PinMap = {mcu_ref: {}}
        gpio_iter = iter(sequence)
        for pad in sorted(getattr(mcu, "pads", []) or [],
                          key=lambda p: str(getattr(p, "name", ""))):
            pin_name = str(getattr(pad, "name", ""))
            net_id = str(getattr(pad, "net_id", "") or "")
            if not net_id or is_power_net(net_id):
                continue  # pin NC ou alimentation : jamais sur un GPIO
            if net_id in allocated:
                gpio = allocated[net_id]
            else:
                try:
                    gpio = next(gpio_iter)
                except StopIteration:
                    log.error("plus de GPIOs libres pour %s (%s)", net_id, family)
                    break
                allocated[net_id] = gpio
            pin_map[mcu_ref][pin_name] = {
                "net": net_id,
                "gpio": gpio,
                "functions": _functions_for(net_id),
            }
        log.info("PinMap %s (%s): %d pins exportées", mcu_ref, family,
                 len(pin_map[mcu_ref]))
        return pin_map


def export(graph: Any, mcu_ref: str | None = None) -> PinMap:
    """Raccourci module-level : PinExporter().export(graph, mcu_ref)."""
    return PinExporter().export(graph, mcu_ref)
