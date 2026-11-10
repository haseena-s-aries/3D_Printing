// Digital Passport report renderer (CN-005). Runs locally with the repository's Playwright Chromium; nothing is sent to
// external services. Two modes, given a JSON job file:
//   {"mode": "views", "glb": "<path>", "out": "<dir>"}  -> front.png, top.png, iso.png rendered from the GLB derivative
//      with the same camera rules as the 3D viewer (packages/viewer3d/src/views.ts)
//   {"mode": "pdf", "html": "<path>", "out": "<file.pdf>", "footer": "<html>"} -> A4 PDF with page numbers
// Prints one JSON line: {"ok": true, ...} or {"ok": false, "error": "..."}.
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const require = createRequire(path.join(ROOT, "package.json"));
const { chromium } = require("playwright");
const THREE_DIR = path.join(ROOT, "node_modules", "three");
const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

// Same directions as packages/viewer3d/src/views.ts (glTF Y-up): camera direction from target, and up vectors.
const VIEWS = { front: { dir: [0, 0, 1], up: [0, 1, 0] }, top: { dir: [0, 1, 0], up: [0, 0, -1] }, iso: { dir: [1, 1, 1], up: [0, 1, 0] } };

const PAGE = `<!doctype html><html><head><script type="importmap">{"imports":{"three":"/three/build/three.module.js","three/addons/":"/three/examples/jsm/"}}</script>
<style>html,body{margin:0;background:#fff}</style></head><body><script type="module">
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
window.renderViews = async (views, w, h) => {
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setSize(w, h); renderer.setPixelRatio(1); document.body.appendChild(renderer.domElement);
  const scene = new THREE.Scene(); scene.background = new THREE.Color(0xffffff);
  const pmrem = new THREE.PMREMGenerator(renderer); scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x667788, 0.5));
  const sun = new THREE.DirectionalLight(0xffffff, 1.1); sun.position.set(1, 2, 3); scene.add(sun);
  const gltf = await new GLTFLoader().loadAsync("/model.glb");
  const neutral = new THREE.MeshStandardMaterial({ color: 0xb8bec6, metalness: 0.55, roughness: 0.42 });
  gltf.scene.traverse((o) => { if (o.isMesh) o.material = neutral; });  // neutral engineering rendering
  scene.add(gltf.scene);
  const box = new THREE.Box3().setFromObject(gltf.scene); const sphere = box.getBoundingSphere(new THREE.Sphere());
  if (!isFinite(sphere.radius) || sphere.radius <= 0) throw new Error("empty model");
  const camera = new THREE.PerspectiveCamera(30, w / h, sphere.radius / 100, sphere.radius * 100);
  const vfov = camera.fov * Math.PI / 180, hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
  const dist = sphere.radius / Math.sin(Math.min(vfov, hfov) / 2) * 1.1;
  const out = {};
  for (const [name, v] of Object.entries(views)) {
    const d = new THREE.Vector3(...v.dir).normalize();
    camera.position.copy(sphere.center).addScaledVector(d, dist); camera.up.set(...v.up); camera.lookAt(sphere.center);
    renderer.render(scene, camera); out[name] = renderer.domElement.toDataURL("image/png");
  }
  return out;
};
window.ready = true;
</script></body></html>`;

async function views(browser) {
  const page = await browser.newPage();
  await page.route("http://report.render/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ body: PAGE, contentType: "text/html" });
    if (url.pathname === "/model.glb") return route.fulfill({ body: fs.readFileSync(job.glb), contentType: "model/gltf-binary" });
    if (url.pathname.startsWith("/three/")) {
      const file = path.join(THREE_DIR, url.pathname.slice("/three/".length));
      if (!file.startsWith(THREE_DIR) || !fs.existsSync(file)) return route.fulfill({ status: 404, body: "" });
      return route.fulfill({ body: fs.readFileSync(file), contentType: "text/javascript" });
    }
    return route.fulfill({ status: 404, body: "" });
  });
  await page.route(/^(?!http:\/\/report\.render\/).*/, (route) => route.abort());  // nothing leaves the machine
  await page.goto("http://report.render/");
  await page.waitForFunction(() => window.ready === true, null, { timeout: 30000 });
  const imgs = await page.evaluate(([v]) => window.renderViews(v, 900, 700), [VIEWS]);
  fs.mkdirSync(job.out, { recursive: true });
  const files = {};
  for (const [name, dataUrl] of Object.entries(imgs)) {
    const file = path.join(job.out, `${name}.png`);
    fs.writeFileSync(file, Buffer.from(dataUrl.split(",")[1], "base64"));
    files[name] = file;
  }
  return { views: files };
}

async function pdf(browser) {
  const page = await browser.newPage();
  await page.route(/^(?!data:|file:).*/, (route) => route.abort());  // the HTML is self-contained
  await page.setContent(fs.readFileSync(job.html, "utf8"), { waitUntil: "load" });
  await page.pdf({ path: job.out, format: "A4", printBackground: true, displayHeaderFooter: true, headerTemplate: "<span></span>",
    footerTemplate: job.footer, margin: { top: "14mm", bottom: "16mm", left: "12mm", right: "12mm" } });
  return { pdf: job.out };
}

let browser;
try {
  browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  const result = job.mode === "views" ? await views(browser) : await pdf(browser);
  console.log(JSON.stringify({ ok: true, ...result }));
} catch (e) {
  console.log(JSON.stringify({ ok: false, error: String(e && e.message || e).slice(0, 500) }));
} finally {
  if (browser) await browser.close();
}
