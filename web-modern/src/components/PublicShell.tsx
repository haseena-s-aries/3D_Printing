/** Frame for public pages (sign-in, registration, verification, password reset): same card as the login page. */
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { Icon } from "./icons";
import { MarineHero } from "./MarineHero";
import { ThemeSwitch } from "./theme";
import ariesMark from "../assets/aries-mark.png";

export interface RegistrationConfig {
  registration_enabled: boolean;
  /** Aries staff roles a person may request on the staff account page (empty while registration is off). */
  staff_roles?: { value: string; label: string }[];
  dev_outbox: boolean;
}

export function useRegistrationConfig(): RegistrationConfig | null {
  const [cfg, setCfg] = useState<RegistrationConfig | null>(null);
  useEffect(() => {
    api<RegistrationConfig>("/public/registration-config/").then(setCfg).catch(() => setCfg({ registration_enabled: false, dev_outbox: false }));
  }, []);
  return cfg;
}

export function PublicShell({ title, subtitle, children, wide }: { title: string; subtitle?: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className="login-page">
      <MarineHero />
      <ThemeSwitch className="public-theme" />
      <div className={`login-card${wide ? " login-card-wide" : ""}`}>
        <div className="brand brand-lg">
          <span className="brand-tile" aria-hidden><img src={ariesMark} alt="" /></span>
          <div>
            <h1>{title}</h1>
            <p className="muted">{subtitle ?? "Digital Passport Platform · Aries"}</p>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Shown only when the server runs with the DEBUG-only development outbox. */
export function DevOutboxHint({ cfg }: { cfg: RegistrationConfig | null }) {
  if (!cfg?.dev_outbox) return null;
  return (
    <p className="notice notice-info small" data-testid="dev-outbox-hint">
      Development environment: no email is delivered. Open the <Link to="/dev/outbox">development outbox</Link> to read the message.
    </p>
  );
}

export function BackToSignIn() {
  return <p className="muted small center back-to-sign-in"><Link to="/login"><Icon name="arrowLeft" size="sm" />Back to sign in</Link></p>;
}
