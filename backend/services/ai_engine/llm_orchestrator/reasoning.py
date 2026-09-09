"""Raisonnement symbolique — chain-of-thought et décomposition d'objectifs."""
from __future__ import annotations

import json
import re

from shared.utilities import get_logger

from services.ai_engine.llm_orchestrator.orchestrator import LLMOrchestrator

log = get_logger("ai_engine.llm.reasoning")

# Sous-objectifs canoniques du pipeline EDA
CANONICAL_STEPS: list[str] = [
    "Sélection des composants (MPN, empreintes, disponibilité usine)",
    "Placement des composants (proximité des nets critiques)",
    "Routage des pistes (alimentation puis signaux rapides)",
    "Simulation (thermique, intégrité du signal, PDN)",
    "Vérification (DRC, ERC, DFM) et corrections",
    "Export du package manufacturing (Gerber, BOM, POS)",
]

_STEP_KEYWORDS = [
    ("composant", "sélection"),
    ("sélection", "sélection"),
    ("selection", "sélection"),
    ("place", "placement"),
    ("rout", "routage"),
    ("simul", "simulation"),
    ("vérif", "vérification"),
    ("verif", "vérification"),
    ("export", "export"),
    ("gerber", "export"),
]


def chain_of_thought(
    orchestrator: LLMOrchestrator,
    question: str,
    steps_hint: list[str] | None = None,
) -> str:
    """Prompt CoT structuré : force le LLM à raisonner étape par étape."""
    steps = steps_hint or [
        "1. Comprendre le besoin et les contraintes",
        "2. Lister les hypothèses et les risques",
        "3. Proposer une solution concrète chiffrée",
        "4. Vérifier la solution contre les règles (clearance, impedance, thermal)",
        "5. Conclure par les prochaines actions",
    ]
    system = (
        "Tu es un expert conception PCB. Raisonne étape par étape, "
        "explicitement, en suivant les étapes données. Termine par 'Conclusion :'."
    )
    user = (
        f"Question : {question}\n\n"
        "Étapes à suivre :\n" + "\n".join(f"- {s}" for s in steps) + "\n\n"
        "Raisonnement :"
    )
    return orchestrator.ask(question=user, system=system, temperature=0.2)


def decompose_objective(
    orchestrator: LLMOrchestrator | None,
    objective: str,
) -> list[str]:
    """Découpe un objectif en sous-objectifs (LLM, sinon heuristique mots-clés)."""
    if orchestrator is not None:
        try:
            raw = orchestrator.ask(
                question=(
                    f"Décompose cet objectif en sous-objectifs EDA ordonnés "
                    f"(JSON liste de chaînes, max 8) : {objective}"
                ),
                system=(
                    "Tu renvoies UNIQUEMENT un JSON valide: "
                    '["étape 1", "étape 2", ...].'
                ),
                temperature=0.1,
            )
            txt = raw.strip()
            if txt.startswith("```"):
                txt = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", txt)
            data = json.loads(txt)
            if isinstance(data, list) and data and all(isinstance(x, str) for x in data):
                return data[:8]
        except Exception as exc:
            log.warning("decompose_objective via LLM a échoué (%s) → heuristique", exc)
    return _heuristic_decompose(objective)


def _heuristic_decompose(objective: str) -> list[str]:
    """Découpage par mots-clés sur les étapes canoniques du pipeline."""
    low = objective.lower()
    ordered: list[str] = []
    seen: set[str] = set()
    for kw, label in _STEP_KEYWORDS:
        if kw in low and label not in seen:
            seen.add(label)
            ordered.append(label)
    if not ordered:
        return list(CANONICAL_STEPS)
    # Toujours terminer par vérification + export (sécurité design)
    if "vérification" not in seen:
        ordered.append("vérification")
    if "export" not in seen:
        ordered.append("export")
    return ordered
