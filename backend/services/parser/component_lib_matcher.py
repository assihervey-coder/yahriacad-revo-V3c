"""component_lib_matcher — bibliothèque de composants indexée + matching flou.

Au premier usage, sème `data/component_library/index.json` avec ~16 composants
réalistes (MCU, capteurs, régulateurs, USB-C, passives, connecteurs...).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.utilities import get_logger

log = get_logger("parser.component_lib")

_REPO_ROOT = Path(__file__).resolve().parents[3]   # .../pcb_ai_designer_v3

# ------------------------------------------------------------- bibliothèque seed
_SEED: List[Dict[str, Any]] = [
    {"mpn": "ESP32-WROOM-32E", "category": "mcu_module", "footprint": "ESP32-WROOM-32E",
     "package": "Module-18x25.5mm", "pins": 38, "power_w": 0.5, "price_usd": 2.90,
     "voltage": "3.3V", "description": "Module WiFi/BLE ESP32 dual-core, 4MB flash"},
    {"mpn": "STM32F103C8T6", "category": "mcu", "footprint": "LQFP-48",
     "package": "LQFP-48", "pins": 48, "power_w": 0.3, "price_usd": 3.20,
     "voltage": "3.3V", "description": "MCU ARM Cortex-M3 72MHz, 64KB flash (Blue Pill)"},
    {"mpn": "AMS1117-3.3", "category": "regulator", "footprint": "SOT-223",
     "package": "SOT-223", "pins": 4, "power_w": 0.4, "price_usd": 0.12,
     "voltage": "3.3V", "description": "Régulateur LDO 1A, entrée jusqu'à 12V"},
    {"mpn": "AP2112K-3.3", "category": "regulator", "footprint": "SOT-25",
     "package": "SOT-25", "pins": 5, "power_w": 0.2, "price_usd": 0.15,
     "voltage": "3.3V", "description": "LDO 600mA faible bruit, enable"},
    {"mpn": "BME680", "category": "sensor", "footprint": "LGA-8",
     "package": "LGA-8", "pins": 8, "power_w": 0.001, "price_usd": 4.50,
     "voltage": "3.3V", "description": "Capteur température/humidité/pression/gaz, I2C/SPI"},
    {"mpn": "USB4105-GF-A", "category": "connector", "footprint": "USB-C",
     "package": "USB-C-16pin", "pins": 16, "power_w": 0.0, "price_usd": 0.45,
     "voltage": "5V", "description": "Connecteur USB Type-C 16 pins, USB 2.0, GCT"},
    {"mpn": "RC0402FR-0710KL", "category": "resistor", "footprint": "0402",
     "package": "0402", "pins": 2, "power_w": 0.0625, "price_usd": 0.004,
     "voltage": "50V", "description": "Résistance 10kΩ 1% Yageo 0402"},
    {"mpn": "RC0402FR-074K7L", "category": "resistor", "footprint": "0402",
     "package": "0402", "pins": 2, "power_w": 0.0625, "price_usd": 0.004,
     "voltage": "50V", "description": "Résistance 4.7kΩ 1% Yageo 0402"},
    {"mpn": "RC0603FR-0710KL", "category": "resistor", "footprint": "0603",
     "package": "0603", "pins": 2, "power_w": 0.1, "price_usd": 0.005,
     "voltage": "75V", "description": "Résistance 10kΩ 1% Yageo 0603"},
    {"mpn": "CL05B104KO5NNNC", "category": "capacitor", "footprint": "0402",
     "package": "0402", "pins": 2, "power_w": 0.0, "price_usd": 0.004,
     "voltage": "16V", "description": "Condensateur 100nF X7R Samsung 0402"},
    {"mpn": "CL05A105KA5NNNC", "category": "capacitor", "footprint": "0402",
     "package": "0402", "pins": 2, "power_w": 0.0, "price_usd": 0.005,
     "voltage": "25V", "description": "Condensateur 1uF X5R Samsung 0402"},
    {"mpn": "CL21A106KOQNNNE", "category": "capacitor", "footprint": "0805",
     "package": "0805", "pins": 2, "power_w": 0.0, "price_usd": 0.02,
     "voltage": "16V", "description": "Condensateur 10uF X5R Samsung 0805"},
    {"mpn": "KP-1608SGC", "category": "led", "footprint": "0603",
     "package": "0603", "pins": 2, "power_w": 0.06, "price_usd": 0.03,
     "voltage": "2.2V", "description": "LED verte 0603, 20mA, Kingbright"},
    {"mpn": "ABM8-8.000MHZ", "category": "crystal", "footprint": "XTAL-3225",
     "package": "3225", "pins": 4, "power_w": 0.0, "price_usd": 0.25,
     "voltage": "-", "description": "Cristal 8MHz 3225, ±10ppm, Abracon"},
    {"mpn": "S2B-PH-K", "category": "connector", "footprint": "JST-PH",
     "package": "JST-PH-2", "pins": 2, "power_w": 0.0, "price_usd": 0.10,
     "voltage": "12V", "description": "Connecteur JST-PH 2 pins latéral (batterie)"},
    {"mpn": "CH340C", "category": "usb_uart", "footprint": "SOIC-16",
     "package": "SOIC-16", "pins": 16, "power_w": 0.05, "price_usd": 0.30,
     "voltage": "3.3-5V", "description": "Pont USB-série, oscillator interne, WCH"},
    {"mpn": "TP4056", "category": "power_management", "footprint": "SOP-8",
     "package": "SOP-8", "pins": 8, "power_w": 0.3, "price_usd": 0.09,
     "voltage": "5V", "description": "Chargeur Li-Ion 1A CC/CV avec LED d'état"},
    {"mpn": "W25Q128JV", "category": "memory", "footprint": "SOIC-8",
     "package": "SOIC-8", "pins": 8, "power_w": 0.02, "price_usd": 0.55,
     "voltage": "3.3V", "description": "Flash SPI 16MB, Winbond"},
]


@dataclass
class LibEntry:
    """Entrée de bibliothèque : identité, empreinte, pins, coût, tension."""

    mpn: str
    category: str
    footprint: str
    package: str
    pins: int
    power_w: float
    price_usd: float
    voltage: str = ""
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LibEntry":
        return cls(
            mpn=str(d.get("mpn", "")), category=str(d.get("category", "")),
            footprint=str(d.get("footprint", "")), package=str(d.get("package", "")),
            pins=int(d.get("pins", 0) or 0), power_w=float(d.get("power_w", 0.0) or 0.0),
            price_usd=float(d.get("price_usd", 0.0) or 0.0),
            voltage=str(d.get("voltage", "") or ""), description=str(d.get("description", "") or ""),
        )


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


class ComponentLibMatcher:
    """Indexe les composants JSON de `lib_dir` et fournit match/resolve flous."""

    def __init__(self, lib_dir: str = "data/component_library", auto_seed: bool = True) -> None:
        path = Path(lib_dir)
        self.lib_dir = path if path.is_absolute() else (_REPO_ROOT / path)
        self.index_path = self.lib_dir / "index.json"
        self._entries: List[LibEntry] = []
        if not self.index_path.exists():
            if auto_seed:
                self._seed()
            else:
                log.warning("index absent et auto_seed=False : %s", self.index_path)
        self.reload()

    # ------------------------------------------------------------------- seed
    def _seed(self) -> None:
        """Crée data/component_library/index.json avec la bibliothèque de départ."""
        self.lib_dir.mkdir(parents=True, exist_ok=True)
        payload = {"components": _SEED, "version": "3.0.0"}
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        log.info("bibliothèque composants semée : %s (%d entrées)",
                 self.index_path, len(_SEED))

    def reload(self) -> None:
        """(Re)charge l'index depuis le disque."""
        self._entries = []
        if self.index_path.exists():
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            self._entries = [LibEntry.from_dict(e) for e in data.get("components", [])]

    # ----------------------------------------------------------------- lecture
    def all(self) -> List[LibEntry]:
        """Toutes les entrées indexées."""
        return list(self._entries)

    def resolve(self, mpn: str) -> Optional[LibEntry]:
        """Résolution exacte (insensible casse/tirets) d'un MPN."""
        target = _normalize(mpn)
        for entry in self._entries:
            if _normalize(entry.mpn) == target:
                return entry
        return None

    def match(self, query: str, limit: int = 5) -> List[LibEntry]:
        """Matching flou par sous-chaîne et recouvrement de tokens, score décroissant."""
        q = query.lower().strip()
        q_tokens = set(re.findall(r"[a-z0-9]+", q))
        scored: List[tuple] = []
        for entry in self._entries:
            haystacks = {
                "mpn": entry.mpn.lower(),
                "category": entry.category.lower(),
                "package": entry.package.lower(),
                "description": entry.description.lower(),
                "footprint": entry.footprint.lower(),
            }
            score = 0.0
            for field, text in haystacks.items():
                weight = {"mpn": 4.0, "category": 2.0}.get(field, 1.0)
                if q and q in text:
                    score += weight * 2.0
                tokens = set(re.findall(r"[a-z0-9]+", text))
                overlap = q_tokens & tokens
                if overlap:
                    score += weight * len(overlap)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda pair: -pair[0])
        return [entry for _, entry in scored[:limit]]
