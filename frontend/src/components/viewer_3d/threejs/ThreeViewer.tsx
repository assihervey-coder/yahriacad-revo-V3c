/**
 * ThreeViewer V3+ — rendu 3D WebGL "grade A+++" du PCB :
 *  - stack physique multicouche (cuivre + préimprégnés) avec vue ÉCLATÉE,
 *  - traces de cuivre EXTRUDÉES (boîtes fusionnées par classe, pas des lignes),
 *  - vias dorés avec bague annulaire,
 *  - composants colorés par famille + hover/selection au RAYCASTER,
 *  - capture PNG intégrée, grille optionnelle, OrbitControls amortis.
 * Importé dynamiquement (ssr:false) par PcbViewer3D.
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import type { DesignSchema } from "@/types";

export interface ThreeViewerProps {
  design: DesignSchema | null;
  layersVisible?: Record<string, boolean>;
  autoRotate?: boolean;
  /** Vue éclatée 0..1 — sépare les couches du stack verticalement. */
  exploded?: number;
  /** Sélection d'un composant au clic (ref), hover en continu. */
  onSelectComponent?: (ref: string | null) => void;
  /** Affiche la grille de référence sous la carte. */
  showGrid?: boolean;
  /** Appelé si WebGL est indisponible → l'appelant bascule en vue 2D. */
  onError?: () => void;
}

const BOARD_COLOR = 0x0d5c3f;
const VIA_COLOR = 0xd4af37;
const COPPER_EDGE = 0x67e8f9;

/** Couleurs des classes de cuivre (cohérentes avec la vue 2D). */
const CLASS_COLORS: Record<string, number> = {
  power: 0xf59e0b,
  high_speed: 0x22d3ee,
  differential: 0xa78bfa,
  analog: 0x34d399,
  default: 0x60a5fa,
};

/** Couleur des composants par préfixe de repère. */
const REF_COLORS: Record<string, number> = {
  U: 0x22c55e,   // CI : vert
  J: 0xf472b6,   // connecteurs : rose
  C: 0x94a3b8,   // condensateurs : gris clair
  R: 0xcbd5e1,   // résistances : gris
  L: 0x818cf8,   // inductances : indigo
  D: 0xfbbf24,   // diodes/LED : ambre
  Y: 0xe879f9,   // cristaux
  SW: 0x38bdf8,
};

const BOARD_T = 1.6;          // épaisseur FR4 (mm)
const COPPER_T = 0.07;        // épaisseur visuelle du cuivre (mm)
const TRACE_W = 0.22;         // largeur visuelle d'une trace (mm)
const TRACE_H = 0.08;

interface SceneRefs {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  boardGroup: THREE.Group;
  stackGroup: THREE.Group;
  hoverables: THREE.Object3D[];
  refByUuid: Map<string, string>;
  highlighted: THREE.Object3D | null;
  observer: ResizeObserver;
  frameId: number;
  autoRotate: boolean;
  exploded: number;
  raycaster: THREE.Raycaster;
  pointer: THREE.Vector2;
  pointerActive: boolean;
  disposed: boolean;
}

/** Hauteur (y) d'une couche de cuivre dans le stack — vue normale/éclatée. */
function layerY(index: number, count: number, exploded: number): number {
  const spread = 1 + exploded * 14;                 // écartement éclaté
  if (count <= 1) return 0;
  const t = index / (count - 1);                    // 0 = top, 1 = bottom
  return (0.5 - t) * spread;
}

export function ThreeViewer({
  design,
  layersVisible = {},
  autoRotate = true,
  exploded = 0,
  onSelectComponent,
  showGrid = false,
  onError,
}: ThreeViewerProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const refs = useRef<SceneRefs | null>(null);
  const [hint, setHint] = useState<string | null>(null);

  // --- Initialisation unique de la scène -----------------------------------
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || refs.current) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    } catch {
      onError?.();
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0e14);
    scene.fog = new THREE.Fog(0x0b0e14, 260, 560);

    const camera = new THREE.PerspectiveCamera(45, mount.clientWidth / Math.max(1, mount.clientHeight), 0.1, 2000);
    camera.position.set(55, 60, 70);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.autoRotateSpeed = 1.0;

    // Lumières : ambiance froide + key cyan + fill violet + contre-jour
    scene.add(new THREE.AmbientLight(0xffffff, 0.4));
    const key = new THREE.DirectionalLight(0x22d3ee, 1.15);
    key.position.set(60, 90, 40);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xa78bfa, 0.45);
    fill.position.set(-50, 40, -60);
    scene.add(fill);
    const rim = new THREE.DirectionalLight(0xffffff, 0.25);
    rim.position.set(0, -60, 20);
    scene.add(rim);

    const boardGroup = new THREE.Group();
    const stackGroup = new THREE.Group();
    scene.add(boardGroup);
    scene.add(stackGroup);

    const grid = new THREE.GridHelper(240, 48, 0x1e293b, 0x111827);
    grid.position.y = -14;
    grid.visible = showGrid;
    scene.add(grid);

    const observer = new ResizeObserver(() => {
      const w = mount.clientWidth;
      const h = Math.max(1, mount.clientHeight);
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    });
    observer.observe(mount);

    const state: SceneRefs = {
      renderer, scene, camera, controls, boardGroup, stackGroup,
      hoverables: [], refByUuid: new Map(), highlighted: null,
      observer, frameId: 0, autoRotate, exploded,
      raycaster: new THREE.Raycaster(),
      pointer: new THREE.Vector2(),
      pointerActive: false,
      disposed: false,
    };
    refs.current = state;

    // --- interactions : hover + clic au raycaster --------------------------
    const updatePointer = (ev: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      state.pointer.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      state.pointer.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
      state.pointerActive = true;
    };
    const pick = (): { obj: THREE.Object3D | null; ref: string | null } => {
      if (!state.pointerActive || state.hoverables.length === 0) return { obj: null, ref: null };
      state.raycaster.setFromCamera(state.pointer, camera);
      const hits = state.raycaster.intersectObjects(state.hoverables, false);
      if (hits.length === 0) return { obj: null, ref: null };
      const obj = hits[0].object;
      return { obj, ref: state.refByUuid.get(obj.uuid) ?? null };
    };
    const onPointerMove = (ev: PointerEvent) => {
      updatePointer(ev);
      const { obj, ref } = pick();
      const prev = state.highlighted;
      if (obj !== prev) {
        if (prev) {
          const m = (prev as THREE.Mesh).material as THREE.MeshStandardMaterial;
          if (m && m.emissive) m.emissive.setHex(0x000000);
        }
        if (obj) {
          const m = (obj as THREE.Mesh).material as THREE.MeshStandardMaterial;
          if (m && m.emissive) m.emissive.setHex(0x0ea5e9);
        }
        state.highlighted = obj;
        setHint(ref);
      }
    };
    const onPointerLeave = () => {
      state.pointerActive = false;
      if (state.highlighted) {
        const m = (state.highlighted as THREE.Mesh).material as THREE.MeshStandardMaterial;
        if (m && m.emissive) m.emissive.setHex(0x000000);
        state.highlighted = null;
      }
      setHint(null);
    };
    const onClick = () => {
      const { ref } = pick();
      onSelectComponent?.(ref);
    };
    renderer.domElement.addEventListener("pointermove", onPointerMove);
    renderer.domElement.addEventListener("pointerleave", onPointerLeave);
    renderer.domElement.addEventListener("click", onClick);

    const animate = () => {
      if (state.disposed) return;
      state.frameId = requestAnimationFrame(animate);
      controls.autoRotate = state.autoRotate;
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      state.disposed = true;
      cancelAnimationFrame(state.frameId);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointermove", onPointerMove);
      renderer.domElement.removeEventListener("pointerleave", onPointerLeave);
      renderer.domElement.removeEventListener("click", onClick);
      controls.dispose();
      disposeGroup(boardGroup);
      disposeGroup(stackGroup);
      grid.geometry.dispose();
      renderer.dispose();
      if (renderer.domElement.parentElement === mount) mount.removeChild(renderer.domElement);
      refs.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- Sync props simples ----------------------------------------------------
  useEffect(() => {
    if (refs.current) refs.current.autoRotate = autoRotate;
  }, [autoRotate]);
  useEffect(() => {
    if (refs.current) refs.current.exploded = exploded;
  }, [exploded]);
  useEffect(() => {
    const grid = refs.current?.scene.children.find((c) => c instanceof THREE.GridHelper) as THREE.GridHelper | undefined;
    if (grid) grid.visible = showGrid;
  }, [showGrid]);

  // --- Capture PNG ------------------------------------------------------------
  const capture = useCallback(() => {
    const state = refs.current;
    if (!state) return;
    state.renderer.render(state.scene, state.camera);
    const url = state.renderer.domElement.toDataURL("image/png");
    const a = document.createElement("a");
    a.href = url;
    a.download = `pcb_3d_${Date.now()}.png`;
    a.click();
  }, []);

  // --- Reconstruction du board à chaque design / visibilité ------------------
  useEffect(() => {
    const state = refs.current;
    if (!state) return;
    const { boardGroup, stackGroup, camera, controls, refByUuid, hoverables } = state;
    disposeGroup(boardGroup);
    disposeGroup(stackGroup);
    hoverables.length = 0;
    refByUuid.clear();
    if (!design) return;

    const [w, h] = design.board_size_mm;
    const exploded = state.exploded;
    const nLayers = Math.max(1, design.layers.length);

    const isLayerVisible = (idx: number): boolean => {
      const name = design.layers[idx]?.name ?? "F.Cu";
      return layersVisible[name] !== false;
    };

    // --- Stack physique : substrat entre couches de cuivre -------------------
    for (let i = 0; i < nLayers; i++) {
      const layer = design.layers[i];
      const y = layerY(i, nLayers, exploded);
      const isCopperVisible = isLayerVisible(i);
      // diélectrique sous la couche de cuivre (sauf sous la dernière)
      if (i < nLayers - 1) {
        const yNext = layerY(i + 1, nLayers, exploded);
        const gap = Math.max(0.7, Math.abs(y - yNext) - COPPER_T * 2);
        const diel = new THREE.Mesh(
          new THREE.BoxGeometry(w, gap, h),
          new THREE.MeshStandardMaterial({
            color: 0x14532d, roughness: 0.9, metalness: 0.0,
            transparent: true, opacity: 0.42 + exploded * 0.25,
            depthWrite: false,
          }),
        );
        diel.position.set(0, (y + yNext) / 2, 0);
        stackGroup.add(diel);
      }
      // plan de cuivre de la couche (translucide si plan, cuivre fin)
      const copperColor = layer?.type === "ground" ? 0xc2410c
        : layer?.type === "power" ? 0xb45309 : 0xa16207;
      const copper = new THREE.Mesh(
        new THREE.BoxGeometry(w * 0.985, COPPER_T, h * 0.985),
        new THREE.MeshStandardMaterial({
          color: copperColor, roughness: 0.35, metalness: 0.85,
          transparent: true, opacity: isCopperVisible ? 0.55 : 0.08,
          depthWrite: false,
        }),
      );
      copper.position.set(0, y, 0);
      stackGroup.add(copper);
    }

    // --- Board FR4 (fin, sous le stack) --------------------------------------
    const board = new THREE.Mesh(
      new THREE.BoxGeometry(w, BOARD_T, h),
      new THREE.MeshStandardMaterial({ color: BOARD_COLOR, roughness: 0.65, metalness: 0.05 }),
    );
    board.position.y = layerY(nLayers - 1, nLayers, exploded) - BOARD_T / 2 - COPPER_T;
    boardGroup.add(board);

    // Contour lumineux
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(w, BOARD_T, h)),
      new THREE.LineBasicMaterial({ color: COPPER_EDGE, transparent: true, opacity: 0.55 }),
    );
    edges.position.copy(board.position);
    boardGroup.add(edges);

    // --- Composants ------------------------------------------------------------
    const addComponent = (
      ref: string, bw: number, bh: number, cx: number, cy: number,
      top: boolean, footprint: string, height: number,
    ) => {
      const prefix = (ref.match(/^[A-Z]+/) ?? ["U"])[0];
      const color = REF_COLORS[prefix] ?? REF_COLORS.U;
      const mesh = new THREE.Mesh(
        new THREE.BoxGeometry(bw, height, bh),
        new THREE.MeshStandardMaterial({
          color, roughness: 0.4, metalness: 0.18,
          transparent: true, opacity: top ? 0.96 : 0.72,
        }),
      );
      const surfaceY = top
        ? layerY(0, nLayers, exploded) + height / 2
        : layerY(nLayers - 1, nLayers, exploded) - height / 2;
      mesh.position.set(cx, surfaceY, -cy);
      mesh.userData = { ref };
      refByUuid.set(mesh.uuid, ref);
      hoverables.push(mesh);
      boardGroup.add(mesh);
    };

    for (const c of design.components) {
      const [bw, bh] = c.bbox_mm;
      const top = c.side !== "bottom";
      const isIc = (c.ref ?? "").startsWith("U") || (c.ref ?? "").startsWith("J");
      const height = isIc ? 2.2 : 0.8;
      if (top) {
        if (!isLayerVisible(0)) continue;
        addComponent(c.ref, bw, bh, c.x_mm, c.y_mm, true, c.footprint ?? "", height);
      } else {
        if (!isLayerVisible(nLayers - 1)) continue;
        addComponent(c.ref, bw, bh, c.x_mm, c.y_mm, false, c.footprint ?? "", height);
      }
    }

    // --- Traces extrudées fusionnées par classe + vias -----------------------
    interface Seg { x: number; y: number; z: number; len: number; vertical: boolean }
    const byClass: Record<string, Seg[]> = {};
    const vias: THREE.Vector3[] = [];

    for (const net of design.nets) {
      if (!net.routed || !net.path || net.path.length < 2) continue;
      const layerIdx = net.layer ?? 0;
      if (!isLayerVisible(layerIdx)) continue;
      const cls = net.class_name ?? "default";
      const yTop = layerY(layerIdx, nLayers, exploded) + TRACE_H / 2 + 0.02;
      for (let i = 0; i < net.path.length - 1; i++) {
        const a = net.path[i];
        const b = net.path[i + 1];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const len = Math.hypot(dx, dy);
        if (len < 1e-6) continue;
        const vertical = Math.abs(dx) < Math.abs(dy);
        (byClass[cls] ??= []).push({
          x: (a.x + b.x) / 2,
          y: yTop,
          z: -(a.y + b.y) / 2,
          len, vertical,
        });
      }
      for (const via of net.vias ?? []) {
        vias.push(new THREE.Vector3(via.x, 0, -via.y));
      }
    }

    const boxProto = new THREE.BoxGeometry(1, 1, 1);
    for (const [cls, segs] of Object.entries(byClass)) {
      if (segs.length === 0) continue;
      const geos: THREE.BufferGeometry[] = [];
      const m = new THREE.Matrix4();
      const q = new THREE.Quaternion();
      const scale = new THREE.Vector3();
      const pos = new THREE.Vector3();
      for (const s of segs) {
        if (s.vertical) {
          scale.set(TRACE_W, TRACE_H, s.len);
          q.identity();
        } else {
          scale.set(s.len, TRACE_H, TRACE_W);
          q.identity();
        }
        pos.set(s.x, s.y, s.z);
        m.compose(pos, q, scale);
        const g = boxProto.clone().applyMatrix4(m);
        geos.push(g);
      }
      const merged = geos.length === 1 ? geos[0] : mergeGeometries(geos, false);
      if (!merged) continue;
      for (const g of geos) if (g !== merged) g.dispose();
      const mesh = new THREE.Mesh(
        merged,
        new THREE.MeshStandardMaterial({
          color: CLASS_COLORS[cls] ?? CLASS_COLORS.default,
          roughness: 0.35, metalness: 0.75,
          emissive: new THREE.Color(CLASS_COLORS[cls] ?? CLASS_COLORS.default).multiplyScalar(0.15),
        }),
      );
      boardGroup.add(mesh);
    }
    boxProto.dispose();

    // vias dorés traversants
    if (vias.length > 0) {
      const viaGeos: THREE.BufferGeometry[] = [];
      for (const v of vias) {
        const cyl = new THREE.CylinderGeometry(0.32, 0.32, BOARD_T + 0.5, 10);
        cyl.translate(v.x, 0, v.z);
        viaGeos.push(cyl);
      }
      const mergedVias = viaGeos.length === 1 ? viaGeos[0] : mergeGeometries(viaGeos, false);
      if (mergedVias) {
        for (const g of viaGeos) if (g !== mergedVias) g.dispose();
        boardGroup.add(new THREE.Mesh(
          mergedVias,
          new THREE.MeshStandardMaterial({ color: VIA_COLOR, metalness: 0.9, roughness: 0.25 }),
        ));
      }
    }

    // --- Cadrage caméra ---------------------------------------------------------
    const radius = Math.max(w, h) * 1.15;
    camera.position.set(w * 0.55, radius * 0.9, h * 0.95);
    camera.near = 0.1;
    camera.far = radius * 12;
    camera.updateProjectionMatrix();
    controls.target.set(0, 0, 0);
    controls.update();
  }, [design, layersVisible, exploded]);

  return (
    <div className="relative h-full w-full">
      <div ref={mountRef} className="h-full w-full" data-testid="three-viewer" />
      {hint && (
        <div className="pointer-events-none absolute left-3 top-3 rounded-lg border border-cyan-500/40 bg-panel/90 px-2.5 py-1 text-xs text-cyan-300 shadow-lg">
          {hint}
        </div>
      )}
      <button
        type="button"
        onClick={capture}
        title="Capture PNG de la vue 3D"
        className="absolute right-3 top-3 rounded-lg border border-white/10 bg-panel/90 px-2.5 py-1 text-xs text-slate-300 transition hover:border-cyan-500/50 hover:text-cyan-300"
      >
        Capture
      </button>
    </div>
  );
}

/** Libère les géométries/matériaux d'un groupe (évite les fuites GPU). */
function disposeGroup(group: THREE.Group): void {
  for (const child of [...group.children]) {
    group.remove(child);
    const mesh = child as THREE.Mesh;
    if (mesh.geometry) mesh.geometry.dispose();
    const material = (mesh as THREE.Mesh).material;
    if (Array.isArray(material)) {
      material.forEach((m) => m.dispose());
    } else if (material) {
      (material as THREE.Material).dispose();
    }
  }
}
