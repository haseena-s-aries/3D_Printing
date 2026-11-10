# CN-004: Manufacturing job sheet, draft specification (PROPOSAL, for approval)

| | |
|---|---|
| **Status** | **J1–J8 APPROVED with amendments (26 Oct 2026).** The draft-only module is implemented in the isolated access-test environment; see §8. Sections 1–7 keep the original proposal for reference. |
| **Date** | 2026-10-26 |
| **Baseline** | BRD v0.4, CN-002, CN-003 (client submissions, Clone Part, material-change enquiry) |
| **Why a proposal only** | Job-number generation, job-sheet ownership, the manufacturing-method list and the approval/issue criteria are **not decided** in BRD v0.4 (OQ-14, OQ-36, OQ-40, PUB-004, CN-002 U2). Implementing them would invent business rules. |
| **Never activated by this note** | Production orders, manufacturing release, manufacturing eligibility, QA verification |

## 1. Sources reviewed

| Source | What it says |
|---|---|
| BR-025 (CONFIRMED) | The design specification (drawing) is separate from the manufacturing/printing specification (process, heat treatment, materials, tests) |
| BR-026 (CONFIRMED) | The manufacturing specification includes: job number, material, feedstock, machine, layer thickness, support strategy, build orientation, inert gas, heat treatment, post-processing, machining, printing hours, post-processing hours |
| BR-041 (CONFIRMED) | AM process parameters are documented on the passport |
| FR-08 (CONFIRMED) | Manufacturing and test specifications. Owner: manufacturing engineer and QA. Trigger: "Specification issued". Client variants versioned (OQ-40). |
| FR-13 (PROPOSED, manual) | Manufacturing order and production tracking. Trigger: "Order authorised". |
| FR-14 / BR-050 (PROPOSED) | QA and traceability: inspection documents, certificates, batch/serial links |
| PUB-004 / OQ-36 (open) | Each order needs engineering and QA confirmation before production release |
| OQ-14 (open) | Numbering schemes |
| OQ-40 (open) | Client-specific print specification variants and their approval |
| Meeting `3d pr.mp3` | Manual form with job number, company details, standards, vertical/horizontal tensile, NDT test samples, manufacturing process (01:19–02:09). The sheet is always prepared, "as a record with our job number" (04:26–04:37). For a material change, the process stays standard and small values such as printing hours change (08:27–09:09). |
| Current application | Passport R-L2 already holds the BR-026 manufacturing specification (`content.rl2.manufacturing_spec`, including `job_number`), BR-041 process parameters, mechanical acceptance, NDT, ITP, MTC and test coupons, all per passport revision. Manufacturing enquiries record part, passport revision and (CN-003) original and proposed material with a linked clone. |

**Key observation:** BR-026 puts the job number inside the manufacturing specification, but a job number belongs to one
job, while a passport revision describes the part. The proposal separates the two:
- The **passport R-L2 specification** is the approved template for the part revision.
- A **job sheet** is the per-job instance, created from a manufacturing enquiry, that copies the template, records
  deviations (such as a proposed material) and carries the job reference.

**Decision J5 confirms or rejects this split.**

## 2. Proposed workflow (draft only; every "issue/release" step stays disabled)

```text
Manufacturing enquiry (ClientRequest, kind = enquiry)
   │ Aries Engineer: "Prepare job sheet draft"   [capability: jobsheets.prepare (J2)]
   ▼
Job sheet DRAFT (rev 1)
   │  prefilled from: part + passport revision cited by the enquiry (R-L2 spec, process parameters, quality)
   │  material: original from the part; proposed from the enquiry/clone (flagged "suitability not assessed")
   │  job reference: provisional "JS-DRAFT-…" until J1 is decided
   │  edits create revisions; every change is audited
   ▼
"Submit for engineering/QA review"   ── disabled until J4 / OQ-36 decided
"Issue job sheet" / "Release to production" ── disabled (OQ-36, PUB-004)
```

**Material change.** A job sheet for a proposed material is created against the **cloned part** (BR-033 lineage), never
the original. Its source passport revision is shown as a reference. Material-dependent fields (feedstock, heat treatment,
process parameters, printing hours) are marked "to be re-specified" rather than copied as approved values.

## 3. Proposed data model (draft schema, not migrated)

### `manufacturing_jobsheet`

Tenant-owned; forced row-level security; project-scoped like parts.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `tenant_id` | FK tenant | client company |
| `enquiry_id` | FK `servicerequests_clientrequest` | required: the job sheet always starts from an enquiry |
| `part_id` | FK `parts_sparepart` | the part being made (the clone when the material changes) |
| `source_part_id` | FK `parts_sparepart`, null | the original part when `part` is a clone |
| `passport_id`, `passport_revision_number` | FK, int | the revision the specification is based on (frozen at creation) |
| `job_reference` | text, unique per tenant | provisional `JS-DRAFT-YYYY-NNNNN` until **J1** |
| `status` | enum | `draft`, `in_review` (gated), `issued` (gated), `superseded`, `cancelled`. Only `draft` and `cancelled` are reachable until J4. |
| `original_material`, `proposed_material` | text | `proposed_material` comes from the enquiry/clone |
| `material_suitability` | enum | `not_assessed` (default), `assessed_suitable`, `assessed_unsuitable`; who may set it depends on **J4** |
| `manufacturing_method` | text | from a controlled list after **J3**; until then the provisional list `manufacturing_processes` plus Other |
| `owner_id` | FK user | **J2** |
| `created_by`, `created_at`, `updated_at` | | |

### `manufacturing_jobsheetrevision`

Append-only; immutable once superseded, like passport revisions.

| Column | Notes |
|---|---|
| `jobsheet_id`, `revision_number` | revision 1 created with the draft |
| `content` (JSON) | Mirrors the passport serializers so the same validation and structured controls are reused:<br>`spec` = BR-026 fields (`ManufacturingSpecSerializer`)<br>`process_parameters` = BR-041 rows<br>`quality` = mechanical acceptance rows, NDT, ITP reference, test coupons, MTC required, dimensional tolerances, applicable standards<br>`deviations` = changes against the passport template, with reason<br>`notes` |
| `prefill_sources` (JSON) | per field: `passport_rev_N` / `enquiry` / `clone_proposal` / `entered`, for provenance display |
| `documents` (JSON) | references to existing `EngineeringFile` ids (drawings, ITP, MTS, certificates); **no file copies** |
| `change_summary`, `created_by`, `created_at` | |

### Audit events

`jobsheet.created`, `jobsheet.revision_saved`, `jobsheet.cancelled`; later `jobsheet.submitted` and `jobsheet.issued`,
which stay gated.

## 4. UI proposal

| Where | What |
|---|---|
| Aries: Incoming request (manufacturing enquiry) | Button **Prepare job sheet draft** (assigned engineers only), then the job-sheet editor |
| Job-sheet editor | Header: job reference (provisional), enquiry reference, part and source part, passport revision, original → proposed material with a suitability badge.<br>Tabs: **Specification** (BR-026; same structured controls as R-L2), **Process parameters** (BR-041), **Quality and inspection** (acceptance table, NDT multi-select, ITP/MTC/test coupons, standards), **Documents** (selectors over existing files), **Revisions and audit**.<br>"Differs from passport rev N" markers on every changed field. |
| Gated actions | **Submit for review**, **Issue** and **Release to production** are shown disabled, citing OQ-36 / PUB-004 |
| Client | Nothing by default (internal record). Client visibility is decision **J6**. |

## 5. Decisions required before implementation

| # | Decision | Options | Proposed default |
|---|---|---|---|
| **J1** | Job-number format and generation; who assigns it (OQ-14) | A) system sequence per year (`JS-2026-00001`); B) entered manually from the existing Aries job system; C) both (manual, validated as unique) | **C.** The meeting describes Aries' own job numbers. |
| **J2** | Ownership: who prepares, reviews and issues (FR-08: manufacturing engineer and QA; CN-002 U2) | Aries Engineer prepares; Aries QA reviews; issue role to be defined | Prepare: Aries Engineer. Review and issue: undecided. |
| **J3** | Authoritative manufacturing-method list | Provisional `manufacturing_processes` list, or a list supplied by Aries | The Aries-supplied list (OQ-16) |
| **J4** | Review and issue criteria, and who may mark material suitability | Linked to OQ-36 / PUB-004 | Keep gated |
| **J5** | Relationship to the passport R-L2 specification | A) passport = template, job sheet = per-job instance (this proposal); B) job sheet = the passport spec itself | **A** |
| **J6** | Client visibility of job sheets | none / summary / full | none (internal) |
| **J7** | Client-specific variants (OQ-40) | | deferred |
| **J8** | Production traceability (batch, serial, operator, machine; BR-050) | | later; can reference the job reference |

## 6. Implementation estimate (after approval)

- Migration: 2 tables with row-level security and an immutability trigger.
- API: create from enquiry, get/patch draft, revisions list, cancel.
- Web: editor reusing `controls.tsx`/`ReadinessForms` components.
- Tests: tenant/project isolation, prefill without mutating the passport, gates disabled, revision immutability.

No existing data changes.

## 7. Decision table for approval (rev 2, 26 Oct 2026)

Basis: BRD v0.4 (BR-025, BR-026, BR-041, FR-08, FR-13, FR-14, PUB-004, OQ-14, OQ-16, OQ-36, OQ-40, BR-050) and the meeting
recording `3d pr.mp3` (timestamps mm:ss). Recommendations are the author's; nothing is implemented.

| # | Proposed rule | Alternatives | Recommendation and why | Operator / Client portal | Engineering / QA / manufacturing approvals | Unresolved dependency |
|---|---|---|---|---|---|---|
| J1 Job number | The Aries job number is entered by the Aries Engineer and validated as unique per Aries. Until entered, the draft carries a provisional `JS-DRAFT-YYYY-NNNNN`. | A) system sequence `JS-YYYY-NNNNN`<br>B) manual only<br>C) manual with validation, plus provisional draft ref (proposed) | **C.** The meeting speaks of "our job number" kept as a record (04:26–04:37); BR-026 lists it as spec content. Aries likely has existing job numbers. | Operator: job-number field on the job sheet, uniqueness check.<br>Client: none. | None. Numbering grants nothing. | Format, and whether it comes from Aries' ERP or job system (OQ-14) |
| J2 Ownership | Aries Engineer (assigned to the client/project) prepares and revises. Aries QA reviews. Issue/release role kept unassigned. | A) engineer prepares and issues<br>B) manufacturing engineer prepares, QA issues<br>C) as proposed | **C.** FR-08 names manufacturing engineer and QA. The QA capability set is still open (CN-002 U2). | Operator: Prepare button for assigned engineers; QA review queue later.<br>Client: none. | Separation of duties: preparer ≠ QA reviewer (CN-002 D9). | QA/manufacturing role definitions (CN-002 U2) |
| J3 Manufacturing method | Method chosen from an Aries-supplied controlled list with Other; until supplied, the provisional `manufacturing_processes` list, flagged provisional. | A) free text<br>B) provisional list (now)<br>C) Aries-supplied list | **C, using B meanwhile.** The meeting says Aries defines the process (08:01–08:10) and it "will be standard" (08:27–09:09); OQ-16 is open. | Operator: dropdown with Other.<br>Client: none. | None. The method is data, not approval. | Aries master list of methods and materials (OQ-16) |
| J4 Review and issue criteria | Draft only. "Submit for QA review", "Issue" and "Release to production" stay disabled. Material suitability stays "not assessed" until criteria exist. | A) keep gated (proposed)<br>B) define criteria now | **A.** PUB-004 and OQ-36 require per-order engineering and QA confirmation, whose rules are not decided. Inventing them is not allowed. | Operator: disabled buttons that cite OQ-36.<br>Client: none. | All approval and release gates unchanged and closed. | OQ-35, OQ-36, PUB-004 decision |
| J5 Relationship to the passport | The passport R-L2 manufacturing specification is the template for a part revision. The job sheet is a per-job copy that records deviations (e.g. proposed material, printing hours). | A) template/instance split (proposed)<br>B) the job sheet is the passport spec | **A.** BR-026 puts a job number in the spec, but a passport revision serves many jobs. The meeting: process standard, small per-job changes (08:43–09:09). | Operator: job sheet prefilled from passport rev N, with "differs from rev N" markers.<br>Client: none. | The passport and its approvals are untouched; job deviations never change the passport. | Confirm that passport R-L2 stays the approved template |
| J6 Client visibility | Job sheets are internal Aries records; the client sees only enquiry status. | A) none (proposed)<br>B) summary (method, material, status)<br>C) full sheet | **A for now.** The meeting wants client-shareable reports (09:49–13:33), but that is the passport report, a separate topic, and third-party sharing has IP/download issues (OQ-33). | Operator: internal only.<br>Client: no change. | None. | Client report/export decision; IP policy (OQ-33, OQ-38) |
| J7 Client variants | One job sheet per job, based on one passport revision. Client-specific variants of the specification are not modelled. | A) defer (proposed)<br>B) versioned variants per client | **A.** OQ-40 is open; the default "versioned variants approved per client" needs approval rules. | No change. | None. | OQ-40 |
| J8 Production traceability | Not in this scope. A later production record (batch, serial, machine, operator, inspection) references the job number. | A) defer (proposed)<br>B) include now | **A.** BR-050 and FR-14 are PROPOSED; FR-13 is "manual milestones in MVP". | No change. | No release exists, so there is nothing to trace yet. | BR-050 / FR-13 / FR-14 approval |

### Identifiers

| Identifier | Example | Scope | Created by | Meaning |
|---|---|---|---|---|
| Manufacturing enquiry reference | `MR-2026-00012` | per client company | system, at enquiry submission (exists today) | The client's request: quantity, date, material choice |
| Manufacturing job number | e.g. `J-2026-0457` (format J1) | per Aries | Aries Engineer (J1) | One manufacturing job; Aries' internal record |
| Digital passport number and revision | `DP-2026-00004` rev 2 | per part | system (exists today) | The part and its approved specification template |
| Job-sheet revision | job sheet rev 1, 2, … | per job | each saved change (proposed) | Change history of the job's specification and deviations |

One enquiry leads to at most one job (J5). One job cites one passport revision. A job sheet has many revisions.


## 8. Approved decisions and implementation (26 Oct 2026)

### Decisions as approved

| # | Approved rule |
|---|---|
| J1 | Manual Aries job-number entry with a uniqueness check, plus a provisional `JS-DRAFT-YYYY-NNNNN` reference. No ERP integration and no final format assumed. |
| J2 | Aries Engineers prepare and revise. QA review is a separate restricted capability. A preparer may not approve their own job sheet. |
| J3 | Controlled manufacturing-method selection from the provisional list, with Other / Specify until Aries supplies the official list |
| J4 | Draft only. QA submission, issue and production release stay disabled. |
| J5 | Per-job specification linked to one immutable passport revision. Deviations are shown. For a material change, dependent parameters are marked for engineering revalidation. |
| J6 | *(amended)* Clients see a non-confidential progress summary on their enquiry only. They never see the job sheet, process parameters or internal notes. |
| J7 | Client-specific variants deferred |
| J8 | *(amended)* Foundation only: links between enquiry, Aries job reference, passport revision and job-sheet revisions. Batches, serials, machine logs, inspection execution and delivery are deferred. |

### Implementation

| Area | What exists |
|---|---|
| Data | App `apps.jobsheets`:<br>- `JobSheet`: one per enquiry; part (the clone for a material change); source part; passport, revision number and status; frozen R-L2 template; draft reference; job reference (unique index across all tenants); status; method; original and proposed material<br>- `JobSheetRevision`: append-only (immutability trigger); content, per-field sources, change summary, author, timestamp<br>- `ClientRequest.job_progress`: the client-visible summary |
| Confidentiality (J6) | - Tenant row-level security on both tables.<br>- An additional **restrictive** policy: rows are visible only while the job-sheet service has set `app.jobsheet_access` for authorised Aries staff. Client-facing queries cannot read them, even inside the client's tenant.<br>- Detailed audit events (`jobsheet.created`, `revision_saved`, `cancelled`) go to the **Aries** audit trail. The client audit trail receives no job number, draft reference or specification content. |
| API | All under `/api/v1/operator/requests/{envelope}/jobsheet/`:<br>- `GET` read, `POST` prepare, `PATCH` save new revision<br>- `revisions/{n}/`<br>- `cancel/`<br>- `submit/`, `issue/`, `release/`: always **409 `policy_not_configured`** (OQ-36)<br>Inherits client assignment and project scope from the intake API. |
| Capabilities | `jobsheets.view` (Aries Engineer, Aries QA); `jobsheets.prepare` (Aries Engineer); `jobsheets.qa_review` (Aries QA; no usable action while J4 is gated). Aries Admin has none. |
| Prefill sources | `verified` (approved passport revision; none exist yet); `proposed` (passport draft, not approved); `missing`; `client_proposal` (proposed material); `revalidate` (material-dependent after a material change); `entered` (changed on the job sheet). |
| Web | Aries incoming request shows **Manufacturing job sheet (draft · Aries internal)**:<br>- prepare form<br>- identity block (enquiry, Aries job number or provisional reference, job-sheet revision, part/clone, passport basis, material)<br>- structured specification, process parameters, quality and inspection, internal notes<br>- deviations table with reasons<br>- revision list with read-only view of older revisions<br>- disabled QA, issue and release buttons<br>- cancel with reason<br>The client request page shows only "Manufacturing preparation" progress and a timeline entry. |
| Migrations | `servicerequests.0004_job_progress`; `jobsheets.0001_initial`; `jobsheets.0002_security`. Applied to `passport_access` only. |
| Tests (26 Oct 2026) | - Backend: 256 passed, including 7 in `tests/test_jobsheets.py`.<br>- Web: 71 passed, including `jobsheet.test.tsx`.<br>- Browser: `flow-jobsheet.mjs` 32/32.<br>- Regressions: forms 28/28, clone 37/37, submissions 33/33, CN-002 24/24. |
