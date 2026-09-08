# LLM Orchestrator — le cerveau symbolique

## Architecture (`backend/services/ai_engine/llm_orchestrator/`)

```
provider.py          Protocol LLMProvider → MockLLMProvider (défaut) · OpenAIProvider · ZAIProvider
orchestrator.py      LLMOrchestrator.chat(messages, tools) → LLMResponse + boucle tool-use
reasoning.py         chain_of_thought, decompose_objective
tool_use.py          ToolSpec · ToolRegistry · run_tool_loop
prompt_engineering.py prompts système par rôle (FR) + few-shot NL→SKIDL
prompt_optimizer.py  A/B testing de prompts (Thompson sampling)
intent_parser.py     texte → IntentParseResult → IntentGraph
```

## Providers

| `LLM_PROVIDER` | Comportement |
|---|---|
| `mock` (défaut) | Réponses déterministes structurées par mots-clés — CI sans réseau |
| `openai` | API OpenAI compatible (`OPENAI_API_KEY`, base URL overridable) |
| `zai` | Endpoint Z.ai (`ZAI_API_KEY`, `ZAI_API_BASE`) |

## Prompts système

`prompt_engineering.SYSTEM_PROMPTS` contient un prompt par rôle (planner, researcher, selector, placement, routing, corrector, manufacturing, verifier) en français, chacun incluant les règles de sécurité design : respecter la clearance, les cibles d'impédance, les budgets thermiques, et ne jamais modifier le DesignGraph directement (passer par les révisions).

## Tool-use

`run_tool_loop` exécute jusqu'à 4 itérations : le LLM propose `{"tool": "nom", "arguments": {...}}`, le `ToolRegistry` exécute le handler réel, le résultat est réinjecté. Exemples de tools enregistrés côté plateforme : `query_design_stats`, `list_constraints`, `export_for_llm` (SharedMentalModel).

## Intent parsing

`IntentParser.parse("Carte ESP32 4 couches 60x40mm USB-C, impédance 50Ω, JLCPCB")` → `IntentParseResult` (type projet, couches, dimensions, composants détectés, contraintes textuelles, usine cible, confiance). Le fallback heuristique (regex riche) fonctionne sans LLM ; en présence d'un provider, les deux sources sont fusionnées.

## Optimisation de prompts

`PromptOptimizer` teste 2 variantes par tâche, enregistre les scores (acceptation des designs, taux de correction) et sélectionne par Thompson sampling — le prompt système s'améliore avec l'usage.
