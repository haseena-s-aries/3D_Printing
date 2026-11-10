/** Theme (dark = primary presentation, light = alternative), toasts, and app-wide keyboard/focus behaviour. */
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { Icon } from "./icons";

// ------------------------------------------------------------------ theme

export type Theme = "dark" | "light";
const THEME_KEY = "dp-theme";

export function storedTheme(): Theme {
  try {
    const v = window.localStorage.getItem(THEME_KEY);
    if (v === "light" || v === "dark") return v;
  } catch { /* storage unavailable: default */ }
  return "dark";
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme as Theme) || storedTheme());
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { window.localStorage.setItem(THEME_KEY, theme); } catch { /* per-browser convenience only */ }
  }, [theme]);
  return [theme, setTheme];
}

export function ThemeToggle({ className = "" }: { className?: string }) {
  const [theme, setTheme] = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button type="button" className={`icon-btn theme-toggle ${className}`} onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`} title={`Switch to ${next} theme`}>
      <Icon name={theme === "dark" ? "sun" : "moon"} />
    </button>
  );
}

// ------------------------------------------------------------------ toasts

type Toast = { id: number; text: string; tone: "success" | "warning" | "error" };
const ToastContext = createContext<(text: string, tone?: Toast["tone"]) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const push = useCallback((text: string, tone: Toast["tone"] = "success") => {
    const id = ++seq.current;
    setToasts((t) => [...t.slice(-3), { id, text, tone }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toast-region" aria-live="polite" aria-relevant="additions">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone}`} role={t.tone === "error" ? "alert" : "status"}>
            <Icon name={t.tone === "success" ? "check" : t.tone === "error" ? "alert" : "info"} size="sm" />
            <span className="grow">{t.text}</span>
            <button type="button" className="icon-btn" style={{ width: 24, height: 24 }} aria-label="Dismiss"
              onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}><Icon name="close" size="sm" /></button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

// ------------------------------------------------------------------ keyboard and focus (installed once by the shells)

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Every modal dialog in the app (role="dialog" aria-modal="true"): Tab and Shift+Tab stay inside the topmost dialog,
 * and focus returns to the element that opened it when it closes. Every tab list (role="tablist" or .tabs): Left /
 * Right / Home / End move between tabs and activate them.
 */
export function useAppKeyboard() {
  useEffect(() => {
    let opener: HTMLElement | null = null;
    let open = false;
    const topDialog = () => {
      const all = document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]');
      return all.length ? all[all.length - 1] : null;
    };
    const observer = new MutationObserver(() => {
      const d = topDialog();
      if (d && !open) {
        open = true;
      } else if (!d && open) {
        open = false;
        if (opener && document.contains(opener)) opener.focus();
        opener = null;
      }
    });
    const onFocusIn = (e: FocusEvent) => {
      if (!topDialog()) opener = e.target as HTMLElement;
    };
    const onKey = (e: KeyboardEvent) => {
      const d = topDialog();
      if (e.key === "Tab" && d) {
        const items = [...d.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((x) => x.offsetParent !== null);
        if (!items.length) return;
        const first = items[0], last = items[items.length - 1];
        if (!d.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
        else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        return;
      }
      const target = e.target as HTMLElement;
      const list = target.closest?.('[role="tablist"], .tabs, .subtabs');
      if (!list || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key) || target.tagName !== "BUTTON") return;
      // grouped tab bars nest their tabs one level down; plain lists keep direct-child buttons
      const nested = [...list.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
      const tabs = (nested.length ? nested : [...list.querySelectorAll<HTMLButtonElement>(":scope > button")]).filter((b) => !b.disabled);
      const i = tabs.indexOf(target as HTMLButtonElement);
      if (i < 0) return;
      e.preventDefault();
      const j = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      tabs[j].focus();
      tabs[j].click();
    };
    observer.observe(document.body, { childList: true, subtree: true });
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("keydown", onKey);
    return () => {
      observer.disconnect();
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("keydown", onKey);
    };
  }, []);
}
