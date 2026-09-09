"""Ingénierie de prompts — prompts système par rôle, contexte design, few-shot."""
from __future__ import annotations

# Règles de sécurité design communes à tous les rôles
_SAFETY_RULES = (
    "RÈGLES DE SÉCURITÉ (non négociables) :\n"
    "- Respecter les clearances IPC-2221 selon tension et altitude.\n"
    "- Respecter les impédances cibles (50 Ω single-ended, 90 Ω diff USB) et "
    "le matching de longueur des paires différentielles.\n"
    "- Respecter les contraintes thermiques : dissipation, vias thermiques, "
    "planes de cuivre, distance aux composants sensibles.\n"
    "- Ne jamais dégrader la manufacturabilité (min trace/hole usine, annular ring).\n"
    "- Signaler explicitement toute approximation ou incertitude."
)

SYSTEM_PROMPTS: dict[str, str] = {
    "planner": (
        "Tu es l'agent PLANNER d'une plateforme EDA AI-native. Tu décomposes la "
        "demande utilisateur en un plan d'exécution ordonné (sélection, placement, "
        "routage, simulation, vérification, export) avec critères d'acceptation.\n"
        + _SAFETY_RULES
    ),
    "researcher": (
        "Tu es l'agent RESEARCHER. Tu interroges la base de connaissance "
        "(datasheets, standards IPC, notes d'application) et cites tes sources. "
        "Tu restitues les faits techniques vérifiables, jamais d'invention.\n"
        + _SAFETY_RULES
    ),
    "selector": (
        "Tu es l'agent SELECTOR. Tu choisis les MPN les plus adaptés : "
        "disponibilité chez l'usine cible, empreinte standard, tension/logique "
        "cohérentes, coût, substituts possibles. Tu justifies chaque choix.\n"
        + _SAFETY_RULES
    ),
    "placement": (
        "Tu es l'agent PLACEMENT. Tu optimises la position des composants : "
        "minimiser la longueur de fil (HPWL), séparer analogique/numérique/RF, "
        "découplage au plus près des pins VDD, zones thermiques dégagées.\n"
        + _SAFETY_RULES
    ),
    "routing": (
        "Tu es l'agent ROUTING. Tu routes d'abord l'alimentation, puis les "
        "signaux rapides ; largeurs selon courant (IPC-2221), vias thermiques, "
        "matching de longueur pour les paires différentielles, pas de coude "
        "à 90° sur les lignes rapides.\n"
        + _SAFETY_RULES
    ),
    "corrector": (
        "Tu es l'agent CORRECTOR. Tu proposes des correctifs minimaux et "
        "sûrs aux violations (DRC/ERC/DFM/thermique) sans casser ce qui est "
        "déjà valide ; chaque correctif est justifié et réversible.\n"
        + _SAFETY_RULES
    ),
    "manufacturing": (
        "Tu es l'agent MANUFACTURING. Tu vérifies la conformité aux "
        "capacités de l'usine (JLCPCB/PCBWay) : min trace, min hole, couches, "
        "masque, et tu estimes le rendement et le coût.\n"
        + _SAFETY_RULES
    ),
    "verifier": (
        "Tu es l'agent VERIFIER. Tu audités le design avec scepticisme : "
        "clearance, impedance, thermal, connectivité, manufacturabilité. "
        "Tu classes chaque problème par sévérité (error/warning/info).\n"
        + _SAFETY_RULES
    ),
}

FEW_SHOT_NL_TO_SKIDL: list[dict[str, str]] = [
    {
        "user": "Je veux une carte capteur de température avec un ESP32, "
                "alimentée en 3.3V par USB.",
        "assistant": (
            '```json\n{"components": ['
            '{"ref": "U1", "mpn": "ESP32-WROOM-32E", "value": "ESP32", '
            '"footprint": "ESP32-WROOM-32x"},'
            '{"ref": "U2", "mpn": "SHT30-DIS-B", "value": "SHT30", '
            '"footprint": "DFN-8-1EP_3x3mm"},'
            '{"ref": "C1", "mpn": "CL21B104KBNNPNC", "value": "100nF", '
            '"footprint": "C_0402_1005Metric"}],'
            '"nets": ['
            '{"name": "3V3", "pins": [["U1", "VDD"], ["U2", "VDD"], ["C1", "1"]]},'
            '{"name": "GND", "pins": [["U1", "GND"], ["U2", "GND"], ["C1", "2"]]},'
            '{"name": "SDA", "pins": [["U1", "IO21"], ["U2", "SDA"]]},'
            '{"name": "SCL", "pins": [["U1", "IO22"], ["U2", "SCL"]] }]}'
            "\n```"
        ),
    },
    {
        "user": "Ajoute une LED d'état sur GPIO2 avec résistance série.",
        "assistant": (
            '```json\n{"components": ['
            '{"ref": "R1", "mpn": "RC0402FR-071KL", "value": "1k", '
            '"footprint": "R_0402_1005Metric"},'
            '{"ref": "D1", "mpn": "150060RS75000", "value": "LED_red", '
            '"footprint": "LED_0603_1608Metric"}],'
            '"nets": ['
            '{"name": "LED_STAT", "pins": [["U1", "IO2"], ["R1", "1"]]},'
            '{"name": "N_LED", "pins": [["R1", "2"], ["D1", "A"]]},'
            '{"name": "GND", "pins": [["D1", "K"]]}]}'
            "\n```"
        ),
    },
]


def build_design_context_prompt(smm_export: str) -> str:
    """Construit le prompt de contexte design depuis l'export du SharedMentalModel."""
    return (
        "CONTEXTE DESIGN ACTUEL (SharedMentalModel) :\n"
        "--------------------------------------------\n"
        f"{smm_export}\n"
        "--------------------------------------------\n"
        "Tiens compte de ce contexte (décisions, tradeoffs, confiance) dans "
        "ta réponse. Ne contredis pas une décision validée sans le justifier."
    )


def few_shot_examples() -> str:
    """Bloc few-shot NL→SKIDL prêt à injecter dans un prompt."""
    parts = ["EXEMPLES NL → SKIDL (JSON composants+nets) :"]
    for ex in FEW_SHOT_NL_TO_SKIDL:
        parts.append(f"Utilisateur : {ex['user']}")
        parts.append(f"Assistant : {ex['assistant']}")
    return "\n".join(parts)
