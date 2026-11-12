/**
 * Marine / offshore artwork (inline SVG, no image downloads; motion stops with prefers-reduced-motion; all decorative
 * artwork is aria-hidden and the text is real text):
 * - MarineHero: left panel of the public pages: Aries logo, headline, three highlights, and a sunset sea with an
 *   offshore vessel and rig and a metallic 3D impeller on glowing rings.
 * - MarineBanner: page-title banner (dashboards: large, with a vessel and a wireframe propeller; section pages: compact).
 * - PropellerWireframe: the wireframe propeller, also used at the foot of the sidebar.
 */
import type { ReactNode } from "react";

import ariesLogo from "../assets/aries-logo.png";
import { Icon, type IconName } from "./icons";

export { ariesLogo };

/* ------------------------------------------------------------------ shared pieces */

/** Metallic impeller (7 backward-curved blades on a back shroud, hub with bore), seen at a tilt. */
export function MetalImpeller({ className = "", spin = true }: { className?: string; spin?: boolean }) {
  const blades = Array.from({ length: 7 }, (_, i) => i * (360 / 7));
  const blade = "M36 -14 C 78 -34, 118 -78, 146 -128 C 152 -126, 158 -118, 160 -108 C 134 -56, 92 -8, 40 14 Z";
  return (
    <svg className={`metal-impeller ${className}`} viewBox="-200 -150 400 330" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="mi-face" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f4f8fb" />
          <stop offset="0.35" stopColor="#b9c6d1" />
          <stop offset="0.6" stopColor="#6d7c89" />
          <stop offset="0.8" stopColor="#d5dde4" />
          <stop offset="1" stopColor="#59656f" />
        </linearGradient>
        <linearGradient id="mi-edge" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3b4650" />
          <stop offset="1" stopColor="#141b22" />
        </linearGradient>
        <radialGradient id="mi-disc" cx="0.4" cy="0.35" r="0.75">
          <stop offset="0" stopColor="#e6edf3" />
          <stop offset="0.55" stopColor="#8796a3" />
          <stop offset="1" stopColor="#36414b" />
        </radialGradient>
        <linearGradient id="mi-hub" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#5d6a75" />
          <stop offset="0.35" stopColor="#f2f6f9" />
          <stop offset="0.7" stopColor="#9aa8b4" />
          <stop offset="1" stopColor="#47525c" />
        </linearGradient>
        <filter id="mi-shadow" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="14" stdDeviation="12" floodColor="#000814" floodOpacity="0.55" />
        </filter>
      </defs>
      <g filter="url(#mi-shadow)">
        {/* back shroud with thickness */}
        <ellipse cx="0" cy="22" rx="168" ry="94" fill="url(#mi-edge)" />
        <ellipse cx="0" cy="10" rx="168" ry="92" fill="url(#mi-disc)" />
        <g transform="scale(1 0.55)">
          <g className={spin ? "mi-spin" : ""}>
            {/* blade thickness first (darker, offset), then the bright blade faces */}
            {blades.map((a) => <path key={`e${a}`} d={blade} transform={`rotate(${a}) translate(0 16)`} fill="url(#mi-edge)" />)}
            {blades.map((a) => <path key={`f${a}`} d={blade} transform={`rotate(${a})`} fill="url(#mi-face)" stroke="#e9f0f5" strokeOpacity="0.6" strokeWidth="1" />)}
          </g>
        </g>
        {/* hub: cylinder with a bore */}
        <path d="M-44 -6 V -40 A 44 24 0 0 1 44 -40 V -6 A 44 24 0 0 1 -44 -6 Z" fill="url(#mi-hub)" />
        <ellipse cx="0" cy="-40" rx="44" ry="24" fill="#e9eff4" stroke="#7d8a96" strokeWidth="1" />
        <ellipse cx="0" cy="-40" rx="22" ry="12" fill="#1c252e" />
        <ellipse cx="0" cy="-37" rx="16" ry="8" fill="#0b1117" />
      </g>
    </svg>
  );
}

/** Wireframe 3-blade propeller in a technical (HUD) style. */
export function PropellerWireframe({ className = "", frame = false }: { className?: string; frame?: boolean }) {
  const blade = "M0 -18 C 26 -40, 62 -92, 54 -150 C 30 -168, -18 -150, -26 -112 C -30 -80, -18 -44, 0 -18 Z";
  const mesh = [0.35, 0.55, 0.75, 0.92];
  return (
    <svg className={`propeller-wire ${className}`} viewBox="-190 -190 380 380" aria-hidden="true" focusable="false">
      {frame && <g className="pw-frame"><path d="M-178 -140 V -178 H -140 M140 -178 H 178 V -140 M178 140 V 178 H 140 M-140 178 H -178 V 140" /></g>}
      <g className="pw-spin">
        {[0, 120, 240].map((a) => (
          <g key={a} transform={`rotate(${a})`}>
            <path d={blade} className="pw-blade" />
            {mesh.map((m) => <path key={m} d={blade} className="pw-mesh" transform={`scale(${m})`} />)}
            <path d="M0 -18 C 10 -60, 30 -110, 40 -150" className="pw-mesh" />
            <path d="M0 -18 C -8 -60, -14 -100, -20 -130" className="pw-mesh" />
          </g>
        ))}
        <circle r="22" className="pw-blade" />
        <circle r="10" className="pw-mesh" />
      </g>
    </svg>
  );
}

/** Offshore supply vessel (side view, with hull depth and lit windows). */
function Vessel({ x, y, s = 1 }: { x: number; y: number; s?: number }) {
  const id = `v${Math.round(x)}${Math.round(y)}`;
  return (
    <g transform={`translate(${x} ${y}) scale(${s})`}>
      <defs>
        <linearGradient id={`${id}-hull`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3a6595" />
          <stop offset="0.55" stopColor="#1d3d66" />
          <stop offset="1" stopColor="#0e223d" />
        </linearGradient>
        <linearGradient id={`${id}-sup`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="1" stopColor="#c9d5e0" />
        </linearGradient>
      </defs>
      {/* hull with a raked bow, red boot-topping and a white sheer line */}
      <path d="M-176 -46 H 150 C 166 -46, 180 -40, 190 -52 L 168 0 H -160 L -176 -20 Z" fill={`url(#${id}-hull)`} />
      <path d="M-168 -10 H 172 L 168 0 H -160 Z" fill="#c0392b" />
      <path d="M-176 -46 H 150 C 166 -46, 180 -40, 190 -52 L 188 -48 C 178 -38, 166 -42, 150 -42 H -176 Z" fill="#eef3f7" />
      {/* aft deck with cargo, A-frame crane */}
      <rect x="-150" y="-62" width="34" height="16" fill="#e67e22" />
      <rect x="-112" y="-60" width="30" height="14" fill="#2e86c1" />
      <rect x="-78" y="-58" width="26" height="12" fill="#27ae60" />
      <path d="M-60 -46 L -22 -118 L -16 -116 L -50 -46 Z" fill="#f0a500" />
      {/* superstructure */}
      <path d="M10 -46 V -96 H 128 L 142 -74 V -46 Z" fill={`url(#${id}-sup)`} />
      <path d="M30 -96 V -126 H 118 L 128 -110 V -96 Z" fill={`url(#${id}-sup)`} />
      <path d="M46 -126 V -140 H 104 L 110 -132 V -126 Z" fill="#dfe7ee" />
      <g fill="#14304e">
        {[0, 1, 2, 3, 4, 5].map((i) => <rect key={i} x={40 + i * 13} y="-120" width="9" height="8" rx="1.5" />)}
        {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => <rect key={`l${i}`} x={22 + i * 13} y="-88" width="9" height="8" rx="1.5" />)}
      </g>
      <g fill="#ffd27a" opacity="0.9">
        <rect x="66" y="-120" width="9" height="8" rx="1.5" /><rect x="35" y="-88" width="9" height="8" rx="1.5" /><rect x="100" y="-88" width="9" height="8" rx="1.5" />
      </g>
      <path d="M74 -140 V -184 M60 -168 H 88 M66 -156 H 82" stroke="#e6edf3" strokeWidth="3" />
      <circle cx="74" cy="-184" r="3" fill="#ffd27a" className="mh-light" />
      <path d="M-176 -20 L -160 0" stroke="#0a1626" strokeWidth="2" />
    </g>
  );
}

/** Jack-up rig silhouette with lights. */
function Rig({ x, y, s = 1 }: { x: number; y: number; s?: number }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${s})`} fill="#0b1a2e">
      <rect x="-70" y="-150" width="6" height="190" />
      <rect x="64" y="-150" width="6" height="190" />
      <rect x="-4" y="-150" width="6" height="190" />
      <rect x="-90" y="-52" width="180" height="26" />
      <rect x="-70" y="-90" width="70" height="38" />
      <path d="M20 -52 L 30 -160 H 42 L 52 -52 Z" />
      <path d="M26 -110 H 46 M24 -90 H 48 M22 -70 H 50" stroke="#0b1a2e" strokeWidth="3" />
      <path d="M60 -52 L 120 -110 L 124 -106 L 70 -52 Z" />
      {[[-60, -84], [-40, -84], [36, -160], [-80, -50], [80, -50]].map(([cx, cy], i) => (
        <circle key={i} cx={cx} cy={cy} r="2.4" fill="#ffcf73" className="mh-light" />
      ))}
    </g>
  );
}

/** Sunset sea with vessel, rig and glowing rings: the backdrop of the public pages and banners. */
export function MarineScene({ className = "", viewBox = "0 0 1200 900", ships = true }: { className?: string; viewBox?: string; ships?: boolean }) {
  return (
    <svg className={`marine-scene ${className}`} viewBox={viewBox} preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="ms-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#030b1c" />
          <stop offset="0.38" stopColor="#0a2149" />
          <stop offset="0.56" stopColor="#1b3f73" />
          <stop offset="0.64" stopColor="#c86b3c" />
          <stop offset="0.68" stopColor="#f2a65a" />
        </linearGradient>
        <radialGradient id="ms-sun" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#fff1c9" />
          <stop offset="0.25" stopColor="#ffbe6b" stopOpacity="0.9" />
          <stop offset="1" stopColor="#ff8c42" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="ms-sea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#2a4f7c" />
          <stop offset="0.25" stopColor="#0f2f57" />
          <stop offset="1" stopColor="#020a18" />
        </linearGradient>
        <linearGradient id="ms-glint" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffd08a" stopOpacity="0.85" />
          <stop offset="1" stopColor="#ffd08a" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="ms-glow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#2ad8ff" stopOpacity="0.45" />
          <stop offset="1" stopColor="#2ad8ff" stopOpacity="0" />
        </radialGradient>
        <pattern id="ms-grid" width="44" height="44" patternUnits="userSpaceOnUse">
          <path d="M44 0H0V44" fill="none" stroke="#58c7ff" strokeOpacity="0.06" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width="1200" height="900" fill="url(#ms-sky)" />
      <g fill="#cfe3ff" opacity="0.5">
        {[[90, 70], [210, 140], [330, 60], [470, 120], [610, 50], [760, 100], [905, 60], [1040, 130], [1150, 80], [150, 220], [560, 200], [990, 230]].map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={i % 3 === 0 ? 1.6 : 1} />
        ))}
      </g>
      <circle cx="430" cy="600" r="210" fill="url(#ms-sun)" />
      <rect y="606" width="1200" height="294" fill="url(#ms-sea)" />
      <path d="M380 612 h 110 l 40 260 h -190 z" fill="url(#ms-glint)" opacity="0.5" />
      <g stroke="#ffd9a0" strokeLinecap="round" opacity="0.45">
        <path d="M395 630 h 70" strokeWidth="2" /><path d="M380 652 h 100" strokeWidth="1.5" /><path d="M402 676 h 56" strokeWidth="1.2" />
      </g>
      {ships && <>
        <Rig x={640} y={606} s={0.9} />
        <Vessel x={250} y={612} s={0.75} />
      </>}
      <path className="mh-wave mh-wave-a" fill="#0b2546" opacity="0.85" d="M0 720 C 150 700, 300 745, 450 720 S 750 695, 900 722 S 1150 745, 1200 725 V 900 H 0 Z" />
      <path className="mh-wave mh-wave-b" fill="#061830" d="M0 800 C 200 778, 360 825, 600 800 S 980 778, 1200 805 V 900 H 0 Z" />
      <rect width="1200" height="900" fill="url(#ms-grid)" />
      <ellipse cx="850" cy="790" rx="330" ry="120" fill="url(#ms-glow)" />
    </svg>
  );
}

/* ------------------------------------------------------------------ public pages */

const HIGHLIGHTS: [IconName, string][] = [["cube", "3D part models"], ["file", "Certifications & evidence"], ["gear", "Spare part management"]];

/** Left-hand panel of the public pages (on small screens only the scene shows, behind the card). */
export function MarineHero() {
  return (
    <aside className="marine-hero">
      <MarineScene />
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

/** Page-title banner. Dashboards: large, with tagline chips, a vessel and a wireframe propeller. Section pages: compact. */
export function MarineBanner({ children, compact = false }: { children: ReactNode; compact?: boolean }) {
  return (
    <div className={`marine-banner${compact ? " marine-banner-compact" : ""}`}>
      <MarineScene viewBox={compact ? "0 470 1200 220" : "0 420 1200 300"} ships={false} />
      <svg className="marine-banner-vessel" viewBox="-200 -200 410 214" aria-hidden="true" focusable="false"><Vessel x={0} y={0} s={1} /></svg>
      <PropellerWireframe className="marine-banner-part" frame={!compact} />
      <div className="marine-banner-body">
        {children}
        {!compact && (
          <ul className="marine-banner-chips" aria-label="Platform">
            {CHIPS.map(([icon, text]) => <li key={text}><Icon name={icon} />{text}</li>)}
          </ul>
        )}
      </div>
    </div>
  );
}
