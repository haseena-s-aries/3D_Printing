# Finding: `app_user` inherits `app_worker`, so the API role bypasses tenant isolation on the job queue

- **Date:** 2026-10-16
- **Found during:** the showcase dataset work.
- **Status:** **fixed (2026-10-16)** with option B: `GRANT app_worker TO app_user WITH INHERIT FALSE, SET TRUE` in
  `scripts/localdb.py` (test mode, replaces an inheriting grant) and in CI. Verified on the running cluster
  (`inherit_option = f`, `set_option = t`); regression test
  `tests/test_rls_postgres.py::test_api_role_does_not_inherit_the_worker_queue_policy`. No data was changed and
  the showcase database was not reset. Option A (separate logins, no grant) remains the long-term recommendation.
- **Severity:** medium (defence in depth). No API endpoint exposes it today.

## What was observed (measured, read-only)

On the local embedded PostgreSQL 16.2 (`backend/.pgdata`), shared by the `passport` and `passport_demo`
databases:

| Check | Result |
|---|---|
| `pg_auth_members` | `app_user` is a member of `app_worker`, with `inherit_option = t` and `set_option = t` |
| `pg_has_role('app_user', 'app_worker', 'USAGE')` | `true`: `app_user` has the privileges of `app_worker` |
| Policies on `jobs_job` | `tenant_isolation` (PUBLIC, `tenant_id = app.tenant_id`) **and** `worker_queue` (`TO app_worker`, `USING (true) WITH CHECK (true)`, all commands); both permissive |
| Rows of `jobs_job` visible to `app_user` in the **operator** tenant context (`passport_demo`) | **31 jobs from 3 other tenants** (expected 0) |
| Rows of `jobs_job` visible to `app_user` with **no** tenant context | **31** (expected 0) |
| Rows of `files_fileversion` visible in the operator tenant context | 0 (correct) |

PostgreSQL applies a policy to a role and to every role that *has the privileges of* it (inherited membership).
Permissive policies are combined with OR. So for `app_user` the `worker_queue` policy (`true`) overrides
`tenant_isolation`, for SELECT, INSERT, UPDATE and DELETE on `jobs_job`.

**Only `jobs_job` is affected.** It is the only table with a policy for `app_worker`. The table grants to
`app_worker` (`apps/tenancy/rls.py`) give it no extra rows elsewhere, because all other tables have only the
tenant policy. 11 policies in total, checked in `pg_policies`.

## Why the membership exists

| Environment | Where it comes from | Purpose |
|---|---|---|
| Local tests and local development (same cluster) | `scripts/localdb.py start(test_mode=True)`, called by `tests/pg_bootstrap.py`, runs `GRANT app_worker TO app_user` | Tests switch to the worker role with `SET LOCAL ROLE app_worker` (`tests/test_rls_postgres.py`, `tests/test_files.py` via `WORKER_DB_ROLE`) |
| CI | `.github/workflows/ci.yml` lines 41–43: `GRANT app_worker TO app_user` | Same as above |
| `WORKER_DB_ROLE` option | `apps/jobs/queue.py`: the worker may log in as `app_user` and `SET LOCAL ROLE app_worker` to claim jobs | Requires the same membership |

The local development database inherits the grant because tests and development share one embedded cluster.
After the first local test run, the development API (`passport`) and the demo API (`passport_demo`) both
connect as an `app_user` that inherits `app_worker`.

## Intended production configuration (documented, not yet built)

Azure is not provisioned and there is no infrastructure code yet. The intended configuration, per
`docs/data-model.md` "Database roles" and `docs/local-setup.md` "CAD worker", is:

| Role | Used by | Membership |
|---|---|---|
| `app_user` | API only | **Not** a member of `app_worker` |
| `app_worker` | CAD worker only, logging in as itself (`WORKER_DB_ROLE` empty) | None |

In that configuration the issue does not occur. The `WORKER_DB_ROLE` mode is incompatible with it, unless the
grant is non-inheriting (see option B below).

## Impact today

- **No API exposure found.** The two code paths that read jobs filter by tenant explicitly:
  `apps/files/api.py:72` (`tenant_id=obj.tenant_id`) and `apps/parts/dashboard.py:42` (`tenant=tenant`). There is
  no job endpoint.
- **Defence in depth is lost for one table.** A future query on `Job` without an explicit tenant filter would
  return other tenants' rows. Those rows include file-version IDs, error codes and messages, the creating user
  and timestamps. The same applies to an update or insert: the database would not stop a cross-tenant write
  from the API role.
- **The test suite doesn't detect it.** The RLS meta-test checks that every tenant table has forced RLS and a
  policy, but no test asserts that `app_user` cannot see another tenant's jobs.

## Options (for decision; none applied)

| Option | Change | Effect | Trade-off |
|---|---|---|---|
| **A. Separate login roles everywhere (recommended)** | Remove `GRANT app_worker TO app_user` from `localdb.py` and CI. Tests that need the worker open a second connection as `app_worker` instead of `SET ROLE`. Remove or restrict the `WORKER_DB_ROLE` mode. | Matches production; the API role never sees the queue across tenants. | Test changes (two tests); a second DB connection in those tests. |
| **B. Non-inheriting grant (PostgreSQL 16+)** | `GRANT app_worker TO app_user WITH INHERIT FALSE, SET TRUE` (local and CI) | `SET LOCAL ROLE app_worker` still works for tests and `WORKER_DB_ROLE`, but the plain `app_user` session no longer gets the worker policy | Smallest change. Requires PostgreSQL 16+ everywhere, including Azure Flexible Server. Must not be used with an inheriting grant anywhere. |
| **C. Separate local clusters** | Tests use their own pgserver data directory (e.g. `.pgdata-test`) | Development and demo databases never get the test grant | CI and the `WORKER_DB_ROLE` mode still have the issue. |

**In every case:**
- Add a regression test: `app_user`, in tenant A's context and with no context, sees zero jobs belonging to
  tenant B.
- Add a production deployment check that `pg_has_role('app_user', 'app_worker', 'USAGE')` is false.

**Recommended:** A, plus the regression test, as a small security batch after the demo review. B is acceptable
if role switching must stay. Nothing should change while the demo is running. Changing the grant needs either
re-creating the local roles (A) or running one `GRANT`/`REVOKE` as the cluster superuser (B), and then
re-running the backend tests.
