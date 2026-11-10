# Web batch W1: "Complete passport workspace" — results

- **Date:** 2026-10-16
- **Scope:** as authorised from `web-application-review.md` §8, starting with defects D-1 to D-5.
- **Not changed:** BRD v0.4, Azure, mobile features, and the gated rules. OQ-35, OQ-36, OQ-27 and OQ-33 stay
  disabled, and no approval, publication or eligibility rules were invented.

## 1. Defects from the review

| ID | Fix | Verified by |
|---|---|---|
| D-1 | The API accepts an empty `password` for existing users. The member form omits empty fields and hides name and password for operator roles. | `test_api_isolation.py` (exact web payload); E2E W1 test 1 |
| D-2 | The client list reloads after a member is added, so the count is current. | E2E W1 test 1 (count = 2) |
| D-3 | The slug pattern is escaped for the browser's `v`-flag regex. | E2E W1 test 1 (no console pattern error) |
| D-4 | After sign-in, the remembered page is used only for the same user. Deep links with no prior session are kept. | `review-defects.test.ts` (4 cases); E2E W1 test 2 |
| D-5 | The 3D viewer adds a studio environment map and a neutral non-metallic material when a GLB defines none. Root cause: OCCT writes no materials, and glTF's default material is fully metallic. | `materials.test.ts`; screenshots before and after |

## 2. W1 items delivered

| # | Item | Where | Requirements |
|---|---|---|---|
| 2 | Embedded 3D viewer in the passport | Passport → *Interactive 3D model* tab. Model picker, full screen, active-view state, pan/zoom hint. A distinct message and next step for queued, failed, not-requested, not-available, load-failed and unsupported states. The standalone route is kept. | VWR-001 to 011, VWR-009 |
| 3 | Embedded PDF viewer with a separate *preview* right | Passport → *Documents* → *Preview*. Previous/next page, page-number entry, zoom in/out, fit width. Uses the new `preview` link variant, served inline, audited as `file.previewed`, with the same roles as 3D viewing. Client users can now read specifications without download rights. | DRW-003, BR-039 |
| 4 | File versioning UI | *Versions* (history with uploader, date, SHA-256, note; per-version preview and download) and *New version* (the earlier version is kept). Uploader shown on every file. | CAD-005, CAD-009, CAD-010 |
| 5 | Revision UI | *Revision history* tab: who created and last changed each revision, a read-only view of any revision, and a field-level comparison with the previous one. "Start new revision" appears once a revision is no longer a draft, which needs approval (OQ-35). | BR-034, DM-002 |
| 6 | R-L2 and R-L3 forms | *Product information* → R-L1 / R-L2 / R-L3 sub-tabs, each with its own completeness. R-L2 covers the BR-007 field set, the acceptance table, the BR-026 manufacturing specification (numeric hours) and BR-041 process parameters. R-L3 links the five BR-008 evidence documents to the passport's own files; QA confirmation is disabled (OQ-35). | BR-005 to 009, BR-026, BR-041, BR-043 |
| 7 | Part edit; R-L1 pre-fill; summary reset | Part master data *Edit*. R-L1 pre-fills material, size and application from the part (hint shown). R-L1 fields can be marked not applicable with a reason. RPM is required for rotating parts. The revision summary input starts empty and replaces the old summary. | BR-001, BR-006, BR-009, UX-3, UX-4 |
| 8 | Organisation switcher and operator overview | Topbar *Organisation* selector and dashboard *My organisations* (counts per organisation, *Open*). Uses only memberships the user already has (`/auth/memberships/`, `/auth/switch/`), revokes the old refresh token, and is audited in both organisations. Operator staff in a client organisation see "Operator portal · client workspace". | BR-029, UX-1, UX-2 |
| 9 | Pagination and filters | Parts (search, category, criticality), passports (search plus data-capture column), audit trail (action, object type), clients. | BR-010, BR-054 |

Also addressed:

| UX item | Change |
|---|---|
| UX-5 | Aligned file-table columns |
| UX-7 | Success messages for clients, members and part edits |
| UX-9 | Read-only users no longer see "Drafts can be prepared now" |
| PSEC-001 | Every section shown on every passport, "None uploaded." when empty, plus a Manufacturing history section |

## 3. Tests (all executed 2026-10-16, after the security fix in §5)

| Suite | Result |
|---|---|
| Backend `pytest` on PostgreSQL | **113 passed**: 73 Phase 1, plus 12 in `test_w1_passport_workspace.py`, 19 in `test_membership_security.py` and 9 in `test_document_access.py` |
| OpenAPI schema | 0 warnings; `docs/openapi.yaml` and `packages/api-types` regenerated and current |
| Web typecheck / unit tests / build | Passed / **21 passed** / passed |
| Viewer package unit tests | **10 passed** |
| Mobile typecheck / Jest (shared types changed) | Passed / 16 passed |
| E2E Playwright | **10 passed**: 3 Phase 1 (updated for the new passport layout), 7 W1 |

The W1 E2E covers four roles plus another organisation:

- **Operator admin:**
  - D-1 to D-3.
  - Managing an operator assignment in a client organisation.
- **Operator engineer:** D-4, switcher, full workspace.
- **Client admin and client user:**
  - Embedded 3D and PDF viewing, with download and new-version rights following the role.
  - The client admin's Users page: operator staff are read-only, own users can be added, changed and
    deactivated, and an operator address cannot be added.
- **Another client organisation:** "Not found", no viewer content.

Bundle: the main chunk is 335 kB. The 3D viewer (648 kB) and PDF viewer (440 kB, plus the pdf.js worker) load
only when opened.

## 4. Decisions made during W1 (please review)

1. **PDF preview rights.** These are the same roles that may view 3D derivatives: operator admin, engineer, QA,
   support; client admin, engineer, user. Procurement and auditor are excluded, as for 3D. I chose this to avoid
   inventing a new permission policy; change it in `CAPABILITIES` if the permission matrix (FR-02) says
   otherwise.
2. **R-L2 "Criticality (AMSL)"** is provisional free text, because the AMSL values are not defined in BRD v0.4.
   It is stored as entered and never used to derive eligibility, evidence level or approval. The form says so, and
   `test_amsl_criticality_is_provisional_and_changes_no_state` proves it.
3. **"Original part image" and "CAD image"** (listed in BR-006) are not separate fields. Images can be attached
   as documents; this needs a decision on whether thumbnails are expected.
4. **Completeness** counts R-L1 as 10 fields plus RPM for rotating parts, R-L2 as 12 fields plus 13
   specification fields, and R-L3 as 5 documents. It is guidance only.
5. **Client admins could change or deactivate operator staff** assigned to their organisation (UX-6). This is
   **fixed**; see §5.

## 5. Security fix: client administrators could manage operator staff

### Issue

Found in the web review (UX-6) and confirmed in the API. A client administrator could change the role of, or
deactivate, operator staff assigned to their organisation, through the Users page or a direct `PATCH /users/{id}/`.

The same code path had four further weaknesses:

- **Adding other accounts:** it could add any existing account to the client organisation, including operator
  staff and other organisations' users, by entering their email.
- **Loose boolean handling:** `is_active` was coerced with `bool(...)`, so the string `"false"` meant `true`.
- **Role-family changes:** nothing stopped a role moving between the operator and client families.
- **Operator admin inside a client:** the role `operator_admin` could be assigned inside a client organisation.

Against the pre-fix code, **15 of the 19 new security tests fail**. They were run by temporarily restoring the
committed `tenancy/api.py`.

### Fix (server-side; the UI only reflects it)

- **One policy module** for every membership write: `backend/apps/tenancy/membership_policy.py`, used by
  `UserViewSet.create/update/partial_update` and by the operator's `clients/{id}/members/` endpoints.
- **Ownership:**
  - **Operator-owned:** any operator role, any membership in the operator organisation, and any account of
    operator staff. These are managed **only by operator administrators acting from the operator organisation**.
  - **Organisation-owned:** client-role memberships of client users. These are managed by that organisation's
    client administrators, and by operator administrators as platform administrators.
- **Client administrators:**
  - Assign client roles only.
  - Cannot add operator staff or accounts that belong to another organisation. The same neutral message is
    returned in both cases, so the response doesn't reveal which organisation an address belongs to.
  - Cannot change their own role or deactivate themselves.
  - Get 404 for any membership outside their organisation.
- **Roles keep their family.** A client user cannot become operator staff, nor the reverse
  (`role_family_change`). Only engineer, QA and support operator roles can be assigned inside a client
  organisation; operator administration stays in the operator organisation.
- **Strict update input.** `MemberUpdateSerializer` parses booleans properly and rejects unknown roles.
- **Operator management of assignments.** New `PATCH /clients/{id}/members/{membership_id}/` lets operator
  administrators change or deactivate operator assignments. It is audited in both organisations, and deactivation
  ends access immediately.
- **The API now tells the UI** `managed_by` (`operator` or `organisation`) and `can_manage` for the caller. The
  Users page shows operator staff as "Platform operator staff · managed by the operator", with no controls.
- **Support access stays separate.** Support-access grants (ACC-001: purpose, expiry, client review) remain a
  separate, unimplemented mechanism. No consent rules were added (OQ-37 is open).

### Evidence

`test_membership_security.py` (19 tests) covers:

- A client admin changing role, deactivating (also via the string `"false"`) or using PUT on an operator engineer:
  403 `operator_staff_managed_by_operator`, and the database is unchanged.
- A client admin adding operator staff or another client's user: 403 `user_not_addable`, with an identical message
  in both cases.
- Another organisation's membership ids, including the operator admin's: 404. The operator-only endpoint returns
  403 to client admins.
- Elevated roles (`operator_admin`, `operator_engineer`): 403. An unknown role: 400.
- Own role change or deactivation: 400 `cannot_change_self`.
- Client engineer, client user and procurement have no management rights; neither does an operator engineer
  working in a client.
- **Allowed workflows still work:**
  - A client admin adds, re-roles, deactivates and reactivates their own users and promotes a colleague to client
    admin; every change is audited.
  - An operator admin re-roles and deactivates an operator assignment; the engineer's session in that client ends
    at once.
  - An operator admin manages operator staff in the operator organisation.

`test_document_access.py` (9 tests) covers:

- Original versus preview rights for each of five roles.
- 404 for another organisation on file, version list, links and passport.
- Preview only for PDFs.
- Preview links that stop working when the membership is deactivated and cannot be forged.
- AMSL text that changes no state, with direct writes to the state fields ignored.

E2E W1 tests 1 and 6 exercise the same rules through the UI.

| Screenshot | Shows |
|---|---|
| `screens/sec-01-client-admin-users.png` | Client admin's Users page: operator staff are read-only |
| `screens/sec-02-operator-admin-client-members.png` | Operator admin's Clients page: member controls |
| `screens/sec-03-amsl-provisional.png` | The provisional AMSL hint |
| `e2e/results/screenshots/w1-05-client-admin-users.png` | The refusal message after adding an operator address |

### Residual notes

- **Download and preview links are bearer links.** They are signed, valid for 5 minutes, bound to the issuing
  membership, and re-checked on use (HYB-012). Anyone holding the URL during those minutes can open it.
  Single-use links would be a Phase 2 hardening option.
- **Account enumeration is still possible in one place.** Adding a *new* address still requires a password, while
  an existing one is refused. The difference reveals that an account exists, though not where. An invitation flow
  would remove this.

## 6. Still open after W1

- **Gated:**
  - Approval, publication and evidence-level transitions (OQ-35). Until then, every passport has a single draft
    revision, and comparison has nothing to compare in practice.
  - Manufacturing eligibility (OQ-36).
  - DWG preview (OQ-27).
  - Watermarking (OQ-33).
- **Not in W1:**
  - Ordering (BR-013/014).
  - Advanced viewer features (VWR-012 to 018).
  - Human-readable audit objects (UX-10).
  - An invitation flow instead of admin-set passwords.
- **Environment:**
  - Real STEP/DWG samples (B-01).
  - CI has never run (B-06).
