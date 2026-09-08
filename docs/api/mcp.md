# Serveur MCP (Model Context Protocol)

Endpoint : `POST http://localhost:8000/mcp` — JSON-RPC 2.0. Permet à un agent IA externe (Claude, GPT, agent CLI...) de piloter la plateforme comme un outil natif.

## Méthodes

| Méthode | Description |
|---|---|
| `initialize` | handshake, renvoie capabilities + version |
| `tools/list` | liste des outils + JSON Schema des arguments |
| `tools/call` | exécute un outil |
| `resources/list` | designs, rapports, exports disponibles |
| `resources/read` | contenu JSON d'une ressource (design, rapport qualité...) |

## Outils exposés

| Outil | Arguments | Effet |
|---|---|---|
| `run_design_command` | `message: string`, `project_id?: string` | Lance le pipeline complet depuis une intention en langage naturel |
| `query_design` | `project_id: string`, `include_stats?: bool` | Retourne l'état du DesignGraph (composants, nets, révision) |
| `simulate` | `project_id: string`, `kinds: string[]` | Thermique / EM / SI / PI |
| `export_package` | `project_id: string`, `factory: string` | Gerber + BOM + Pick&Place + IPC-2581 |

## Permissions

`api_gateway/mcp_server/permissions.py` associe des scopes à chaque outil (`tools:run`, `design:read`, `sim:run`, `export:write`). Le middleware d'auth fournit les scopes du JWT ; en mode dev, tous les scopes sont accordés.

## Exemple

```bash
curl -X POST http://localhost:8000/mcp -H "Content-Type: application/json" -d '{
  "jsonrpc": "2.0", "id": 1, "method": "tools/call",
  "params": {
    "name": "run_design_command",
    "arguments": {"message": "Carte STM32 2 couches avec régulateur 3.3V et connecteur JST"}
  }
}'
# {"jsonrpc":"2.0","id":1,"result":{"jobId":"job_...","accepted":true}}
```

Le frontend embarque aussi un `mcp_client.ts` (TypeScript) pour piloter ces outils depuis l'interface.
