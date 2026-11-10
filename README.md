# Aries 3D Digital Passport

A multi-company platform for 3D-printed and 3D-printable spare parts, built for Aries and its industrial clients.

- **Digital Passport**: one controlled record per part: identity, R-L1/R-L2/R-L3 readiness data, STEP model with a 3D
  viewer, drawings and documents, revisions, approval and publication.
- **Digital Inventory**: each client company's catalogue of parts, with search, filters, photos and inventory import.
- **Spare Parts Intelligence**: classification, manufacturing feasibility, cost and lead-time comparison (OEM, additive,
  conventional), recommendations, engineering review and quarterly assessments. AI suggestions (Gemini) are optional and
  switched off unless explicitly configured. They are always marked as preliminary, never as manufacturing approval.
- **Workflow**: client part submissions, controlled edit requests, job sheets, PDF reports (client and Aries-internal
  variants), invitations and an audit log.

Roles: Aries Admin, Aries Engineer, Client Admin, Client User. Every company's data is isolated in the database itself
(row-level security), not only in the API.

## Architecture

```
Browser ── React SPA (web-modern/) ──/api──> Django REST API (backend/) ──> PostgreSQL 17  or  SQL Server 2022
                                                  │                          (row-level security in both)
                                                  └── job queue (in the database)
                                                            │
                               Background worker (same codebase, separate process)
                               STEP → GLB conversion (OCCT/cadquery-ocp), assessment runs, report rendering
Files (CAD, PDFs, photos, reports): local folder in development, Azure Blob Storage optional
```

| Area | Location | Stack |
|---|---|---|
| API (modular monolith) | `backend/` (`apps/*`, `config/`) | Python 3.14 (3.12 also supported), Django 6.1, DRF 3.18, SimpleJWT, drf-spectacular |
| Databases | `backend/apps/tenancy`, `backend/apps/core` | PostgreSQL 17 (default for development, forced RLS) or Microsoft SQL Server 2022 via mssql-django (security policies on `SESSION_CONTEXT`, immutability triggers) |
| Background worker | `backend/apps/jobs` (`manage.py run_worker`) | Database job queue; claims jobs as the `app_worker` role |
| CAD conversion | `backend/apps/files/cad_pipeline.py`, `backend/apps/files/jobs.py` | cadquery-ocp (OCCT) + VTK, STEP → GLB |
| Spare Parts Intelligence | `backend/apps/intelligence`, `backend/apps/imports` | Rules, costing and feasibility services; optional Gemini provider |
| PDF reports | `backend/apps/reports`, `backend/scripts/report_render.mjs` | Node.js 22 + Playwright Chromium |
| Web app (current UI) | `web-modern/` | React 19, TypeScript, Vite 7, Vitest. **This is the UI that is deployed.** |
| Web app (original UI) | `web/` | Same API and routes; kept for comparison and its tests |
| Shared packages | `packages/viewer3d`, `packages/api-types` | Three.js viewer; API types generated from `docs/openapi.yaml` |
| Mobile | `mobile/` | React Native (Phase 1 foundation) |
| End-to-end tests | `e2e/` | Playwright |
| Windows Server deployment | `deploy/windows-sqlserver/` | SQL Server scripts, IIS `web.config`, Waitress, NSSM; Python 3.14 compatibility test |
| Documentation | `docs/` | API, data model, change notes CN-002 to CN-007, local setup, demo guides |

## Development prerequisites

| Tool | Version |
|---|---|
| Git | Any recent version |
| Python | **3.14 x64** (tested with 3.14.4). Use 3.12 only for the embedded-PostgreSQL option below. |
| Node.js | 22 LTS, with npm |
| Database | One of: Microsoft SQL Server 2022 (Developer or Express) + **ODBC Driver 18 for SQL Server** + SSMS; or PostgreSQL 17 |
| Optional | Docker is **not** required. Android Studio / JDK 17 only for `mobile/`. |

## Getting the code

```powershell
git clone https://github.com/one-software-aries/3D-Digital-Passport.git
cd 3D-Digital-Passport
git checkout feature/sqlserver-support
```

## Backend setup with Python 3.14 and SQL Server

### 1. Python environment

```powershell
cd backend
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-sqlserver.txt -c constraints-sqlserver.txt
.venv\Scripts\python -m pip install pytest==9.1.1 pytest-django
# CAD worker (STEP → GLB); vtk without its optional dependencies (matplotlib is not needed):
.venv\Scripts\python -m pip install -c constraints-sqlserver.txt --no-deps cadquery-ocp==8.0.1.1.0 cadquery-ocp-proxy==8.0.1.1.0 vtk==9.6.2
.venv\Scripts\python -m pip check      # only "vtk ... requires matplotlib" is expected
```

`constraints-sqlserver.txt` pins every package to the versions tested on Python 3.14.

### 2. Development database (SSMS, as a sysadmin)

Use a **new, separate database** for development. Never point a development machine at a shared or production database.

```sql
CREATE DATABASE [DigitalPassport_Dev] COLLATE Latin1_General_100_CS_AS_SC;  -- case-sensitive, as tested
ALTER DATABASE [DigitalPassport_Dev] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
ALTER DATABASE [DigitalPassport_Dev] SET AUTO_CLOSE OFF;                       -- Express turns it on by default
CREATE LOGIN [dp_dev_owner] WITH PASSWORD = N'<choose a password>', DEFAULT_DATABASE = [DigitalPassport_Dev];
USE [DigitalPassport_Dev];
CREATE USER [dp_dev_owner] FOR LOGIN [dp_dev_owner];
ALTER ROLE db_owner ADD MEMBER [dp_dev_owner];
```

`deploy/windows-sqlserver/01-create-database.sql` and `02-grant-runtime.sql` show the production setup with a separate
least-privilege runtime login. For local development a single owner login is enough. To test the runtime-login
permissions, create a second login and run `02-grant-runtime.sql` with the database name changed.

### 3. Environment variables (`backend/.env`)

Create `backend/.env` (it is git-ignored, so never commit it). Use placeholders like these, with your own values:

```ini
# Django
DJANGO_SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(64))">
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
WEB_BASE_URL=http://127.0.0.1:5173

# SQL Server (DB_ENGINE=mssql switches from PostgreSQL to SQL Server)
DB_ENGINE=mssql
DB_HOST=<server>\<instance>          # e.g. localhost\SQLEXPRESS
DB_NAME=DigitalPassport_Dev
DB_USER=<sql login>
DB_PASSWORD=<sql login password>
DB_DRIVER=ODBC Driver 18 for SQL Server
DB_TRUST_SERVER_CERTIFICATE=true     # local self-signed certificate only

# Files
FILE_STORAGE_BACKEND=local
LOCAL_STORAGE_ROOT=.storage
AZURE_STORAGE_CONNECTION_STRING=

# E-mail (prints to the console in development)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
INVITATION_LINK_IN_RESPONSE=true

# External AI stays off unless explicitly approved
AI_PROVIDER=
GEMINI_API_KEY=
```

All other settings have safe defaults. See `backend/config/settings.py`; the PostgreSQL template is
`backend/.env.example`. Feature flags such as `PART_INTELLIGENCE_ENABLED`, `INVENTORY_IMPORT_ENABLED`,
`EDIT_REQUESTS_ENABLED` and `FOUR_ROLE_MODEL_ENABLED` are read from the environment.

### 4. Database migrations

```powershell
cd backend
.venv\Scripts\python manage.py migrate        # creates tables, security policies and immutability guards
.venv\Scripts\python manage.py check
```

After changing models: `manage.py makemigrations <app>`, then run the tests on **both** databases (see below). The
SQL Server security objects are created by migrations in `apps/tenancy` and `apps/core`.

### 5. First admin user

```powershell
$env:FIRST_ADMIN_EMAIL = "<you@example.com>"; $env:FIRST_ADMIN_PASSWORD = Read-Host "first admin password"
.venv\Scripts\python manage.py shell -c "exec(open(r'..\deploy\windows-sqlserver\create_first_admin.py', encoding='utf-8').read())"
Remove-Item Env:FIRST_ADMIN_EMAIL, Env:FIRST_ADMIN_PASSWORD
```

## Alternative: PostgreSQL

Without `DB_ENGINE`, the backend uses `DATABASE_URL` (PostgreSQL, see `backend/.env.example`). The database login
must **not** be a superuser, because superusers bypass row-level security. `docs/local-setup.md` describes the roles
(`app_user`, `app_worker`) and an embedded PostgreSQL (`pgserver`, `requirements-dev.txt`) that needs Python 3.12.
CI (`.github/workflows/ci.yml`) runs the backend tests on PostgreSQL 17.

## Running the API and the worker

```powershell
cd backend
.venv\Scripts\python manage.py runserver 127.0.0.1:8000      # API: http://127.0.0.1:8000/api/  (health: /api/health/, docs: /api/docs/)
$env:WORKER_DB_ROLE = "app_worker"                            # second terminal: worker only, never set for the API
.venv\Scripts\python manage.py run_worker                     # background worker (loops; --once / --drain for one pass)
```

The worker switches to the `app_worker` database role only to claim jobs. Keep `WORKER_DB_ROLE` out of `backend/.env`.

The worker needs the CAD packages for STEP conversion. For PDF reports, also run `npm install` and
`npx playwright install chromium` at the repository root (the renderer is `backend/scripts/report_render.mjs`).

Production runs the API under Waitress behind IIS: see `deploy/windows-sqlserver/WINDOWS-SERVER-DEPLOYMENT.md`.

## Frontend setup (React)

```powershell
npm install                                    # at the repository root (workspaces: web, packages/*)
cd web-modern
npx vite                                       # http://127.0.0.1:5173, proxies /api to http://127.0.0.1:8000
```

Set `VITE_API_PROXY_TARGET` to use an API on another address. `web-modern` uses the root `node_modules`.

```powershell
npm run typecheck      # in web-modern
npm test               # in web-modern (Vitest)
npm run build          # in web-modern → web-modern/dist, the files IIS serves (with deploy/windows-sqlserver/web.config)
```

After an API change, regenerate the schema and the shared types:

```powershell
cd backend; .venv\Scripts\python manage.py spectacular --validate --fail-on-warn --file ..\docs\openapi.yaml
cd ..; npm run gen:api
```

## Running tests

| What | Command |
|---|---|
| Backend on SQL Server | Create an empty, separate test database (e.g. `DigitalPassport_Dev_Test`, same settings as above), then in `backend`: `$env:DB_TEST_NAME = "DigitalPassport_Dev_Test"; .venv\Scripts\python -m pytest --reuse-db -q`. `DB_ENGINE=mssql` and the `DB_*` login must be set. |
| Backend on PostgreSQL | `.venv\Scripts\python -m pytest -q` (embedded PostgreSQL, or `TEST_DATABASE_URL`; see `docs/local-setup.md`) |
| CAD conversion tests | Included when the CAD packages are installed (marker `cad`) |
| Web app | `npm run typecheck` and `npm test` in `web-modern/` (and at the root for `web/` and `packages/`) |
| End-to-end | `npx playwright test -c e2e/playwright.config.ts`, with the API, web and seeded synthetic data running (see `docs/local-setup.md`) |
| Python 3.14 server check | `deploy/windows-sqlserver/py314-compat/README.md` |

Tests write to their database. On SQL Server always set `DB_TEST_NAME` to a dedicated, empty test database (the
first `--reuse-db` run migrates it). Never point tests at a shared or production database.

## Data and security rules for contributors

- Never commit `.env` files, passwords, API keys, connection strings, database backups, uploaded files, client CAD or
  drawings, customer documents, test results or generated builds and ZIPs. `.gitignore` covers the usual paths. Check
  `git status` before every commit.
- Use synthetic data only. The only CAD file in the repository is a synthetic test fixture
  (`backend/tests/fixtures/sleeve_d45_h40_5_synthetic.stp`).
- Do not weaken tenant isolation, approval controls or the role permissions. Changes to `apps/tenancy`, security
  policies or migrations need a reviewer.
- External AI (Gemini) stays disabled unless the company and use are explicitly approved (`AI_ALLOWED_COMPANIES`).

## Git branching and contributions

- `feature/sqlserver-support` is the current tested baseline: complete application, Spare Parts Intelligence, D-23 fixes,
  SQL Server support and the Python 3.14 deployment kit.
- Create a branch per change from the latest baseline: `git checkout -b feature/<short-name>` (or `fix/<short-name>`).
- Keep commits focused, with a message that says what and why. Run the backend tests (on SQL Server when you touch the
  database layer) and the web typecheck and tests before pushing.
- Push your branch (`git push -u origin feature/<short-name>`) and open a pull request into `feature/sqlserver-support`.
  At least one review is required before merging. Never force-push shared branches.
- After a merge, delete the feature branch. Releases are built from the reviewed baseline as an offline deployment package
  (see `deploy/windows-sqlserver/WINDOWS-SERVER-DEPLOYMENT.md`).

## Business decisions still open

Actions that depend on undecided policy are refused by the API with HTTP 409 `policy_not_configured` and shown as disabled
in the UI: publication/approval (OQ-35), manufacturing release (OQ-36), support access consent (OQ-37), ownership
transfer (OQ-38). See `backend/apps/policies/seams.py`.

## Further documentation

- [Local setup (PostgreSQL, mobile, end-to-end)](docs/local-setup.md)
- [API reference](docs/api.md) and [OpenAPI schema](docs/openapi.yaml)
- [Data model and migrations](docs/data-model.md)
- [Change notes CN-002 to CN-007](docs/brd-change-notes/)
- [Windows Server deployment (SQL Server, IIS, Python 3.14)](deploy/windows-sqlserver/WINDOWS-SERVER-DEPLOYMENT.md)
- [Python 3.14 compatibility test](deploy/windows-sqlserver/py314-compat/README.md)
- [UI modernization notes](web-modern/UI-MODERNIZATION.md)
