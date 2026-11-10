/**
 * Shared Three.js viewer for STEP-derived GLB derivatives (VWR-001..VWR-011, MOB-014..MOB-018).
 * Used directly by the web portals and, later, inside the React Native WebView.
 * Carried over from the Phase 0 proof of concept (passed in headless Chromium; not yet verified on devices).
 */
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import { NEUTRAL_MATERIAL, usesDefaultMaterial, type GltfJsonLike } from "./materials";
import { cameraPosition, upVector, type ViewName } from "./views";

export * from "./materials";
export * from "./views";

export type ViewerErrorKind = "LOAD_FAILED" | "UNSUPPORTED_OR_CORRUPT";

export interface ViewerStats {
  loadMs: number;
  triangles: number;
  sizeMm: [number, number, number];
}

export interface ViewerOptions {
  background?: number;
  onError?: (kind: ViewerErrorKind, detail: string) => void;
  onLoaded?: (stats: ViewerStats) => void;
}

export interface Viewer {
  load(url: string): Promise<ViewerStats>;
  setView(view: ViewName): void;
  fit(): void;
  reset(): void;
  readonly currentView: ViewName;
  dispose(): void;
}

export function createViewer(container: HTMLElement, options: ViewerOptions = {}): Viewer {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  container.appendChild(renderer.domElement);
  renderer.domElement.style.display = "block";
  renderer.domElement.style.touchAction = "none";

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(options.background ?? 0xf4f5f7);
  // Studio environment so PBR materials (including metals) are lit from every side (review defect D-5).
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envMap = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environment = envMap;
  scene.environmentIntensity = 0.55;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x667788, 0.5));
  const sun = new THREE.DirectionalLight(0xffffff, 1.1);
  sun.position.set(3, 5, 4);
  scene.add(sun);

  const camera = new THREE.PerspectiveCamera(40, 1, 0.0001, 1000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  let root: THREE.Object3D | null = null;
  let view: ViewName = "iso";
  let frame = 0;
  let disposed = false;

  function resize() {
    const w = container.clientWidth || 1;
    const h = container.clientHeight || 1;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = `${w}px`;
    renderer.domElement.style.height = `${h}px`;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
  ro?.observe(container);
  resize();

  function setView(name: ViewName) {
    view = name;
    if (!root) return;
    const box = new THREE.Box3().setFromObject(root);
    const center = box.getCenter(new THREE.Vector3());
    const radius = box.getBoundingSphere(new THREE.Sphere()).radius;
    // Flush damping momentum first; otherwise leftover rotation drifts the camera (Phase 0 defect fix).
    const damping = controls.enableDamping;
    controls.enableDamping = false;
    controls.update();
    controls.enableDamping = damping;
    const { position, distance } = cameraPosition(name, center.toArray() as [number, number, number], radius, camera.fov, camera.aspect);
    camera.up.set(...upVector(name));
    camera.position.set(...position);
    camera.near = distance / 1000;
    camera.far = distance * 100;
    camera.updateProjectionMatrix();
    controls.target.copy(center);
    controls.update();
  }

  function loop() {
    if (disposed) return;
    frame = requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  }
  loop();

  async function load(url: string): Promise<ViewerStats> {
    const t0 = performance.now();
    let gltf;
    try {
      gltf = await new GLTFLoader().loadAsync(url);
    } catch (e) {
      const detail = String(e);
      const kind: ViewerErrorKind = /JSON|Unexpected|glTF|magic/i.test(detail) ? "UNSUPPORTED_OR_CORRUPT" : "LOAD_FAILED";
      options.onError?.(kind, detail);
      throw Object.assign(new Error(detail), { kind });
    }
    if (root) scene.remove(root);
    root = gltf.scene;
    const neutral = usesDefaultMaterial(gltf.parser.json as GltfJsonLike) ? new THREE.MeshStandardMaterial({ ...NEUTRAL_MATERIAL }) : null;
    let triangles = 0;
    root.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (mesh.isMesh) {
        const g = mesh.geometry;
        triangles += (g.index ? g.index.count : g.attributes.position.count) / 3;
        if (neutral || !mesh.material || !(mesh.material as THREE.MeshStandardMaterial).color) {
          mesh.material = neutral ?? new THREE.MeshStandardMaterial({ ...NEUTRAL_MATERIAL });
        }
      }
    });
    scene.add(root);
    const size = new THREE.Box3().setFromObject(root).getSize(new THREE.Vector3());
    setView("iso");
    const stats: ViewerStats = {
      loadMs: Math.round(performance.now() - t0),
      triangles: Math.round(triangles),
      sizeMm: [size.x * 1000, size.y * 1000, size.z * 1000],
    };
    options.onLoaded?.(stats);
    return stats;
  }

  return {
    load,
    setView,
    fit: () => setView(view),
    reset: () => setView("iso"),
    get currentView() {
      return view;
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(frame);
      ro?.disconnect();
      envMap.dispose();
      pmrem.dispose();
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}
