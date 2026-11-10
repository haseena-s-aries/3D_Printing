# Web Application Review (end of Phase 1)

- **Review date:** 2026-10-16
- **Build:** commit `64f8a49` (no code changes during this review)
- **Business baseline:** BRD v0.4, `Requirements_Register_v0.4.xlsx`
- **Method:** every flow below was opened and exercised by hand in the browser pane against the live local stack
  (PostgreSQL, Django API, Vite dev server and CAD worker). It was then repeated in headless Chromium at
  1440×900 to capture the screenshots in `screens/` and to test the 3D viewer controls. The pane stops drawing
  WebGL while it is hidden.
- **Data:** demo tenants from `seed_demo`, earlier E2E data, and records created during this review: client
  *Northwind Marine (review)*, part *PMP-IMP-2207* and passport *DP-2026-00006*.
- **Files:** all uploads were the repository's synthetic fixtures. No real customer CAD was used.

Status key:

- **Working:** opened and verified.
- **Partial:** works but is incomplete against the BRD.
- **Gated:** disabled on purpose pending a business decision.
- **Missing:** no web UI exists.
- **Not tested:** present but not exercised in this review.

## 1. How to run the web application

| Piece | Location | Command | Address |
|---|---|---|---|
| Web (React 19, TypeScript, Vite 7) | `web/` | `npm run dev --workspace web` (from the repo root) | http://127.0.0.1:5173 |
| API (Django 6.1, DRF) | `backend/` | `.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000` | http://127.0.0.1:8000/api/ (docs at `/api/docs/`) |
| Database (PostgreSQL 16, embedded) | `backend/` | `.venv\Scripts\python.exe scripts\localdb.py` (writes `DATABASE_URL` to `.env`) | local port in `.env` |
| CAD worker (STEP → GLB) | `backend/` | `manage.py run_worker` with `DATABASE_URL` using the `app_worker` role | not applicable |

Full instructions are in `docs/local-setup.md`. Vite proxies `/api` to port 8000.

The demo accounts, from `seed_demo`, all use the `DEMO_PASSWORD` set when seeding:

| Account | Organisation | Role |
|---|---|---|
| `admin@operator.demo` | Platform Operator | operator admin |
| `engineer@operator.demo` | Platform Operator and Demo Client Energy | operator engineer |
| `admin@client.demo` | Demo Client Energy | client admin |
| `user@client.demo` | Demo Client Energy | client user |

## 2. What was demonstrated

### 2.1 Operator / Admin portal

| Step | Result |
|---|---|
| Sign in as operator admin | Working. Lands on the *Operator dashboard* (3 clients, platform status notices for OQ-35/36 and OQ-27). |
| Clients: list | Working. Shows name, slug, status, hosting model and member count. |
| Clients: create *Northwind Marine (review)* as a **dedicated** deployment | Working. It appears in the list. No success message is shown. |
| Clients: add a client admin (`admin@northwind.test`) | Working. The new user signed in later in the review. |
| Clients: assign existing operator staff (`engineer@operator.demo`) as operator engineer | **Defect D-1.** Refused with "password: This field may not be blank". |
| Users (operator tenant) | Working. Shows members, inline role selector, Deactivate and Add user. The role change and deactivate actions were not executed. |
| Audit trail | Working. Shows login, logout, `client.created`, `membership.created`, newest first. |
| Spare parts / Digital passports in the operator tenant | Empty, which is correct because parts belong to client tenants. The operator admin cannot see client inventories without a membership in each one (UX-1). |
| Sign in as operator engineer → choose *Demo Client Energy* | Working. The organisation selector appears for multi-tenant users. After sign-in the app returned to the previous user's last page (`/clients`) and showed "Not available" (D-4). |
| Spare parts: list, search "rq9sm" | Working. The search returned the single matching part. |
| Create spare part PMP-IMP-2207 | Working. Opens the part detail with master data. |
| Create passport draft from the part | Working. Creates DP-2026-00006 with revision 1 as a draft. |
| R-L1 editor: fill and Save draft | Working. "Draft saved." is shown, and all values persisted after a reload. |
| Submit for approval / Approve | **Gated** (disabled with OQ-35 explanations), as intended. |
| Upload STEP, DWG and PDF into passport sections | Working. Each file shows type detection (STEP ISO-10303-21, DWG AC1032, PDF 1.4), size, SHA-256 and v1. |
| Upload a `.txt` | Working. Rejected with "Only STEP (.stp, .step), DWG (.dwg) and PDF (.pdf) files can be uploaded." |
| STEP conversion | Working. The worker converted it, the row shows *3D derivative: succeeded*, and *View 3D* appeared. |
| DWG preview | **Gated** (OQ-27). Shows "Preview not available". |
| Download originals (PDF and STEP) | Working. The downloaded SHA-256 matches the uploaded bytes exactly (`c896da11…`, `7bbc85ae…`), and `file.download_link_issued` and `file.downloaded` were audited. |
| 3D viewer | Working (screens 15 to 19). Loaded in 42 to 115 ms, 464 triangles, bounding box 44.98 × 40.50 × 44.99 mm (matches Ø45 × 40.5). Top, Front and Isometric views, mouse orbit, wheel zoom and Reset all change the view; Reset returns to the exact default. |

### 2.2 Client Web Portal

| Step | Result |
|---|---|
| Client admin: dashboard | Working. Shows "Client portal — Digital inventory of Demo Client Energy" (6 parts, 6 passports, recent passports). |
| Client admin: spare parts | Working, read-only. There is no *New spare part* button; the operator creates parts (OQ-05). |
| Client admin: passport detail | Working. R-L1 is read-only and Approve is disabled (OQ-35). An upload form is shown, which matches the provisional OQ-32 upload rights. |
| Client admin: download original PDF | Working. SHA-256 matches. |
| Client admin: Users | Working. Shows client members **and** the assigned operator engineer, whose role can be changed or deactivated by the client admin (see UX-6). |
| Client admin: Audit trail | Working. Shows the tenant's own events, including the operator engineer's actions in this tenant. |
| Client admin opens `/clients` | Correctly "Not available". |
| Client user: navigation | Working. Shows Dashboard, Spare parts and Digital passports only. |
| Client user: passport detail | Working, read-only. "Your role can view this draft but not edit it." There are **0** *Download original* controls, no upload form, and *View 3D* is available. |
| Client user: 3D viewer | Working. |
| Client user opens `/users`, `/audit`, `/clients` | Each shows "Not available". |
| Other client (`admin@northwind.test`) opens Demo Client's passport URL and viewer URL | **Not found** for both. Its parts list is empty. |

## 3. Screen-by-screen status mapped to BRD v0.4

| Screen | Status | BRD requirements served | Gaps against the BRD |
|---|---|---|---|
| Login and organisation selection | Working | BR-036, HYB-010, HYB-002 | No password reset or invitation flow. Post-login redirect bug (D-4). |
| Operator dashboard | Partial | BR-029 | No cross-client overview or digitalisation project tracking (BR-044, BR-022). Counts cover only the operator's own tenant. |
| Client dashboard | Partial | BR-011, BR-029 | No orders or supply-chain view (BR-012, a candidate). Shows draft passports only, because publication is gated by OQ-35. |
| Clients (operator only) | Partial | BR-029, BR-018, HYB-004 (recorded only) | Operator staff assignment broken (D-1). Member count not refreshed (D-2). No edit or suspend (status is shown but can't be changed). Invalid slug pattern disables browser validation (D-3). No pagination. |
| Users | Working (actions not executed) | BR-036, ACC-001 | Initial password is typed by an admin; there's no invitation (planned). Client admins can alter or deactivate operator staff roles in their tenant, which needs a policy decision (UX-6, relates to OQ-37/ACC-001). |
| Spare parts list | Partial | BR-001, BR-010, BR-011 | No filters in the UI (the API supports category, status and project), no pagination (first 25 only), no criticality or status filters. |
| Spare part detail | Partial | BR-001, BR-003 | **No edit of master data.** Projects are not visible (no Projects UI, although the API exists). |
| Digital passports list | Working | BR-003, PUB-001, PUB-002, PUB-003 | Filters by evidence and eligibility wait on OQ-35/36. |
| Passport detail: header and status | Working / Gated | PUB-001 to PUB-003, BR-005 | Publication, evidence and eligibility are read-only by design (OQ-35/36). |
| Passport detail: R-L1 editor | Working | BR-006, BR-009 (partly) | Fields are not pre-filled from the part master data (UX-3), and the change summary is pre-filled with the previous text (UX-4). |
| Passport detail: R-L2 / R-L3 | **Missing** | BR-007, BR-008, BR-041, BR-043, BR-026 | The API stores free-form R-L2/R-L3, but there's no web form. The R-L2 manufacturing solution, AM parameters and R-L3 evidence checklist are not built. |
| Passport detail: revisions | Partial | BR-034, DM-002, CAD-009 | History is shown. **No "new revision" button** (the API supports it). Approved-revision immutability is enforced by the database (tested in the backend suite). |
| Passport detail: submit / approve | Gated | BR-019, PUB-004 | Disabled pending OQ-35. No rules were invented. |
| Passport files: upload and list by section | Working | CAD-001 to CAD-003, CAD-005, CAD-007, CAD-008, CAD-010, PSEC-001, BR-028 | **No upload-new-version UI** (API supported). Section tables don't line up (UX-5). Metadata can't be edited after upload. |
| Download (original) | Working | BR-039, HYB-012, BR-057, HYB-015 | Watermarking not implemented (BR-027, OQ-33). |
| 3D viewer | Working, with issues | VWR-001 to VWR-008, VWR-010, VWR-011, CAD-006 | Opens on a **separate page**, not inside the passport. **Unlit faces render black** (D-5). Pan and Fit were not separately verified. Error handling (VWR-009) only seen as "Not found". VWR-012 to 018 (advanced) not built, as agreed for MVP. Fidelity is unverified on real CAD (B-01). |
| PDF viewer | **Missing** | DRW-003 (Must, MVP) | There's no embedded PDF viewer, although Phase 0 proved PDF.js. Client users cannot read PDFs at all: no viewer and no download right. |
| DWG viewer | Gated | DRW-001, DRW-004 | "Preview not available" pending OQ-27. |
| Audit trail | Partial | BR-054, HYB-015 | Read-only, newest first. No filters or pagination in the UI (the API supports filters). Objects are shown as raw IDs ("membership ea4ba1cc"). |
| Not-available / not-found pages | Working | BR-036, HYB-002 | "Not found" shows a support reference ID; "Not available" does not. |

**Not built in the web app at all** (MVP requirements, for planning):

| Area | Requirements |
|---|---|
| On-demand ordering, request routing and requesters | BR-013, BR-014, BR-015 |
| Production milestones, post-production report, batch/serial traceability | BR-051, BR-021, BR-050 |
| Reorder eligibility | BR-049 (needs OQ-36) |
| Notifications | BR-053 |
| ERP integration API | BR-017 |
| Digitalisation project tracking UI | BR-022, BR-044 (Projects API only) |
| Obsolescence management | BR-035 (only the R-L1 "IP consideration" field) |
| Licensing and charges | BR-031, BR-032 |

## 4. Defects found in this review

| ID | Severity | Defect | Evidence | Likely fix |
|---|---|---|---|---|
| D-1 | **High** | The operator admin cannot assign existing operator staff to a client. The API rejects the empty `password` the form always sends. | Clients → Members → role *operator engineer* → "password: This field may not be blank" | `allow_blank=True` on `MemberSerializer.password`, or omit empty fields in the form. Add a web test. |
| D-2 | Low | The client list's member count isn't refreshed after a member is added. | Northwind showed 0 members after adding one | Reload the client list after `AddMember`. |
| D-3 | Low | The "Short identifier" `pattern="[a-z0-9-]+"` is invalid under the browser's `v`-flag regex rules, so browser validation is silently off. | Console error in Chromium | Escape the hyphen: `[a-z0-9\-]+`. |
| D-4 | Medium | After sign-out and sign-in, the app returns to the **previous user's** last page, so the next user may land on "Not available". | Admin signed out on `/clients`; the engineer landed on `/clients` | Clear the stored "from" location on logout, or redirect only when the new user can access it. |
| D-5 | Medium | The 3D viewer has one directional light, so the faces away from it render pure black and hide geometry. | `screens/17-viewer-orbited.png` | Add hemisphere and ambient light, or an environment map, in `@passport/viewer3d`. |

## 5. UI/UX problems

| ID | Problem |
|---|---|
| UX-1 | Operator staff must sign out and in again to switch between client organisations. There's no organisation switcher and no cross-client overview, and the operator dashboard shows "0 spare parts". |
| UX-2 | Operator staff working inside a client tenant see "Client portal" branding, which is confusing about who they are acting as. |
| UX-3 | R-L1 doesn't pre-fill from the spare part's material, dimensions and application, so data is entered twice. |
| UX-4 | The change summary is pre-filled with the previous summary, so new text gets appended to it ("Initial draftR-L1 identification…"). |
| UX-5 | Each passport file section is a separate table with its own column widths, so the columns don't align. |
| UX-6 | Client admins see an inline role selector and Deactivate for the operator engineer assigned to their tenant. Whether clients may revoke operator access is a policy question (ACC-001, OQ-37). |
| UX-7 | No success toasts after creating a client or member. The forms just reset. |
| UX-8 | The 3D viewer is a separate page with only a "Back" link. It needs to be embedded in the passport, with a fullscreen option. |
| UX-9 | The passport notice "Drafts can be prepared now" is also shown to read-only client users. |
| UX-10 | The audit trail shows raw object IDs. It needs human-readable names and links. |

## 6. Remaining functional blockers (not fixable by web work alone)

| Blocker | Effect on the web app | Decision owner |
|---|---|---|
| OQ-35 publication/approval rules | Submit, approve and publish stay disabled. Clients only ever see drafts. | Business owner |
| OQ-36 manufacturing eligibility | Eligibility stays "Not eligible". No reorder or ordering. | Business owner |
| OQ-27 DWG rendering and licence | DWG preview unavailable | Business owner (licensing) |
| OQ-33 watermarking | Downloads are not watermarked | Business owner |
| OQ-32 who uploads | Client admin and client engineer upload rights are provisional | Business owner |
| OQ-37 / ACC-001 consent for operator access | Affects UX-6 and the operator switcher design | Business owner / Legal |
| B-01 real STEP/DWG samples | Viewer fidelity on real parts is unverified | Business owner |

## 7. Regression tests (run 2026-10-16 during this review)

| Suite | Result |
|---|---|
| Backend `pytest` (PostgreSQL, RLS) | **73 passed** |
| Web typecheck (web, api-types, viewer3d) | Passed |
| Web unit tests (Vitest) | **7 passed**, plus viewer3d **7 passed** |
| Web production build | Passed (main 302.7 kB, viewer chunk 643.5 kB lazy-loaded) |
| E2E Playwright (3 flows) | **3 passed**, on a re-run |

On the first E2E run, test 1 failed. The background worker started for this review had already converted the
test's job, so the test's own worker step found 0 jobs. That's an environment interaction, not a product defect.
With that worker stopped, all 3 passed.

## 8. Recommended next web batch: W1, "Complete passport workspace"

The aim is that an operator engineer can take a part from intake to a complete, reviewable passport (R-L1 to
R-L3 with evidence, files versioned, 3D and PDF viewable in place), and a client can review it without
downloads. Approval itself stays gated until OQ-35 is decided.

| # | Item | Requirements | Notes |
|---|---|---|---|
| 1 | Fix D-1 to D-5 | BR-029, VWR-002 | Small. Add regression tests for each. |
| 2 | **Embedded 3D viewer in the passport page** (tab or panel, fullscreen, lighting fix, pan/fit verified, clear error and empty states) | VWR-001 to 011 | Reuses `@passport/viewer3d`. Keep the standalone route for deep links. |
| 3 | **Embedded PDF viewer** (PDF.js, from Phase 0) with a *preview* right separate from *download original*, so client users can read specifications | DRW-003, BR-039 | Needs a server-side preview stream that respects roles. Watermark hook point left for OQ-33. |
| 4 | **File versioning UI**: upload new version, version history per file, compare checksums; clear "current vs superseded" | CAD-005, CAD-009, BR-034 | API already supports versions. |
| 5 | **Revision UI**: start new revision, view any past revision read-only, diff of R-L fields between revisions | BR-034, DM-002 | API supports revisions. |
| 6 | **R-L2 and R-L3 forms**: manufacturing solution, AM process parameters, inspection and evidence checklist linking uploaded files | BR-007, BR-008, BR-041, BR-043, BR-026 | Field list to be confirmed with the business against BRD §R-L2/R-L3. These are data capture only; no evidence-level transitions (OQ-35). |
| 7 | Part master data edit; R-L1 pre-fill from part; change summary starts empty | BR-001, BR-006 | Small. |
| 8 | **Organisation switcher for operator staff** and an operator overview across assigned clients (counts, recent drafts) | BR-029, ACC-001 | Uses the existing per-membership token, re-issued for the chosen tenant; no cross-tenant queries. Confirm UX-6 policy first. |
| 9 | List pagination and filters (parts, passports, audit, clients) | BR-010, BR-054 | The API supports both. |

Explicitly **out of W1**:

- Approval, publication and manufacturing logic (OQ-35/36).
- DWG viewing (OQ-27).
- Watermarking (OQ-33).
- Ordering (BR-013/014).
- Advanced viewer features (VWR-012 to 018).

**Acceptance for W1:** an E2E test that takes a part through R-L1, R-L2 and R-L3 with versioned STEP, PDF and DWG
files and a second revision, with the 3D and PDF viewers embedded and checked for each of the four roles.

## 9. Evidence

Screenshots are in `docs/web-review/screens/`:

| Range | Content |
|---|---|
| 01 to 05 | Login and operator admin screens |
| 10 to 19 | Operator engineer in the client tenant, including viewer views, orbit, zoom and reset |
| 20 to 24 | Client admin screens |
| 30 to 31 | Client user screens |
| 40 | The other tenant's "Not found" |

Live checks in the pane also covered: client creation, adding members (including D-1), part creation, passport
creation, R-L1 save, uploads and `.txt` rejection.
