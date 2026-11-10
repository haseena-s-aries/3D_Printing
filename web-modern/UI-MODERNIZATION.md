# UI/UX modernization: audit and plan (access-test, `web-modern/`)

## Isolation

`web/` is served live by three Vite dev servers: showcase 5173, validation 5174 and access-test 5175. The
modernization therefore lives in this copy:
- **5175 only:** `AccessTest/tools/web.py` now serves `web-modern/`.
- **5173 and 5174:** still served from the unchanged `web/`.
- **Unchanged here:** backend, API contracts, routes, URLs, permissions and calculations.

## Audit (before)

- **Styling.** One stylesheet (523 lines) has light-only tokens, about 40 hard-coded colours and duplicate rules
  (`.check-grid` ×3, `.num` ×2, `.form-section` ×2). Each feature appended its own section, so spacing, radius and
  typography drift between modules.
- **Shell.** The sidebar is a flat, text-only list (up to 13 items) with no grouping or icons. The AI workflow
  (intelligence, assessment) is only reachable through tabs inside "Inventory import". Breadcrumbs are not links. The
  topbar has a coloured tenant "pill" (orange or blue) and a plain "Sign out" text button.
- **Feedback.** Loading shows the plain text "Loading…": no skeletons, so layouts shift. There are no toasts. Empty
  states are bare text. Badges get their tone at each call site, so the same meaning can appear in different colours.
- **Dialogs.** Four dialogs share a pattern with initial focus and Escape, but focus is neither trapped nor returned,
  and the page behind still scrolls.
- **Tables.** Headers don't stick; mobile turns tables into blocks; long technical values are not truncated or given
  tooltips.
- **AI screens.** The part page stacks four large cards (intelligence, feasibility, cost, recommendation) with no
  overview or progression. Savings, qualification and review states are clear in text but not visually distinct.
- **Login.** A split diagonal gradient; the brand mark is orange.
- **Accessibility.** There is a visible focus ring. Tabs have no arrow-key support. Reduced-motion preferences are not
  handled.

## Direction

- **Theme:** a premium industrial SaaS look. Deep navy/slate dark theme by default, a light theme as the alternative
  (toggle in the topbar, remembered per browser, no flash on load). Muted teal accent.
- **Visual system:** a 4 px spacing grid, 6/10/14 px radius, restrained elevation, 150–220 ms transitions (none under
  reduced motion), and one semantic colour per status.
- **Dependencies:** no new UI framework or font download. Icons are a small inline SVG set (no dependency); charts are
  inline SVG.

## Stages

1. **Design tokens and primitives.**
   - Tokens: colour, type, space, radius, elevation and motion, with dark and light themes.
   - Primitives: buttons, inputs, cards, tables, tabs, badges/status, notices, skeletons, empty and error states,
     toasts, dialog focus management, tooltips for truncated values, icons and the theme toggle.
   - Shell: grouped sidebar with icons (collapsible rail on desktop, drawer on mobile), topbar (working-in context,
     organisation switcher, theme, notifications, user), linked breadcrumbs.
2. **Main screens:** dashboards (Aries Admin, Aries Engineer, client), login/registration/activation, Client
   Management, Engineers & Access, users, Digital Inventory (catalog, table, quick view), projects, requests, audit.
3. **Digital Passport workspace:** header and state strip, tabs, 3D viewer chrome, PDF viewer, documents, revision
   history, and the Report Builder (template cards, attachment ordering, complete-PDF preview).
4. **AI assessment experience:** a workflow stepper (Inventory → Classification → Feasibility → Commercial →
   Recommendation → Engineering review → Quarterly assessment) on the AI screens, plus a section navigator on the
   part page.
   - Qualification is shown consistently: never green for an unqualified option. "Approved for further study" is not
     shown as an approval.
   - Estimated and verified savings are visually separate.
   - Quarterly trend charts.
5. **Polish and verification:** responsive and accessibility pass, lazy loading of heavy screens, no repeated
   requests, then a full regression (unit, build, every browser flow) and before/after screenshots at 1440 px and 390 px.

## Test hooks kept

Accessible names, roles, `data-testid`s, visible labels and routes used by unit tests and browser flows are unchanged
(e.g. "Sign out", "Working in", tab names, table names, KPI test ids). `NAV` and `visibleNav` keep their exact output;
grouping and icons are layered on top.

## Implementation record (all five stages)

Source changes are confined to `web-modern/` (23 files in `src/`: 1,294 lines added, 554 removed, against `web/src`).
`web/`, `backend/` and `packages/` are untouched; the redesign is served on 5175 only.

### Design system
- **Tokens** (`styles.css`, `:root[data-theme]`): colour (surfaces, ink, line, accent, four status families with
  bg/ink/line, chart series), type scale, spacing, radius, elevation, motion (150/200 ms; zero under reduced motion).
  Dark is the default; light is chosen with the topbar toggle (`dp-theme` in localStorage, applied before first paint).
- **Primitives:** buttons (primary, ghost, danger, small; gated actions with a lock icon), inputs and selects, segmented
  controls, tabs (arrow/Home/End keys), cards, tables (sticky headers in scroll lists, edge shadows when wider than
  the card), badges with a status dot, notices, skeleton loaders (`Loading variant`), empty states with an icon, toasts,
  dialogs (focus trapped and returned, page scroll locked), `Truncate` and `Clamp` for long values, icons
  (`components/icons.tsx`), workflow stepper (`components/AiWorkflow.tsx`), inline SVG charts.
- **Shell:** grouped sidebar with icons (Overview, Inventory & passports, AI assessment, Requests, Administration),
  a collapsible rail on desktop and a drawer on mobile, a skip link, a sticky topbar (working-in context, organisation
  switcher, theme, notifications, user), and linked breadcrumbs.

### Screens
- **Stage 1–2:** login, registration and activation; dashboards for all three portals (KPI icons, sorted and
  filterable organisations, an assessment snapshot for engineers); clients list (scrolling list), client management;
  users (wider member table); digital inventory (card badges wrap, image placeholders, mobile filters two per row,
  section switch scrolls); admin inventory, audit filters.
- **Stage 3:** passport header with compact gated actions, a two-column state strip on mobile; the 3D viewer with a
  canvas matching the theme, segmented views, icon actions and a spinner; compact empty document sections; Report
  Builder with template cards, a sticky attachment-order panel and a dashed empty state.
- **Stage 4:** the AI workflow stepper on part intelligence, quarterly assessment and the part page (sticky there,
  jumping to each section).
  - Recommendation review states are never green: "Approved for further study" and "Potentially suitable" use the
    info tone.
  - Estimated savings show amber with a dashed underline; verified savings show green.
  - The review-queue detail is clamped, with "Show more".
  - Changes since the preceding run list only what changed.
  - A run-history chart (assessed, reused and failed per run) has a legend and a table view; its colours were
    validated for colour vision deficiency in both themes.
- **Stage 5:**
  - Workspace routes are lazy-loaded, cutting the main bundle from 637 KB to 415 KB.
  - Identical in-flight GETs are shared, cutting dashboard API calls from 13 to 8.
  - Long identifiers wrap.
  - Accessibility audit added (`AccessTest/tools/a11y-check.mjs`).

### Verification (2026-10-28, on 5175 against the access-test API 8002)
- **Static checks:** `tsc --noEmit` clean; vitest 23 files, 107/107 tests; production build passes.
- **Browser flows:** 17 flows on the final code, 546/546 checks.
  - Admin, company and inventory flows: flow 24, client-management 30, company-profile 49, inventory 23.
  - Submission and editing flows: submissions 33, clone 37, edits 41, forms-material 28, jobsheet 32.
  - Report and import flows: reports 19, report-builder 27, inventory-import 40.
  - AI flows: part-intelligence 20, feasibility 36, cost-comparison 53, recommendation 40, independent-review 14.
- **Not re-run:** `flow-assessment`. It is state-dependent and changes the pilot data. Its dashboard is covered by
  the unit test (KPIs, "estimated vs verified" text, history, start/retry/active run) and the screenshots.
- **Accessibility (`a11y-check.mjs`):** 23 pages × 4 roles at 1440 px and 390 px.
  - No unnamed controls, unlabelled fields, images without alt or duplicate ids.
  - No horizontal page scroll at phone width.
  - The first Tab stop is the skip link, with a visible focus ring.
  - Every text token is ≥ 4.5:1 on the page and card surfaces in both themes.
- **Screenshots:** `AccessTest/evidence/ui-modernization/{before,after,after-light}` hold 54 screens each, at
  1440 and 390 px. `compare.html` shows them side by side.
- **Other environments:** showcase (5173 → 8000) and engineering validation (5174 → 8001) still serve the unchanged
  `web/`. No file in `web/`, `backend/` or `packages/` changed during this work.

### Outstanding usability items (not done)
- **Part page length.** The part page is still long. The sticky workflow stepper makes it navigable; splitting the
  four AI panels into tabs would shorten it further.
- **Wide tables.** The quarterly "Parts" table (9 columns) and the cost option columns stay dense. They scroll
  horizontally on narrow screens.
- **Savings trend chart.** A per-run trend of estimated vs verified savings needs per-run summaries. The run list does
  not carry them, and fetching each run would add requests, so the chart shows parts processed per run instead.
- **Theme switch with an open 3D view.** The canvas keeps its colour until the viewer reloads.
- **Mobile stepper.** The workflow stepper scrolls sideways on phones.
- **Adoption.** To make this the default for 5173/5174, replace `web/src` and `web/index.html` with this copy. That
  changes the showcase and validation environments, so it needs approval first.

## Layout correction: Digital Inventory and Digital Passport (2026-10-28, round 2)

Feedback: the colour palette was fine; the problems were information density, weak hierarchy, too little whitespace
and unclear navigation. This round reworks layout only. Data, APIs, permissions, readiness rules and gates are
unchanged.

**Digital Inventory**
- **Grid:** at most 3 cards per row (`.part-grid`), 2 on tablets and 1 on phones, with 24 px gaps and 20–22 px card
  padding.
- **Card face:** part number, name and project/size; a small 64 px photo or initials tile (was a 150–190 px
  placeholder); one stage status, plus review/critical badges only when they apply; then a quiet four-row fact list
  (passport, data captured, manufacturing, documents as text).
- **Card actions:** one primary action (Open passport, or Open part) and Quick view. "More actions" (an accessible menu:
  arrow keys, Escape and focus return) holds Request, Clone part and Open part record. Nothing was removed.
- **Filters:** search, project, sort, Advanced filters (category, data captured, evidence level, eligibility, Has 3D
  view; starts open when one is in use), and Clear filters.
- **Grid/List switch:** icons added. The list view shows one status badge per cell and documents as text.

**Digital Passport**
- **Header:** the identity comes first (eyebrow `Digital passport DP-…`, the part title as H1, spare part link and
  revision). Publication state is the one prominent status. Evidence level, manufacturing and per-level
  data-captured meters sit in a compact summary row. The gate notice is a single line with a lock icon instead of a
  full-width warning banner.
- **Tabs:** the same seven tabs, `?tab=` values and permissions, now separated tab surfaces in three labelled groups:
  Passport (Overview, Readiness data), Engineering files (3D model, Documents, Reports), History (Revision,
  Manufacturing).
  - Clear active, hover and focus states, with icons.
  - Readiness shows its completion count (hidden from the accessible name).
  - Arrow/Home/End keys move between tabs (roving tabindex).
  - On phones the bar scrolls sideways without the group labels.
- **Overview:** the Status card that repeated the header was removed; the readiness summaries have a heading with the
  "guidance only" note.
- **Readiness data:**
  - Level cards (R-L1, R-L2, R-L3) act as the level tabs and show missing counts and meters.
  - Each level's fields sit in collapsible sections whose headers show "n missing" or "Complete" and "x/y required".
  - "Expand all sections" and "Collapse all" controls are provided, and the missing fields are listed as chips.
  - Sections start collapsed and keep their state across saves. Fields stay mounted, so data, validation and saving
    are unchanged. Saving opens any section holding an invalid "not applicable" reason before the browser reports it.

**Verification**
- **Static checks:** typecheck clean; unit tests 108/108 (a new test covers the card menu: keyboard, focus return, no
  approval action).
- **Accessibility:** audit 0 issues.
- **Browser flows (546/546 as last run, affected flows re-run):** inventory 23, clone 37, forms-material 28,
  submissions 33, edits 41, reports 19, report-builder 27, jobsheet 32, flow 24.
- **Flow updates:** `flow-clone`, `flow-forms-material` and `flow-submissions` were changed for the new interaction
  (open "More actions"; "Expand all sections"). The checks themselves are unchanged.
- **Screenshots:** `AccessTest/evidence/ui-redesign/{before,after}` hold 22 captures each; `compare.html` shows them
  side by side.
