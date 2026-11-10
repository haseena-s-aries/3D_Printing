# API reference (v1)

The machine-readable contract is [`openapi.yaml`](openapi.yaml), which is generated from code and validated with
zero warnings. When the API is running, it is rendered at `/api/docs/`. This page covers the rules that apply
across all endpoints.

## Conventions

- **Base path:** `/api/v1/`. Request and response bodies are JSON; file uploads use `multipart/form-data`.
- **Authentication:** `Authorization: Bearer <access token>`. Each access token is bound to one membership, so
  one user in one tenant. The membership is re-validated on every request: deactivation or tenant suspension
  takes effect immediately.
- **Tenant scope:** every endpoint works on the tenant in the token, and a `tenant` field in a body is ignored.
  Objects belonging to other tenants return **404**, never 403, so their existence is not revealed.
  PostgreSQL row-level security enforces the same boundary underneath.
- **Roles:** each action needs a capability, and actions not declared for a view are denied (403). The session
  (`/auth/me/`) lists the caller's capabilities, and the UIs use that list to show or hide controls.
- **Pagination:** list endpoints return `{count, next, previous, results}`. Use `?page=` and
  `?page_size=` (default 25, max 200).
- **No hard deletes:** there are no DELETE endpoints for business records. Versions, derivatives, approved
  revisions and audit events are immutable at database level.

## Errors

Every error uses the same envelope:

```json
{"error": {"code": "unsupported_file_type", "message": "Human readable.", "details": {}, "request_id": "9f2c..."}}
```

`request_id` is also returned in the `X-Request-ID` header and written to logs and audit events.

| HTTP | Code | When |
|---|---|---|
| 400 | `validation_error` | Field validation failed (`details` holds the field errors) |
| 400 | `tenant_selection_required` | The user has several tenants; `details.tenants` lists them, and the client retries with `tenant` |
| 400 | `unsupported_file_type`, `kind_mismatch`, `empty_file`, `file_too_large`, `content_mismatch` | Upload validation |
| 401 | `invalid_credentials` | Wrong email or password (same response whether or not the account exists) |
| 401 | `not_authenticated`, `token_invalid`, `membership_invalid` | Missing or expired token, or membership deactivated |
| 403 | `permission_denied`, `no_active_membership` | Role lacks the capability, or no active access to the tenant |
| 404 | `not_found`, `derivative_not_available` | Not found, or not in your tenant |
| 409 | `policy_not_configured` | The action depends on an open business decision (`details.decision`, for example `OQ-35`) |
| 409 | `revision_not_editable`, `draft_exists` | Revision rules |
| 400 | `image_too_large` | Photograph exceeds the pixel limit (`MAX_IMAGE_PIXELS`, default 60 MP; `details` gives width, height, limit) |
| 403 / 410 | `link_invalid`, `link_expired`, `link_used` | Download link forged, revoked, expired, or already used once |
| 400 / 403 | `invitation_invalid`, `invitation_required`, `invitation_not_applicable` | Invitation unusable (generic); client admins must invite; account cannot join by invitation |
| 429 | `throttled` | Too many login attempts |

## Endpoints

| Method and path | Capability | Notes |
|---|---|---|
| `GET /api/health/` | none | Liveness, plus database check |
| `POST /auth/token/` | none | `{email, password, tenant?}` → `{access, refresh, session}`. Throttled. Audited. |
| `POST /auth/refresh/` | none | `{refresh}` → `{access, refresh}`. Rotates the token and re-checks the membership. |
| `POST /auth/logout/` | authenticated | `{refresh}` → 204. Blacklists the refresh token. |
| `GET /auth/me/` | authenticated | Session: user, tenant, membership, capabilities |
| `GET /dashboard/summary/` | `parts.view` | Facts from the organisation's own records: parts, passports by publication / evidence level / data captured, open drafts, documents by kind and category, parts with drawing / specification / 3D / photo, conversion status counts with failed items, eight most recently active parts. No production or order statistics. |
| `GET/POST /invitations/`, `POST /invitations/{id}/revoke/` | `users.manage` | Organisation administrators invite by `{email, role}`. The response is the same whether or not the address has an account. `invite_url` is always `null` unless both `DEBUG` and `INVITATION_LINK_IN_RESPONSE` are on (development aid); otherwise the link is only emailed. Client roles only in client organisations; 400 `already_member` for existing members of the same organisation. |
| `GET/POST /invitation-acceptance/{token}/` | public, rate-limited | GET shows organisation, role, email and expiry (nothing about existing accounts). POST `{first_name?, last_name?, password}`: an existing account must give its password, a new address sets one. Generic 400 `invitation_invalid`; 403 `invitation_not_applicable` for operator staff and other organisations' accounts. Single-use, expires (`INVITATION_DAYS`). |
| `GET /auth/memberships/` | authenticated | The caller's own active organisations with role and counts (parts, passports, open drafts), each read inside that organisation's RLS context. Used by the organisation switcher and operator overview. |
| `POST /auth/switch/` | authenticated | `{tenant, refresh}` → `{access, refresh, session}` for another organisation the user already belongs to (403 otherwise). Revokes the presented refresh token. Audited as `auth.switched_out` / `auth.switched_in`. |
| `GET/POST /clients/`, `GET/PATCH /clients/{id}/` | `clients.view` / `clients.manage` | Operator tenant only |
| `GET/POST /clients/{id}/members/` | `clients.manage` | Operator adds or assigns users to a client tenant |
| `PATCH /clients/{id}/members/{membership_id}/` | `clients.manage` | Operator administrators change `role` or `is_active` of a membership in that client, including operator staff assignments. Audited in both organisations. |
| `GET/POST /users/`, `GET/PATCH /users/{id}/` | `users.view` / `users.manage` | Memberships of the current tenant, each with `managed_by` (`operator` or `organisation`) and `can_manage` for the caller. Rules in `apps/tenancy/membership_policy.py`: operator staff are managed only by operator administrators (403 `operator_staff_managed_by_operator`); client admins assign client roles only, cannot add operator staff or other organisations' accounts (403 `user_not_addable`), and cannot change themselves (400 `cannot_change_self`); roles keep their operator/client family (403 `role_family_change`). |
| `GET/POST /projects/`, `GET/PATCH /projects/{id}/` | `projects.view` / `projects.manage` | |
| `GET/POST /parts/`, `GET/PATCH /parts/{id}/` | `parts.view` / `parts.manage` | The digital inventory catalog. `search` (part number, name, description, passport number); filters `category`, `criticality`, `status`, `project`, `evidence_level` (official), `data_level` (`rl1`/`rl2`/`rl3` = at least that much data captured, or `none`), `eligibility` (stored manufacturing eligibility; `not_eligible` includes parts without a passport, MOB-010), `catalog` (`published` = client manufacturing catalog, `in_digitisation` = everything else), `has_passport`, `has_3d`; `ordering` (`part_number`, `-part_number`, `name`, `-name`, `last_activity`, `-last_activity` (default), `created`, `-created`). Each row includes passport number, publication, evidence level, manufacturing eligibility (read-only), data captured, current revision, project name, document counts by kind, `has_3d`, `thumbnail` and `last_activity`. Tenant-scoped and under RLS. |
| `GET/POST /passports/`, `GET/PATCH /passports/{id}/` | `passports.view` / `passports.edit_draft` | Create `{part, title?, initial_content?}` creates revision 1 as a draft. State fields are read-only. |
| `GET/POST /passports/{id}/revisions/` | view / edit_draft | POST opens a new draft (409 `draft_exists` if one is open) |
| `GET/PATCH /passports/{id}/revisions/{rev}/` | view / edit_draft | PATCH works on drafts only. `content` holds structured `rl1`, `rl2` and `rl3` (see below); levels sent in a PATCH are **merged** into the stored content, so each level can be saved on its own. Responses include `completeness` per level and `created_by_email` / `updated_by_email`. |
| `POST /passports/{id}/revisions/{rev}/submit/` and `.../approve/` | edit_draft | **Always 409 `policy_not_configured` (OQ-35).** No approval rules are implemented. |
| `GET/POST /files/`, `GET /files/{id}/` | `files.view` / `files.upload` | Multipart `{part, file, passport?, kind?, category?, title?}`. Filters: `part`, `passport`, `kind`, `category`. |
| `GET/POST /files/{id}/versions/` | view / upload | New immutable version; earlier originals are kept |
| `POST /files/{id}/versions/{n}/download-link/` | `files.download_original` (original) or `files.download_derivative` (glb, preview) | `{variant: "original", "glb" or "preview"}` → `{url, expires_at, filename}`. `preview` is for PDFs and photographs (400 `preview_not_available` otherwise) and is served inline; it uses the same roles as 3D viewing (BR-039). Audited. |
| `GET /files/{id}/versions/{n}/thumbnail/` | `files.view` | 480 px JPEG of a photograph with all metadata removed, for lists. Uses the caller's own token (no link); tenant-scoped; not audited (like list views). |
| `GET /downloads/{token}/` | signed token | **Single use**: a second request gets 410 `link_used`. Links expire after `DOWNLOAD_LINK_SECONDS` (default 120). Streams the object with `X-Content-SHA256`, `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`. Re-checks the user, membership, tenant and RLS on use. Audited as `file.downloaded` or `file.previewed`. |
| `GET /audit-events/` | `audit.view` | Read-only. Filters: `action`, `object_type`, `object_id`. |
| `GET /requests/`, `GET /requests/{id}/` | `requests.view` (client roles) | The organisation's manufacturing enquiries / requests and 3D scanning requests, with history (`events`) and `attachments`. Filters `kind`, `status`. |
| `POST /requests/` | `requests.create` (client admin, client engineer, procurement) | `request_type: manufacturing` with `part`, `quantity`, `required_date`, `delivery_location`, `services[]`, `priority`, `remarks?`, `client_reference?`; the server attaches the part, organisation and current passport revision and classifies it: **enquiry** unless the passport is published **and** eligible (then `manufacturing_request`). `request_type: digitisation` with `site_location`, `equipment?`, `part_description`, `reason`, `preferred_date?`, contact fields, `remarks?`. Returns a unique reference (`MR-…` / `DR-…`) with status `submitted`. Audited; operator staff notified. |
| `GET /requests/form-options/` | `requests.view` | Service options for the request form. |
| `POST /requests/{id}/reply/`, `.../withdraw/` | `requests.create` | Message to the operator team (answers an information request); withdraw while not yet answered. |
| `POST /requests/{id}/attachments/`, `GET .../attachments/{aid}/` | create / view | Photographs and documents validated like engineering uploads (JPEG, PNG, PDF, STEP, DWG; content checked; max 10); downloads `nosniff`, `no-store`, SHA-256 header, audited. |
| `GET /operator/requests/` | `requests.handle` (operator staff) | Intake queue across clients, read from summaries kept in the operator organisation (no cross-tenant query). `assigned` says whether the caller may open it. Filters `kind`, `status`, `priority`, `client_tenant`, `open=true`. |
| `GET /operator/requests/{id}/`, `POST .../act/`, `GET .../attachments/{aid}/` | `requests.handle` **and** an active assignment to that client (403 `not_assigned`) | Detail runs in the client's tenant context. Actions: `acknowledge`, `request_information`*, `respond`*, `close`* (enquiries), `schedule`, `start`, `complete`, `decline`* (scanning), `create_project` (scanning: project + one draft part, once). *Message required. There is no review, release or production action (OQ-36). |
| `GET /notifications/`, `POST /notifications/{id}/read/`, `POST /notifications/read-all/` | authenticated | The caller's own in-app notifications (`unread` count, latest 30) — per-user row-level security. |

## Passport content (readiness levels)

All fields are optional while a revision is a draft. `completeness` reports per level `{total, done, missing[],
complete}`. It is guidance only: the evidence level and QA verification do not change (OQ-35).

| Level | Fields | Rules |
|---|---|---|
| `rl1` (BR-006, BR-009) | `cad_3d_available`, `drawings_2d_available`, `original_material_grade`, `proposed_material`, `proposed_material_reason`, `material_identification_method` (pmi/destructive/oem), `technical_description`, `part_size`, `application`, `atmosphere` (corrosive/non_corrosive), `motion` (static/rotating), `rpm`, `ip_status` (obsolete/active), `not_applicable` `{field: reason}` | `rpm` is required for rotating parts. A field marked not applicable needs a non-empty reason. |
| `rl2` (BR-007, BR-026, BR-041) | `manufacturing_solution`, `material_selection`, `material_category` (equivalent/superior), `criticality_amsl`, `feedstock`, `applicable_standards`, `mechanical_acceptance[]` `{property, requirement, unit, standard}`, `dimensional_tolerances`, `ndt`, `inspection_test_plan`, `mtc_required`, `test_coupons`, `manufacturing_spec` `{job_number, material, feedstock, machine, layer_thickness, support_strategy, build_orientation, inert_gas, heat_treatment, post_processing, machining, printing_hours, post_processing_hours, process_parameters[] {name, value, unit}}` | Hours are numbers ≥ 0. |
| `rl3` (BR-008) | `evidence` `{itp, machine_details, print_orientation, dimensional_inspection, material_test_certificate}` → file id, `notes` | Each id must be a file attached to the same passport (400 `evidence_file_invalid`). |

## Files and conversion

- **Accepted formats:** `.stp`/`.step`, `.dwg`, `.pdf`, and part photographs `.jpg`/`.jpeg`/`.png`. The content
  is checked as well as the extension: the STEP `ISO-10303-21` header, `%PDF-` for PDF, DWG versions AC1012 to
  AC1032, and JPEG/PNG signatures. Photographs are also checked against the pixel limit from their header (before decoding), must decode as the
  format their signature claims, and are fully decoded with Pillow; truncated images, GIF and SVG are rejected.
- **Photographs:** the original is stored unchanged, and a metadata-free 480 px thumbnail is stored as a
  `thumb` derivative.
- **File-revision association:** each version records the passport revision in force when it was uploaded
  (`passport_revision_number`).
- **Size limits:** set per kind in settings, and provisional until OQ-31 is decided.
- **Integrity:** originals are stored byte-for-byte with a SHA-256 checksum, under write-once keys.
- **STEP:** each STEP version queues a `cad.step_to_glb` job. The version's `conversion` field shows
  `queued`, `running`, `succeeded` or `failed`, and a GLB derivative is available once it succeeds.
- **DWG:** conversion is reported as `not_available` (OQ-27). The original is stored and downloadable.
