# Local setup

Tested on Windows 11 (Python 3.12, Node 22). The same steps work on macOS and Linux, with `.venv/bin/python`
in place of `.venv\Scripts\python.exe`. No Docker is needed; the container runtime decision is still open.

## 1. Backend (API)

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# Optional, needed for STEP → GLB conversion by the worker (and the conversion tests):
.venv\Scripts\python.exe -m pip install -r requirements-cad.txt
.venv\Scripts\python.exe -m pip install --no-deps vtk==9.6.2   # required by the cadquery-ocp DLLs
```

Python 3.12 is required locally because `pgserver` (embedded PostgreSQL, see below) has no 3.13 wheel yet.

### PostgreSQL

The app only runs on PostgreSQL. Row-level security is part of tenant isolation and can't be tested on SQLite.

- **No PostgreSQL installed:** `python scripts/localdb.py` starts an embedded PostgreSQL server (`pgserver`) in
  `backend/.pgdata`. It creates the `app_user` and `app_worker` roles and the `passport` database, and writes
  `DATABASE_URL` to `backend/.env`. The port can change between starts, so re-run the script after a reboot.
  To stop the server, run `python scripts/localdb.py --stop`.
- **Your own PostgreSQL (14+):** create the roles as in `.github/workflows/ci.yml` and set `DATABASE_URL` in
  `backend/.env` (copy `.env.example`). Never connect the app as a superuser, because superusers bypass
  row-level security.

```powershell
.venv\Scripts\python.exe scripts\localdb.py
.venv\Scripts\python.exe manage.py migrate
$env:DEMO_PASSWORD = "<choose a local password>"; .venv\Scripts\python.exe manage.py seed_demo   # DEBUG only
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

`seed_demo` creates these accounts, all with the `DEMO_PASSWORD` value:

| Email | Tenant | Role |
|---|---|---|
| admin@operator.demo | operator | operator_admin |
| engineer@operator.demo | operator, demo-client | operator_engineer |
| admin@client.demo | demo-client | client_admin |
| user@client.demo | demo-client | client_user |

The API is then available at these addresses:

- `http://127.0.0.1:8000/api/health/`
- API docs (Redoc): `http://127.0.0.1:8000/api/docs/`
- Raw schema: `/api/schema/`

### Invitations and email

Client administrators add people by invitation. No email provider is configured, so the console backend
writes each invitation email, including its link, to the API server log. In development
(`INVITATION_LINK_IN_RESPONSE=true`, the default when `DJANGO_DEBUG=true`) the Users page also shows the link
to the inviting administrator. The setting is ignored whenever `DJANGO_DEBUG` is off, so a hosted environment
never returns the link; turn it off as well wherever real email is configured, otherwise the inviter could act
as the invitee.

### CAD worker

The worker is a separate process that claims jobs from the PostgreSQL queue. It connects as `app_worker`, so
it can read the queue across tenants but sees each tenant's data only inside that job's tenant context.

```powershell
# Use the same DATABASE_URL as backend/.env, with app_worker credentials
$env:DATABASE_URL = "postgresql://app_worker:app_worker@127.0.0.1:<port>/passport"
.venv\Scripts\python.exe manage.py run_worker            # loop; --once / --drain for a single pass
```

Without the optional CAD packages, conversion jobs fail cleanly with `worker_dependency_missing`.

### Tests

```powershell
.venv\Scripts\python.exe -m pytest -q
```

The test run starts its own embedded PostgreSQL unless `TEST_DATABASE_URL` is set (CI sets it to a PostgreSQL
service). It never uses SQLite.

## 2. Web portal

```powershell
npm install                                   # at repository root (workspaces: web, packages/*)
npm run dev --workspace web                   # http://127.0.0.1:5173, proxies /api to 127.0.0.1:8000
npm run typecheck; npm test; npm run build
npm run gen:api                               # after API changes: regenerate packages/api-types from docs/openapi.yaml
```

To regenerate the schema after backend changes, run this in `backend`:

```powershell
.venv\Scripts\python.exe manage.py spectacular --validate --fail-on-warn --file ..\docs\openapi.yaml
```

## 3. End-to-end tests

The API, the web dev server and seeded demo data must all be up first (sections 1 and 2).

```powershell
npx playwright install chromium
$env:DEMO_PASSWORD = "<the seed password>"; npx playwright test -c e2e/playwright.config.ts
```

Screenshots go to `e2e/results/screenshots`. The specs run the CAD worker themselves, through the backend venv's
Python on Windows, macOS or Linux, so **stop any separately running worker first**. Otherwise it converts the
test's job before the test's own worker step can.

The full suite signs in more often than the default limit of 10 per minute. On a local machine only, add
`LOGIN_THROTTLE=200/min` to `backend/.env` and restart the API.

## Demonstration dataset

A separate, synthetic showcase database (three fictitious client organisations, 32 parts, STEP/PDF/image files) can be
created with `scripts\demo_db.py` and `scripts\run_demo.py`. It never touches the development or E2E database. See
[demo-showcase.md](demo-showcase.md).

## 4. Mobile (React Native)

```powershell
cd mobile
npm install
npx tsc --noEmit; npx eslint .; npx jest
```

**Android.** You need Android Studio (its bundled JDK) and the SDK. The template targets compile SDK 37, build
tools 37.0.0 and NDK 27.1, which Gradle installs on first build if the SDK licences are accepted.

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
# Windows only: if Gradle fails with "Unable to establish loopback connection", give the JDK a short socket dir:
$env:JAVA_TOOL_OPTIONS = "-Djdk.net.unixdomain.tmpdir=C:\jdk-tmp"
cd android; .\gradlew.bat assembleDebug           # APK: android/app/build/outputs/apk/debug/
cd ..; npx react-native run-android               # emulator + Metro
```

**On Windows the SDK path must not contain spaces.** Otherwise CMake calls the NDK's `clang++.exe` by its
8.3 short name (`CLANG_~1.EXE`). Clang then runs in C mode and native modules fail to link, with undefined
`std::__ndk1` and `__cxa_*` symbols (B-07). `android/app/build.gradle` stops the build with a clear message
in that case.

If your SDK lives under a profile with a space (for example `C:\Users\First Last\...`), add a junction. It needs no
admin rights and nothing is moved:

```powershell
cmd /c mklink /J D:\Android\Sdk "C:\Users\<you>\AppData\Local\Android\Sdk"
```

Then set `android/local.properties` (git-ignored, per machine) to `sdk.dir=D:/Android/Sdk`. Use forward
slashes, because backslashes are escape characters in properties files.

The development deployment is `http://10.0.2.2:8000`, the emulator's alias for the host loopback. Add
`10.0.2.2` to `DJANGO_ALLOWED_HOSTS` in `backend/.env` for emulator sessions. Plain HTTP is accepted only for
development hosts; every other deployment must use HTTPS (`src/config/deployments.ts`).

**iOS.** You need macOS with Xcode and CocoaPods: `cd ios && pod install`, then `npx react-native run-ios`.
This has not been built or run in Phase 1.
