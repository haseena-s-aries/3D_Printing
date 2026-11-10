# Baseline commit manifest (CN-002 Batch 0) — FOR REVIEW, nothing committed

| | |
|---|---|
| Date | 26 October 2026 (rev 2: B1, B3, B4, B5 approved; B2 identity pending confirmation) |
| Repository state | Branch `main`, last commit `aa74237` (W2). No remote configured. Configured Git identity: `Jennifer J <johnjenij@gmail.com>` |
| Working tree | **125 files**: 43 modified, 82 untracked (git status shows 109 entries because new folders count once) |
| Proposal | **89 source/doc files in 5 focused commits** + this manifest; **36 generated screenshots excluded**; **3 files must be sanitised first** |
| Rules (D10) | No history rewrite, no push, no confidential CAD, credentials, database/storage files or generated artifacts; regressions before each commit |

## 1. Audit results

| Check | Result |
|---|---|
| Confidential engineering files (STEP/DWG/STL/ASC/GLB, Sample Projects, EngValidation, storage, databases) | **None** in the working tree. `.storage*`, `.pgdata`, `.env`, `e2e/results/artifacts*` are ignored |
| Real project identifiers in text | **3 files**: `backend/tests/test_engineering_notes.py`, `web/src/test/engineering-notes.test.tsx` (real job numbers, materials, QC-report number, report file name/hash prefix) and `docs/brd-change-notes/CN-002-user-categories-registration-access.md` (mentions a real customer job number) → **sanitise before commit** (§3) |
| Credentials | No new secrets. `e2e/helpers.ts` default demo password and the DEBUG-only `insecure-development-key` fallback are **already in committed history** (unchanged; not rewritten). Docs use placeholders (`<choose a local password>`) |
| Local absolute paths / user names | None |
| Generated artifacts | 31 new and 5 modified screenshots under `e2e/results/screenshots/` → **excluded** (§4) |
| `.gitignore` change | Adds `backend/.storage-demo/`, `backend/.showcase/`, `e2e/results/artifacts-showcase/` — keep (protects showcase files) |

## 2. Proposed commit series (in this order)

Each commit is prepared in the index only after the previous one; each intermediate state is verified in a **temporary Git worktree**
(see §5). Commit messages end with the agreed attribution trailer.

### C1 — `db: non-inheriting app_worker grant for the API role` (4 files)
`.github/workflows/ci.yml`, `backend/scripts/localdb.py`, `backend/tests/test_rls_postgres.py`, `docs/web-review/db-role-rls-finding.md`

### C2 — `client portal: visual catalog (P1), service requests and notifications (CN-001), workspace scoping` (60 files)
These features import each other (quick view ↔ request dialog; layout ↔ notification bell; dashboard ↔ catalog), so separate commits would
not build. One commit, detailed message.
- Backend: `apps/servicerequests/` (8 files incl. migrations 0001–0002), `config/settings.py`, `config/api_v1.py`, `apps/tenancy/context.py`,
  `apps/accounts/authentication.py`, `apps/accounts/views.py`, `apps/parts/api.py`, `apps/tenancy/permissions.py` (**requests hunk only**)
- Backend tests: `test_service_requests.py`, `test_org_scoping.py`, `test_p1_catalog.py`, `test_auth.py`
- Web: `App.tsx`, `api/useApi.ts`, `auth/AuthContext.tsx`, `components/{Layout, NotificationBell, RequestDialog, requests, QuickView, ImagePreview,
  catalog, decision}.tsx/ts`, `components/passport/DocumentsTab.tsx`, `components/passport/OverviewTab.tsx` (**decision-label hunks only**),
  `pages/{Dashboard, Clients, Parts, PartDetail, Passports, PassportDetail, MyRequests, RequestDetail, ScanRequest, IncomingRequests,
  IncomingRequestDetail}Page.tsx`, `styles.css` (**all hunks except the D-13 block**)
- Web tests: `test/client.test.ts`, `test/requests.test.tsx`, `test/org-switch.test.tsx`, `test/p1.test.tsx`
- E2E: `e2e/helpers.ts`, `e2e/requests-workflow.spec.ts`, `e2e/p1-client-catalog.spec.ts`, `e2e/w1-passport-workspace.spec.ts`, `e2e/w2-client-portal.spec.ts`
- Docs: `docs/brd-change-notes/CN-001-client-digitisation-requests.md`, `docs/api.md`, `docs/data-model.md`, `docs/web-review/p1-visual-catalog-results.md`
- Contract: `docs/openapi.yaml`, `packages/api-types/src/schema.d.ts`, `packages/api-types/src/index.ts` — **regenerated from the C2 state**
  (without the D-13 fields)

### C3 — `showcase: synthetic demonstration dataset and demo tooling` (20 files)
`.gitignore`, `backend/apps/core/management/{__init__,commands/__init__,commands/seed_showcase}.py`, `backend/showcase/{__init__,cad,data,documents,pdf,render}.py`,
`backend/scripts/{demo_db,run_demo}.py`, `backend/tests/test_showcase.py`, `docs/{demo-showcase,demo-guide,local-setup}.md`,
`docs/demo/DEMO_PRESENTATION_GUIDE.md`, `e2e/playwright.config.ts`, `e2e/showcase/{playwright.config.ts,demo-walkthrough.spec.ts}`
(includes the one-line viewer scroll fix).

### C4 — `passports: engineering notes visible only to authorised roles (D-13)` (9 files: 4 new to this commit, 5 shared files re-staged)
`backend/apps/passports/api.py`, `backend/apps/tenancy/permissions.py` (**D-13 hunk**), `backend/tests/test_engineering_notes.py` (**sanitised**),
`web/src/components/passport/EngineeringNotesPanel.tsx`, `web/src/components/passport/OverviewTab.tsx` (**panel hunks**), `web/src/styles.css`
(**D-13 block**), `web/src/test/engineering-notes.test.tsx` (**sanitised**), `docs/openapi.yaml` + `packages/api-types/src/schema.d.ts`
(regenerated: adds `notes_restricted`, `engineering_review_pending`).

### C5 — `docs: CN-002 user categories, registration and access (proposal) and baseline manifest` (2 files)
`docs/brd-change-notes/CN-002-user-categories-registration-access.md` (**sanitised**), `docs/brd-change-notes/CN-002-baseline-manifest.md`.

Total distinct files: 4 (C1) + 60 (C2) + 20 (C3) + 4 (C4, new) + 1 (C5, CN-002) = **89**, plus this manifest.

## 3. Required sanitisation before committing (text-only edits, needs your approval)

| File | Replace | With |
|---|---|---|
| `backend/tests/test_engineering_notes.py` | real material pair, real lengths, part number `AMD-TEST/1` | `Grade A vs Grade B`, `50.0 mm vs drawing 48 mm`, `TST-0001` (assertions unchanged in meaning) |
| `web/src/test/engineering-notes.test.tsx` | real job numbers, materials, QC-report number, report file name and hash prefix | `JOB-0001 vs JOB-0002`, `Grade A vs Grade B`, `QC report QC-REF-01`, `Reports/Example_Report.pdf sha256 0000…` |
| `docs/brd-change-notes/CN-002-…md` | the real customer job number (2 places) | "real customer engineering files" |

Both test suites are re-run after sanitising.

## 4. Excluded from all commits

| Item | Reason | Proposal |
|---|---|---|
| 31 new `e2e/results/screenshots/*.png` (p1-*, req-*, showcase-*) | Generated by test runs | Leave untracked |
| 5 modified tracked `e2e/results/screenshots/w1-0*.png` | Regenerated artifacts | Leave modified, unstaged |
| Future handling | Screenshots are partly tracked from earlier commits | **Decision B3**: ignore `e2e/results/screenshots/` and stop tracking existing ones (`git rm --cached`, history unchanged) |

Outside the repository (never committed): `EngValidation\`, `Sample Projects\`, `ACL-Backups\`, `.claude\launch.json`, session scratch files.

## 5. Verification per commit

1. Build the index for the commit (whole files; partial files via filtered patches applied with `git apply --cached`).
2. Create a temporary worktree from the previous commit (`git worktree add --detach`, in the session scratch area) and apply the staged diff.
3. In the worktree: `manage.py check`; for C2/C4 regenerate `docs/openapi.yaml` (`spectacular --validate --fail-on-warn`) and
   `packages/api-types` and confirm they equal the staged files; backend pytest (PostgreSQL test database); web typecheck and Vitest.
4. Commit only if all pass; remove the worktree (`git worktree remove`).
5. After C5: full regression in the main tree (backend, web tests, typecheck, production build) and confirm the tree matches the
   pre-commit state except the excluded files. E2E specs were run on the final state earlier (passport workspace 7/7; showcase walkthrough
   blocked only by two showcase records containing real customer files, see CN-002).

## 6. Decisions needed

| ID | Decision | Recommendation |
|---|---|---|
| B1 | Local branch `baseline/2026-10-cn002-prep` from `main` (no push) | **Approved — created** |
| B2 | Git author identity | **Pending** — the configured global identity must be confirmed by the user before any commit |
| B3 | Ignore `e2e/results/screenshots/` and stop tracking the 14 tracked screenshots (`git rm --cached` in C3; files stay on disk; history unchanged) | **Approved** |
| B4 | Sanitisation edits in §3 | **Approved — applied** |
| B5 | 5-commit split (C2 as one combined portal commit) | **Approved** |
