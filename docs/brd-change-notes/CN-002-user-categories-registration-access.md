# CN-002 — User categories, client company registration and access control (PROPOSAL)

| | |
|---|---|
| Status | **Approved in principle (26 Oct 2026) with amended decisions — see §11.** **Partly implemented, in the isolated access-test environment only** (status corrected 26 Oct 2026). Batches 1–4 of §10 (access-control realignment, company and project assignment, email outbox and password reset, company self-registration) and decision D3a (§13) are implemented and tested there. Batches 5 (administrative oversight grants), 6 (Aries QA / Support capability sets) and 7 (scan files) are not implemented. Showcase and engineering-validation are not migrated, public registration stays off by default, and nothing is deployed. BRD v0.4 is unchanged; this note becomes a BRD change only through an approved change-control update |
| Date | 26 October 2026 (rev 3: decision D3a recorded, administrative inventory summary; see §13) |
| Scope | Aries Admin / Aries Engineer / Client company access; public company registration with Aries approval |
| Out of scope here | Scan-file formats (D-01) — listed as a later batch; manufacturing approval/release (OQ-35/36 stay closed) |
| Constraints kept | Existing accounts, memberships, passports, documents, requests, showcase records (including real customer engineering files already uploaded to the showcase) and the engineering-validation environment are preserved; no reset, commit, push or deploy |

Terminology: in the code the operator organisation is `Tenant.kind = operator`; **"Aries" = the platform operator**. "Aries Admin" =
role `operator_admin`, "Aries Engineer" = role `operator_engineer`. Display names change; stored role values do not.

---

## 1. Findings from the current code (including uncommitted work)

| # | Question | Finding (file) |
|---|---|---|
| 1 | Reusable auth/tenant models | `accounts.User` (email login, UUID), `tenancy.Tenant` (kind operator/client, status active/suspended), `tenancy.Membership` (user × tenant × role, unique, `is_active`, `created_by`), `tenancy.Invitation` (hashed single-use token, expiry, one pending per email/tenant). JWT sessions carry `tid`; every tenant-owned table uses **forced PostgreSQL RLS** on `app.tenant_id`; notifications use per-user RLS on `app.user_id`. All reusable. |
| 2 | Existing roles | Operator: `operator_admin`, `operator_engineer`, `operator_qa`, `operator_support`. Client: `client_admin`, `client_engineer`, `client_user`, `procurement`, `auditor` (`tenancy/models.py`). Capabilities in `tenancy/permissions.py`. |
| 3 | Self-registration | **None.** Clients are created only by an operator administrator (`ClientViewSet.perform_create`). |
| 4 | Invitation / password / organisation selection | Client admins invite by email (`tenancy/invitations.py`): hashed token, 7-day expiry, throttled (`login` scope 10/min), no account enumeration, existing operator staff or users of another organisation are refused. Password policy: 12+ characters, common/numeric/similarity validators. **No password-reset flow.** Sign-in asks for an organisation only when the user has several (`tenant_selection_required`); a workspace switcher exists; assigned operator engineers are not offered the empty operator home (`accounts/views.py: selectable_workspaces`, uncommitted). Email: console backend in development; invitation links are returned in API responses only when `DEBUG`. |
| 5 | Engineer-to-client assignment | An assignment **is a Membership** of the engineer in the client tenant with role `operator_engineer/qa/support`, created only by an operator administrator acting from the operator organisation (`membership_policy.py`: `CLIENT_ASSIGNABLE_OPERATOR_ROLES`, `is_platform_admin`). Engineers cannot assign anyone; client admins cannot manage operator staff. Audited in both tenants. |
| 6 | Project-level assignment | **Does not exist.** Projects have no assignee relation; an assigned engineer sees every project, part, passport, file and request of the client. |
| 7 | Client Admin rights over engineering data | `files.upload` is held by **client_admin and client_engineer**: they can upload files, **rename/recategorise any file (PATCH)** and **upload new versions of any file, including operator-uploaded STEP sources** (`files/api.py`, versions POST). Originals stay immutable (v1 kept), but the "latest" version — and the 3D conversion — would change. `projects.manage` includes `client_admin`. `parts.manage` and `passports.edit_draft` are operator-only. Engineering notes (D-13) are readable by client admin/engineer/auditor. |
| 8 | Aries Admin access to all client records | The operator admin has a membership **only in the operator tenant**. Today it sees aggregate counts per client computed inside each client's RLS context (`OperatorOverviewView`), client/member lists, and request **envelopes** stored in the operator tenant; it **cannot open any client record** (by design: opening a request needs an assignment). Support-access grants with purpose/expiry (ACC-001) are explicitly *not implemented* pending client-consent rules (OQ-37). |
| 9 | Operator queue / notifications | Client submissions write a `RequestEnvelope` in the operator tenant (no cross-tenant query); notifications go to operator admins + staff assigned to that client (`servicerequests/services.py: operator_recipients`). New registration notifications can reuse `Notification` (per-user RLS). Project scoping would change who is notified. |
| 10 | Demo credentials / history | Showcase (`passport_demo`): 1 operator tenant, 3 clients, 8 users; `engineer@operator.demo` assigned to all demo clients; `admin@operator.demo` operator-only. Development DB (`passport`): 67 client tenants from E2E runs, 81 users. Role values are reused, so **existing memberships keep working**; capability changes alter behaviour, not data. Showcase seed creates parts as the operator engineer and clients as the operator admin — compatible. |

## 2. Current versus required

| Requirement | Current | Gap |
|---|---|---|
| **A. Aries Admin** | | |
| View/manage client registrations; approve/reject | No registrations | **New** (Batch 3) |
| Create/manage Aries employee accounts | Operator admin adds operator staff directly (Users page in operator org) | Rename/label only; add deactivate/role audit view |
| Assign/remove engineers to companies | Yes (client members, operator admin only) | Dedicated "Aries staff" UI, notifications to engineer |
| Assign/remove engineers to scanning projects | No | **New** if project scoping approved (Batch 6) |
| Manage organisations / operator settings | Clients create/update, suspend via status | Registration-created clients; settings page minimal |
| View all client projects/inventories/passports/requests via explicit authorised access | Aggregates + envelopes only | **New** time-boxed read-only access grant (Batch 5, decision D3) |
| Audit trails of access and assignments | Audit events in both tenants | Add registration/grant events; admin audit view across clients (aggregated per tenant) |
| Separate platform admin from engineering edit / manufacturing approval | `operator_admin` holds `parts.manage`, `passports.edit_draft`, `files.upload` (usable only in operator tenant today) | **Remove engineering capabilities from Aries Admin**; manufacturing approval stays disabled for everyone |
| **B. Aries Engineer** | | |
| Individual login; switch authorised workspaces | Yes | – |
| Only assigned companies | Yes (membership) | – |
| Only assigned projects | No | Batch 6 (decision D4) |
| Register parts; create/edit passport drafts; review CAD/docs/revisions; handle requests | Yes | – |
| Upload STEP/DWG/PDF/photos | Yes | **Scan files**: not supported (D-01, Batch 7) |
| No self-assignment / escalation / admin management / manufacturing approval | Yes (only operator admin assigns; approval disabled) | Add explicit tests; separation-of-duties rule (D9) |
| **C. Client company** | | |
| Company registration | No | **New** (Batch 3) |
| Individual login; Client Admin manages users (invitations) | Yes | – |
| Browse inventory, 3D, passports, permitted documents | Yes | – |
| Request manufacturing / scanning; track requests and notifications | Yes | – |
| Restricted to own organisation | Yes (RLS + API) | – |
| No altering operator-controlled CAD sources / no bypassing engineering approval | **Gap:** clients can rename and re-version operator files; client admin can manage projects | Batch 1 (decisions D1, D2) |
| Password reset | No | Batch 2 (D8) |

## 3. Proposed role and permission matrix

`✓` allowed · `–` not allowed · `Δ` change from today · *A* = only through a time-boxed read-only access grant (Batch 5) · *own* = own organisation only.

| Capability | Aries Admin | Aries Engineer (assigned) | Aries QA (assigned) | Aries Support (assigned) | Client Admin | Client Engineer | Client User | Procurement | Auditor |
|---|---|---|---|---|---|---|---|---|---|
| Review/approve/reject company registrations (new `registrations.review`) | ✓ | – | – | – | – | – | – | – | – |
| Manage client organisations (`clients.manage`) | ✓ | – | – | – | – | – | – | – | – |
| Manage Aries staff accounts | ✓ | – | – | – | – | – | – | – | – |
| Assign/remove Aries staff to clients (and projects) (new `assignments.manage`) | ✓ (not self) | – | – | – | – | – | – | – | – |
| Manage company users (invite, role, deactivate) | (platform) | – | – | – | ✓ own | – | – | – | – |
| View projects / parts / passports | *A* | ✓ | ✓ | ✓ | ✓ own | ✓ own | ✓ own | ✓ own | ✓ own |
| Manage digitisation projects (`projects.manage`) | Δ – | Δ ✓ | – | – | Δ – (D2) | – | – | – | – |
| Register/edit parts (`parts.manage`) | Δ – | ✓ | – | – | – | – | – | – | – |
| Create/edit passport drafts (`passports.edit_draft`) | Δ – | ✓ | – | – | – | – | – | – | – |
| Read engineering notes (D-13) | *A* | ✓ | ✓ | – | ✓ own | ✓ own | – | – | ✓ own |
| Upload/version operator engineering files (STEP, DWG, PDF, photos) | Δ – | ✓ | – | – | Δ – | Δ – | – | – | – |
| Add client-supplied documents/photos (new `files.upload_client`) (D1) | – | – | – | – | Δ ✓ own | Δ ✓ own | – | – | – |
| Edit/version **operator-uploaded** files | – | ✓ | – | – | Δ **never** | Δ **never** | – | – | – |
| Download engineering originals | *A*: – (D3) | ✓ | ✓ | – | ✓ own | ✓ own | – | – | – |
| View 3D / preview documents | *A* | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – | – |
| Create requests (manufacturing / scanning) | – | – | – | – | ✓ | ✓ | – | ✓ | – |
| View/track own requests | – | – | – | – | ✓ | ✓ | ✓ | ✓ | ✓ |
| Handle client requests (`requests.handle`) | intake list only; detail *A* | ✓ | ✓ | ✓ | – | – | – | – | – |
| View audit trail | ✓ operator; *A* client | – | – | – | ✓ own | – | – | – | ✓ own |
| Approve passports / set evidence level / publish / manufacturing release | **nobody** (OQ-35/36 gated; reserved capability, not granted) | – | – | – | – | – | – | – | – |

Notes:
- "Full access" for Client Admin means full control of **company users and requests and read access to company records** — never
  replacing, editing, reclassifying or versioning Aries-controlled engineering master files (STEP, DWG, drawings, specifications), and never
  bypassing engineering approval (D1).
- *A* (Aries Admin oversight, D3): read-only, audited, inside each client's tenant context; never engineering edits, CAD original downloads,
  approvals or manufacturing release. Built behind a switch that stays **off** until support-access consent (OQ-37) is resolved.
- Aries QA and Aries Support columns are **provisional** (D5): their capability sets are to be defined and approved separately; existing
  memberships are preserved meanwhile.
- One identity per person may hold several roles (D9); **separation of duties** is enforced per action (see §4a), not by separate accounts.

## 4. Aries Engineer assignment workflow

1. Aries Admin → **Clients** → company → **Aries staff** tab → *Assign engineer*: chooses from active Aries staff (operator-tenant members with an
   engineer/QA/support role). Server checks: actor is Aries Admin in the operator organisation; target ≠ actor; target is Aries staff; role is
   assignable. Creates/reactivates the client membership; audit event in **both** tenants; in-app notification to the engineer.
2. *Remove*: deactivates the membership (never deleted, history kept); open sessions in that workspace stop at the next request (tokens carry
   `tid`; membership is re-checked per request).
3. Engineer signs in → sees only assigned companies in the switcher; unassigned company IDs return 404 at API level (RLS + membership).
4. **Project-level assignment (D4 approved)**: each company assignment gets a scope — **company-wide** (all projects, today's behaviour)
   or **project-limited** (only listed projects). Aries Admin → company → project → *Assigned engineers*.
   - **Safe migration:** every existing assignment becomes *company-wide*, so nobody gains or loses access on deployment. Narrowing to
     projects is a later, explicit, audited admin action.
   - A project-limited engineer sees only parts/passports/files/requests of assigned projects. Records without a project (and requests not
     tied to a project) are visible to company-wide engineers only — **open item U4**.
   - **Server-side enforcement everywhere:** list/detail querysets, file versions and download links, CAD derivatives (GLB/PDF previews),
     thumbnails, request detail and attachments, notifications/recipients, search and dashboard counts, and background jobs (a job may only be
     queued by a user allowed on that record; worker output is reachable only through the same checks). Tests cover each path.
5. Guards: engineers cannot call assignment endpoints; nobody can assign themselves or widen their own scope.

### 4a. Identities and separation of duties (D9 amended)

- **One identity per person.** A person may hold several roles through memberships (e.g. Aries Admin in the operator organisation and
  Aries Engineer assigned to a client). Each session acts in one workspace with that workspace's role; capabilities never merge across
  workspaces.
- The current model allows **one role per person per organisation** (unique user × tenant). Holding two roles inside the *same* organisation
  would need a schema change — **open item U5** (not needed for the cases above).
- **Separation-of-duties rules** (enforced server-side, independent of roles held):
  - nobody approves, publishes or releases a passport revision they created or last edited (future OQ-35/36 actions; still disabled);
  - nobody approves a company registration they submitted, or an assignment/access grant to themselves;
  - administrative oversight sessions are read-only even when the same person is also an assigned engineer elsewhere.

## 5. Client registration and Aries approval workflow

### 5.1 States

`unverified` → (email link + password re-entry) → `pending_approval` → `approved` (tenant + Client Admin created) or `rejected`.
`unverified` expires after 24 h; a registration can be withdrawn while pending.

### 5.2 Screens (proposed)

| # | Screen | Content |
|---|---|---|
| S1 | Sign in | Email, password; links **Register your company** and **Forgot password?** (Batch 2) |
| S2 | Register your company | Company legal name, country, city, address, website/email domain, trade-licence/registration no. (D7), industry; contact first/last name, job title, work email, phone; password + confirm; agreement to terms/privacy (texts to be supplied); hidden honeypot field |
| S3 | Check your email | Same message in every case: "If the details can be used, we have sent a verification link to the address." |
| S4 | Verify email (from link) | Shows company name and email; asks for the **password chosen at registration**; on success: "Submitted — pending Aries approval" |
| S5 | Registration status (registrant signs in, no workspace yet) | "Pending Aries review" or "Not approved" with the client-facing message only; no reviewer identity, no internal notes |
| S6 | Aries Admin › Registrations | Tabs Pending / Approved / Rejected; detail shows submitted data, verification time, **possible duplicates** (similar company names/domains/registration numbers — visible to Aries Admin only); actions *Approve* (confirm organisation name and identifier) and *Reject* (client-facing message + internal note) |
| S7 | First sign-in after approval | Client workspace as Client Admin → Users → Invite colleagues (existing flow) |

### 5.3 Security design

| Threat / rule | Design |
|---|---|
| Account takeover (pre-registration of someone else's email) | Password is chosen at registration but **verification requires the emailed link and the same password**; the email owner cannot activate an attacker's registration by clicking, and the attacker cannot verify without the mailbox |
| Existing account email | Identical public response; the email sent to that address says an account already exists (sign in / reset). No registration created, no change to the account |
| Claiming an existing organisation | Public registration **never** links to an existing tenant; approval always creates a **new** tenant. Possible duplicates are shown only to Aries Admin, who rejects and refers the company to its existing Client Admin (invitation) |
| Enumeration | Same response/timing for new/existing emails and companies; status visible only to the authenticated registrant |
| No access before approval | **No tenant exists until approval**; the verified user has no membership, so no RLS context can be opened |
| Tokens | 32-byte random, only SHA-256 stored, purpose-bound (`registration`, `password_reset`), 24 h expiry, single use (atomic redemption, like download links) |
| Rate limits | Register 5/h per IP and 3/day per email; verify 10/h per IP; resend 3/h per registration; existing `login` scope for sign-in |
| Storage and RLS | Registration records owned by the **operator tenant** (forced RLS), written by public endpoints through a narrow service function running in the operator context (pattern of `RequestEnvelope`) |
| Audit | `registration.submitted / verified / approved / rejected / expired`, `client.created`, `membership.created` (operator and new client tenant) |
| Notifications | In-app notification to every active Aries Admin on `pending_approval`; to the registrant on decision (in-app + email) |
| Email delivery | Provider-independent mail interface; development uses a local file **outbox** — the link must still be opened by a person; **no auto-verification, no auto-approval**. Production provider deferred (D6) — **public production registration stays disabled** (feature switch) until real email verification works |
| Password reset (D8) | Same token rules (expiring, single-use, hashed), identical response for known/unknown emails, rate-limited, audited; sessions revoked after a reset |
| Data retention / privacy (D7) | Collect company identification, contact details and trade-licence data; retention period, duplicate-handling procedure and privacy notice — **open item U3**, required before production rollout |

## 6. Aries Admin administrative oversight without weakening tenant isolation (Batch 5, D3 amended)

Required: explicit, audited oversight across **all** client companies; no bypass of tenant isolation; no engineering edits, CAD original
downloads, approvals or manufacturing release; **not activated until support-access consent (OQ-37) is resolved**.

- **Aggregates** (already safe): extend the operator overview with per-client counts computed inside each client's RLS context.
- **Record-level viewing**: an **administrative access grant** — Aries Admin opens a client in *read-only review mode* by stating a reason and a
  duration (e.g. ≤ 8 h). The grant is a temporary, expiring membership-like record with a read-only role (`aries_admin_review`): view
  projects/parts/passports/documents metadata/3D and engineering notes; **no editing, no original downloads** (unless D3 decides otherwise).
- All reads still run in the **client's tenant context under RLS**; nothing queries across tenants.
- Every grant, use and expiry is audited in both tenants; a banner shows "Read-only administrative access — expires hh:mm — logged".
- Whether the client is notified or must consent is **OQ-37 — open item U1**. The capability ships switched off; activation needs that
  decision and a separate approval.
- Cross-company oversight screens (lists of companies, projects, passports and requests with status) are assembled by iterating companies
  and reading each inside its own tenant context — never a cross-tenant query.

## 7. Database / API / UI change list

**Database** (additive migrations only; no change to existing rows):
- `CompanyRegistration` (operator-tenant owned, RLS): company fields, contact fields, normalised name/domain, status, user FK (set at
  verification), reviewer, decision timestamps, client-facing message, internal note, created-tenant FK.
- `EmailToken` (hash, purpose, expiry, used_at, user/registration FK) — also used for password reset.
- Administrative access: `Membership.expires_at` + `purpose` (or a separate `AccessGrant` table) — Batch 5.
- `ProjectAssignment` (client-tenant owned, RLS) — Batch 6, only if approved.
- Optional `Tenant.registration_number`, `primary_domain` for duplicate detection.

**API**:
- Public: `POST /public/registrations/`, `POST /public/registrations/verify/`, `POST /public/registrations/resend/`, `POST /auth/password-reset/` and `/confirm/`.
- Aries Admin: `GET /registrations/`, `POST /registrations/{id}/approve/`, `/reject/`; `/clients/{id}/staff/` (assign/unassign);
  `/admin-access/` (grants, Batch 5); `/projects/{id}/assignments/` (Batch 6).
- `GET /auth/me` returns `registration_status` for a verified registrant without a workspace.
- Capability changes (Batch 1): remove engineering capabilities from `operator_admin`; restrict client file writes (D1); `projects.manage` (D2).

**UI**: login links; Register, Check-email, Verify, Status pages; Aries Admin *Registrations* page with nav badge; *Aries staff* tab on client;
project assignment panel (Batch 6); review-mode banner (Batch 5); role labels "Aries Admin", "Aries Engineer", "Client Admin", …; role
descriptions on the Users page; client upload restricted to *client-supplied* documents.

## 8. Security and migration risks

| Risk | Mitigation |
|---|---|
| Public endpoints attract spam/abuse | Rate limits, honeypot, unverified expiry; a CAPTCHA would need an external service (approval required) |
| No production email service | Registration and password reset cannot go live until D6 is decided; development uses a local outbox |
| Capability removals change behaviour (client uploads, admin edits) and break tests | Batch 1 updates API, UI and E2E/showcase specs together; existing files and audit history unchanged |
| Privileged admin access | Read-only, time-boxed, reason-required, audited, banner, client notification (D3) |
| Project scoping hides records or breaks request routing | Separate batch with its own migration, "unassigned" queue, and RLS/API tests |
| Separation of duties | Decision D9; enforced in membership policy |
| 109 uncommitted changes from earlier batches | Recommend a reviewed baseline commit before Batch 1 (D10) |
| Showcase contains real customer engineering files | Left untouched as instructed; registration work does not touch the showcase |

## 9. Acceptance criteria and test plan (summary)

- **Registration**: identical responses for new/existing email and company; token single-use/expiry/purpose tests; verification fails without
  the password; no tenant or membership exists before approval; RLS shows registrations only in the operator tenant; throttles return 429;
  approval creates exactly one tenant + one Client Admin; rejection creates none; audit and notifications present.
- **Roles**: matrix tests per capability (API) for every role; client cannot PATCH or version operator files; Aries Admin cannot edit parts or
  passports; engineers cannot assign; nobody can approve/publish/release.
- **Isolation**: cross-tenant 404s for all new endpoints; registrant without workspace sees only their own status.
- **Admin review access**: read-only enforced; expiry enforced server-side; audit on grant/use/expiry.
- **Regression**: full backend (PostgreSQL), web tests, typecheck, build, E2E (registration → approval → first sign-in → invite; engineer
  assignment/unassignment; client restrictions), showcase walkthrough on a separate stack.

## 10. Implementation sequence (rev 2)

Ordered to deliver Aries Admin / Aries Engineer / Client access controls first, then client self-registration. Each batch ends with its own
tests and regression run and is committed only after review. Nothing is deployed and public registration stays disabled throughout.

| Batch | Content | Gate before starting |
|---|---|---|
| 0 | Git review and focused baseline commits of the current uncommitted work (manifest in `docs/brd-change-notes/CN-002-baseline-manifest.md`) | Manifest reviewed |
| 1 | **Access-control realignment** (no new tables): role display names; Aries Admin loses engineering edit capabilities; clients may add supporting documents/photos but cannot replace, edit, reclassify or version Aries-controlled master files (file ownership flag on `EngineeringFile`, additive migration: existing files marked by uploader side); `projects.manage` → Aries Engineers only; separation-of-duties checks scaffolded | Baseline committed |
| 2 | **Company and project assignment** (D4): assignment scope (company-wide / project-limited), `ProjectAssignment` with RLS, server-side checks on every path in §4 incl. derivatives, requests and jobs; existing assignments migrated as company-wide; Aries staff assignment UI | Batch 1 |
| 3 | **Email and password reset**: provider-independent mail interface, local file outbox, hashed single-use tokens, rate limits, audit; password reset (D8) | Batch 1 |
| 4 | **Company self-registration**: register → verify (link + password) → pending → Aries Admin review/approve/reject → tenant + Client Admin; notifications; registration switch **off** for production | Batch 3; U3 drafted |
| 5 | **Administrative oversight** (D3): read-only, audited, per-tenant-context oversight screens; switch **off** | Batch 2; activation needs U1 |
| 6 | **Aries QA / Support capability sets** (D5) | U2 decided |
| 7 | Scan-file support (STL/OBJ/PLY/ASC) | D-01 requirement decision |

## 11. Decisions (approved in principle, 26 Oct 2026)

| ID | Decision | Status |
|---|---|---|
| D1 | Client users may add permitted supporting documents and photographs; they must **not** replace, edit, reclassify or create new versions of Aries-controlled STEP, DWG and other engineering master files | **Approved** |
| D2 | Aries Engineers manage scanning/digitisation projects; client users view authorised progress and submit requests | **Approved** |
| D3 | Explicit, audited Aries Admin oversight across all client companies; no tenant-isolation bypass; no engineering edits, CAD original downloads, approvals or manufacturing release; resolve support-access consent before activation | **Amended — approved; record-level activation still blocked by U1** |
| D3a | Aries Admin may access a **read-only administrative inventory summary** across client companies for operational management, without a separate time-limited client-support grant per summary view. Limited to authorised Aries Admin accounts. Conditions in §13. | **Approved 26 Oct 2026** |
| D4 | Company-level **and** project-level engineer assignment; server-side checks incl. documents, CAD derivatives, requests and background jobs; existing assignments migrated safely | **Approved** |
| D5 | Keep Aries QA and Aries Support as internal sub-roles with separately defined capabilities | **Approved; capability sets open (U2).** Superseded by the four-role decision of 30 Oct 2026 (CN-008: QA becomes a permission on Aries Engineers; Aries Support has no place in the four roles, see CN-008 D-2), pending change control |
| D6 | Paid email provider deferred; build provider-independent integration and local outbox; no public production registration without real email verification | **Deferred (provider) / approved (integration)** |
| D7 | Collect company identification, contact details and trade-licence information | **Provisional; retention, duplicates and privacy open (U3)** |
| D8 | Password reset with expiring single-use tokens, rate limits and audit | **Approved** |
| D9 | One identity per person with explicitly assigned roles; separation of duties for sensitive approvals and manufacturing release even when one person holds several roles | **Amended — approved** |
| D10 | Git review and focused baseline commits; exclude confidential CAD, local credentials, database/storage files and generated artifacts; regressions before committing; no history rewrite, no push | **Approved** |

## 12. Open items (must be resolved before the stated step)

| ID | Item | Blocks |
|---|---|---|
| U1 | Support-access consent and client notification for **detailed** Aries Admin or support access (OQ-37). The administrative inventory summary (D3a) is not blocked by U1. | Activating record-level access (Batch 5 grants) |
| U2 | Exact capability sets for Aries QA and Aries Support | Batch 6 |
| U3 | Registration data retention period, duplicate-handling procedure, privacy notice and terms texts | Production rollout of Batch 4 |
| U4 | Visibility of records without a project for project-limited engineers | Finalising Batch 2 (proposal: company-wide engineers only) |
| U5 | Whether one person needs two roles inside the **same** organisation (schema change) | Only if such a case is required |
| U6 | Email provider selection and any paid service approval (D6) | Public production registration and production password reset |
| U7 | CAPTCHA or other bot protection beyond rate limits (external service would need approval) | Production rollout of Batch 4 |
| U8 | Change-control update to BRD v0.4 for CN-002 | Treating CN-002 as a baselined requirement |


## 13. Decision D3a: administrative inventory summary (approved 26 Oct 2026)

**Decision (business owner).** Aries Admin may access a read-only administrative inventory summary across client
companies for operational management, without a separate time-limited client-support grant for each summary view. The
permission is strictly limited to authorised Aries Admin accounts.

### Conditions

| # | Condition | How it is met |
|---|---|---|
| 1 | Every administrative inventory view is audited | Each request writes `inventory.admin_overview_viewed` (with the filters) to the Aries audit trail, and `inventory.admin_summary_viewed` to the audit trail of **every** client company included, so the client can see it |
| 2 | Permitted content | Client, part number and name, project, passport reference and revision, engineering completeness (R-L1/R-L2/R-L3 counts, % and document **count**), review status, digitisation stage, publication status and assigned Aries Engineer |
| 3 | No access to confidential CAD originals, engineering notes, complete passport records or downloads | The summary returns no file names, links, checksums, passport content or notes. **Open record** is disabled (OQ-37). The normal part, passport and file endpoints still return nothing to the Aries Admin in the operator organisation. |
| 4 | No engineering editing, passport approval, manufacturing approval or production release | The Aries Admin role holds no `parts.manage`, `passports.edit_draft`, `parts.review`, `jobsheets.*` or approval capability; approval and release seams stay closed (OQ-35/OQ-36) |
| 5 | Clients never see another company's data | Unchanged: tenant row-level security and tenant-scoped queries. The summary endpoint is refused (403) to every client role. |
| 6 | Aries Engineers stay restricted to assigned companies and projects | Unchanged (D4). The summary endpoint is refused (403) to engineers; their inventory counts follow their project scope. |
| 7 | OQ-37 stays unresolved for detailed Aries Admin or support access | U1 reworded to cover record-level access only; the Batch 5 time-limited grant remains unbuilt and switched off |
| 8 | Privacy disclosure | Administrative summary visibility is part of the platform's **operational privacy policy**. Before production rollout it requires appropriate contractual and privacy disclosure to client companies (terms of service / data-processing terms). Tracked as open item **U9**. |

### Technical design

- Endpoint `GET /api/v1/admin/inventory/`, capability `inventory.admin_overview` (Aries Admin; operator-organisation
  sessions only).
- The read model iterates client companies and reads each one **inside its own tenant context** under row-level
  security. There is no cross-tenant query.
- Filters: client, project, review status, publication state, stage, search.
- Code: `backend/apps/parts/admin_overview.py`, `web/src/pages/AdminInventoryPage.tsx`; navigation entry "Digital
  inventory" for the Aries Admin.

### Traceability

| Requirement | Code | Tests (26 Oct 2026, passing) |
|---|---|---|
| D3a summary access, Aries Admin only | `apps/tenancy/permissions.py` (`inventory.admin_overview`, `OPERATOR_TENANT_ONLY`), `AdminInventoryView` | `tests/test_inventory_stages.py::test_only_aries_admin_gets_the_overview_and_no_extra_rights`; browser `flow-inventory.mjs` (engineer and client refused) |
| Conditions 1–3 (audited, content limits, no record/file access) | `admin_overview.py` (audit records, field list, `DETAIL_ACCESS`) | `test_admin_overview_across_companies_is_summary_only_and_audited`; browser `flow-inventory.mjs` (client audit shows the view; Open record disabled) |
| Condition 4 (no engineering or approval rights) | capability map unchanged for the Aries Admin | `test_only_aries_admin_gets_the_overview_and_no_extra_rights` |
| Conditions 5–6 (isolation, engineer scope) | tenant RLS; `apps/projects/scoping.py` | `test_counts_respect_tenant_and_project_scope`; existing CN-002 isolation suite; browser `flow-inventory.mjs` |
| Role-specific navigation | `web/src/components/Layout.tsx` | `web/src/test/access.test.ts` |

### New open item

| ID | Item | Blocks |
|---|---|---|
| U9 | Contractual/privacy disclosure of administrative summary visibility to client companies (operational privacy policy) | Production rollout of D3a |
