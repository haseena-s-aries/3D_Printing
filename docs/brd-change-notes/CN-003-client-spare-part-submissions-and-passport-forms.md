# CN-003: Client spare-part submissions (FR-04 amendment) and structured passport forms

| | |
|---|---|
| **Status** | **APPROVED by the business owner, 26 Oct 2026.**<br>FR-04 amendment: approved.<br>Structured R-L1/R-L2/R-L3 forms: approved in principle.<br>Enabled **only** in the isolated access-test environment. Enabling it anywhere else waits for review of `CN-003-migration-and-regression-plan.md`. |
| **Baseline** | BRD v0.4, Requirements Register v0.4, CN-002 (approved in principle). The BRD document and the register spreadsheets are **not edited** by this note. This note and its traceability table (§6) record the approved change until the next BRD/register revision folds it in. |
| **Date** | 2026-10-26 |
| **Constraints kept** | Showcase and engineering-validation data are not reset or migrated. No production deployment, no push, no manufacturing release. OQ-35/OQ-36 gates stay closed. |

## 1. Approved decision (business owner, 26 Oct 2026; summarised)

1. **Who submits.** Client Administrators and authorised Client Users may submit new spare-part information belonging to
   their own company.
2. **Initial state.** Every client-created part starts as **Pending Aries Review**.
3. **Aries review.** Aries Engineers assigned to that client or project review the information, request corrections where
   needed, and accept it into the engineering digitisation workflow.
4. **What clients may not do.** Clients must not approve engineering specifications, replace Aries-controlled CAD master
   files, publish passports or authorise manufacturing.
5. **Passport forms.** The structured R-L1/R-L2/R-L3 form improvements are approved in principle: dropdowns, searchable
   selections, numeric/unit fields and Other / Specify.
6. **Existing data.** Existing engineering data, custom values and historical revisions are preserved.

## 2. Requirement change

### FR-04: Spare-Part Identification and Registration

| | Before (BRD v0.4) | After (CN-003) |
|---|---|---|
| **Actor** | Engineer | Aries Engineer (engineering record).<br>**Client Administrator** (company record).<br>**Authorised client user** (new-part proposal). |
| **Client entries** | Not possible | Held as **Pending Aries Review**. They enter the engineering workflow only when an assigned Aries Engineer accepts them. |
| **Unchanged** | | The system UUID is the identifier. The part number is unique per company. Numbering is open (OQ-14). |

### New requirements

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---|---|
| **FR-04a** Client submission | A Client Administrator creates a company spare-part record. An authorised client user creates a new-part proposal.<br>Fields: part number (if known), part name, equipment / machinery, manufacturer / OEM, application, material (if known), dimensions (if known), description, project (if applicable), photographs and PDF documents.<br>"Unknown / not available" is allowed where appropriate. | Must | The record belongs only to the submitter's company. It is marked Pending Aries Review, stays a draft, and has no passport, publication or manufacturing eligibility. An unknown part number gets a provisional `TBC-` number. Submission is audited and notifies the assigned engineers. |
| **FR-04b** Aries review | Assigned Aries Engineers can review, request corrections, accept into the engineering workflow (optionally linking a scanning/digitisation project), decline with a reason, and mark client values as verified. | Must | Only engineers whose company or project assignment covers the part can act. A passport draft can be created only after acceptance. Every decision records user, time and note, and is visible to the client. |
| **FR-04c** Corrections loop | The client corrects an open submission and sends it back for review. | Must | Editing is allowed only while the submission is Pending or Information requested. A Client Administrator may edit any open submission of the company; other client users only their own. |
| **FR-04d** Provenance | Each master-data value records whether the client or Aries entered it, and whether Aries verified it. Passport R-L1 values pre-filled from a client submission keep that marker. | Must | The UI distinguishes "Client-submitted · not verified", "Client-submitted · verified by Aries" and "Aries Engineering". A client change clears verification. |
| **FR-04e** Protection | Clients cannot set criticality or status, cannot edit Aries-maintained parts or reviewed submissions, and cannot replace, edit, reclassify or version Aries-controlled engineering files. Client users may attach photographs and PDFs only to their own open submissions. | Must | Refused server-side (403 or 404); covered by tests. |
| **FR-04f** Routing | Notifications go to the engineers who can review the part. If none can, the Aries Admins are told to assign one. | Should | Aries Admins cannot review (no engineering capability, CN-002). |
| **PF-01** Structured passport forms | R-L1/R-L2/R-L3 use fixed dropdowns, searchable controlled lists, multi-selects, Yes/No/Not applicable, numeric values with units and file selectors, each with Other / Specify where a list may be incomplete. | Must (approved in principle) | No field is removed. Stored values are not converted; non-matching values open as "Custom value". Drafts can be saved incomplete. Completeness and the approval/eligibility gates are unchanged. |
| **PF-02** Controlled lists | Lists are served by `GET /api/v1/passport-field-options/` and marked provisional. | Should | Provisional until the authoritative master list is decided (OQ-16). No AMSL or mandatory-standard rules are invented (OQ-36, OQ-21). |
| **PF-03** New optional fields | `rl1.operating_environment`, `rl2.manufacturing_process`, `rl1.value_sources` | Could | Optional. Not counted in completeness. Existing content is unaffected. |

## 3. What does not change

- BR-006/007/008 required fields and completeness rules.
- Evidence levels, QA verification, passport approval and publication (OQ-35, closed).
- Manufacturing eligibility and release (OQ-36, closed).
- CN-002 role and permission matrix, except for the two new capabilities in §4.
- Tenant isolation (row-level security) and project scoping (CN-002 D4).
- Existing parts: they keep `origin = aries` and `review_state = not_required`, and behave exactly as before.

## 4. Implementation summary (all uncommitted)

| Area | Change |
|---|---|
| **Capabilities** | `parts.submit` (Client Admin, Client Engineer, Client User).<br>`parts.review` (Aries Engineer).<br>Both granted only when `CLIENT_PART_SUBMISSIONS_ENABLED=true` (default **false**). |
| **Database** | `parts.0003_client_submissions`: additive columns on `parts_sparepart`. No data rewrite. Row-level security already applies to the table. |
| **API** | `POST /parts/` and `PATCH /parts/{id}/` (client path).<br>`POST /parts/{id}/review/` (`request_info`, `accept`, `decline`, `verify`).<br>`POST /parts/{id}/resubmit/`.<br>`?review_state=open` and `?origin=` filters.<br>`GET /passport-field-options/`. |
| **Passport create** | Refused with `part_not_accepted` while a submission is open or declined. |
| **Web** | `/parts/submit` page; review panel, resubmit form and provenance tags on the part page; Pending Aries review queue in the inventory; structured R-L1/R-L2/R-L3 controls. |
| **Access-test environment** | Feature enabled; migration applied to `passport_access` only. |

## 5. Open items

| ID | Item | Proposed default |
|---|---|---|
| C3-1 | **"Authorised Client Users."** Today every Client User and Client Engineer of the company can propose a part (role-based). Should only users the Client Administrator authorises be able to, through a per-user permission? | Decide before production. A per-user flag would need a small additive migration. |
| C3-2 | Client Engineers create *proposals*, not company records | Keep, unless the business wants them treated like Client Administrators |
| C3-3 | Provisional `TBC-YYMM-XXXXXX` numbers for unknown part numbers | Keep until OQ-14 is decided |
| C3-4 | After acceptance, clients can no longer edit their submission. The meeting of 26 Oct suggested clients keep editing the parts they create. | Keep locked (engineering integrity). Corrections go through an enquiry, or later through an edit-request flow. **Confirm.** |
| C3-5 | Authoritative material, machine and process master list, and who maintains it (OQ-16) | Use provisional lists; load the business-supplied grade list when received |
| C3-6 | Operating-temperature field (not in BRD) | Not added; needs its own change |
| C3-7 | Submissions with no project reach only company-wide engineers (CN-002 U4) | Keep, with the Aries Admin alert |

## 6. Traceability

| Requirement | BRD / CN reference | Code | Tests (executed 26 Oct 2026, all passing) |
|---|---|---|---|
| FR-04 (amended) | BRD v0.4 FR-04, BR-001; CN-002 D1, D2 | `backend/apps/parts/models.py` (origin, review_state, submission fields)<br>`backend/apps/tenancy/permissions.py` (`parts.submit`, `parts.review`, feature switch)<br>`backend/config/settings.py` (`CLIENT_PART_SUBMISSIONS_ENABLED`) | `test_disabled_by_default` |
| FR-04a | FR-04; OQ-14 | `backend/apps/parts/api.py` `perform_create`, serializer `validate`<br>`backend/apps/parts/submissions.py` `provisional_number`, `stamp`<br>`web/src/components/PartSubmission.tsx` `SubmissionForm`<br>`web/src/pages/PartSubmissionPage.tsx` | `test_client_admin_creates_a_pending_company_record`<br>`test_client_users_create_proposals_and_part_number_is_required_unless_unknown` |
| FR-04b | FR-03 (projects); CN-002 D4 | `submissions.py` `request_info`, `accept`, `decline`, `verify_fields`<br>`api.py` `review`<br>`passports/api.py` (`part_not_accepted`)<br>`PartSubmission.tsx` `ReviewPanel` | `test_review_workflow_request_info_resubmit_accept_and_passport`<br>`test_decline_and_aries_edits_mark_values_as_aries`<br>`test_engineers_review_only_authorised_clients_and_projects` |
| FR-04c | — | `submissions.py` `check_client_may_edit`, `resubmit`<br>`api.py` `perform_update`, `resubmit`<br>`ResubmitForm` | `test_clients_cannot_edit_aries_records_or_reviewed_submissions`<br>`test_review_workflow_…` |
| FR-04d | BR-009 (provenance of material) | `submissions.py` `stamp`, `verify`<br>`Provenance` component<br>`passports/content.py` `value_sources`<br>`ReadinessForms.tsx` `prefillSources` | `test_review_workflow_…`<br>web `passport-controls.test.ts` (R-L1 pre-fill provenance) |
| FR-04e | CN-002 D1; BR-036 | `api.py` serializer `validate` (criticality/status)<br>`files/api.py` `_check_own_submission`, `_check_client_supplied` | `test_clients_cannot_set_aries_classifications`<br>`test_client_a_cannot_create_or_modify_client_b_parts`<br>`test_submission_files_are_limited_and_aries_masters_stay_protected` |
| FR-04f | BR-053; CN-002 U4 | `submissions.py` `reviewers`, `notify_reviewers`, `notify` | `test_aries_admins_are_told_when_no_engineer_can_review`<br>`test_client_admin_creates_a_pending_company_record` |
| PF-01 | BR-006, BR-007, BR-008, BR-009, BR-026, BR-041 | `web/src/components/passport/controls.tsx`<br>`ReadinessForms.tsx`<br>mapping: `docs/passport-field-control-mapping.md` | `test_controlled_custom_and_unit_values_round_trip_and_history_is_kept`<br>web `passport-controls.test.ts` (13 tests)<br>access-test end-to-end `flow-submissions.mjs` (33/33) |
| PF-02 | OQ-16, OQ-21, OQ-36 | `backend/apps/passports/options.py`; `PassportFieldOptionsView` | `test_field_options_are_provisional_and_readable_by_all_roles` |
| PF-03 | — | `backend/apps/passports/content.py` | `test_controlled_custom_and_unit_values_…` |
| Gates unchanged | OQ-35, OQ-36 | none changed | `test_review_workflow_…` (accepted part has no eligibility or publication); existing gate tests in the full suite |

**Last executed results (26 Oct 2026)**
- Backend: 229 passed.
- Web: typecheck passed, 65 unit tests passed, production build succeeded.
- OpenAPI contract: valid.
- Access-test end-to-end: `flow-submissions.mjs` 33/33; CN-002 `flow.mjs` 24/24.
- Repository Playwright specs `e2e/w1-passport-workspace.spec.ts` and `e2e/portal.spec.ts` were updated for the new
  controls but **not yet executed** (see the migration and regression plan).

## 7. Addendum (26 Oct 2026): Client Clone Part (BR-033), approved for implementation

**Scope approved by the business owner.**
- Clients clone an accepted part of their own organisation into a **new, separate spare part** permanently linked to the
  original. The usual purpose is to propose a new material.
- A mandatory reason is required for any material change.
- The clone is Pending Aries review, with the same review actions as above: request corrections, accept for engineering
  work, reject with reason.
- Acceptance enters the engineering workflow; it does **not** approve manufacturing.

**Resolves C3-1:** ordinary Client Users submit or clone only when the Client Administrator grants
`part_submission_allowed` on their membership. Client Administrators and Client Engineers are authorised by role.

| ID | Requirement | Code | Tests |
|---|---|---|---|
| CL-01 Clone action | **Clone part** on the inventory card, Quick View and Part Details, for `parts.submit` holders, on parts that are Aries-maintained or accepted | `web/src/pages/PartClonePage.tsx` (`canClone`)<br>`components/catalog.tsx`<br>`components/QuickView.tsx`<br>`pages/PartDetailPage.tsx` | web `part-clone.test.ts`<br>browser `flow-clone.mjs` |
| CL-02 Clone form | Shows the original part; prefills the clone; new unique number; proposed material and reason; editable descriptive fields; remarks; live comparison | `PartClonePage.tsx` | browser `flow-clone.mjs` |
| CL-03 Identity and lineage | New record with `source_part`, `source_part_number`, `source_passport_number`, `source_revision_number`, `source_snapshot`, `proposed_material`, `material_change_reason`, `client_remarks`, `submission_kind=clone`. Lineage is immutable: a database trigger enforces it. | `backend/apps/parts/models.py`<br>migrations `0004_clone_lineage`, `0005_clone_security`<br>`submissions.clone` | `test_client_clones_an_aries_scanned_part`<br>`test_lineage_cannot_be_changed_even_in_the_database` |
| CL-04 Nothing implying approval is inherited | No passport, files, evidence, publication or eligibility. Criticality is reset to "Not assessed". Inherited values are tagged as references. The source passport is not copied. | `submissions.clone` | `test_client_clones_an_aries_scanned_part`<br>`test_review_corrections_accept_and_gates_stay_closed` |
| CL-05 Source unchanged | The original part, its files and its passport are not modified | `submissions.clone` (writes only the new row) | `test_client_clones_an_aries_scanned_part`<br>`test_clients_still_cannot_touch_source_cad` |
| CL-06 Permissions | Client Administrator and Client Engineer by role; Client User only with permission; no cross-company cloning; Aries staff do not use the client clone path | `apps/tenancy/permissions.py`<br>`Membership.part_submission_allowed` (migration `tenancy.0003`)<br>Users page toggle | `test_who_may_clone`<br>`test_cross_client_clone_is_denied` |
| CL-07 Review | Assigned engineers are notified; the review screen shows the comparison, material change, reason, source CAD and passport references and remarks; request corrections, accept or reject; audit event `spare_part.cloned` plus the review events | `submissions.notify_reviewers`<br>`components/PartLineage.tsx`<br>`ReviewPanel` | `test_review_corrections_accept_and_gates_stay_closed`<br>`test_reject_with_reason`<br>`test_project_restricted_engineer` |
| CL-08 Client visibility | Original and clone linked both ways; Pending status; review history and comments (`SparePartReviewEvent`: append-only, row-level security); searchable; not in the Published catalog | `GET /parts/{id}/history/`<br>`?source_part=` filter | `test_client_clones_an_aries_scanned_part` |
| CL-09 Integrity | Atomic creation; case-insensitive unique number; database unique constraint | `submissions.clone` | `test_part_number_must_be_new_and_reason_is_mandatory`<br>`test_duplicate_number_race_is_atomic` |
| CL-10 Passport pre-fill | When a passport draft is created for an accepted clone, R-L1 is prefilled. The proposed material and reason are marked client-submitted; inherited values are marked "inherited reference". | `ReadinessForms.tsx` (`rl1Prefill`, `prefillSources`)<br>`content.py` `value_sources` | web `part-clone.test.ts`<br>browser `flow-clone.mjs` |

**Results (26 Oct 2026)**
- Backend: 241 passed.
- Web: 67 passed, plus typecheck and build.
- Browser: clone flow 37/37, submission flow 33/33, CN-002 flow 24/24.

## 8. Addendum (26 Oct 2026): structured part forms and material change in the manufacturing enquiry

| ID | Requirement | Code | Tests |
|---|---|---|---|
| PF-04 Structured part form | New Part, Edit Part, client submission and Clone Part use one control set (`PartFieldInput`):<br>- material, application and OEM: searchable lists (provisional master data plus the company's own values) with Other;<br>- equipment: the company's recorded equipment plus free entry;<br>- dimensions: L×W×H or Ø×H with unit, legacy text kept as a Custom value;<br>- category and criticality: existing choices only;<br>- project: the company's projects only.<br>The passport R-L1 uses the same size and material controls. | `web/src/components/PartFieldInput.tsx`<br>`PartForm.tsx`<br>`PartSubmission.tsx`<br>`PartClonePage.tsx`<br>`GET /parts/field-values/` (tenant- and project-scoped)<br>`options.py` `manufacturers` (provisional) | `test_field_values_are_company_and_project_scoped`<br>`test_custom_dimension_text_and_other_values_are_preserved`<br>web `part-clone.test.ts`<br>browser `flow-forms-material.mjs` |
| MC-01 Material option on the manufacturing enquiry | Manufacture in the original material, or propose a different one with a mandatory reason. Supporting documents are attached to the request. | `servicerequests` migration `0003_material_change`<br>`ManufacturingInput`<br>`services.material_change`<br>`RequestDialog.tsx` | `test_original_material_request_is_unchanged`<br>`test_material_change_validation` |
| MC-02 Lineage | A proposal links to a clone of the part (a new clone created atomically, or an existing clone). Requesters without part-submission permission record the proposal only. The original part and passport are never changed. | `services.material_change` → `submissions.clone` | `test_proposed_material_creates_a_linked_clone_and_stays_an_enquiry`<br>`test_link_existing_clone_and_cross_company_denied`<br>`test_requesters_without_part_permission_record_the_proposal_only` |
| MC-03 Gates | A material change is always an **enquiry**, even for a published and eligible part. Suitability is "not yet assessed", and the clone carries no eligibility or publication. | `api.create` (forces enquiry) | `test_material_change_never_creates_a_manufacturing_request` |

The job-sheet design is in `CN-004-manufacturing-job-sheet-proposal.md`; it is a proposal only and not implemented.


## 9. Addendum (26 Oct 2026): inventory stages and role-specific labels (accepted)

Stages are derived on the server from two separate stored dimensions: the part's `review_state` and the passport's
`publication_state`. No stage filter, tab or count writes either field.

| Stage (`catalog=`) | Rule | Aries Engineer | Client | Aries Admin |
|---|---|---|---|---|
| `review` | `review_state` in pending_review, info_requested | Awaiting Review | Submitted for Review | Review Backlog |
| `in_digitisation` | not published, and `review_state` in not_required, accepted | In Digitisation | Being Digitised | Digitisation Progress |
| `published` | passport `publication_state = published` | Published | Published | Published |
| `declined` | `review_state = declined` (listed under All only) | none | none | none |
| `all` / none | every authorised record | All parts | All parts | All parts |

| ID | Requirement | Code | Tests |
|---|---|---|---|
| ST-01 Derived stages | `stage_q()`; list filter `catalog=`; `GET /parts/stage-counts/` (same filters, access scope) | `backend/apps/parts/api.py` | `tests/test_inventory_stages.py::test_stages_are_derived_and_separate`, `::test_counts_respect_tenant_and_project_scope` |
| ST-02 Role labels and descriptions | `web/src/components/inventoryStages.ts`; `PartsPage.tsx`; `AdminInventoryPage.tsx` | `web/src/test/access.test.ts` (labels); browser `flow-inventory.mjs` (labels, counts equal server counts, filtering) |
