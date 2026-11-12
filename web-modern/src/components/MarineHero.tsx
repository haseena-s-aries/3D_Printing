/**
 * Marine / offshore artwork from the Aries images (vessel and rig at sunset, wireframe propeller, holographic impeller).
 * Decorative images have empty alt text; the text is real text; motion stops with prefers-reduced-motion.
 * - MarineHero: left panel of the public pages: Aries logo, headline, the holographic impeller and the vessel photograph.
 * - MarineBanner: page-title banner over the vessel photograph with the wireframe propeller (dashboards: large, with
 *   tagline chips; section pages: compact).
 */
import type { ReactNode } from "react";

import ariesLogo from "../assets/aries-logo.png";
import impellerHolo from "../assets/impeller-holo.webp";
import marineVessel from "../assets/marine-vessel.jpg";
import propellerWireframe from "../assets/propeller-wireframe.jpg";
import { Icon, type IconName } from "./icons";

export { ariesLogo, propellerWireframe };

/* ------------------------------------------------------------------ shared pieces */

/* ------------------------------------------------------------------ public pages */

/** Left-hand panel of the public pages (on small screens only the photograph shows, behind the card). */
export function MarineHero() {
  return (
    <aside className="marine-hero">
      <div className="marine-hero-bg" aria-hidden="true" />
      <img className="marine-hero-photo" src={marineVessel} alt="" />
      <WaveLines className="marine-hero-waves" />
      <img className="marine-hero-holo" src={impellerHolo} alt="" />
      <div className="marine-hero-copy">
        <div className="marine-hero-brand">
          <img src={ariesLogo} alt="Aries Marine & Engg. Services" />
          <span className="marine-hero-divider" aria-hidden="true" />
          <span>Digital Passport<br />Platform</span>
        </div>
        <p className="marine-hero-title">Digital passports for marine &amp; offshore <span className="accent">3D spare parts</span></p>
        <span className="marine-hero-rule" aria-hidden="true" />
        <p className="marine-hero-lead">From 3D scan to qualified additive-manufactured spare parts, with models, specifications and evidence in one platform.</p>
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
