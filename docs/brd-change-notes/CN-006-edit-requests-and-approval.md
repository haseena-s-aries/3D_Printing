# CN-006: Controlled edit requests and reviewer approval

| | |
|---|---|
| **Status** | **Implemented in the isolated access-test environment only** (`EDIT_REQUESTS_ENABLED=true` on 5175 → 8002). Off by default everywhere else. **Formal engineering approval authority is unresolved (§6).** BRD v0.4 is not changed by this note; adding the requirement needs an approved change-control update. |
| **Date** | 2026-10-26 |
| **Basis** | - Requirement "Controlled edit request and manager approval" (26 Oct 2026).<br>- BRD v0.4: OQ-02 (Aries access to client data), OQ-35 (passport approval), OQ-36 (manufacturing release), OQ-33/OQ-38 (external sharing).<br>- CN-002 (roles, engineer company and project scope), CN-003 (client submissions, clones, field provenance), CN-004 (job sheets are Aries-internal). |
| **Unchanged** | Production-release rules; passport approval and publication (still disabled, OQ-35); manufacturing eligibility (OQ-36); stored files and CAD originals; showcase (5173) and engineering-validation (5174) databases. |

## 1. What it does

Anyone allowed to request an edit proposes new values for named fields of a target. An authorised edit reviewer then decides. Nothing in
the target changes until approval.

Possible targets:
- a spare part: Aries-registered, client-submitted or cloned;
- the current revision of a Digital Passport.

Approving an edit request is **not** any of the following:
- engineering verification;
- passport approval or publication;
- manufacturing authorisation.

The UI states this on the dialog and on the request page.

| Captured on each request | Where |
|---|---|
| Target, and the exact base | - Part: `part` plus `base_updated_at`.<br>- Passport: `passport` plus `base_revision_number`, `base_revision_status` and the revision's `updated_at`. |
| Field names, original values (at request), proposed values | `changes` (JSON). Originals are refreshed only by an explicit revalidation. |
| Reason; supporting documents | - `reason` is required.<br>- `evidence_files` must be existing files of the same part. Read-only references; files are never copied or changed. |
| Requester, role, side, timestamps | `created_by`, `requester_role`, `requester_side`, `created_at` and `submitted_at` |
| Reviewer, decision and reason, decision time | `reviewer`, `decision_reason`, `decided_at` |
| Application result and revision reference | `application_result`, `applied_at`, `applied_revision_number` |
| History | `EditRequestEvent` rows: action, from and to status, note, side, user, time. Insert-only. |

Reference format: `ER-YYYY-NNNNN`, numbered per company.

## 2. Status model

The status labels are:
- **Draft**
- **Submitted**
- **Under Review**
- **Corrections Requested**
- **Approved**
- **Rejected**
- **Applied**
- **Conflict / Revalidation Required**
- **Withdrawn**

Transitions:
- Draft → Submitted (requester).
- Submitted → Under Review (reviewer).
- Submitted or Under Review → one of the reviewer's decisions:
  - **Approved → Applied**, in one transaction;
  - **Approved → Conflict**, with nothing written, when the target changed;
  - **Rejected**, with a reason (required);
  - **Corrections Requested**, with a note (required).
- Corrections Requested → the requester edits and resubmits.
- Conflict → **Revalidate and resubmit** (requester). This refreshes the originals and the base to the current values, then returns to Submitted.
- Withdrawn (requester): from Draft, Submitted, Corrections Requested or Conflict.

"Approved" is recorded as an event. The request immediately becomes Applied, or Conflict if the target changed.

**Closed requests are immutable.** Once a request is Applied, Rejected or Withdrawn, a database trigger refuses any further change to it.

## 3. Who may do what (server-side)

| Capability | Roles | Conditions |
|---|---|---|
| `edits.request` | Aries Engineer, Client Administrator, Client Engineer, Client User | - Client Users only with the CN-003 `part_submission_allowed` permission.<br>- Engineers only within their company and project scope (CN-002). |
| `edits.review` | Aries Engineer only | - Requires `Membership.edit_reviewer = true` in that client company. Set by the Aries Admin in **Clients → Aries engineers → Access** ("Authorised edit reviewer (provisional, CN-006)").<br>- Scoped to the engineer's projects. |

Never permitted:
- **Aries Admin is not an edit reviewer.** No `edits.review`; the admin only grants the flag and is notified when a company has no reviewer.
- **No self-approval.** The requester can never review their own request (`self_approval`, 403). Their own requests are excluded from their queue.
- **No privilege escalation.** Requests cannot touch tenant, ownership, origin, lineage, part status, files or file versions, revision status, approval records, evidence level, publication or manufacturing eligibility. Only fields in `apps/edits/fields.py` are accepted (`field_not_editable`, 400).
- **No confidential data in client responses.** Client responses and notifications never carry engineering notes, R-L3, process parameters, manufacturing spec or job-sheet data. Passport edits are limited to R-L1 and R-L2 descriptive fields, excluding the manufacturing spec and process parameters. Notifications name fields only, never values.

## 4. Applying an approved edit

| Class (`data_class`) | When | Effect |
|---|---|---|
| A. Client-owned descriptive data | Client-submitted or cloned part, and only client-descriptive fields | - Fields updated; previous values kept in the request.<br>- Provenance stamped `client` and marked verified by the reviewer. |
| B. Aries-controlled master data | Any other part field, or an Aries-registered part | - Same mechanics, but requires an authorised reviewer.<br>- Provenance is `aries`.<br>- CAD originals and file versions are never touched. |
| C. Passport draft | The latest revision is a draft | - A **new draft revision N+1** is created with the changes.<br>- The earlier draft is marked superseded and kept unchanged. |
| D. Approved or published passport | The latest revision is not a draft | - Never mutated.<br>- A **new draft revision N+1** is proposed.<br>- Approval and publication of that revision remain under OQ-35 and stay disabled. |

**Lost-update prevention.** Before writing, every requested field is compared with the target's current value:
- If any requested field differs from the recorded original, the request goes to **Conflict / Revalidation Required** and nothing is written.
- If only *other* fields changed, the edit applies and the result says so.

## 5. Notifications and audit

- **Submit or resubmit:** in-app notification to the authorised reviewers in scope. If none exist, the Aries Admins are told to authorise one.
- **Each decision** (corrections, rejection, applied, conflict): the requester is notified.
- **Audit events:** `edit_request.created`, `.updated`, `.submitted`, `.resubmitted`, `.review_started`, `.corrections_requested`, `.rejected`, `.approved`, `.applied`, `.conflict`, `.rebased` and `.withdrawn` go into the client tenant's audit trail. The engineer-access audit records grants of `edit_reviewer`.

## 6. Unresolved: formal engineering approval authority (not invented here)

| # | Open point | Interim behaviour (access-test only) |
|---|---|---|
| U1 | Who formally holds engineering approval authority for Aries-controlled master data and passport content (OQ-35)? | A **provisional** per-company `edit_reviewer` flag on Aries Engineers. It confers no passport approval, verification or release right. |
| U2 | Should a client manager approve edits to the client's **own** descriptive data instead of, or before, Aries? | - Not implemented: all decisions are by an Aries edit reviewer.<br>- Needs a business decision on whether the "manager" is a Client Administrator, and on whether Aries must also review. |
| U3 | Does an Applied edit to a passport draft need separate engineering verification before approval? | - The new revision is an ordinary draft and goes through the normal (still disabled) OQ-35 approval path.<br>- Edit approval never activates it. |
| U4 | Should two-person review apply (requester's company plus Aries)? | Not implemented |
| U5 | Retention of edit-request history, and whether clients may see the reviewer's name | Kept indefinitely; the reviewer's name is shown to the requester. To be confirmed. |
| U6 | Can supporting documents be new uploads (photos) rather than existing part files? | Existing files of the part only. A client can upload a photo or PDF on the part first (CN-003), then attach it. |

## 7. Traceability

| Requirement item | Implementation | Test |
|---|---|---|
| Request edit on part, passport draft, client-submitted and cloned parts | `EditRequestDialog.tsx`; buttons on `PartDetailPage` and `PassportDetailPage` | `flow-edits.mjs` steps 1 and 7; `test_client_descriptive_data_on_client_submission` |
| Exact base, originals, reason, requester and role | `EditRequest` model, `services.create` | `test_client_request_…`; flow "request pins the target" |
| Queue, comparison, history, status indicators | `EditRequestsPage.tsx` (`/edit-requests`, `/edit-requests/:id`) | `edit-requests.test.tsx`; flow screenshots 03–05 |
| Approve, reject with reason, corrections | `services.approve`, `reject`, `request_corrections` | `test_corrections_rejection_and_immutable_history`; flow steps 2, 3, 6 and 9 |
| No self-approval or unauthorised approval; Admin is not an approver | `_require_reviewer`, `capabilities_for` | `test_no_self_approval_…`; flow steps 0, 1 and 5 |
| Client isolation, engineer company and project scope | RLS plus `restrict(…, "part__project")` | `test_isolation_and_project_scope`; flow step 4 |
| Clients cannot change CAD; protected fields | `fields.py` whitelist | `test_protected_fields_cad_and_confidential_data`; flow step 4 |
| Passport draft → new revision; approved revision never mutated | `_apply_passport` | `test_passport_draft_becomes_new_revision…`, `test_approved_revision_is_never_mutated`; flow step 7 |
| Stale conflict, then revalidation | `_drift`, `rebase` | `test_stale_conflict_then_rebase`; flow step 8 |
| No bypass of manufacturing or publication gates | Not touched by the apply step | flow "no publication or manufacturing change" |
| Off by default | `EDIT_REQUESTS_ENABLED` | `test_disabled_by_default` |

## 8. Migrations

| Migration | Change |
|---|---|
| `tenancy.0004_membership_edit_reviewer` | Adds `edit_reviewer` (default false) to memberships. No existing access changes. |
| `edits.0001_initial`, `edits.0002_security` | New tables with tenant row-level security. Events are insert-only, and closed requests cannot be updated. No existing data changes. |
