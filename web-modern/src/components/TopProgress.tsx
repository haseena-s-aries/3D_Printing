/** Thin animated bar at the top of the window while something is saving or a page is loading its data
 *  (api/activity). Appears after a short delay so instant responses do not flicker. */
import { useEffect, useState } from "react";

import { onActivity } from "../api/activity";

export default function TopProgress() {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    let timer: number | undefined;
    const off = onActivity((busy) => {
      window.clearTimeout(timer);
      if (busy) timer = window.setTimeout(() => setVisible(true), 150);
      else setVisible(false);
    });
    return () => { off(); window.clearTimeout(timer); };
  }, []);
  return <div className={`top-progress${visible ? " is-active" : ""}`} role="progressbar" aria-hidden={!visible} aria-label="Loading" />;
}
