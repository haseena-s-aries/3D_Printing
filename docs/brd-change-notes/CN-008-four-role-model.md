# CN-008 — Four core roles with QA and feature permissions

| | |
|---|---|
| Status | **Business decision confirmed (30 Oct 2026). Implemented in the isolated access-test environment only**, behind `FOUR_ROLE_MODEL_ENABLED` (off by default). Existing access-test memberships were **mapped on 30 Oct 2026** after a zero-difference dry run (53 memberships, 35 accounts). Showcase and engineering-validation are unchanged. Nothing is deployed. |
| Supersedes | CN-002 decision D5 ("keep Aries QA and Aries Support as internal sub-roles") and the provisional QA / Support columns of the CN-002 role matrix. Needs a change-control entry against CN-002 before any shared environment. |
| Detail | `AccessTest/FOUR-ROLE-MODEL.md` (audit, mapping, risks, test results) |

## 1. Roles

| Role | Organisation | Summary |
|---|---|---|
| **Aries Admin** | Aries | Platform administration; assigns staff and permissions; never an engineering sign-off (unchanged) |
| **Aries Engineer** | Aries, assigned to client companies and projects | Engineering work in assigned scope; QA and review duties only through the permissions below |
| **Client Admin** | Client company | Company administration, users and feature permissions, company decisions (data sharing, AI members) |
| **Client User** | Client company | Base read access plus feature permissions given by the Client Admin |

Legacy stored values (`operator_qa`, `operator_support`, `client_engineer`, `procurement`, `auditor`) are kept in the code and
database. Memberships that hold them keep exactly their current rights until mapped (§4); they are never assigned again
(new assignments, role changes and invitations offer only the four roles) and are shown as "(legacy)".

## 2. Aries Engineer permissions (granted by the Aries Admin)

| Permission | Where it is set | Allows | Never allows |
|---|---|---|---|
| **CanAuthorEngineering** (`engineering_authoring`, default on) | per client company: Engineers & Access; Aries organisation: Users | Engineering work: projects, parts and submission review, passport drafts, engineering files and origin claims, report generation, edit requests, job-sheet drafts, imports, Part Intelligence, client AI sharing; receiving submission notifications | QA verification; contract review |
| **CanPerformQA** (`qa_permitted`) | per client company: Clients → company → Engineers & Access; in the Aries organisation: Users | Photo-origin confirm / reject / withdraw and the QA queue, within the engineer's project scope; job-sheet QA review from the Aries intake queue (closed until OQ-36) | Confirming a claim the engineer made or a photo they uploaded; contract verification; objection review |
| **CanReviewEngineering** (`edit_reviewer`, CN-006) | per client company: Engineers & Access | Deciding edit requests in that company | Deciding the engineer's own request; passport approval (OQ-35) |
| **CanReviewContract** (`contract_reviewer`) | Aries organisation: Users | Thumbnail contract list; verifying or ending an authorization someone else recorded | Objection review, which additionally needs the deployment-designated authority (`CONTRACT_OBJECTION_REVIEWERS` + `CONTRACT_OBJECTION_AUTHORITY`) and independence from the recorder, verifiers, claimants and uploaders |

Rules: only an Aries Admin acting from the Aries organisation grants or revokes; never on their own account; only for Aries
Engineers. Each change is audited (`membership.permissions_changed` in the company and Aries trails for company permissions,
`membership.updated` with before / after for the rest) and the engineer is notified. Rights are recomputed on every request,
so a revocation applies immediately. History records the role at the time; an engineer acting under a permission is recorded
as "Aries Engineer (QA)" or "Aries Engineer (contract reviewer)".

## 3. Client User feature permissions (granted by the Client Admin or the Aries Admin)

| Feature | Field | Allows |
|---|---|---|
| Submit and clone spare parts | `part_submission_allowed` (CN-003) | Part submissions, clones, edit requests (always Pending Aries review) |
| Technical submissions | `technical_access` | Supporting documents and photos, engineering notes, manufacturing / scanning requests, AI analysis requests and reports; AI workspace member access by default |
| Procurement | `procurement_access` | Manufacturing / scanning requests, AI price comparisons, AI reports |
| Read-only audit | `audit_access` | Company audit trail, engineering notes (read only) |
| Document access | `document_access`: none / preview (default) / full | Preview: 3D views and report previews. Full: also original downloads and client report generation and download |

Nobody changes their own features. Client Admins have every client feature by role. AI features still need the company's AI
workspace to be switched on and the Client Admin's member access.

## 4. Mapping of existing memberships

`manage.py four_role_mapping` (dry run by default; `--apply --confirm` to change in place, keeping membership id, user id,
project scope and all history; audited as `membership.role_mapped`).

| Existing | Becomes | Permissions |
|---|---|---|
| Aries QA in a client company | Aries Engineer | CanPerformQA on, CanAuthorEngineering off |
| Aries QA in the Aries organisation | Aries Engineer | CanPerformQA, CanReviewContract on; CanAuthorEngineering off |
| Client Engineer | Client User | Submit and clone parts, Technical submissions, Document access = full |
| Procurement | Client User | Procurement, Document access = none |
| Auditor | Client User | Read-only audit, Document access = none |
| Aries Support | not mapped | decision needed (no accounts in access-test) |

Every mapping is exactly equivalent: same capabilities, same rights outside the capability map (submission notifications,
responsible-engineer listing, AI member access) and same project scope. Converted QA memberships keep their QA rights and
gain no engineering authoring (decision of 30 Oct 2026 on risk R1).

## 5. Enforcement layers

- **API / service:** `apps/tenancy/permissions.py` (`granted_permissions`, `capabilities_for`), every view's declared capability,
  service-level independence checks (photo origin, contract verification, objection review, edit requests).
- **Project and company scope:** unchanged (`apps/projects/scoping.py`, tenant RLS). The photo-origin QA queue now also applies
  project scope (it previously listed claims from the whole company).
- **Database:** no RLS policy refers to roles; tenant isolation and the job-sheet restrictive policy are unchanged.
- **Frontend:** navigation is capability-driven (QA queue, contract list appear only with the permission); role pickers offer the
  four roles (`components/roles.ts`); permission editors in Users, Clients → Client Users and Engineers & Access.

## 6. Onboarding

Self-registration still creates the company's Client Admin. Invitations and direct additions offer only the four roles; a
new Client User starts with previews only and no other feature until the Client Admin grants one. Aries staff are created as
Aries Engineers and assigned to companies; QA and review permissions are granted after assignment.

## 7. Open decisions

| # | Decision |
|---|---|
| D-1 | Applied in access-test on 30 Oct 2026 (zero-difference, verified). Any other environment needs its own dry run and approval |
| D-2 | Aries Support: no place in the four roles; confirm it is retired or define its replacement |
| D-3 | Whether revoking QA permission should also void confirmations made while it was held (today they stay valid, as for a deactivated Aries QA account) |
| D-4 | Whether feasibility / recommendation technical review (`intelligence.review`, today all assigned engineers) should move under CanReviewEngineering |
| D-5 | Client-facing wording still says "Aries QA" for the QA function (Data sharing); confirm or change |
| D-6 | CN-002 change control for D5 and the role matrix |
