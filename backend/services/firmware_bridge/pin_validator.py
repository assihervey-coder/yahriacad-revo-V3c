"""Validation d'un PinMap — allocations doubles, nets power, boot straps, capacité."""
from __future__ import annotations

from dataclasses import dataclass

from shared.utilities import get_logger

from services.firmware_bridge.pin_exporter import is_power_net

log = get_logger(__name__)

_ESP32_BOOT_STRAPS = {"GPIO0", "GPIO2", "GPIO12", "GPIO15"}
_DEFAULT_CAPACITY = {"esp32": 34, "stm32": 128, "nrf52": 32, "rp2040": 30, "generic": 32}


@dataclass
class PinIssue:
    """Anomalie détectée sur un PinMap."""

    code: str
    message: str
    severity: str = "error"  # error | warning | info


def _family(pin_map: dict[str, dict[str, dict]]) -> str:
    """Famille déduite du style de nommage des GPIOs."""
    gpios = [info.get("gpio", "") for pins in pin_map.values() for info in pins.values()]
    if any(str(g).startswith("PA") or str(g).startswith("PB") for g in gpios):
        return "stm32"
    if any(str(g).startswith("GPIO") for g in gpios):
        return "esp32"
    if any(str(g).startswith("P") and len(str(g)) == 3 and str(g)[1:].isdigit() for g in gpios):
        return "nrf52"
    return "generic"


def validate(pin_map: dict[str, dict[str, dict]],
             available: int | None = None) -> list[PinIssue]:
    """Retourne la liste des anomalies (double allocation, power sur GPIO, …)."""
    issues: list[PinIssue] = []
    gpio_owner: dict[str, tuple] = {}
    used = 0

    for ref, pins in pin_map.items():
        for pin, info in pins.items():
            gpio = str(info.get("gpio", "") or "")
            net = str(info.get("net", "") or "")
            if not gpio:
                continue
            used += 1
            owner = (ref, pin)
            if gpio in gpio_owner and gpio_owner[gpio] != owner:
                issues.append(PinIssue(
                    code="DOUBLE_ALLOCATION",
                    message=f"{gpio} alloué deux fois: {gpio_owner[gpio][0]}.{gpio_owner[gpio][1]} "
                            f"et {ref}.{pin}",
                    severity="error",
                ))
            else:
                gpio_owner.setdefault(gpio, owner)
            if is_power_net(net):
                issues.append(PinIssue(
                    code="POWER_ON_GPIO",
                    message=f"net alimentation {net!r} affecté à {gpio} ({ref}.{pin})",
                    severity="error",
                ))
            if _family(pin_map) == "esp32" and gpio in _ESP32_BOOT_STRAPS:
                issues.append(PinIssue(
                    code="BOOT_STRAP",
                    message=f"{gpio} est un strap de boot ESP32 — usage prudent requis "
                            f"({ref}.{pin}, net {net})",
                    severity="warning",
                ))

    capacity = available if available is not None else _DEFAULT_CAPACITY.get(
        _family(pin_map), _DEFAULT_CAPACITY["generic"])
    if used > capacity:
        issues.append(PinIssue(
            code="GPIO_OVERFLOW",
            message=f"{used} GPIOs requis > {capacity} disponibles sur le MCU",
            severity="error",
        ))

    for issue in issues:
        log.log(30 if issue.severity == "warning" else 40,
                "pin issue [%s] %s", issue.code, issue.message)
    return issues
