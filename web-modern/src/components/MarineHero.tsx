/**
 * Aries artwork for the public pages and page banners, from the supplied images: a metal 3D printer building an
 * impeller, its dimension drawing, a holographic wireframe model and an example digital-passport card, plus animated
 * wave lines. All decorative (aria-hidden / empty alt); the text is real text; motion stops with prefers-reduced-motion.
 */
import type { ReactNode } from "react";

import ariesLogo from "../assets/aries-logo.png";
import hudDimensions from "../assets/hud-dimensions.jpg";
import hudHolo from "../assets/hud-holo.jpg";
import printImpeller from "../assets/print-impeller.jpg";
import propellerWireframe from "../assets/propeller-wireframe.jpg";
import { Icon, type IconName } from "./icons";

export { ariesLogo, propellerWireframe };

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

/** Technical overlay: dimension drawing, holographic model, example passport card and (optionally) the build steps. */
function PrintHud({ steps = false }: { steps?: boolean }) {
  return (
    <div className="print-hud" aria-hidden="true">
      <div className="hud-panel hud-dims"><img src={hudDimensions} alt="" /></div>
      <div className="hud-row">
        <div className="hud-panel hud-holo"><img src={hudHolo} alt="" /></div>
        <div className="hud-panel hud-passport">
          <div className="hud-passport-head"><Icon name="file" /><strong>Digital Passport</strong></div>
          <div className="hud-passport-body">
            <ul>{PASSPORT_ROWS.map(([k, v]) => <li key={k}><Icon name="check" />{k}: {v}</li>)}</ul>
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

/** Animated cyan wave lines (a slow drift; still for reduced motion). */
export function WaveLines({ className = "" }: { className?: string }) {
  // Each line is drawn twice as wide as the box and moved by half its width, so the drift loops seamlessly.
  const line = (y: number, amp: number) =>
    `M0 ${y} ` + Array.from({ length: 8 }, (_, i) => `q 150 ${i % 2 ? amp : -amp} 300 0`).join(" ");
  return (
    <svg className={`wave-lines ${className}`} viewBox="0 0 1200 200" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <g className="wl-a"><path d={line(120, 38)} /></g>
      <g className="wl-b"><path d={line(140, 30)} /></g>
      <g className="wl-c"><path d={line(160, 24)} /></g>
      <g className="wl-d"><path d={line(178, 18)} /></g>
    </svg>
  );
}

const HERO_FEATURES: [IconName, string][] = [["cube", "3D Printing"], ["gear", "Print Workflows"], ["layers", "Digital Passports"], ["nodes", "Traceability"]];

/** Left-hand panel of the public pages (on small screens only the photograph shows, behind the card). */
export function MarineHero() {
  return (
    <aside className="marine-hero">
      <div className="marine-hero-bg" aria-hidden="true" />
      <img className="marine-hero-photo" src={printImpeller} alt="" />
      <WaveLines className="marine-hero-waves" />
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

const BANNER_FEATURES: [IconName, string][] = [["printer3d", "3D Printing"], ["gear", "Spare Parts"], ["passport", "Digital Passports"], ["nodes", "Traceability"]];

/**
 * Page-title banner: the printer photograph with the eyebrow, title and four features. Dashboards (hud) also show the
 * technical overlay; section pages (compact) show the photograph only. The same height everywhere.
 */
export function MarineBanner({ children, compact = false }: { children: ReactNode; compact?: boolean }) {
  return (
    <div className={`marine-banner${compact ? "" : " marine-banner-hud"}`}>
      <img className="marine-banner-photo" src={printImpeller} alt="" />
      <WaveLines className="marine-banner-waves" />
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
