/**
 * Marine / offshore artwork, from the Aries photographs (vessel and rig at sunset; wireframe propeller) plus a metallic 3D
 * impeller drawn as inline SVG. Decorative images have empty alt text; the text is real text; motion stops with
 * prefers-reduced-motion.
 * - MarineHero: left panel of the public pages: Aries logo, headline, three highlights, the vessel photograph and the
 *   impeller on glowing rings.
 * - MarineBanner: page-title banner over the vessel photograph with the wireframe propeller (dashboards: large, with
 *   tagline chips; section pages: compact).
 */
import type { ReactNode } from "react";

import ariesLogo from "../assets/aries-logo.png";
import marineVessel from "../assets/marine-vessel.jpg";
import propellerWireframe from "../assets/propeller-wireframe.jpg";
import { Icon, type IconName } from "./icons";

export { ariesLogo, propellerWireframe };

/* ------------------------------------------------------------------ shared pieces */

/** Metallic impeller (7 backward-curved blades on a back shroud, hub with bore), seen at a tilt. */
export function MetalImpeller({ className = "", spin = true }: { className?: string; spin?: boolean }) {
  const blades = Array.from({ length: 7 }, (_, i) => i * (360 / 7));
  const blade = "M36 -14 C 78 -34, 118 -78, 146 -128 C 152 -126, 158 -118, 160 -108 C 134 -56, 92 -8, 40 14 Z";
  return (
    <svg className={`metal-impeller ${className}`} viewBox="-200 -150 400 330" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="mi-face" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#bff4ff" stopOpacity="0.95" />
          <stop offset="0.4" stopColor="#3cc8f5" stopOpacity="0.75" />
          <stop offset="0.75" stopColor="#1567b8" stopOpacity="0.7" />
          <stop offset="1" stopColor="#0b3a7a" stopOpacity="0.8" />
        </linearGradient>
        <linearGradient id="mi-edge" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#0d4f95" />
          <stop offset="1" stopColor="#051a3d" />
        </linearGradient>
        <radialGradient id="mi-disc" cx="0.42" cy="0.38" r="0.72">
          <stop offset="0" stopColor="#5fd8ff" stopOpacity="0.55" />
          <stop offset="0.6" stopColor="#135aa6" stopOpacity="0.55" />
          <stop offset="1" stopColor="#06224d" stopOpacity="0.85" />
        </radialGradient>
        <linearGradient id="mi-hub" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#0d4f95" />
          <stop offset="0.4" stopColor="#9eeaff" />
          <stop offset="0.75" stopColor="#2a8fd6" />
          <stop offset="1" stopColor="#0b3a7a" />
        </linearGradient>
        <filter id="mi-shadow" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="0" stdDeviation="7" floodColor="#2ad8ff" floodOpacity="0.55" />
        </filter>
      </defs>
      <g filter="url(#mi-shadow)">
        {/* back shroud with thickness */}
        <ellipse cx="0" cy="22" rx="168" ry="94" fill="url(#mi-edge)" />
        <ellipse cx="0" cy="10" rx="168" ry="92" fill="url(#mi-disc)" stroke="#7fe6ff" strokeOpacity="0.8" strokeWidth="1.6" />
        <ellipse cx="0" cy="10" rx="140" ry="76" fill="none" stroke="#7fe6ff" strokeOpacity="0.25" strokeWidth="1" />
        <ellipse cx="0" cy="10" rx="105" ry="57" fill="none" stroke="#7fe6ff" strokeOpacity="0.2" strokeWidth="1" />
        <g transform="scale(1 0.55)">
          <g className={spin ? "mi-spin" : ""}>
            {/* blade thickness first (darker, offset), then the bright blade faces */}
            {blades.map((a) => <path key={`e${a}`} d={blade} transform={`rotate(${a}) translate(0 16)`} fill="url(#mi-edge)" />)}
            {blades.map((a) => <path key={`f${a}`} d={blade} transform={`rotate(${a})`} fill="url(#mi-face)" stroke="#a8f0ff" strokeOpacity="0.95" strokeWidth="1.6" />)}
          </g>
        </g>
        {/* hub: cylinder with a bore */}
        <path d="M-44 -6 V -40 A 44 24 0 0 1 44 -40 V -6 A 44 24 0 0 1 -44 -6 Z" fill="url(#mi-hub)" />
        <ellipse cx="0" cy="-40" rx="44" ry="24" fill="#bff4ff" fillOpacity="0.9" stroke="#e6fbff" strokeWidth="1.4" />
        <ellipse cx="0" cy="-40" rx="22" ry="12" fill="#06224d" stroke="#7fe6ff" strokeWidth="1" />
        <ellipse cx="0" cy="-37" rx="16" ry="8" fill="#031332" />
      </g>
    </svg>
  );
}

/* ------------------------------------------------------------------ public pages */

const HIGHLIGHTS: [IconName, string][] = [["cube", "3D part models"], ["file", "Certifications & evidence"], ["gear", "Spare part management"]];

/** Left-hand panel of the public pages (on small screens only the photograph shows, behind the card). */
export function MarineHero() {
  return (
    <aside className="marine-hero">
      <div className="marine-hero-bg" aria-hidden="true" />
      <img className="marine-hero-photo" src={marineVessel} alt="" />
      <WaveLines className="marine-hero-waves" />
      <div className="marine-hero-stage" aria-hidden="true">
        <div className="marine-hero-rings"><span /><span /><span /></div>
        <MetalImpeller className="marine-hero-part" />
      </div>
      <div className="marine-hero-copy">
        <div className="marine-hero-brand">
          <img src={ariesLogo} alt="Aries Marine & Engg. Services" />
          <span className="marine-hero-divider" aria-hidden="true" />
          <span>Digital Passport Platform</span>
        </div>
        <p className="marine-hero-title">Digital passports for marine &amp; offshore <span className="accent">3D spare parts</span></p>
        <p className="marine-hero-lead">From 3D scan to qualified additive-manufactured spare parts, with models, specifications and evidence in one platform.</p>
        <ul className="marine-hero-features">
          {HIGHLIGHTS.map(([icon, text]) => (
            <li key={text}><span className="marine-hero-icon"><Icon name={icon} /></span>{text}</li>
          ))}
        </ul>
      </div>
    </aside>
  );
}

/* ------------------------------------------------------------------ in the app */

const CHIPS: [IconName, string][] = [["cube", "3D spare parts"], ["shield", "Digital passports"], ["anchor", "Marine assets"]];

/** Page-title banner over the vessel photograph. Dashboards: large, with a tagline and chips. Section pages: compact. */
export function MarineBanner({ children }: { children: ReactNode; compact?: boolean }) {
  // One layout and one height on every page (dashboards and section pages alike): tagline, title, chips.
  return (
    <div className="marine-banner">
      <img className="marine-banner-photo" src={marineVessel} alt="" />
      <WaveLines className="marine-banner-waves" />
      <img className="marine-banner-part" src={propellerWireframe} alt="" />
      <div className="marine-banner-body">
        <p className="marine-banner-tagline">Marine 3D spare parts &amp; digital passport operations</p>
        {children}
        <ul className="marine-banner-chips" aria-label="Platform">
          {CHIPS.map(([icon, text]) => <li key={text}><Icon name={icon} />{text}</li>)}
        </ul>
      </div>
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
