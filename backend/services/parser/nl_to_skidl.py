"""nl_to_skidl — traduit une demande en langage naturel en script SKIDL.

Deux modes :
  - LLM fourni  : prompte l'orchestrateur LLM (system prompt "générateur SKIDL")
    et attend un JSON {"components": [...], "nets": [...]};
  - sans LLM    : générateur de template DÉTERMINISTE par mots-clés
    (esp32, stm32, bme680/sensor, usb, regulator, connector, resistor, capacitor).

Le code généré embarque un DSL JSON en commentaire (`# SKIDL-DSL: {...}`) que
`build_graph()` interprète pour construire le DesignGraph.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from shared.utilities import get_logger, new_id

from services.design_core.design_graph.graph import DesignGraph

log = get_logger("parser.nl_to_skidl")

try:  # service ai_engine (peut ne pas exister selon l'ordre de génération des agents)
    from services.ai_engine.llm_orchestrator.orchestrator import LLMOrchestrator  # type: ignore
except Exception:  # pragma: no cover
    try:
        from services.ai_engine.orchestrator import LLMOrchestrator  # type: ignore
    except Exception:
        LLMOrchestrator = Any  # type: ignore[misc,assignment]

POWER_NETS = {"PWR", "GND", "VBUS", "VIN"}
HIGH_SPEED_NETS = {"USB_DP", "USB_DM"}


@dataclass
class SkidlScript:
    """Script SKIDL généré : code lisible + structures exploitables + DSL embarqué."""

    code: str
    components: list[dict[str, Any]] = field(default_factory=list)
    nets: list[dict[str, Any]] = field(default_factory=list)


def _net_class(name: str) -> str:
    if name in POWER_NETS:
        return "power"
    if name in HIGH_SPEED_NETS:
        return "high_speed"
    return "default"


class _TemplateBuilder:
    """Constructeur déterministe de composants/nets à partir de mots-clés."""

    def __init__(self) -> None:
        self.components: list[dict[str, Any]] = []
        self._pins: dict[str, list[list[str]]] = {}
        self._order: list[str] = []
        self._counters: dict[str, int] = defaultdict(int)

    def ref(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}{self._counters[prefix]}"

    def add(
        self,
        prefix: str,
        value: str,
        footprint: str,
        mpn: str = "",
        power_w: float = 0.0,
        price_usd: float = 0.0,
        pin_nets: dict[str, str] | None = None,
    ) -> str:
        """Ajoute un composant et raccorde ses pads aux nets demandés."""
        ref = self.ref(prefix)
        self.components.append({
            "ref": ref, "value": value, "footprint": footprint, "mpn": mpn,
            "power_w": power_w, "price_usd": price_usd,
        })
        for pad, net in (pin_nets or {}).items():
            self.connect(ref, pad, net)
        return ref

    def connect(self, ref: str, pad: str, net_name: str) -> None:
        if net_name not in self._pins:
            self._pins[net_name] = []
            self._order.append(net_name)
        self._pins[net_name].append([ref, pad])

    def nets(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "class_name": _net_class(name), "pins": self._pins[name]}
            for name in self._order
        ]


def _add_esp32(b: _TemplateBuilder) -> None:
    b.add("U", "ESP32-WROOM-32E", "ESP32-WROOM-32E", "ESP32-WROOM-32E-N8",
          power_w=0.5, price_usd=2.90,
          pin_nets={"VDD": "PWR", "GND": "GND", "EN": "RESET", "IO0": "BOOT",
                    "TXD0": "UART_TX", "RXD0": "UART_RX", "IO21": "I2C_SDA", "IO22": "I2C_SCL",
                    "IO19": "USB_DM", "IO20": "USB_DP"})          # USB natif (paire diff)
    b.add("C", "100nF", "0402", "CL05B104KO5NNNC", price_usd=0.004,
          pin_nets={"1": "PWR", "2": "GND"})                       # découplage
    b.add("R", "10k", "0402", "RC0402FR-0710KL", price_usd=0.004,
          pin_nets={"1": "RESET", "2": "PWR"})                     # pull-up EN
    b.add("C", "1uF", "0402", "CL05A105KA5NNNC", price_usd=0.005,
          pin_nets={"1": "RESET", "2": "GND"})                     # reset RC


def _add_stm32(b: _TemplateBuilder) -> None:
    b.add("U", "STM32F103C8T6", "LQFP-48", "STM32F103C8T6",
          power_w=0.3, price_usd=3.20,
          pin_nets={"VDD_1": "PWR", "VSS_1": "GND", "NRST": "RESET",
                    "PA9": "UART_TX", "PA10": "UART_RX", "PB6": "I2C_SCL", "PB7": "I2C_SDA",
                    "SWDIO": "SWDIO", "SWCLK": "SWCLK"})
    b.add("C", "100nF", "0402", "CL05B104KO5NNNC", price_usd=0.004,
          pin_nets={"1": "PWR", "2": "GND"})


def _add_bme680(b: _TemplateBuilder) -> None:
    b.add("U", "BME680", "LGA-8", "BME680", power_w=0.001, price_usd=4.50,
          pin_nets={"VDD": "PWR", "GND": "GND", "SDA": "I2C_SDA", "SCL": "I2C_SCL",
                    "CSB": "PWR", "SDO": "GND"})
    b.add("R", "4.7k", "0402", "RC0402FR-074K7L", price_usd=0.004,
          pin_nets={"1": "I2C_SDA", "2": "PWR"})                   # pull-ups I2C
    b.add("R", "4.7k", "0402", "RC0402FR-074K7L", price_usd=0.004,
          pin_nets={"1": "I2C_SCL", "2": "PWR"})


def _add_usb_c(b: _TemplateBuilder) -> None:
    b.add("J", "USB-C", "USB-C", "USB4105-GF-A", price_usd=0.45,
          pin_nets={"VBUS": "VBUS", "GND": "GND", "DP": "USB_DP", "DM": "USB_DM",
                    "CC1": "CC1", "CC2": "CC2"})
    b.add("R", "5.1k", "0402", "RC0402FR-075K1L", price_usd=0.004,
          pin_nets={"1": "CC1", "2": "GND"})                       # CC pull-downs (UFP)
    b.add("R", "5.1k", "0402", "RC0402FR-075K1L", price_usd=0.004,
          pin_nets={"1": "CC2", "2": "GND"})


def _add_regulator(b: _TemplateBuilder, from_vbus: bool) -> None:
    vin = "VBUS" if from_vbus else "VIN"
    b.add("U", "AMS1117-3.3", "SOT-223", "AMS1117-3.3", power_w=0.4, price_usd=0.12,
          pin_nets={"VI": vin, "VO": "PWR", "GND": "GND"})
    b.add("C", "10uF", "0805", "CL21A106KOQNNNE", price_usd=0.02,
          pin_nets={"1": vin, "2": "GND"})                         # entrée
    b.add("C", "22uF", "0805", "CL21A226MQQNNNE", price_usd=0.03,
          pin_nets={"1": "PWR", "2": "GND"})                       # sortie


def _add_connector(b: _TemplateBuilder) -> None:
    b.add("J", "Conn_01x04", "JST-PH", "S4B-PH-K", price_usd=0.18,
          pin_nets={"1": "PWR", "2": "GND", "3": "SIG1", "4": "SIG2"})


def _add_generic_passives(b: _TemplateBuilder) -> None:
    b.add("R", "10k", "0402", "RC0402FR-0710KL", price_usd=0.004,
          pin_nets={"1": "SIG1", "2": "PWR"})
    b.add("C", "100nF", "0402", "CL05B104KO5NNNC", price_usd=0.004,
          pin_nets={"1": "SIG1", "2": "GND"})


# Mots-clés -> constructeur (ordre d'ajoute contrôlé plus bas)
_HAS_MCU = ("esp32", "stm32")
_HAS_SENSOR = ("bme680", "sensor", "capteur", "temperature", "humidity", "pression")


def _template(natural_language: str) -> SkidlScript:
    """Générateur déterministe : mots-clés -> BOM réaliste + nets PWR/GND/signaux."""
    text = (natural_language or "").lower()
    b = _TemplateBuilder()

    has_mcu = any(k in text for k in _HAS_MCU)
    has_sensor = any(k in text for k in _HAS_SENSOR)
    has_usb = "usb" in text or "type-c" in text or "usb-c" in text
    has_reg = any(k in text for k in ("regulator", "ldo", "ams1117", "3.3v", "3v3", "alimentation"))
    has_connector = "connector" in text or "connecteur" in text or "jst" in text

    if "usb" in text:
        _add_usb_c(b)
    if has_reg or (has_mcu and not has_usb):
        _add_regulator(b, from_vbus=has_usb)
    if "esp32" in text:
        _add_esp32(b)
    if "stm32" in text:
        _add_stm32(b)
    if has_sensor:
        _add_bme680(b)
    if has_connector or not b.components:
        _add_connector(b)
    if "resistor" in text and not has_mcu:
        b.add("R", "10k", "0402", "RC0402FR-0710KL", price_usd=0.004,
              pin_nets={"1": "SIG1", "2": "GND"})
    if "capacitor" in text:
        b.add("C", "100nF", "0402", "CL05B104KO5NNNC", price_usd=0.004,
              pin_nets={"1": "PWR", "2": "GND"})
    if not b.components:
        _add_generic_passives(b)

    script = _render(b, natural_language)
    log.info("template SKIDL : %d composants, %d nets",
             len(script.components), len(script.nets))
    return script


def _render(b: _TemplateBuilder, natural_language: str) -> SkidlScript:
    """Produit le code pseudo-SKIDL lisible + le DSL JSON embarqué en commentaire."""
    dsl = {"components": b.components, "nets": b.nets()}
    lines: list[str] = [
        f'# SKIDL généré par NLToSkidl — demande : "{natural_language}"',
        "from skidl import Part, Net",
        "",
    ]
    for net in b.nets():
        lines.append(f'{net["name"].lower()} = Net("{net["name"]}")')
    lines.append("")
    for comp in b.components:
        lines.append(
            f'{comp["ref"].lower()} = Part("Device", "{comp["footprint"]}", '
            f'ref="{comp["ref"]}", value="{comp["value"]}", mpn="{comp["mpn"]}")'
        )
    for comp in b.components:
        ref = comp["ref"]
        for net in b.nets():
            for pin_ref, pad in net["pins"]:
                if pin_ref == ref:
                    lines.append(f'{ref.lower()}["{pad}"] += {net["name"].lower()}')
    lines.append("")
    lines.append(f"# SKIDL-DSL: {json.dumps(dsl, ensure_ascii=False, separators=(',', ':'))}")
    return SkidlScript(code="\n".join(lines), components=b.components, nets=b.nets())


class NLToSkidl:
    """Traducteur langage naturel -> SKIDL (LLM si fourni, template sinon)."""

    SYSTEM_PROMPT = (
        "Tu es un générateur SKIDL expert en électronique. À partir de la demande "
        "utilisateur, réponds UNIQUEMENT avec un JSON valide de forme "
        '{"components": [{"ref", "value", "footprint", "mpn", "power_w", "price_usd"}], '
        '"nets": [{"name", "class_name", "pins": [["REF", "PAD"], ...]}]} '
        "avec des références fabricant réalistes et les nets PWR/GND nécessaires."
    )

    def __init__(self, llm: LLMOrchestrator | None = None) -> None:  # type: ignore[name-defined]
        self.llm = llm

    # ------------------------------------------------------------------ public
    def translate(self, natural_language: str) -> SkidlScript:
        """Traduit la demande ; retombe sur le template déterministe si le LLM échoue."""
        if self.llm is not None:
            try:
                script = self._via_llm(natural_language)
                log.info("SKIDL via LLM : %d composants", len(script.components))
                return script
            except Exception as exc:
                log.warning("génération LLM impossible (%s) — template déterministe", exc)
        return _template(natural_language)

    def build_graph(self, script: SkidlScript) -> DesignGraph:
        """Exécute le script : DSL JSON du code si présent, sinon structures du script."""
        components, nets = script.components, script.nets
        match = re.search(r"#\s*SKIDL-DSL:\s*(\{.*\})", script.code or "", re.S)
        if match:
            try:
                dsl = json.loads(match.group(1))
                components = dsl.get("components", components)
                nets = dsl.get("nets", nets)
            except json.JSONDecodeError:
                log.warning("DSL embarqué illisible — usage des structures du script")

        graph = DesignGraph(project_id=new_id("skidl"), name="skidl-design")
        for comp in components:
            graph.add_component(
                ref=str(comp.get("ref", "?")), value=str(comp.get("value", "") or ""),
                footprint=str(comp.get("footprint", "") or ""),
                mpn=str(comp.get("mpn", "") or ""),
                power_w=float(comp.get("power_w", 0.0) or 0.0),
                price_usd=float(comp.get("price_usd", 0.0) or 0.0),
            )
        for i, net in enumerate(nets, start=1):
            name = str(net.get("name", f"N{i}") or f"N{i}")
            graph.add_net(net_id=name, name=name,
                          class_name=str(net.get("class_name", _net_class(name)) or "default"))
            for pin in net.get("pins", []):
                if isinstance(pin, (list, tuple)) and len(pin) >= 2:
                    ref, pad = str(pin[0]), str(pin[1])
                    if ref not in graph.components:
                        graph.add_component(ref=ref)
                    graph.connect(ref, pad, name)
        log.info("graphe SKIDL : %d composants, %d nets", len(graph.components), len(graph.nets))
        return graph

    # --------------------------------------------------------------------- LLM
    def _via_llm(self, natural_language: str) -> SkidlScript:
        """Prompte l'orchestrateur LLM et valide sa réponse JSON."""
        if self.llm is None:
            raise ValueError("aucun LLM fourni")
        user = (
            f"Demande : {natural_language}\n"
            "Réponds uniquement avec le JSON demandé, sans texte autour."
        )
        raw = self._call_llm(self.SYSTEM_PROMPT, user)
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise ValueError("le LLM n'a pas renvoyé de JSON")
        data = json.loads(match.group(0))
        components = list(data.get("components", []))
        nets = list(data.get("nets", []))
        if not components:
            raise ValueError("réponse LLM sans composants")
        return SkidlScript(code=raw, components=components, nets=nets)

    def _call_llm(self, system: str, user: str) -> str:
        """Adaptateur : LLMOrchestrator (ai_engine), complete/generate, ou appelable."""
        llm = self.llm
        out: Any
        if hasattr(llm, "chat"):
            try:  # interface LLMOrchestrator : chat(messages=[...], system=...)
                out = llm.chat(messages=[{"role": "user", "content": user}], system=system)
            except TypeError:
                out = llm.chat(system=system, user=user)   # variante system/user
        elif hasattr(llm, "complete"):
            out = llm.complete(prompt=f"{system}\n\n{user}")
        elif hasattr(llm, "generate"):
            out = llm.generate(prompt=f"{system}\n\n{user}")
        elif callable(llm):
            out = llm(f"{system}\n\n{user}")
        else:
            raise ValueError("interface LLM inconnue")
        if isinstance(out, dict):
            out = out.get("text") or out.get("content") or out.get("response") or ""
        elif hasattr(out, "content"):                # LLMResponse (ai_engine)
            out = out.content
        return str(out)
