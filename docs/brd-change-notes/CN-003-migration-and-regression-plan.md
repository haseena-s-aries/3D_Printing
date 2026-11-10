# CN-003: Migration and regression plan (FOR REVIEW: nothing below has been executed)

| | |
|---|---|
| **Purpose** | How to enable CN-003 (client spare-part submissions, FR-04 amended; structured passport forms) beyond the isolated access-test environment |
| **Status** | Plan only, awaiting business-owner review. The only environment changed so far is access-test (`passport_access`, ports 8002/5175). |
| **Not in scope** | Production deployment, Azure provisioning, GitHub push, manufacturing release (OQ-36) and passport approval (OQ-35). All remain off. |

## 1. Environments on this machine

All four environments run from the **same source tree** (`3dp-passport/backend` and `3dp-passport/web`).

| Environment | Database | API / Web | Code currently loaded | CN-003 state |
|---|---|---|---|---|
| Development / E2E | `passport` | started on demand | — | migration not applied |
| **Showcase** | `passport_demo` | 8000 / 5173 | API and worker: **old** code (loaded before the change, `--noreload`). Web: **new** code (Vite hot reload). | migration not applied |
| **Engineering validation** | `passport_validation` | 8001 / 5174 | Same as showcase | migration not applied |
| Access test | `passport_access` | 8002 / 5175 | new | **applied, feature on** |

### Existing condition you should know about (found while preparing this plan)

**What is happening:** because the web dev servers reload from the shared source, the showcase and validation web pages
already show the new screens. Their APIs are still the old ones, so:
- `GET /passport-field-options/` returns 404.
- The structured passport controls show **no option lists**, and existing values appear as "Custom value".
- Client-submission screens stay hidden, because those APIs do not grant `parts.submit`.

**Effect on data:** none. Values are displayed and saved unchanged: the old API ignores the new optional keys. It is a
display degradation only. The same applies to the CN-002 screens made earlier.

**Choose one:**
- **A (recommended).** Apply the additive migration to showcase and validation, then restart their API and worker, with
  the feature switch **off**. Steps 3–4 below.
- **B.** Serve showcase and validation from a frozen build of the previous web code until CN-003 is promoted.

**Restart warning:** if the showcase or validation API or worker is restarted **without** the migration, parts pages will
fail, because the new columns don't exist yet. Apply the migration first, or choose B.

## 2. What the migration does

`parts.0003_client_submissions` adds 11 columns to `parts_sparepart`:

| Column | Type / default | Existing rows get |
|---|---|---|
| `manufacturer` | text, blank | blank |
| `origin` | text, default `aries` | `aries` |
| `review_state` | text, default `not_required` | `not_required` |
| `submission_kind` | text, blank | blank |
| `submitted_by`, `reviewed_by` | nullable user FK | null |
| `submitted_at`, `reviewed_at` | nullable timestamp | null |
| `review_note` | text, blank | blank |
| `unknown_fields` | JSON, default `[]` | `[]` |
| `field_provenance` | JSON, default `{}` | `{}` |

- **Nothing is rewritten:** no passport, revision, file or request data.
- **Row-level security:** the table already has forced RLS (`parts.0002_security`), and new columns inherit it.
- **Passport content:** no migration. The new keys `rl1.operating_environment`, `rl1.value_sources` and
  `rl2.manufacturing_process` are optional JSON keys. Existing revisions keep their exact content, and approved revisions
  stay immutable.
- **Behaviour with the switch off** (`CLIENT_PART_SUBMISSIONS_ENABLED=false`, the default): identical to before for all
  users, except that the structured passport controls are active. Those are approved in principle and are a display
  change only.
- **Rollback:** `manage.py migrate parts 0002` drops only the 11 new columns. Any client submissions made while the switch
  was on would lose their review metadata, but not the part rows. Restore from the pre-migration backup if exact
  reversal is needed.

## 3. Procedure per environment (proposed order: development/E2E → validation → showcase)

For each environment, after your approval:

1. **Freeze.** Stop that environment's API and worker. The web server can keep running.
2. **Back up.**
   - Database: `pg_dump -Fc <db>` to `D:\Applications\3DPriniting\backups\<db>-pre-CN003-<timestamp>.dump`.
   - Record row counts of: `parts_sparepart`, `passports_digitalpassport`, `passports_passportrevision`,
     `files_engineeringfile`, `files_fileversion`, `servicerequests_clientrequest`, `audit_auditevent`.
   - Record SHA-256 checksums of all stored file versions (from `files_fileversion.sha256`) and verify a sample of storage
     files against them.
3. **Dry run.** `manage.py migrate --plan` and `manage.py sqlmigrate parts 0003`, then review that the SQL is
   `ALTER TABLE … ADD COLUMN` only.
4. **Migrate.** `manage.py migrate`, using that environment's own runner: `run_demo.py manage`, `EngValidation/tools/run.py
   manage`, or the development `.env`.
5. **Verify integrity.**
   - Row counts are unchanged.
   - Every part has `origin='aries'` and `review_state='not_required'`.
   - The passport revision `content` hash is unchanged for every revision, compared with a pre-migration export of
     `md5(content::text)`.
   - File checksums are unchanged.
   - RLS is still forced on `parts_sparepart` (`relforcerowsecurity = true`).
6. **Restart** the API and worker with the switch **off**.
7. **Smoke test.**
   - Sign in as each existing role.
   - Open the inventory, a part, a passport (R-L1/R-L2/R-L3 tabs) and the 3D viewer.
   - Confirm stored passport values display unchanged. Non-matching ones show as "Custom value".
   - Confirm `GET /passport-field-options/` returns 200.
8. **Enable the switch** (separate approval per environment): set `CLIENT_PART_SUBMISSIONS_ENABLED=true`, restart, and run
   §4 B.

**Showcase and validation:** the switch stays **off** unless you decide otherwise. Their data (including the AMD1005
files) is only extended with default columns, never reset or reseeded.

## 4. Regression plan

### A. Automated (before any environment is migrated)

| Suite | Command | Last result (26 Oct) |
|---|---|---|
| Backend: full, PostgreSQL with RLS | `pytest` in `backend` | 229 passed |
| OpenAPI contract | `manage.py spectacular --validate --fail-on-warn`, then `npm run gen:api` with no diff | valid |
| Web typecheck, unit tests, build | `npx tsc --noEmit`, `npx vitest run`, `npm run build` | pass, 65 tests, build OK |
| Repository Playwright: core | `e2e/w1-passport-workspace.spec.ts`, `e2e/portal.spec.ts` (updated for the new controls) | **not yet run**; run against development/E2E |
| Repository Playwright: showcase walkthrough | `e2e/showcase/demo-walkthrough.spec.ts` | not run since CN-002; run after the showcase migration (read-only walkthrough) |
| Access-test end-to-end | `AccessTest/tools/flow-submissions.mjs`, `AccessTest/tools/flow.mjs` | 33/33, 24/24 |

### B. Functional checks after enabling the switch in an environment

1. Client Administrator submits a part with an unknown part number and photo/PDF:
   - It shows Pending Aries review, has a provisional number, and has no passport.
   - The assigned engineer is notified.
2. Client User proposes a part:
   - Another client user cannot edit it; the Client Administrator can.
3. Isolation:
   - Client B cannot open or modify client A's submission (404).
   - A project of company B cannot be linked.
4. Project-limited engineer:
   - Sees only submissions in assigned projects.
   - Cannot accept into another project.
   - Submissions with no project alert the Aries Admins.
5. Review loop:
   - Request information → client corrects and resubmits → accept with verified fields → passport draft created.
   - Before acceptance, passport creation is refused (`part_not_accepted`).
6. Clients cannot:
   - set criticality or status;
   - edit Aries parts;
   - edit reviewed submissions;
   - upload STEP/DWG;
   - rename or version Aries master files.
7. Gates:
   - An accepted part has no evidence level, publication or eligibility change.
   - Submit, approve and publish stay disabled (OQ-35/36).
8. Passport forms:
   - Dropdown, custom and unit values round-trip.
   - Legacy values (e.g. `120.0 x 34.0 mm (Ø x H)`, `SR 650 °C 2 h`) open as Custom value and save unchanged when
     untouched.
   - An incomplete draft saves.
   - Revision history and the revision comparison show only the intended changes.
9. Audit trail contains `spare_part.submitted`, `info_requested`, `resubmitted`, `accepted` and `declined` events.
10. Mobile width (390 px): the submission form and R-L1 have no horizontal scroll.

### C. Data-preservation checks (showcase and validation, after migration)

- Same row counts, revision content hashes and file checksums as the pre-migration backup.
- Showcase walkthrough: the AMD1005 impeller passport shows the same R-L1/R-L2/R-L3 values, documents and 3D model as
  before.

## 5. Decisions needed before promotion

| # | Decision | Default proposed |
|---|---|---|
| P1 | Existing condition (§1): fix showcase and validation by migrating with the switch off (A), or freeze their web to the previous build (B) | A |
| P2 | Which environments get the switch **on** after access-test: development/E2E only, or also validation or showcase | Development/E2E only |
| P3 | "Authorised Client Users" (CN-003 C3-1): role-based (current) or a per-user authorisation set by the Client Administrator (needs a small additive migration) | Decide before production |
| P4 | Client editing after acceptance (CN-003 C3-4) | Keep locked |
| P5 | Commit of the CN-003 work to the local baseline branch (no push), after regressions pass | Awaiting your instruction |

## 6. Addendum: Clone Part migrations (26 Oct 2026)

Applied to `passport_access` only.

| Migration | Change |
|---|---|
| `tenancy.0003_membership_part_submission` | Adds `part_submission_allowed` (default false) to memberships |
| `parts.0004_clone_lineage` | Adds 8 nullable or defaulted lineage columns to `parts_sparepart`; creates `parts_sparepartreviewevent` |
| `parts.0005_clone_security` | Forced row-level security on review events; append-only trigger on review events; immutability trigger on lineage columns. The trigger acts only on rows with `source_part_id`, so existing parts are unaffected. |

**Add to the procedure in §3:**
- Verify that both triggers exist after migrating.
- Existing memberships get `part_submission_allowed = false`. Client Users who should submit or clone parts must be
  granted it by their Client Administrator after the switch is turned on.
- **Rollback:** `migrate parts 0003` and `migrate tenancy 0002`. This drops the clone columns, the review-event table and
  the triggers.

**Add to regression §4:**
- Backend `test_part_clone.py` (12 tests).
- Web `part-clone.test.ts`.
- Browser `flow-clone.mjs`.

## 7. Addendum: material-change enquiry (26 Oct 2026)

| Migration | Change |
|---|---|
| `servicerequests.0003_material_change` | Adds `material_option`, `original_material`, `proposed_material` and `material_change_reason` (blank defaults), and a nullable `linked_part` foreign key, to `servicerequests_clientrequest`. The table already has row-level security. Existing requests are unaffected. |

**Regression additions:**
- Backend `test_material_change.py` (8 tests).
- Browser `flow-forms-material.mjs`.
- The repository Playwright specs need the structured dimension controls on part forms (e.g. `e2e/portal.spec.ts` "Dimensions").


## 8. Addendum: draft job sheets (CN-004, 26 Oct 2026)

| Migration | Change |
|---|---|
| `servicerequests.0004_job_progress` | Adds `job_progress` (blank default) to `servicerequests_clientrequest` |
| `jobsheets.0001_initial`, `0002_security` | New tables with tenant row-level security, a restrictive staff-only policy, a revision immutability trigger and the sequence `jobsheet_draft_seq`. No existing data changes. |

**Procedure additions:**
- Verify the restrictive policy `jobsheet_staff_only` exists on both tables.
- Verify that the application role cannot read `jobsheets_jobsheet` without `app.jobsheet_access`.
- Rollback: `migrate jobsheets zero` and `migrate servicerequests 0003`.

**Regression additions:**
- Backend `tests/test_jobsheets.py`.
- Web `jobsheet.test.tsx`.
- Browser `flow-jobsheet.mjs`.


## 9. Addendum: passport PDF reports (CN-005, 26 Oct 2026)

| Migration | Change |
|---|---|
| `reports.0001_initial`, `reports.0002_security` | New tables with tenant row-level security and immutability triggers. No existing data changes. |

**Runtime requirements:**
- `pypdf` and `pypdfium2` in the Python environment.
- Node, plus the repository's Playwright Chromium, on the host that generates reports.

**Regression additions:**
- Backend `tests/test_passport_reports.py`.
- Browser `flow-reports.mjs`.
- `validate-reports.py`.


## 10. Addendum: controlled edit requests (CN-006, 26 Oct 2026)

| Migration | Change |
|---|---|
| `tenancy.0004_membership_edit_reviewer` | Adds `edit_reviewer` (default false) to `tenancy_membership`. |
| `edits.0001_initial`, `edits.0002_security` | New tables with tenant row-level security, an insert-only event table and a trigger that blocks updates to closed requests. No existing data changes. |

**Enabling outside access-test needs:**
- `EDIT_REQUESTS_ENABLED=true`;
- the CN-006 §6 approval-authority decisions;
- an approved BRD change-control update.

**Procedure additions:**
- Verify that the policies on `edits_editrequest` and `edits_editrequestevent` exist.
- Verify that the trigger `edit_request_closed` refuses updates to applied, rejected or withdrawn requests.
- Rollback: `migrate edits zero`, then `migrate tenancy 0003`.

**Regression additions:**
- Backend `tests/test_edit_requests.py`.
- Web `edit-requests.test.tsx`.
- Browser `flow-edits.mjs`.


## 11. Addendum: bulk inventory import (CN-007 Phase 1, 27 Oct 2026)

| Migration | Change |
|---|---|
| `parts.0006_inventory_identifiers` | Adds eight blank-by-default columns to `parts_sparepart` and the `unknown` category choice. No existing values change. |
| `tenancy.0006_membership_inventory_import_allowed` | Adds the `inventory_import_allowed` flag (default false). |
| `imports.0001_initial`, `imports.0002_security` | New tables with tenant row-level security; committed and discarded imports are frozen. |

**Enabling elsewhere needs:**
- `INVENTORY_IMPORT_ENABLED=true`;
- `openpyxl` installed;
- the CN-007 §5 decisions.

**Rollback:** `migrate imports zero`, `migrate tenancy 0005`, `migrate parts 0005`.

**Regression additions:**
- Backend `tests/test_inventory_import.py`.
- Web `inventory-import.test.tsx`.
- Browser `flow-inventory-import.mjs`.

The access-test database was dumped before migrating, to `Backups/2026-10-27-before-cn007/`.


## 12. Addendum: report builder (CN-005 §10, 27 Oct 2026)

| Migration | Change |
|---|---|
| `files.0005_report_documents` | Adds `client_visible` (existing documents set True; new documents default False), `page_count` and four document categories |
| `reports.0003_report_templates` | Adds `template` (default `standard`; existing immutable reports are not updated) |

**Behaviour change when enabled elsewhere:** Aries-uploaded PDFs are hidden from client users until released.

**Rollback:** `migrate reports 0002`, `migrate files 0004`.

The access-test database was dumped first, to `Backups/2026-10-27-before-cn005-builder/`.
