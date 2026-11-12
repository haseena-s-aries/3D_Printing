/**
 * Aries artwork for the public pages, page banners, sidebar and KPI tiles, built from the supplied images (metal 3D
 * printer building an impeller, impeller CAD drawing, layered wireframe model). Each section has its own wave, placed once
 * as a decorative layer (never tiled or stretched): the supplied dotted mesh waves (login hero, sidebar foot), a thin
 * flowing line wave (dashboard banner) and soft filled waves (sign-in card, KPI tiles). Also the angled engineering panels. All decorative (aria-hidden / empty alt); the text is real text; the slow wave motion
 * stops with prefers-reduced-motion. Presentation only: no functional logic lives here.
 */
import type { ReactNode } from "react";

import ariesLogo from "../assets/aries-logo.png";
import hudDimensions from "../assets/hud-dimensions.jpg";
import hudLayers from "../assets/hud-layers.jpg";
import heroWave from "../assets/login_bottom_dotted_wave.svg";
import printImpeller from "../assets/print-impeller.jpg";
import sidebarWave from "../assets/sidebar_bottom_dotted_wave.svg";
import { Icon, type IconName } from "./icons";

export { ariesLogo };

/* ------------------------------------------------------------------ waves */

/** Sidebar foot: the supplied compact dotted wave (cropped to its band, drawn at its own proportions). */
export function SidebarWave() {
  return (
    <div className="sidebar-wave" aria-hidden="true">
      <img src={sidebarWave} alt="" />
    </div>
  );
}

/** Soft layered wave between the sign-in card heading and the email field: three overlapping filled shapes. */
export function CardWave({ className = "" }: { className?: string }) {
  return (
    <div className={`card-wave ${className}`} aria-hidden="true">
      <svg viewBox="0 0 520 44" preserveAspectRatio="none" focusable="false">
        <path className="wave-layer wave-layer-1" d="M0 20 C 90 6, 170 30, 270 20 S 430 4, 520 14 V 44 H 0 Z" fill="#e3f6fc" />
        <path className="wave-layer wave-layer-2" d="M0 27 C 110 14, 200 38, 300 27 S 450 14, 520 22 V 44 H 0 Z" fill="#cdeef9" fillOpacity="0.75" />
        <path className="wave-layer wave-layer-3" d="M0 34 C 120 25, 230 44, 330 34 S 460 25, 520 30 V 44 H 0 Z" fill="#b5e3f6" fillOpacity="0.5" />
      </svg>
    </div>
  );
}

/** Dashboard banner: a few thin flowing cyan lines along the bottom (its own wave, not shared with other sections). */
export function BannerWave() {
  const lines = [
    "M0 52 C 180 50, 330 30, 520 30 S 860 50, 1000 40 S 1140 22, 1200 26",
    "M0 56 C 200 54, 350 38, 540 38 S 880 56, 1020 47 S 1150 32, 1200 35",
    "M0 59 C 220 58, 370 46, 560 46 S 900 60, 1040 54 S 1160 42, 1200 44",
  ];
  return (
    <span className="marine-banner-wave" aria-hidden="true">
      <svg viewBox="0 0 1200 60" preserveAspectRatio="none" focusable="false">
        <defs>
          <linearGradient id="banner-wave-stroke" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stopColor="#11c5e8" stopOpacity="0" />
            <stop offset="0.35" stopColor="#11c5e8" stopOpacity="0.85" />
            <stop offset="0.75" stopColor="#3d9bff" stopOpacity="0.8" />
            <stop offset="1" stopColor="#3d9bff" stopOpacity="0" />
          </linearGradient>
        </defs>
        <g fill="none" stroke="url(#banner-wave-stroke)">
          {lines.map((d, i) => <path key={d} d={d} strokeWidth={1.5 - i * 0.25} strokeOpacity={1 - i * 0.25} vectorEffect="non-scaling-stroke" />)}
        </g>
      </svg>
    </span>
  );
}

/** The same light-cyan wave along the bottom of every KPI tile (scales with the tile width). */
export function KpiWave() {
  return (
    <span className="kpi-wave" aria-hidden="true">
      <svg viewBox="0 0 400 40" preserveAspectRatio="none" focusable="false">
        <path className="wave-layer wave-layer-1" d="M0 22 C 70 8, 140 30, 220 18 S 340 6, 400 14 V 40 H 0 Z" fill="#ddf7fc" />
        <path className="wave-layer wave-layer-2" d="M0 28 C 90 16, 170 38, 260 26 S 360 16, 400 22 V 40 H 0 Z" fill="#c8f0f8" fillOpacity="0.85" />
        <path className="wave-layer wave-layer-3" d="M0 34 C 100 26, 190 42, 290 33 S 370 27, 400 30 V 40 H 0 Z" fill="#aeeaf5" fillOpacity="0.6" />
      </svg>
    </span>
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

/**
 * Left-hand panel of the public pages: one continuous navy section laid out with flex/grid: the copy on top, then the
 * visual area (printer photograph left, the four engineering panels right). On desktops it stays in view (one screen
 * high, sticky) while the form column scrolls; its composition tightens on shorter screens so nothing is cut off.
 */
export function MarineHero() {
  return (
    <aside className="marine-hero">
      <img className="marine-hero-wave" src={heroWave} alt="" aria-hidden="true" />
      <div className="marine-hero-copy">
        <img className="marine-hero-logo" src={ariesLogo} alt="Aries Marine & Engg. Services" />
        <p className="marine-hero-eyebrow">Aries Digital Passport Platform</p>
        <p className="marine-hero-title">Digital Passports for Marine 3D Printed Spare Parts</p>
        <p className="marine-hero-lead">End-to-end traceability, certifications, 3D print workflows, and comprehensive spare-part records.</p>
        <ul className="hero-features">
          {HERO_FEATURES.map(([icon, text]) => <li key={text}><Icon name={icon} />{text}</li>)}
        </ul>
      </div>
      <div className="marine-hero-visual" aria-hidden="true">
        <div className="marine-hero-photo"><img src={printImpeller} alt="" /></div>
        <div className="marine-hero-hud"><PrintHud steps /></div>
      </div>
    </aside>
  );
}

/* ------------------------------------------------------------------ in the app */

const BANNER_FEATURES: [IconName, string][] = [["printer3d", "3D Printing"], ["gear", "Spare Parts"], ["passport", "Digital Passports"], ["nodes", "Traceability"]];

/**
 * Page-title banner, a grid of three areas: heading (left), printer photograph (centre) and, on dashboards (default),
 * the engineering panels (right); section pages (compact) have heading + photograph. The same height everywhere.
 */
export function MarineBanner({ children, compact = false }: { children: ReactNode; compact?: boolean }) {
  return (
    <div className={`marine-banner${compact ? "" : " marine-banner-hud"}`}>
      <div className="marine-banner-body">
        <p className="marine-banner-tagline">Marine 3D printing &amp; digital passport operations</p>
        {children}
        <ul className="hero-features banner-features" aria-label="Platform">
          {BANNER_FEATURES.map(([icon, text]) => <li key={text}><Icon name={icon} />{text}</li>)}
        </ul>
      </div>
      <div className="marine-banner-photo" aria-hidden="true"><img src={printImpeller} alt="" /></div>
      {!compact && <div className="marine-banner-overlay"><PrintHud /></div>}
      <BannerWave />
    </div>
  );
}
