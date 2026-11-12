/**
 * Decorative marine / offshore scene for the public pages (sign-in, registration, password pages): evening sea, an
 * offshore platform and a supply vessel on the horizon, layered waves, a technical grid and a slowly turning wireframe
 * impeller (the kind of spare part a digital passport describes). Drawn as inline SVG: no image download, sharp at any
 * size, and the motion stops for users who prefer reduced motion. The artwork is aria-hidden; the text is real text.
 */
import type { ReactNode } from "react";

import { Icon, type IconName } from "./icons";

const VANES = 7;

function Impeller({ transform = "translate(800 712) scale(0.86)" }: { transform?: string }) {
  // Seven backward-curved vanes between a hub and a shroud, seen at a slight tilt (the group is scaled on Y).
  const vanes = Array.from({ length: VANES }, (_, i) => {
    const a = (i * 360) / VANES;
    return <path key={i} d="M0 -34 C 30 -60, 70 -86, 92 -150" transform={`rotate(${a})`} />;
  });
  return (
    <g className="mh-impeller" transform={transform}>
      <g transform="scale(1 0.62)">
        <g className="mh-spin">
          <circle r="170" className="mh-shroud" />
          <circle r="150" className="mh-shroud mh-thin" />
          <circle r="34" className="mh-hub" />
          <circle r="14" className="mh-hub mh-thin" />
          <g className="mh-vanes">{vanes}</g>
        </g>
      </g>
      {/* depth: the back shroud and the shaft */}
      <ellipse cx="0" cy="34" rx="170" ry="105" className="mh-shroud mh-back" />
      <path d="M-14 0 V 150 M14 0 V 150" className="mh-shaft" />
      <ellipse cx="0" cy="150" rx="14" ry="8" className="mh-shaft" />
    </g>
  );
}

/** viewBox: the part of the 1200 x 900 scene to show (the dashboard banner shows the horizon band). */
export function MarineScene({ className = "", viewBox = "0 0 1200 900" }: { className?: string; viewBox?: string }) {
  return (
    <svg className={`marine-scene ${className}`} viewBox={viewBox} preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="mh-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#06101f" />
          <stop offset="0.45" stopColor="#0b2340" />
          <stop offset="0.62" stopColor="#14506a" />
          <stop offset="0.7" stopColor="#1f7d86" />
        </linearGradient>
        <radialGradient id="mh-sun" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#ffd9a0" stopOpacity="0.95" />
          <stop offset="0.35" stopColor="#f2a65a" stopOpacity="0.45" />
          <stop offset="1" stopColor="#f2a65a" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="mh-sea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#0f4c63" />
          <stop offset="1" stopColor="#041020" />
        </linearGradient>
        <linearGradient id="mh-wave1" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#1a6b80" stopOpacity="0.9" />
          <stop offset="1" stopColor="#06182b" />
        </linearGradient>
        <linearGradient id="mh-wave2" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#12536a" />
          <stop offset="1" stopColor="#040e1c" />
        </linearGradient>
        <linearGradient id="mh-shade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#04101f" stopOpacity="0.7" />
          <stop offset="0.42" stopColor="#04101f" stopOpacity="0.25" />
          <stop offset="0.6" stopColor="#04101f" stopOpacity="0" />
        </linearGradient>
        <pattern id="mh-grid" width="40" height="40" patternUnits="userSpaceOnUse">
          <path d="M40 0H0V40" fill="none" stroke="#5ccfc2" strokeOpacity="0.07" strokeWidth="1" />
        </pattern>
      </defs>

      <rect width="1200" height="900" fill="url(#mh-sky)" />
      {/* stars */}
      <g fill="#cfe3ff" opacity="0.55">
        {[[90, 70], [210, 140], [330, 60], [470, 120], [610, 50], [760, 100], [905, 60], [1040, 130], [1150, 80], [150, 220], [560, 200], [990, 230]].map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={i % 3 === 0 ? 1.6 : 1} />
        ))}
      </g>
      <circle cx="640" cy="548" r="230" fill="url(#mh-sun)" />

      {/* horizon: offshore jack-up platform and a supply vessel */}
      <g className="mh-silhouette" fill="#06172a">
        <g transform="translate(330 548) scale(0.8)">
          <rect x="-6" y="-120" width="5" height="190" />
          <rect x="70" y="-120" width="5" height="190" />
          <rect x="146" y="-120" width="5" height="190" />
          <rect x="-20" y="-40" width="190" height="34" />
          <rect x="10" y="-78" width="70" height="38" />
          <rect x="96" y="-66" width="44" height="26" />
          <path d="M150 -40 L 205 -112 L 211 -108 L 162 -40 Z" />
          <rect x="34" y="-118" width="6" height="40" />
          <path d="M37 -118 l 22 -6 v 4 z" />
        </g>
        <g transform="translate(540 560) scale(0.7)">
          <path d="M0 0 H 210 L 196 22 H 18 Z" />
          <rect x="140" y="-30" width="52" height="30" />
          <rect x="150" y="-48" width="30" height="18" />
          <rect x="164" y="-66" width="4" height="18" />
          <rect x="30" y="-10" width="96" height="10" />
        </g>
      </g>

      {/* sea and waves */}
      <rect y="548" width="1200" height="352" fill="url(#mh-sea)" />
      <path d="M0 548 h1200" stroke="#ffd9a0" strokeOpacity="0.35" strokeWidth="1.5" />
      <path className="mh-wave mh-wave-a" fill="url(#mh-wave1)" d="M0 650 C 150 625, 300 675, 450 650 S 750 625, 900 650 S 1150 675, 1200 655 V 900 H 0 Z" />
      <path className="mh-wave mh-wave-b" fill="url(#mh-wave2)" d="M0 735 C 180 710, 320 765, 520 735 S 860 705, 1000 740 S 1150 760, 1200 740 V 900 H 0 Z" />
      <path className="mh-wave mh-wave-c" fill="#04101f" d="M0 820 C 200 795, 360 845, 600 820 S 980 795, 1200 825 V 900 H 0 Z" />
      {/* light on the water */}
      <g stroke="#ffd9a0" strokeLinecap="round" opacity="0.4">
        <path d="M600 568 h 80" strokeWidth="2" />
        <path d="M585 590 h 110" strokeWidth="1.5" />
        <path d="M612 612 h 56" strokeWidth="1.2" />
      </g>

      {/* engineering layer: grid and the 3D part */}
      <rect width="1200" height="900" fill="url(#mh-grid)" />
      <Impeller />
      <g className="mh-dims">
        <path d="M654 872 H 946 M654 864 v16 M946 864 v16" />
        <text x="800" y="860">Ø 340 · IMPELLER · L-PBF 316L</text>
      </g>

      {/* readability shade behind the text column */}
      <rect width="1200" height="900" fill="url(#mh-shade)" />
    </svg>
  );
}

/** Dashboard header: the page title over the horizon band of the marine scene. */
export function MarineBanner({ children }: { children: ReactNode }) {
  return (
    <div className="marine-banner">
      <MarineScene viewBox="0 432 1200 200" />
      <svg className="marine-scene marine-banner-part" viewBox="-200 -150 400 330" aria-hidden="true" focusable="false">
        <Impeller transform="translate(0 0) scale(0.9)" />
      </svg>
      <div className="marine-banner-body">{children}</div>
    </div>
  );
}

const HIGHLIGHTS: [IconName, string, string][] = [
  ["cube", "3D models and drawings", "Every spare part with its STEP model, drawings and photos in one passport."],
  ["file", "Manufacturing & test specifications", "Generate the MTS report with the attached QA and lab documents."],
  ["shield", "Secure and audited", "Each company sees only its own data; every action is recorded."],
];

/** Left-hand panel of the public pages (hidden on small screens, where the scene sits behind the card). */
export function MarineHero() {
  return (
    <aside className="marine-hero">
      <MarineScene />
      <div className="marine-hero-copy">
        <div className="marine-hero-brand">
          <span className="brand-mark" aria-hidden>DP</span>
          <span>Aries · Digital Passport Platform</span>
        </div>
        <p className="marine-hero-title">Digital passports for marine and offshore spare parts</p>
        <p>From 3D scan to qualified additive-manufactured part: models, specifications and evidence in one place.</p>
        <ul>
          {HIGHLIGHTS.map(([icon, title, text]) => (
            <li key={title}>
              <span className="marine-hero-icon"><Icon name={icon} /></span>
              <span><strong>{title}</strong><br />{text}</span>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
