# Phase 1 Test Results

- **Executed:** 2026-10-15 on one Windows 11 Pro developer machine (Python 3.12, Node 22). The Android build,
  the emulator run and the mobile checks were re-run on 2026-10-16 for the B-07 fix.
- **Database:** PostgreSQL 16.2, embedded via `pgserver`, with the application connecting as the non-superuser
  role `app_user`.
- **Scope:** only results that were actually executed are reported as passed. Anything not run is listed in
  section 3.

## 1. Results

| Suite | Command | Result |
|---|---|---|
| Backend unit and integration (PostgreSQL) | `backend: python -m pytest -q` | **73 passed**, 0 failed (≈5 s) |
| OpenAPI schema | `manage.py spectacular --validate --fail-on-warn` | **0 warnings**; committed `docs/openapi.yaml` identical to the generated file |
| Django deployment checks | `manage.py check --deploy --fail-level ERROR` (DEBUG off) | **0 errors**, 3 expected warnings (see note A) |
| Web typecheck | `npm run typecheck` | **Passed** (web, api-types, viewer3d) |
| Web unit tests | `npm test` (Vitest) | **7 passed** (API client 5, login 2) |
| Shared viewer unit tests | `npm test` (viewer3d) | **7 passed** (camera views and fit) |
| Web production build | `npm run build` | **Passed**: main bundle 302.7 kB (94.2 kB gzip); viewer chunk 643.5 kB, lazy-loaded |
| End-to-end (Playwright, headless Chromium) | `npx playwright test -c e2e/playwright.config.ts` | **3 passed** (34 s) |
| Mobile typecheck | `mobile: npx tsc --noEmit` | **Passed** |
| Mobile lint | `mobile: npx eslint .` | **0 errors**, 14 style warnings (L-6) |
| Mobile unit tests | `mobile: npx jest` | **16 passed** (API client 10, deployment binding 6) |
| Android debug build (clean) | `mobile/android: gradlew assembleDebug` after deleting all native build output | **Passed** (2026-10-16, 8 min 43 s), after the B-07 fix (note B). Output is `mobile/android/app/build/outputs/apk/debug/app-debug.apk` (145.5 MB, 4 ABIs, debug, unsigned for release). |
| Android emulator install and run | `adb install -r`, then a launch on the API 36 emulator (x86_64) | **Passed** (note C). No native crash, fatal signal or native library load error. |
| iOS build | none | **Not run**: no macOS available (B-04) |
| CI workflow | `.github/workflows/ci.yml` | **Not run**: no remote repository (B-06). Each step was run locally instead. |

**Note A.** The warnings are W003, W005 and W021.

- W003 (no CSRF middleware) is expected. The API authenticates with bearer tokens only and uses no cookie
  sessions, so CSRF does not apply. This must be revisited if the refresh token moves to a cookie (L-1).
- W005 and W021 are about HSTS subdomains and preload, which are deployment decisions.

**Note B: Android build (B-07, resolved).** The first build (2026-10-15) failed at
`:app:buildCMakeDebug[arm64-v8a]`, when linking `libreact_codegen_safeareacontext.so`, with undefined C++
runtime symbols (`std::__ndk1::basic_string`, `__cxa_guard_acquire`, `operator new` and others).

Diagnosis:

1. The generated `build.ninja` link line had `-latomic -lm` but no C++ runtime. The `appmodules` and
   `rnscreens` targets had the same link line, so this was not specific to one library.
2. `ANDROID_STL=c++_shared`, which is normal. With that setting the NDK's `clang++` driver adds libc++
   implicitly.
3. In `rules.ninja`, the linker was invoked as `...\bin\CLANG_~1.EXE`. That is the Windows 8.3 short name of
   `clang++.exe`. CMake's Ninja generator uses short names when the compiler path contains a space, and the SDK
   was in the default location under a Windows user profile whose name contains a space.
4. Clang picks its driver mode from its executable name. Called as `CLANG_~1.EXE`, it runs as the C driver, so
   it compiled `.cpp` files as C++ (by extension) but linked without libc++.

The verified root cause is the SDK path containing a space on Windows. It is **not**
`react-native-safe-area-context` or React Native 0.88, and neither was patched.

The fix:

- `sdk.dir` now points to a path without spaces, through a directory junction. This is per machine and lives in
  git-ignored `local.properties`.
- `android/app/build.gradle` stops early on Windows if the SDK path contains a space. The guard was verified to
  trigger with the old path.

After the fix, the regenerated `rules.ninja` invokes `D:\Android\Sdk\...\bin\clang++.exe`. `:app:buildCMakeDebug`
passed for arm64-v8a, armeabi-v7a, x86 and x86_64, and `BUILD SUCCESSFUL` (169 tasks).

Two other local environment issues were found on the way, and both are documented in `docs/local-setup.md`:

- **Windows JDK loopback socket error:** fixed with `-Djdk.net.unixdomain.tmpdir`.
- **Backslashes in `local.properties`:** use forward slashes.

**Note C: emulator run (2026-10-16).** The emulator was `Medium_Phone_API_36.0` (Android 16, API 36, x86_64,
Google Play image). The debug JS bundle came from Metro through `adb reverse`, and the API ran at
`http://10.0.2.2:8000` against local PostgreSQL. Screenshots are in `docs/phase1/android-emulator/`.

| Check | Result |
|---|---|
| Install | `Success` |
| Cold start | 4.8 s (debug build, includes the first Metro bundle) |
| Native crash / fatal signal / `UnsatisfiedLinkError` | None. The crash buffer is empty and the process stayed alive for the whole session. |
| Sign-in screen layout | Rendered inside the safe area, clear of the status and gesture bars |
| Wrong credentials | The API's `invalid_credentials` message is shown in the app |
| Multi-organisation user (`engineer@operator.demo`) | Organisation selection appears and selecting *Demo Client Energy* signs in |
| Single-organisation user (`user@client.demo`) | Signs in directly |
| Inventory | Lists the client's parts from the API; the header shows the tenant name and Sign out |
| Passport detail (stack navigation) | Opens with a back arrow and title. It shows the OQ-35/36 notice, product information, the STEP file with *3D derivative: succeeded*, the DWG with *Preview not available yet* (OQ-27), and the PDF. |
| Back (system button) and Sign out | Return to Inventory and to Sign in respectively |

Logged during the run, none of it a crash:

- One `ReactNoCrashSoftException`, where window focus arrived before the debug JS bundle had loaded.
- `RNKeychainManager: No entry found` on first launch, the expected result when there is no stored session.

Cosmetic finding: the status bar icons are light on the light sign-in screen (L-7).

## 2. Coverage against the Phase 1 completion criteria

| Criterion | Evidence | Status |
|---|---|---|
| API starts | Dev server running on 127.0.0.1:8000; `/api/health/` checks the database; E2E runs against it | Met |
| Migrations execute | Test database built from migrations on every run, including the `0002_security` RLS and trigger migrations | Met |
| Cross-tenant isolation verified on PostgreSQL | `test_rls_postgres.py` (10): direct SQL with RLS forced, fail-closed with no context, cross-tenant insert, update, move and delete rejected, worker-role scope. `test_api_isolation.py` (13) and `test_security_regression.py` (10): API 404s, filter and nested-route IDs, operator assignment limits, every tenant table has forced RLS. E2E test 3: a second client admin can't see the first client's data. | Met |
| Web app builds and runs | Production build passes; Vite dev server used by E2E | Met |
| Auth works end to end | `test_auth.py` (11): login, tenant selection, refresh rotation with membership re-check, logout blacklist, deactivation and suspension revoke immediately. E2E signs in through the UI as 4 different users. | Met |
| User can create a spare-part draft and a passport draft in the portal | E2E test 1 (operator engineer, UI only) | Met |
| STEP, DWG and PDF uploaded, preserved, retrieved by authorised users | `test_files.py` (20): byte-for-byte storage and SHA-256, content sniffing, versioning keeps earlier originals, signed links, role checks. E2E test 1 uploads all three in the UI, runs the worker as `app_worker`, opens the 3D viewer and checks the downloaded file's SHA-256. | Met, **with synthetic CAD files only (B-01)** |
| Unauthorised users can't retrieve another tenant's records or files | API, RLS and E2E tests above, plus forged, expired and revoked download links (403/410) | Met |
| React Native project builds or passes locally executable checks | Typecheck, lint and 16 Jest tests pass. The Android debug APK builds cleanly, installs and runs on the API 36 emulator through sign-in, inventory, passport detail and sign-out (notes B and C). iOS not built. | **Met for Android (emulator).** iOS not built (B-04); no physical devices (B-05) |
| Tests and limitations recorded | This file and `outstanding-blockers.md` | Met |

## 3. Not tested or not claimed

- **Production CAD fidelity.** Only one OCCT-generated synthetic STEP has been converted. Real customer
  geometry, assemblies, colours and PMI are untested.
- **DWG rendering.** Not implemented (OQ-27). DWG tests cover header validation, storage and retrieval only;
  the DWG fixture is header-only.
- **iOS.** Nothing built or run.
- **Physical devices.** No phone or tablet testing. Android has only run on an x86_64 emulator, and the ARM
  builds (arm64-v8a, armeabi-v7a) were compiled but never executed. On the emulator, sign-in and sign-out used the
  keychain token store without errors. The stored entry itself was not inspected, and hardware-backed Keystore
  behaviour was not verified.
- **Android release build.** Only the debug variant was built. There is no release signing or JS bundle embedding.
- **Azure.** No Blob, PostgreSQL Flexible Server or Entra ID; the Azure storage adapter has not been executed.
- **Performance, load and penetration testing.** Not performed.
- **Browser coverage.** Chromium only, with software WebGL (SwiftShader). Not tested in Firefox, Safari or Edge.
- **Accessibility audit.** Only the labelled form fields are exercised by tests.

## 4. Defects found and fixed during Phase 1 testing

| Found by | Defect | Fix |
|---|---|---|
| Backend tests | The job queue used `now()`, which is the transaction start time, so freshly queued jobs could be skipped | Use `clock_timestamp()` |
| Backend tests | Refresh with a deactivated membership returned 403 | Return 401 `membership_invalid` |
| E2E | Saving a passport draft remounted the page and lost the confirmation message | Show the spinner only on first load |
| E2E | Client-side upload errors showed a generic message | `ErrorNotice` shows the specific message |
| Web tests | Form labels were not associated with inputs (accessibility) | `Field` links the label and input with `useId` and `htmlFor` |
| Mobile tests | An error response with an empty or `null` JSON body crashed the client's error mapping | Treat a missing body as `{}` |
| Android build | Native modules failed to link when the SDK path contained a space (B-07) | Use a space-free `sdk.dir` (junction). Gradle guard added. |

## 5. Evidence files

- Backend tests: `backend/tests/`
- E2E: `e2e/results/e2e-results.json` and screenshots in `e2e/results/screenshots/`
- Android build log: `mobile/android-build.log` (local, git-ignored)
- Android emulator screenshots: `docs/phase1/android-emulator/` (01 launch to 06 passport with files)
