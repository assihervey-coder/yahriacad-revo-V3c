/**
 * Stub gRPC-Web — NON ACTIVÉ par défaut.
 *
 * La gateway V3 expose déjà REST + WebSocket + MCP ; gRPC-Web est prévu pour
 * un canal bas-latence navigateur → services (design_service). Le proto existe
 * côté backend : `pcb_ai_designer_v3/shared/protobuf/design_service.proto`.
 *
 * ─── Comment l'activer ────────────────────────────────────────────────────
 * 1. Générer les stubs navigateur :
 *      npm i grpc-web @improbable-eng/grpc-web google-protobuf
 *      protoc -I=../shared/protobuf design_service.proto \
 *             --js_out=import_style=commonjs,binary:./src/services/grpc \
 *             --grpc-web_out=import_style=commonjs,mode=grpcwebtext:./src/services/grpc
 * 2. Ajouter un proxy gRPC-Web côté passerelle (Envoy ou grpc-web Go proxy)
 *    qui route vers le service gRPC interne (port par défaut 50051).
 * 3. Décommenter l'appel exemple ci-dessous et brancher GrpcWebDesignClient
 *    dans designer/page.tsx à la place d'apiClient.getDesign.
 *
 * ─── Appel exemple (commenté) ─────────────────────────────────────────────
 *   import { GetDesignRequest } from "./grpc/design_service_pb";
 *   import { DesignServiceClient } from "./grpc/DesignServiceClientPb";
 *   const client = new DesignServiceClient("http://localhost:8080", {}, {});
 *   const req = new GetDesignRequest();
 *   req.setProjectId(projectId);
 *   client.getDesign(req, {"x-tenant-id": tenant}, (err, reply) => {
 *     if (err || !reply) return console.warn("gRPC-Web indisponible", err);
 *     const design = designFromProto(reply); // proto → DesignSchema TS
 *     useDesignStore.getState().setDesign(design);
 *   });
 */

/** Configuration d'un canal gRPC-Web (réservée à une activation future). */
export interface GrpcWebConfig {
  /** URL du proxy gRPC-Web (Envoy), ex "http://localhost:8080". */
  host: string;
  /** Tenant injecté dans les métadonnées x-tenant-id. */
  tenant: string;
  /** Format d'encodage des messages. */
  mode: "grpcwebtext" | "grpcweb";
}

export const GRPC_WEB_DEFAULTS: GrpcWebConfig = {
  host: "http://localhost:8080",
  tenant: "default",
  mode: "grpcwebtext",
};

/**
 * Client gRPC-Web placeholder — lève volontairement : le canal REST reste la
 * source de vérité tant que le proxy Envoy n'est pas déployé.
 */
export class GrpcWebDesignClient {
  private readonly config: GrpcWebConfig;

  constructor(config: GrpcWebConfig = GRPC_WEB_DEFAULTS) {
    this.config = config;
  }

  /** getDesign(projectId) → DesignSchema — nécessite les stubs protoc. */
  getDesign(_projectId: string): Promise<never> {
    return Promise.reject(
      new Error(
        `gRPC-Web non activé (host=${this.config.host}) — générer les stubs ` +
          `design_service.proto puis décommenter l'exemple dans src/services/grpc_web.ts`,
      ),
    );
  }
}
