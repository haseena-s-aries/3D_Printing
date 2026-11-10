# Data model and migrations (Phase 1)

All primary keys are UUIDs. `created_at` and `updated_at` are on every table. Tenant-owned tables also carry
`tenant_id` and `created_by_id`.

## Entities

| App | Model | Key fields and rules |
|---|---|---|
| tenancy | **Tenant** | `slug` (unique), `kind`, `status`, `hosting_model`, `region_code` |
| | | `kind`: operator or client |
| | | `status`: active or suspended |
| | | `hosting_model`: shared or dedicated (OQ-70) |
| | | `region_code`: informational only (OQ-71) |
| tenancy | **Membership** | User ↔ tenant with one `role` (9 roles). Unique `(user, tenant)`. |
| | | `is_active` is re-checked on every request and refresh. |
| | | `consent_reference` is stored but not enforced (OQ-37). |
| accounts | **User** | Email login (unique `email`); no tenant column. Access always goes through Membership. |
| projects | **Project** | Unique `(tenant, code)` |
| parts | **SparePart** | Unique `(tenant, part_number)`; category, criticality, material, dimensions, equipment reference |
| passports | **DigitalPassport** | `data_captured` (none/rl1/rl2/rl3) is the stored data-completeness level of the current revision, used by the catalog filter. It is guidance only and never changes evidence level, publication or eligibility (migration `0004_data_captured`, backfilled per tenant). One per spare part (OneToOne). Unique `(tenant, passport_number)`, format `DP-{year}-{nnnnn}`. |
| | | `publication_state`, `evidence_level` and `manufacturing_eligibility` are read-only in the API. |
| passports | **PassportRevision** | Unique `(passport, revision_number)`, with at most one `draft` per passport (partial unique index). |
| | | `content` holds structured R-L1, R-L2 and R-L3 data (see `docs/api.md`, "Passport content"). |
| | | `updated_by` records who last changed the draft (migration `0003_revision_updated_by`); the audit trail keeps every change. |
| | | Submit and approve are gated by OQ-35. |
| files | **EngineeringFile** | Logical document on a part and, optionally, a passport. |
| | | `kind`: step, dwg or pdf. `category` is the passport section. |
| files | **FileVersion** | Immutable original: `sha256`, `size_bytes`, `detected_format`, write-once `storage_key`. |
| | | Unique `(file, version_number)`. |
| files | **Derivative** | Immutable viewer derivative (GLB) of a version, with generator and details. |
| | | Unique `(file_version, kind)`. |
| files | **LinkRedemption** | One row per redeemed download or preview link (unique nonce). Makes links single-use. RLS. |
| tenancy | **Invitation** | Pending, accepted or revoked invitation to an organisation: email, role, SHA-256 token hash, expiry. One pending invitation per email per organisation. Read before any tenant context, so like Membership it isn't under RLS; API querysets are tenant-scoped. |
| servicerequests | **ClientRequest** | Client tenant (RLS). Manufacturing enquiry / request or 3D scanning request: reference (unique per tenant), kind, status, priority, part + passport + revision number at submission, quantity, dates, services, digitisation fields, quotation reference (offline), created project/part. |
| servicerequests | **RequestEvent**, **RequestAttachment** | Client tenant (RLS). Append-only history visible to the client; validated attachments in write-once storage with SHA-256. |
| servicerequests | **RequestEnvelope** | **Operator** tenant (RLS). Minimal summary of each client request for the intake queue (no remarks or documents). |
| servicerequests | **Notification** | Per user, no tenant column; forced RLS with a per-user policy on `app.user_id` (set by authentication), so users read and mark only their own. |
| jobs | **Job** | PostgreSQL work queue: kind, payload, status, attempts, `run_after`, lock fields, error code. |
| audit | **AuditEvent** | Append-only. Records action, actor (email and role copied at the time), object, request id, IP, |
| | | and redacted data. |

## Migrations

Each app has `0001_initial` (schema). Six apps also have `0002_security`:

| Migration | What it adds |
|---|---|
| projects, parts, passports, files, jobs, audit `0002_security` | `ENABLE` and `FORCE ROW LEVEL SECURITY`, with policy `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`. With no tenant context, no rows are visible or writable. |
| jobs `0002_security` | An extra `worker_queue` policy for the `app_worker` role, so the worker can claim jobs across tenants. It grants nothing on other tables. |
| passports `0002_security` | A trigger that blocks UPDATE and DELETE on approved and superseded revisions. The only change allowed is approved → superseded, with content and approval fields unchanged. |
| files, audit `0002_security` | Triggers that block UPDATE and DELETE on `files_fileversion`, `files_derivative` and `audit_auditevent`. |

`tenancy_membership` is deliberately not under RLS, because login has to find a user's memberships before any
tenant context exists. Memberships are only exposed through tenant-scoped API querysets. The regression test
`tests/test_security_regression.py::test_every_tenant_table_has_forced_rls_and_policy` fails if a new model with
a `tenant` column is added without RLS.

## Database roles

| Role | Rights |
|---|---|
| `app_user` | Application role. NOSUPERUSER, NOBYPASSRLS. Owns the tables, and forced RLS still applies to it. |
| `app_worker` | CAD worker role. NOSUPERUSER, NOBYPASSRLS. Reads the queue across tenants, and each tenant's data only inside that job's tenant context. |

Tenant context is set per transaction (`set_config('app.tenant_id', ..., true)`, with `ATOMIC_REQUESTS=True`).
That means it can't leak between pooled connections.

## Object storage keys

- Originals: `tenants/{tenant_id}/originals/{file_id}/v{n}/original.{ext}`
- Derivatives: `tenants/{tenant_id}/derivatives/{file_id}/v{n}/derivative.{kind}`

Both are write-once. In Azure, each tenant gets its own container, named `t-{tenant hex}`.
