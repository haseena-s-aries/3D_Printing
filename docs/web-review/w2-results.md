# Web batch W2: Client Web Portal and Digital Inventory — results

- **Date:** 2026-10-16
- **Base:** commit `45eca47`
- **Status:** final acceptance and security verification done (§9); committed as one local W2 commit, not pushed.
- **Not changed:** BRD v0.4, Azure (nothing provisioned), mobile code. OQ-35, OQ-36, OQ-37 and OQ-27 stay
  gated, and AMSL criticality stays provisional.

## 1. Starting point (inspected before development)

| Area | Already in place (W1 / Phase 1) | Missing at the start of W2 |
|---|---|---|
| Client dashboard | Part and passport counts, recent passports, platform notices | Recently updated parts, document availability, readiness and data distribution, conversion status, drill-down links |
| Catalog | Pagination; search by number, name, description; category and criticality filters | Passport-number search, project filter (and project assignment), readiness/data filter, sorting, photo thumbnails (photos could not be uploaded) |
| Part and passport | Passport tabs, R-L1 to R-L3 forms, documents, versions, revision history | Read-only summaries for clients, passport summary on the part, file-revision association |
| CAD and documents | Worker, embedded 3D and PDF viewers, rights | Live conversion status (manual reload), loading state, pan not tested |
| Security | Signed 5-minute links; neutral refusal messages | Links reusable within their lifetime; account existence inferable when adding users |

## 2. Delivered

### 2.1 Client dashboard (`/`)

The dashboard is built from `GET /dashboard/summary/`, which uses only the organisation's own records:

- **Tiles:** spare parts, digital passports, open passport drafts, parts with a 3D view. Each tile links into the
  catalog with the matching filter.
- **Passport data captured:** meters for none, R-L1, R-L1–R-L2 and R-L1–R-L3 complete, each linking to the
  filtered catalog. A separate line states the official evidence level ("32 of 32 not assessed"), so data
  completeness is never shown as readiness.
- **Engineering documents:** parts with a drawing, specification, 3D view and photograph; file counts by type;
  parts without documents.
- **3D conversion:** ready, queued, converting, failed and not requested, with links to failed items. The panel
  refreshes every 5 seconds while anything is queued or converting.
- **Recently updated parts:** eight parts by last activity, with thumbnail, passport link, data captured and
  document chips.

There are **no manufacturing or order statistics**; none exist yet (OQ-36), and the E2E test checks this.

### 2.2 Digital inventory catalog (`/parts`)

- **Search:** part number, passport number, name, description.
- **Filters:** project, category, data captured (`rl1`/`rl2`/`rl3` or more, or incomplete), official evidence
  level, has 3D view. Criticality and status are available through the API.
- **Sort:** recently updated (default), part number A–Z and Z–A, name, newest.
- **Server-side pagination** (25 per page).
- **URL state:** filters, sort and page live in the URL, so dashboard links land pre-filtered and reload or back
  keep the view.
- **Columns:** thumbnail, part (category, dimensions, project), passport number with revision and publication,
  data captured, document chips, last activity.
- **States:** loading, error, "No spare parts yet." and "No spare parts match these filters." (with a
  *Clear filters* control).
- **Tenant scope:** every query runs on the caller's tenant and every table is under RLS. Tests prove that
  another organisation's searches (part, passport and project values), filters and dashboard return nothing.
- **Projects:** a new **Projects** page (list, create, "View parts"), and a project selector on the part form.

### 2.3 Part and passport experience

- **Part page:**
  - Photo, project link and last activity.
  - A *Digital passport* card: number, current revision, publication, evidence level, data captured, document
    chips.
  - Photographs accepted in the upload form, with the section chosen automatically.
- **Passport tabs:** **Overview**, Readiness data, Interactive 3D model, Documents, Revision history,
  Manufacturing history. Editors land on *Readiness data*; read-only users on *Overview*.
- **Overview tab (new):**
  - Product information with photo.
  - Status: publication, evidence level, manufacturing, and data captured labelled as guidance.
  - R-L1, R-L2 and R-L3 summaries with completeness. R-L1 shows "Not applicable — reason" where used; AMSL is
    marked "(provisional)".
  - R-L3 evidence links with QA shown as pending (OQ-35).
  - Document availability for every PSEC-001 section ("None uploaded" where empty).
  - 3D status with an *Open 3D view* button.
- **Documents:** version history now shows the passport revision each version was uploaded under. Photographs
  open in an inline preview through a single-use link.
- **Completeness never changes state.** The stored `data_captured` level only feeds the catalog filter. Evidence
  level, publication and eligibility stay read-only, and tests keep proving it.

### 2.4 CAD and document viewing (existing implementations reused)

- **Conversion status:** plain-language badges ("Queued for 3D conversion", "Converting to 3D…", "3D view ready",
  "3D conversion failed (code)").
- **Automatic refresh:** passport, part and dashboard views refresh themselves while a conversion is pending,
  every 4–5 seconds for up to about 3 minutes. The E2E test confirms the status changes with no manual reload.
- **Viewer:** shows "Loading 3D model…" until the model is ready, so the panel is never blank. Model selection,
  views, fit, reset and full screen are unchanged. **Pan** (right-drag) is now verified in the E2E test.
- **PDF and photo previews:** inline, permission-checked, audited and single-use. DWG is still "Preview not
  available" (OQ-27), and no commercial DWG software was added.
- **Originals preserved:** photographs too. Thumbnails are separate derivatives.

### 2.5 Photographs (supporting thumbnails and BR-006 "original part image")

- **Formats:** JPEG/PNG accepted as kind `image`, section *Photographs*.
- **Limit:** 20 MB, provisional (OQ-31).
- **Validation:**
  - The file signature is checked.
  - The dimensions are read from the header and refused above `MAX_IMAGE_PIXELS` (default 60 MP) with
    `image_too_large`, *before* decoding. Pillow on its own only refuses above twice its limit.
  - The decoded format must match the signature.
  - Pillow fully decodes the image, so truncated or corrupt files are refused.
  - GIF, SVG and other formats are rejected.
- **Thumbnails:** a 480 px JPEG with orientation applied and **all metadata removed** (EXIF and GPS). This is
  proved by a test using a GPS-tagged JPEG.
- **Serving:** `GET /files/{id}/versions/{n}/thumbnail/` serves thumbnails with the caller's own token. Full
  images use audited preview links.
- **New dependency:** `pillow==12.3.0`, recorded with its justification in `requirements.txt`.

## 3. Security improvement report

### A. Temporary download and preview links

**Before:** links were signed, bound to user, membership and tenant, re-checked on use, and valid for 5 minutes.
Within those 5 minutes the same URL could be used again by anyone holding it.

**Options considered:**

| Option | Assessment |
|---|---|
| Shorter lifetime only | Simple, but still reusable |
| **Single-use nonce recorded in PostgreSQL** | **Chosen.** One small table, no new infrastructure, atomic thanks to a unique constraint |
| Redis/cache-based nonce store | Needs a new always-on service (cost); no benefit at this scale |
| Session cookies instead of links | Breaks the mobile apps and direct downloads |

**Implemented:**

- Every link carries a random nonce. The first redemption inserts a `LinkRedemption` row (tenant-scoped, RLS)
  **after** all existing authorisation checks have passed; a second use returns **410 `link_used`**.
- Links issued before the change have no nonce and are refused.
- The default lifetime is reduced to **120 s**; a single-use link only needs to survive the click.
- Downloads and previews also send `X-Content-Type-Options: nosniff`.

**Cost and implications:**

- **Storage and performance:** one row of about 150 bytes and one indexed insert per download. Old rows can be
  pruned by a scheduled job later (not needed at current volume).
- **Resumed downloads:** an interrupted download can't be resumed with the same link; the user requests a new
  one. Viewer and preview loads are single requests, so they're unaffected.
- **Azure Blob (future): the single-use guarantee covers the application link only.** With Azure storage,
  the API redirects to a Blob SAS URL valid for 60 seconds. That SAS URL is **not** single-use: anyone who
  obtains it can reuse it until it expires. Production should use short user-delegation SAS (already recorded
  as L-2), or stream through the API if strict single use matters more than bandwidth. Locally (and in all tests
  so far) files are streamed by the API, so the single-use check applies end to end.

**Tests:**

- `test_w2_security.py`: links work once for original and preview, redemptions are tenant-scoped, links without
  a nonce are refused.
- E2E: a real browser download, then re-requesting its URL returns 410.

### B. Account enumeration through membership administration

**Before:** a client admin adding a user could tell whether an address had an account. A new address needed a
password, while an existing one was refused with `user_not_addable`.

**Implemented: invitations.**

- **Organisation administrators** invite by email and role (`POST /invitations/`). The response is identical
  for operator staff, other organisations' users, accounts without any organisation and brand-new addresses:
  same status, fields and values. Nothing changes for an existing account until its owner acts. Every address
  receives the email.
- **Direct account creation** (`POST /users/`) is now limited to platform administrators. Client admins get 403
  `invitation_required`, the same for every address.
- **Accepting** is done by the invitee only:
  - An existing account must prove its password; a new address sets one, and it's strength-checked.
  - Errors are generic (`invitation_invalid`).
  - Operator staff and other organisations' accounts are refused (`invitation_not_applicable`), which keeps the
    W1 protections. The refusal is shown to the account owner only and audited on the **operator** side, not in
    the inviting organisation.
- **Tokens:**
  - Only a SHA-256 hash is stored.
  - Single use, 7-day expiry.
  - Re-inviting the same address replaces the old link, and invitations can be withdrawn.
  - Acceptance is rate-limited like sign-in.
- **The public invitation page** shows organisation, role, email and expiry only, never whether an account
  exists. The same key set is returned for existing and new addresses (tested).

**Development caveat.** No email provider is configured, and provisioning one (for example Azure Communication
Services Email) is a paid service needing approval. Emails therefore go to the server log (console backend).
The link is shown to the inviting admin **only** when both `DEBUG` and `INVITATION_LINK_IN_RESPONSE` are on:
- **Settings level:** the setting is forced off whenever `DEBUG` is off, whatever the environment variable says.
- **Request level:** the serializer checks `DEBUG` again for every response.

With the link visible, the inviter could act as the invitee, so this applies to development only. The tests
prove that a mistakenly enabled setting with `DEBUG=False` returns `invite_url: null`, and that the token
appears in neither the create nor the list response.

**W1 protections maintained:** all 19 W1 membership security tests still pass. Four were updated where adding
users now goes through invitations.

**Tests:**

- `test_w2_security.py` (11 invitation tests): uniform response, public view, hashing, new-address flow, weak
  password, operator and other-organisation refusal with audit location, existing-account proof, expiry,
  revocation, replacement, role and cross-tenant rules, production mode.
- E2E W1 test 6: invite, accept in a separate browser session, then manage; inviting an operator address looks
  identical to any other invitation.

## 4. Screenshots (`e2e/results/screenshots/`, from the passing E2E run)

| File | Content |
|---|---|
| `w2-01-dashboard.png` | Client user's dashboard: tiles, data captured, documents, 3D conversion, recent parts |
| `w2-02-catalog.png` | Catalog sorted Z–A, with thumbnails, passport and revision, data captured, document chips, pager |
| `w2-03-passport-overview.png` | Client admin's passport overview with R-L summaries, evidence, documents and 3D status |
| `w2-04-viewer.png` | Embedded 3D viewer after the pan test and reset |
| `w1-05-client-admin-users.png` | Users page with the invitation form, invitations list and read-only operator staff |

## 5. W2 requirements coverage

| W2 item | Status | Evidence |
|---|---|---|
| Dashboard: passport summary, inventory summary, recently updated parts | Done | `DashboardSummaryView`; `test_dashboard_summary_counts`; E2E W2-3 |
| Dashboard: document availability, readiness visibility, conversion status, navigation | Done | Dashboard cards and links; E2E W2-3 (meter → filtered catalog) |
| Dashboard: no fabricated manufacturing statistics | Done | Test and E2E assert none |
| Catalog: search by part number, passport ID, description, category | Done | `test_search_covers_*`; E2E W2-2 |
| Catalog: filter by project, category, readiness level | Done | Data-captured and official evidence-level filters; `test_filters_*`; E2E W2-2 |
| Catalog: sort and paginate (server-side) | Done | `ordering` and page; `test_sorting_*`; E2E W2-2 |
| Catalog: thumbnails where photographs exist | Done | Photo kind and thumbnail derivative; `test_photo_*`; E2E W2-1/2 |
| Catalog: empty, loading and error states | Done | `PartsPage` |
| Catalog: client-specific access, navigation to passports | Done | `test_catalog_and_dashboard_do_not_disclose_other_tenants`; E2E W2-5 |
| Part details, passport navigation, current revision visibility | Done | Part passport card, Overview tab, catalog revision column |
| Engineering info, R-L1/R-L2/R-L3 evidence summaries | Done | Overview tab; E2E W2-4 |
| Document categories, version history, file metadata, completeness | Done (W1 + W2) | Passport revision per version (`test_document_summary_and_3d_flag`) |
| Completeness doesn't change readiness or eligibility | Done | `test_amsl_*` (W1), `data_captured` test asserts `evidence_level` stays `none` |
| STEP upload and conversion status | Done | Badges, auto-refresh; E2E W2-1 |
| GLB loading and errors; selection; rotation, zoom, pan, fit, views | Done | Loading state; E2E W2-1 (pan), W1 (views) |
| File-revision association | Done | `passport_revision_number` |
| PDF preview and navigation; download permissions; unsupported-preview messages | Done (W1 + W2) | W1 PDF tests; photo previews; DWG message |
| Originals preserved; no production CAD fidelity claim; no commercial DWG software | Respected | Byte-identical tests; notices unchanged |
| Security A: single-use links | Done | §3A |
| Security B: enumeration | Done (production requires an email provider) | §3B |
| Business restrictions | Respected | Approve/submit/QA disabled; no ordering; no support grants |

## 6. Regression results (executed 2026-10-16)

| Suite | Result |
|---|---|
| Backend `pytest` on PostgreSQL | **147 passed**: 113 before W2, plus 19 in `test_w2_security.py` and 15 in `test_w2_catalog.py` |
| Tenant isolation and authorisation | Included above: RLS meta-test (with documented exemption for invitations), membership security, W2 catalog and dashboard isolation, invitation isolation |
| OpenAPI | 0 warnings; committed schema matches the code |
| Web typecheck / unit tests / production build | Passed / **28 passed** / passed (main 361 kB, viewers lazy) |
| Viewer unit tests | **10 passed** |
| Mobile typecheck / Jest (shared types changed) | Passed / 16 passed |
| E2E Playwright | **15 passed**: 3 Phase 1, 7 W1, 5 W2 |

These are the final-run results after the §9 corrections.

Existing E2E specs were updated for the W2 UI. The changes were label and flow updates only:

- "Spare parts" becomes "Digital inventory", and "Product information" becomes "Readiness data".
- New badge text, upload message and empty-state text.
- Adding users goes through invitations.
- Assertions were made robust to the growing demo data:
  - A scoped row lookup.
  - Sort checked against the API's full order.
  - The `openClient` helper, which pages through the operator's client list. The demo database now holds more
    than 25 clients, and the new one can be on page 2.

Known warnings:

- Django 6.1 deprecates `EMAIL_BACKEND` in favour of `MAILERS`. It's kept for now because pytest-django still
  sets `EMAIL_BACKEND`; migrate before Django 2028.
- Unclosed-file `ResourceWarning`s come from test-client file responses.

## 7. Remaining blockers

- **Business decisions:**
  - OQ-35: approval, publication and evidence-level transitions.
  - OQ-36: manufacturing eligibility and ordering.
  - OQ-37 / ACC-001: support-access grants.
  - OQ-27: DWG viewer and licence.
  - OQ-33: watermarking.
  - OQ-31: upload limits, including the new 20 MB photo limit.
  - OQ-49, OQ-64, OQ-51, OQ-71.
- **New for production:** an **email provider** is needed for invitations to be non-enumerable outside
  development. That's a paid Azure service and needs approval.
- **Environment:**
  - B-01: no real STEP/DWG samples.
  - B-02: container runtime.
  - B-03: Azure.
  - B-04: no macOS.
  - B-05: no devices.
  - B-06: CI never run.
- **Data hygiene:** the shared demo database accumulates E2E records because each run creates uniquely named
  data: 35+ parts, 28+ client organisations. A reset script, or running E2E against a disposable database, would
  keep screenshots tidy.
- **Not yet covered:**
  - The Clients list has no search, so operators with many clients must page through it.
  - Old `LinkRedemption` rows and invitations are not pruned.
  - `EMAIL_BACKEND` is deprecated and should migrate to `MAILERS`.

## 8. Recommended next batch: W3, "Operator workflow readiness"

Prioritised for what can be built without the open decisions:

1. **Operator cross-client work queue:** drafts with incomplete data, failed conversions, and parts without
   documents, across the organisations the operator is assigned to, reusing the per-tenant summary. This needs
   no new access model.
2. **Bulk intake:** CSV import of spare parts with validation preview, and multi-file upload with automatic
   section detection (photos, PDFs, STEP).
3. **Audit trail usability (UX-10):** human-readable objects and links, actor filter, CSV export for client
   review (supports OQ-37 discussions without implementing grants).
4. **Production email and hardening (needs approval):** the email provider for invitations, password reset
   through the same tokens, refresh token in an httpOnly cookie (L-1), and a CSP.
5. **E2E data isolation:** run E2E against a disposable database, and add CI for web plus E2E once a remote
   repository exists (B-06).
6. **When OQ-35 is decided:** the approval workflow behind the existing seam, then the evidence-level filter
   becomes meaningful.

## 9. Final acceptance and security verification (before commit)

Each requested check was performed. Corrections found during the review are marked **fixed**.

| # | Check | Result |
|---|---|---|
| 1 | Invitation link never in API responses when `DEBUG=False` | **Fixed.** Before: a mistakenly set `INVITATION_LINK_IN_RESPONSE=true` would have returned links with `DEBUG=False`. Now it is forced off in settings and re-checked against `DEBUG` per request. Tests: `test_link_never_returned_without_debug_even_if_the_setting_is_on` (create and list responses contain no token), `test_settings_force_the_link_off_without_debug` (fresh process with `DJANGO_DEBUG=false`). Backend tests now read tokens from the emailed link. |
| 2 | Tokens hashed, expire, single use, no cross-tenant or operator-staff grant | Verified: SHA-256 only (`test_only_a_hash…`), expired GET and POST refused (`test_expired_…`), reuse refused (`test_new_address_accepts…`), operator staff and other-organisation accounts refused (`test_operator_staff_and_other_organisation_accounts…`), accepted invitation grants exactly one membership in its own organisation with its role and no staff flags (`test_accepted_invitation_grants_only…`). **Fixed:** acceptance now locks the invitation row and re-checks that it is still pending, so two concurrent acceptances cannot both proceed. |
| 3 | Download links single-use | Verified at the application layer (backend tests and an E2E re-request returning 410 `link_used`). The Azure Blob SAS limitation is stated explicitly in §3A: the redirected SAS URL is reusable until it expires (60 s). |
| 4 | Photo validation, limits, originals, thumbnails | **Fixed:** an explicit pixel limit is checked before decoding (Pillow alone only refuses above twice its limit), and the decoded format must match the signature. Tests: pixel limit at 1.4× the limit, byte limit, truncated JPEG, corrupt JPEG, PDF named `.png`, GIF, SVG, byte-identical original, thumbnail ≤ 480 px with no EXIF/GPS. |
| 5 | Running-browser check (built-in browser, client user, live dev servers) | Dashboard (real counts; R-L3 meter 8 = catalog filter result 8); passport-number search (1 row); data-captured filter plus Z–A sort (correct order, URL state); Projects → *View parts* (pre-filtered, photo thumbnail loaded); passport Overview (all seven sections, Approve disabled with OQ-35 note); STEP viewer (464 triangles, 44.98 × 40.50 × 44.99 mm, Top view correct); PDF preview (page 1 → page 2 navigation). |
| 6 | No unapproved approvals, transitions, eligibility or production actions | Verified. No W2 code writes `evidence_level`, `publication_state` or `manufacturing_eligibility` (diff search); they remain read-only in the serializer. Submit and approve still return 409 `policy_not_configured` (existing tests). The UI shows Approve disabled. No ordering or support-grant endpoints. |
| 7 | Regressions after corrections | §6 (final run). **Fixed during E2E:** `useApi` let a slow response for an earlier filter or sort overwrite a newer one (seen as a wrong catalog order). Only the latest request now updates state, with a unit test that fails on the old hook. |
| 8 | Diff review | 63 files. No secrets (only a dummy key inside a test), no `.env`, database, storage, uploaded CAD or document files. The only binaries are five screenshots (largest 360 kB). No mobile or BRD changes. No encoding damage. Regenerated Phase 1 and W1 screenshots and `e2e-results.json` were restored. `w1-05` is kept because it shows the new invitation UI. |
