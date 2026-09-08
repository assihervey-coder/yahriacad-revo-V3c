/**
 * ThreeViewer — scène three.js réelle du PCB :
 *  - board en BoxGeometry fine (FR4 vert),
 *  - composants en boîtes (vert dessus / bleu dessous),
 *  - traces en Line3D depuis les paths des nets + vias en cylindres,
 *  - OrbitControls (three/examples), rotation auto optionnelle, ResizeObserver.
 * Importé dynamiquement (ssr:false) par PcbViewer3D.
 */
"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { DesignSchema } from "@/types";

export interface ThreeViewerProps {
  design: DesignSchema | null;
  layersVisible?: Record<string, boolean>;
  autoRotate?: boolean;
  /** Appelé si WebGL est indisponible → l'appelant bascule en vue 2D. */
  onError?: () => void;
}

const BOARD_COLOR = 0x0e5a3c;
const TOP_COLOR = 0x22c55e;
const BOTTOM_COLOR = 0x3b82f6;
const VIA_COLOR = 0xd4af37;

interface SceneRefs {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  boardGroup: THREE.Group;
  observer: ResizeObserver;
  frameId: number;
  autoRotate: boolean;
  disposed: boolean;
}

/** Épaisseur visuelle du board (unités = mm). */
const BOARD_THICKNESS = 1.6;

export function ThreeViewer({ design, layersVisible = {}, autoRotate = true, onError }: ThreeViewerProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const refs = useRef<SceneRefs | null>(null);

  // --- Initialisation unique de la scène -----------------------------------
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || refs.current) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      onError?.();
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0e14);
    scene.fog = new THREE.Fog(0x0b0e14, 200, 420);

    const camera = new THREE.PerspectiveCamera(45, mount.clientWidth / Math.max(1, mount.clientHeight), 0.1, 2000);
    camera.position.set(55, 60, 70);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.autoRotateSpeed = 1.2;

    // Lumières : ambiance froide + key light cyan + fill violet
    scene.add(new THREE.AmbientLight(0xffffff, 0.45));
    const key = new THREE.DirectionalLight(0x22d3ee, 1.1);
    key.position.set(60, 90, 40);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xa78bfa, 0.5);
    fill.position.set(-50, 40, -60);
    scene.add(fill);

    const boardGroup = new THREE.Group();
    scene.add(boardGroup);

    const observer = new ResizeObserver(() => {
      const w = mount.clientWidth;
      const h = Math.max(1, mount.clientHeight);
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    });
    observer.observe(mount);

    const state: SceneRefs = {
      renderer,
      scene,
      camera,
      controls,
      boardGroup,
      observer,
      frameId: 0,
      autoRotate,
      disposed: false,
    };
    refs.current = state;

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
      controls.dispose();
      disposeGroup(boardGroup);
      renderer.dispose();
      if (renderer.domElement.parentElement === mount) mount.removeChild(renderer.domElement);
      refs.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- Sync prop autoRotate -------------------------------------------------
  useEffect(() => {
    if (refs.current) refs.current.autoRotate = autoRotate;
  }, [autoRotate]);

  // --- Reconstruction du board à chaque design / visibilité -----------------
  useEffect(() => {
    const state = refs.current;
    if (!state) return;
    const { boardGroup, camera, controls } = state;
    disposeGroup(boardGroup);
    if (!design) return;

    const [w, h] = design.board_size_mm;

    // Board (BoxGeometry fine) centré à l'origine, x → x, z → -y PCB
    const board = new THREE.Mesh(
      new THREE.BoxGeometry(w, BOARD_THICKNESS, h),
      new THREE.MeshStandardMaterial({ color: BOARD_COLOR, roughness: 0.65, metalness: 0.05 }),
    );
    board.position.y = 0;
    boardGroup.add(board);

    // Sérigraphie : contour lumineux (EdgesGeometry)
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(w, BOARD_THICKNESS, h)),
      new THREE.LineBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.5 }),
    );
    boardGroup.add(edges);

    // Composants
    const isLayerVisible = (idx: number): boolean => {
      const name = design.layers[idx]?.name ?? "F.Cu";
      return layersVisible[name] !== false;
    };
    for (const c of design.components) {
      const [bw, bh] = c.bbox_mm;
      const isTop = c.side !== "bottom";
      if (!isTop && !isLayerVisible(3)) continue;
      const isIc = (c.footprint ?? "").toUpperCase().startsWith("ESP") || (c.ref ?? "").startsWith("U");
      const height = isIc ? 2.2 : 0.8;
      const mesh = new THREE.Mesh(
        new THREE.BoxGeometry(bw, height, bh),
        new THREE.MeshStandardMaterial({
          color: isTop ? TOP_COLOR : BOTTOM_COLOR,
          roughness: 0.4,
          metalness: 0.15,
          transparent: true,
          opacity: isTop ? 0.95 : 0.7,
        }),
      );
      mesh.position.set(c.x_mm, isTop ? BOARD_THICKNESS / 2 + height / 2 : -BOARD_THICKNESS / 2 - height / 2, -c.y_mm);
      boardGroup.add(mesh);
    }

    // Traces (Line3D depuis les paths) + vias
    for (const net of design.nets) {
      if (!net.routed || !net.path || net.path.length < 2) continue;
      const layerIdx = net.layer ?? 0;
      if (!isLayerVisible(layerIdx)) continue;
      const color =
        net.class_name === "power" ? 0xf59e0b : net.class_name === "high_speed" ? 0x22d3ee : net.class_name === "differential" ? 0xa78bfa : 0x60a5fa;
      const pts = net.path.map((p) => new THREE.Vector3(p.x, BOARD_THICKNESS / 2 + 0.15, -p.y));
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineBasicMaterial({ color, linewidth: 2 }),
      );
      boardGroup.add(line);

      for (const via of net.vias ?? []) {
        const cyl = new THREE.Mesh(
          new THREE.CylinderGeometry(0.4, 0.4, BOARD_THICKNESS + 0.4, 12),
          new THREE.MeshStandardMaterial({ color: VIA_COLOR, metalness: 0.8, roughness: 0.3 }),
        );
        cyl.position.set(via.x, 0, -via.y);
        boardGroup.add(cyl);
      }
    }

    // Cadrage caméra sur le board
    const radius = Math.max(w, h) * 1.15;
    camera.position.set(w * 0.55, radius * 0.85, h * 0.9);
    camera.near = 0.1;
    camera.far = radius * 12;
    camera.updateProjectionMatrix();
    controls.target.set(0, 0, 0);
    controls.update();
  }, [design, layersVisible]);

  return <div ref={mountRef} className="h-full w-full" data-testid="three-viewer" />;
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
