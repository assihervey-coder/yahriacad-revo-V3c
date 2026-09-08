# API GraphQL

Endpoint : `http://localhost:8000/graphql` (IDE GraphiQL intégré en dev).

Implémenté avec **Strawberry GraphQL** (fallback JSON simple si la dépendance est absente).

## Schéma

```graphql
type Design {
  name: String!
  revision: Int!
  stats: Stats!          # composants, nets, routage, longueur traces, coût
}

type Agent {
  role: String!          # planner, placement, routing, validator...
  status: String!        # running / succeeded / failed
  confidence: Float!
}

type Query {
  design(projectId: String!, revision: Int = 0): Design
  agents(projectId: String!): [Agent!]!
}

type Mutation {
  runCommand(message: String!, projectId: String = ""): CommandReply!
}
```

## Exemples

```graphql
query {
  design(projectId: "capteur-v1") {
    name
    revision
    stats { components nets routed wireLengthMM costUSD }
  }
  agents(projectId: "capteur-v1") {
    role status confidence
  }
}
```

```graphql
mutation {
  runCommand(message: "Ajoute un capteur BME680 en I2C sur la carte actuelle") {
    jobId
    accepted
    intent
  }
}
```

## Notes

- `runCommand` crée le projet à la volée si `projectId` est vide.
- Les mutations sont asynchrones : la réponse renvoie un `jobId` ; l'avancement arrive via WebSocket (`/ws/{project_id}`) ou via la query `agents`.
- Le serveur MCP (`/mcp`, voir [mcp.md](mcp.md)) expose les mêmes capacités sous forme d'outils pour les agents externes.
