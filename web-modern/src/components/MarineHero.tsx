/**
 * Aries artwork for the public pages and page banners, built from the supplied images (metal 3D printer building an
 * impeller, impeller CAD drawing, layered wireframe model) plus SVG decorations (dotted mesh wave, layered card wave,
 * angled engineering panels). All decorative (aria-hidden / empty alt); the text is real text; the slow wave motion
 * stops with prefers-reduced-motion. No functional logic lives here.
 */
import type { ReactNode } from "react";

import ariesLogo from "../assets/aries-logo.png";
import hudDimensions from "../assets/hud-dimensions.jpg";
import hudLayers from "../assets/hud-layers.jpg";
import printImpeller from "../assets/print-impeller.jpg";
import { Icon, type IconName } from "./icons";

export { ariesLogo };

/* ------------------------------------------------------------------ SVG decorations */

/** Points of one mesh line: a blend between two gentle sine curves (t = 0 back line … 1 front line). */
function meshY(x: number, t: number): number {
  const a = 120 + 46 * Math.sin((x / 1200) * Math.PI * 2.1 + 0.4);
  const b = 230 + 34 * Math.sin((x / 1200) * Math.PI * 2.7 + 1.9);
  return a + (b - a) * t;
}
const MESH_LINES = 14;
const MESH_STEP = 24;
const MESH = (() => {
  const lines: string[] = [];
  const dots: { x: number; y: number; o: number; r: number }[] = [];
  for (let i = 0; i < MESH_LINES; i++) {
    const t = i / (MESH_LINES - 1);
    let d = "";
    for (let x = 0; x <= 1200; x += MESH_STEP) d += `${x === 0 ? "M" : "L"}${x} ${meshY(x, t).toFixed(1)} `;
    lines.push(d);
    for (let x = 0; x <= 1200; x += MESH_STEP * 2) dots.push({ x, y: meshY(x, t), o: 0.25 + 0.6 * t * (0.5 + 0.5 * Math.sin(x / 140 + i)), r: 0.9 + 0.9 * t });
  }
  const cross: string[] = [];
  for (let x = 0; x <= 1200; x += MESH_STEP * 2) cross.push(`M${x} ${meshY(x, 0).toFixed(1)} L${x} ${meshY(x, 1).toFixed(1)}`);
  return { lines, dots, cross: cross.join(" ") };
})();

/** Flowing cyan dotted mesh wave (curved lines, cross lines and small glowing dots; slow drift). */
export function MeshWave({ className = "", slice = false }: { className?: string; slice?: boolean }) {
  // slice: keep the mesh proportions in narrow boxes (sidebar) by cropping instead of squeezing
  return (
    <svg className={`mesh-wave ${className}`} viewBox="0 0 1200 300" preserveAspectRatio={slice ? "xMidYMax slice" : "none"} aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="mw-line" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#11c5e8" stopOpacity="0.15" />
          <stop offset="0.45" stopColor="#11c5e8" stopOpacity="0.85" />
          <stop offset="1" stopColor="#146db6" stopOpacity="0.35" />
        </linearGradient>
        <linearGradient id="mw-fade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0" />
          <stop offset="0.35" stopColor="#fff" stopOpacity="1" />
        </linearGradient>
        <mask id="mw-mask"><rect width="1200" height="300" fill="url(#mw-fade)" /></mask>
      </defs>
      <g className="mw-drift" mask="url(#mw-mask)">
        {!slice && <path d={MESH.cross} fill="none" stroke="#11c5e8" strokeOpacity="0.16" strokeWidth="0.8" vectorEffect="non-scaling-stroke" />}
        {MESH.lines.map((d, i) => (
          <path key={i} d={d} fill="none" stroke="url(#mw-line)" strokeWidth={i === MESH_LINES - 1 ? 2 : 1.1}
            strokeOpacity={0.35 + 0.65 * (i / (MESH_LINES - 1))} vectorEffect="non-scaling-stroke" />
        ))}
        <g fill="#8eeeff">{MESH.dots.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={p.r * 1.3} opacity={Math.min(1, p.o * 1.3)} />)}</g>
      </g>
    </svg>
  );
}

/** Soft layered light-blue wave (between the card heading and the email field). */
export function CardWave({ className = "" }: { className?: string }) {
  return (
    <svg className={`card-wave ${className}`} viewBox="0 0 600 60" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="cw-a" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#bfe6f6" stopOpacity="0.75" /><stop offset="1" stopColor="#bfe6f6" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="cw-b" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#8fd3f0" stopOpacity="0.5" /><stop offset="1" stopColor="#8fd3f0" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d="M0 30 C 120 12, 250 46, 380 28 S 560 10, 600 18 V 60 H 0 Z" fill="url(#cw-a)" />
      <path d="M0 40 C 150 24, 270 54, 420 36 S 570 24, 600 30 V 60 H 0 Z" fill="url(#cw-b)" />
      <path d="M0 40 C 150 24, 270 54, 420 36 S 570 24, 600 30" fill="none" stroke="#11c5e8" strokeOpacity="0.3" strokeWidth="1.2" />
    </svg>
  );
}

/* ------------------------------------------------------------------ engineering panels */

/** Decorative QR-style mark (a fixed pattern, not a readable code). */
function QrMark() {
  const n = 21;
  const cells: [number, number][] = [];
  let seed = 7;
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      const finder = (x < 7 && y < 7) || (x > 13 && y < 7) || (x < 7 && y > 13);
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      if (!finder && seed % 100 < 46) cells.push([x, y]);
    }
  }
  const finder = (x: number, y: number) => (
    <g key={`f${x}${y}`}>
      <rect x={x} y={y} width="7" height="7" fill="#fff" /><rect x={x + 1} y={y + 1} width="5" height="5" fill="#0a1a33" />
      <rect x={x + 2} y={y + 2} width="3" height="3" fill="#fff" />
    </g>
  );
  return (
    <svg className="qr-mark" viewBox="-1 -1 23 23" aria-hidden="true" focusable="false">
      <rect x="-1" y="-1" width="23" height="23" fill="#0a1a33" />
      {cells.map(([x, y]) => <rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" fill="#fff" />)}
      {finder(0, 0)}{finder(14, 0)}{finder(0, 14)}
    </svg>
  );
}

const PASSPORT_ROWS: [string, string][] = [["Part ID", "IMP-01427"], ["Material", "316L"], ["Process", "PBF-LB/M"], ["Certification", "DNV"],
  ["Traceability", "End-to-End"]];
const STEPS = ["Design", "Build", "Inspect", "Certify", "Register"];

/**
 * CAD drawing (angled top-left corner with a border following the edge), layered wireframe model and a sample digital
 * passport (illustrative values, not application data); optionally the build workflow.
 */
function PrintHud({ steps = false }: { steps?: boolean }) {
  return (
    <div className="print-hud" aria-hidden="true">
      <div className="hud-angled hud-dims"><div className="hud-angled-inner"><img src={hudDimensions} alt="" /></div></div>
      <div className="hud-row">
        <div className="hud-panel hud-holo"><img src={hudLayers} alt="" /></div>
        <div className="hud-panel hud-passport">
          <div className="hud-passport-head"><Icon name="file" /><strong>Digital Passport</strong><span className="hud-sample">Sample</span></div>
          <div className="hud-passport-body">
            <ul>{PASSPORT_ROWS.map(([k, v]) => <li key={k}><Icon name="check" /><span>{k}:</span> {v}</li>)}</ul>
            <QrMark />
          </div>
        </div>
      </div>
      {steps && (
        <div className="hud-panel hud-steps">
          <div className="hud-passport-head"><Icon name="cube" /><strong>Build (PBF-LB/M)</strong></div>
          <ol>{STEPS.map((s, i) => <li key={s} className={i === STEPS.length - 1 ? "is-current" : ""}><span><Icon name="check" /></span>{s}</li>)}</ol>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ public pages */

const HERO_FEATURES: [IconName, string][] = [["cube", "3D Printing"], ["gear", "Print Workflows"], ["layers", "Digital Passports"], ["nodes", "Traceability"]];

/** Left-hand panel of the public pages: one continuous navy section (photo blended in with gradient overlays). */
export function MarineHero() {
  return (
    <aside className="marine-hero">
      <div className="marine-hero-photo" aria-hidden="true"><img src={printImpeller} alt="" /></div>
      <div className="marine-hero-shade" aria-hidden="true" />
      <MeshWave className="marine-hero-wave" />
      <div className="marine-hero-hud"><PrintHud steps /></div>
      <div className="marine-hero-copy">
        <img className="marine-hero-logo" src={ariesLogo} alt="Aries Marine & Engg. Services" />
        <p className="marine-hero-eyebrow">Aries Digital Passport Platform</p>
        <p className="marine-hero-title">Digital Passports for Marine 3D Printed Spare Parts</p>
        <p className="marine-hero-lead">End-to-end traceability, certifications, 3D print workflows, and comprehensive spare-part records.</p>
        <ul className="hero-features">
          {HERO_FEATURES.map(([icon, text]) => <li key={text}><Icon name={icon} />{text}</li>)}
        </ul>
      </div>
    </aside>
  );
}

/* ------------------------------------------------------------------ in the app */

const BANNER_FEATURES: [IconName, string][] = [["printer3d", "3D Printing"], ["gear", "Spare Parts"], ["passport", "Digital Passports"], ["nodes", "Traceability"]];

/**
 * Page-title banner: heading on the left, the printer photograph as the central visual; dashboards (default) add the
 * engineering panels on the right, section pages (compact) show the photograph only. The same height everywhere.
 */
export function MarineBanner({ children, compact = false }: { children: ReactNode; compact?: boolean }) {
  return (
    <div className={`marine-banner${compact ? "" : " marine-banner-hud"}`}>
      <img className="marine-banner-photo" src={printImpeller} alt="" />
      <div className="marine-banner-shade" aria-hidden="true" />
      {!compact && <div className="marine-banner-overlay"><PrintHud /></div>}
      <div className="marine-banner-body">
        <p className="marine-banner-tagline">Marine 3D printing &amp; digital passport operations</p>
        {children}
        <ul className="hero-features banner-features" aria-label="Platform">
          {BANNER_FEATURES.map(([icon, text]) => <li key={text}><Icon name={icon} />{text}</li>)}
        </ul>
      </div>
    </div>
  );
}
