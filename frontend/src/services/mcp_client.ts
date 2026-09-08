/**
 * Client MCP minimal (Model Context Protocol) — JSON-RPC 2.0 sur POST {API}/mcp.
 *
 * Côté backend : backend/api_gateway/mcp_server/server.py expose
 *   initialize / tools/list / tools/call / resources/list / resources/read.
 *
 * Toutes les méthodes retournent un fallback mock si l'endpoint est injoignable.
 */

const DEFAULT_ENDPOINT = `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/mcp`;

/** Outil MCP déclaré par le serveur. */
export interface McpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

/** Réponse tools/call normalisée. */
export interface McpToolResult {
  content: unknown;
  isError: boolean;
  source: "api" | "mock";
}

interface JsonRpcError {
  code: number;
  message: string;
  data?: unknown;
}

interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: number;
  result?: unknown;
  error?: JsonRpcError;
}

const MOCK_TOOLS: McpTool[] = [
  {
    name: "run_design_command",
    description: "Commande NL → design complet (pipeline full_design en tâche de fond).",
    inputSchema: { type: "object", properties: { message: { type: "string" }, project_id: { type: "string" } } },
  },
  {
    name: "query_design",
    description: "Statistiques et état du design d'un projet.",
    inputSchema: { type: "object", properties: { project_id: { type: "string" } } },
  },
  {
    name: "export_package",
    description: "Exporte le paquet de fabrication (gerber, ipc2581, bom...).",
    inputSchema: { type: "object", properties: { project_id: { type: "string" }, fmt: { type: "string" }, factory: { type: "string" } } },
  },
  {
    name: "simulate",
    description: "Lance les simulations (thermal, si, pi, em) et retourne les métriques.",
    inputSchema: { type: "object", properties: { project_id: { type: "string" }, kinds: { type: "array", items: { type: "string" } } } },
  },
];

export class McpClient {
  private endpoint: string;
  private nextId = 1;

  constructor(endpoint: string = DEFAULT_ENDPOINT) {
    this.endpoint = endpoint;
  }

  /** Appel JSON-RPC 2.0 brut — null si l'endpoint est injoignable. */
  private async rpc(method: string, params: Record<string, unknown>): Promise<JsonRpcResponse | null> {
    try {
      const res = await fetch(this.endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: this.nextId++, method, params }),
        signal: AbortSignal.timeout(4000),
        cache: "no-store",
      });
      if (!res.ok) return null;
      return (await res.json()) as JsonRpcResponse;
    } catch {
      return null;
    }
  }

  /** initialize — capabilities du serveur. */
  async initialize(): Promise<{ serverInfo: Record<string, unknown>; source: "api" | "mock" }> {
    const res = await this.rpc("initialize", {
      protocolVersion: "2024-11-05",
      clientInfo: { name: "pcb3-frontend", version: "3.0.0" },
    });
    if (res && res.result && !res.error) {
      const result = res.result as { serverInfo?: Record<string, unknown> };
      return { serverInfo: result.serverInfo ?? {}, source: "api" };
    }
    return { serverInfo: { name: "pcb-ai-designer-mcp (mock)", version: "3.0.0" }, source: "mock" };
  }

  /** tools/list — catalogue des outils. */
  async listTools(): Promise<{ tools: McpTool[]; source: "api" | "mock" }> {
    const res = await this.rpc("tools/list", {});
    if (res && res.result && !res.error) {
      const result = res.result as { tools?: McpTool[] };
      if (Array.isArray(result.tools)) return { tools: result.tools, source: "api" };
    }
    return { tools: MOCK_TOOLS, source: "mock" };
  }

  /** tools/call — exécution d'un outil. */
  async callTool(name: string, args: Record<string, unknown> = {}): Promise<McpToolResult> {
    const res = await this.rpc("tools/call", { name, arguments: args });
    if (res && !res.error) {
      const result = res.result as { content?: unknown; isError?: boolean } | undefined;
      return { content: result?.content ?? null, isError: Boolean(result?.isError), source: "api" };
    }
    return {
      content: { mock: true, tool: name, echo: args },
      isError: false,
      source: "mock",
    };
  }
}

/** Singleton partagé. */
export const mcpClient = new McpClient();
