/**
 * Client dashboard: the three ways a spare part enters the platform (post-UAT Phase 4), shown only for the routes the
 * signed-in member may use. Each route ends in the same engineering lifecycle: digital passport, documents and CAD,
 * Part Intelligence, feasibility, cost and lead time, recommendation, independent review and client sharing.
 */
import { Link } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { Icon, type IconName } from "./icons";

type Route = { key: string; icon: IconName; title: string; text: string; to: string; action: string; capability: string };

const ROUTES: Route[] = [
  { key: "details", icon: "file", title: "I have the part details", capability: "parts.submit", to: "/parts/submit", action: "Submit a part",
    text: "Enter the part's identification, material and dimensions, and attach the CAD model, drawing, photographs or documents you have." },
  { key: "scan", icon: "cube", title: "Aries should scan the part", capability: "requests.create", to: "/requests/new-scan", action: "Request 3D scanning",
    text: "No drawings or CAD? Aries scans the physical part on site, reverse-engineers the CAD and drawings and creates its digital passport." },
  { key: "clone", icon: "layers", title: "A variant of an existing part", capability: "parts.submit", to: "/parts?catalog=all", action: "Choose a part to clone",
    text: "Open an accepted part and choose Clone to propose changed dimensions or a different material. The original is never changed." },
];

export function EntryRoutes() {
  const { can } = useAuth();
  const routes = ROUTES.filter((r) => can(r.capability));
  if (!routes.length) return null;
  return (
    <section className="card entry-routes" aria-labelledby="entry-routes-title">
      <div className="card-head"><h2 id="entry-routes-title"><Icon name="plus" size="sm" />Start a new spare part</h2></div>
      <p className="muted small">Each route leads to the same engineering process: digital passport, AI assessment, independent engineering
        review and, when approved for further study, a result shared with you. Nothing here is a manufacturing approval.</p>
      <ul className="entry-route-list">
        {routes.map((r) => (
          <li key={r.key} className="entry-route">
            <span className="entry-route-icon"><Icon name={r.icon} /></span>
            <h3>{r.title}</h3>
            <p className="small">{r.text}</p>
            <Link className="btn btn-primary btn-small" to={r.to}>{r.action}</Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
