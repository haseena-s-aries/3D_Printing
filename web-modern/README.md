# web-modern: UI modernization copy of `web/` (access-test only)

This folder is a working copy of `web/` used for the UI/UX modernization. Only the access-test web server
(port 5175, `AccessTest/tools/web.py`) serves it, so the showcase (5173) and engineering-validation (5174) servers,
which run Vite from `web/`, are not affected while the redesign is reviewed.

- Same API, routes, URLs, permissions and test hooks as `web/`; frontend-only changes.
- Adopting it (after review) = replacing `web/src` with `web-modern/src` (and `index.html`); not done here.
- Tests: `npx vitest run` and `npx tsc --noEmit -p .` in this folder.
