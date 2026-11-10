# P1: Visual client catalog — results

- **Date:** 2026-10-16
- **Status:** implemented and **uncommitted** for review.
- **Unchanged:**
  - No manufacturing request, approval, QA, release or production action exists.
  - OQ-35 and OQ-36 gates are unchanged.
  - BRD v0.4 is unchanged, and no Azure resources were provisioned.
- **Design:** our own design system. No third-party branding or assets.

## What changed

| Area | Change | Requirement basis |
|---|---|---|
| Parts API | Read-only `manufacturing_eligibility` per row | PUB-003 (display only), MOB-010 |
| Parts API | `eligibility` filter (`not_eligible` includes parts without passport) | MOB-010 |
| Parts API | `catalog=published` / `in_digitisation` sections | BR-R03 / MOB-009; drafts stay visible to their own client (your instruction 7) |
| Catalog page | **Grid** (cards) and **List** (the existing searchable table) toggle, kept in the URL | BR-010 |
| Catalog page | Client users default to Grid. Operator staff default to List and get an "All parts" section, so the engineering tables are preserved. | — |
| Catalog page | Sections: **Published catalog (n)** and **In digitisation (n)**. A client opens Published when it has parts, otherwise In digitisation. | BR-R03, MOB-009 |
| Cards | Stored part image (photo thumbnail) with placeholder, part number, name, project, dimensions, passport and revision | BR-010, MOB-011 |
| Cards | Readiness: "Published", or "In digitisation · not manufacturing-ready" | — |
| Cards | Stored eligibility label; data captured; document chips; critical flag | — |
| Cards | Actions: Quick view, Open passport or Open part | — |
| Quick view | Part facts and stored states | — |
| Quick view | Interactive 3D model of the current STEP derivative (existing viewer) | VWR-001 (viewer from the catalog) |
| Quick view | Document list with permission-checked previews (existing PDF and image previewers, single-use links) | BR-039, VWR-010 |
| Quick view | DWG shown as "preview not available (OQ-27)" | — |
| Quick view | Statement that manufacturing requests are not available yet | — |
| Quick view | One media item at a time (3D or document) | Technical, below |
| Responsive | Cards in a single column under 600 px; Quick view becomes a full-screen sheet; filters stack full-width | — |

**Not shown anywhere:** prices, lead times, approvals, or any eligibility other than the stored state. All stored
states are currently draft and not eligible, because the transitions are gated.

**Technical note.** The shared 3D viewer redraws every animation frame. On software WebGL (headless browsers) and
low-end devices, that starved a PDF being rendered beside it in Quick view. Quick view therefore shows either the
3D model or the selected document, with "Back to 3D model". A follow-up could make the viewer render on demand
(package `@passport/viewer3d`); not done in P1.

## Tests (executed 2026-10-16)

| Suite | Result |
|---|---|
| Backend (PostgreSQL) | **159 passed**: 154 before P1 plus 5 in `test_p1_catalog.py` (eligibility field, filter, sections, tenant isolation, read-only states) |
| Web unit / viewer / typecheck / build | **32 passed** (4 new in `p1.test.tsx`) / **10 passed** / 0 errors / passed |
| E2E, development database | **19 passed**: 15 existing plus 4 in `p1-client-catalog.spec.ts` |
| E2E showcase walkthrough (demo database) | **6 passed**, including the new P1 test |

What the P1 E2E tests cover:
- Client administrator: sections, cards, quick view with 3D and PDF preview, list view.
- Ordinary client user: preview only, no download controls, no actions.
- Phone-sized screen: one card per row, full-screen quick view.
- Operator default: table.

In the existing W2 E2E catalog test, the client step now opens the List view, which is the same table as before.

## Screenshots (`e2e/results/screenshots/`)

| From the showcase data | From the regular E2E data |
|---|---|
| `showcase-p1-01-catalog-grid.png`, `showcase-p1-02-published-empty.png`, `showcase-p1-03-quick-view.png`, `showcase-p1-04-list-view.png`, `showcase-p1-05-mobile-grid.png`, `showcase-p1-06-mobile-quick-view.png` | `p1-01-catalog-grid.png`, `p1-02-quick-view.png`, `p1-03-list-view.png`, `p1-04-mobile-grid.png` |

## Not in P1 (awaiting approval)

| Item | Phase |
|---|---|
| Manufacturing request and enquiry forms, operator queue, notifications | P2 |
| Digitisation requests | P3 |
| Publication | P4 |
| Manufacturing authorisation | P5 |
| STEP-derived model thumbnails; parts without a photo show a placeholder | Proposed (E3) |
