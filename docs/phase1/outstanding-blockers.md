# Outstanding Blocker Register (end of Phase 1)

Status date: 2026-10-16 (B-07 closed). Business baseline is BRD v0.4, which was not modified.

- **Owner key:** BO = business owner, Legal = legal/contracts, Ops = operator IT/infrastructure, Dev = development team.
- **Severity:** whether it blocks Phase 2 start, a Phase 2 feature, or release only.

## A. Inputs and environment

| ID | Blocker | Impact | Workaround in Phase 1 | Owner | Severity |
|---|---|---|---|---|---|
| B-01 | **No real STEP or DWG samples.** All CAD fixtures are synthetic: a STEP generated with OCCT, and a DWG that has a valid header only. | Production CAD fidelity is **not** verified, and DWG handling is tested only as storage and retrieval. Conversion time and memory on real assemblies are unknown, which also affects OQ-31. | Pipeline proven end to end on a synthetic part. Real files must stay local; they will not be sent to external services. | BO (supply samples) | Blocks CAD acceptance |
| B-02 | **Container runtime not chosen.** Docker is not installed and there are no images. | No production-like packaging. Can't run Azurite or the Azure Functions/Container Apps tooling locally. | Embedded PostgreSQL (`pgserver`) and local file storage for development. | BO / Ops | Blocks deployment work |
| B-03 | **No Azure resources provisioned** (as instructed). | `AzureBlobStorage` is unit-designed but has **not** been run against Azure or Azurite. Also unverified: Entra ID, Key Vault, managed identity and user-delegation SAS. | Local storage adapter behind the same interface. | BO (approve spend) / Ops | Blocks hosted environments |
| B-04 | **No macOS build host.** | iOS is **not built and not run**. No CocoaPods install, Xcode build or simulator test has been done. | None. The shared TypeScript code is tested with Jest. | Ops (Mac or macOS CI runner and Apple developer account) | Blocks iOS deliverable |
| B-05 | **No physical-device testing.** | Hardware Keystore behaviour, performance and 3D viewing on real phones are untested. The ARM builds were compiled but never executed. | Jest unit tests. The Android debug APK runs on an x86_64 API 36 emulator (see test results). | Ops / QA | Before mobile UAT |
| B-06 | **CI has never run.** The repository has no remote. | `.github/workflows/ci.yml` is unverified. The Linux OCCT/VTK wheels and the GitHub-hosted Android SDK setup are untested. | All CI steps were run locally on Windows. | BO (choose hosting for the repository) | Low, first push |

### Resolved

| ID | Blocker | Resolution | Closed |
|---|---|---|---|
| B-07 | The Android debug build failed to link native modules (undefined `std::__ndk1` and `__cxa_*` symbols). | **Root cause:** the Android SDK sat under a Windows path with a space. CMake therefore invoked `clang++.exe` by its 8.3 short name `CLANG_~1.EXE`, and Clang ran as the C driver and linked without libc++. Neither `react-native-safe-area-context` nor React Native was at fault, and neither was patched or changed. **Fix:** a space-free `sdk.dir` (per-machine junction, git-ignored `local.properties`), plus a Gradle guard that stops Windows builds with a clear message when the SDK path contains a space. **Verified:** clean `assembleDebug` succeeded for 4 ABIs, and the APK installed and ran on the API 36 emulator through sign-in, organisation selection, inventory, passport detail and sign-out. | 2026-10-16 |

## B. Open business decisions affecting the build

These are taken from `Remaining_Decisions_Register_v0.4.xlsx`. No rules have been invented. Every gated action
returns HTTP 409 `policy_not_configured` and appears disabled in the UI.

| ID | Decision | Effect in code now | Unblocks |
|---|---|---|---|
| OQ-35 | Evidence-level transitions; minimum level required for publication | Submit and approve always return 409. Evidence level is read-only (`none`). | Approval workflow, publication |
| OQ-36 | Manufacturing authorisation rules (evidence, approvals and QA; R-L3 for critical/AMSL) | `manufacturing_eligibility` is read-only (`not_eligible`) and the manufacturing seam returns 409 | Manufacturing release, eligibility filters |
| OQ-37 | Client consent wording, contract terms and notification for operator access | `Membership.consent_reference` is stored but not enforced. The support-consent seam returns 409. | Operator support-access flows |
| OQ-38 | Ownership, operator licence scope, third-party OEM IP | The ownership seam returns 409. No transfer endpoints exist. | Ownership/IP fields and transfer |
| OQ-27 | DWG rendering mechanism and licensing | DWG is stored and downloadable; conversion is reported as `not_available` | DWG viewer (likely needs a licensed SDK: a licensing commitment) |
| OQ-31 | File size limits and conversion times | Provisional limits: STEP 200 MB, DWG 100 MB, PDF 100 MB (settings) | Final limits; worker sizing |
| OQ-32 | Who uploads STEP, DWG and PDF | Upload allowed for operator admin/engineer and client admin/engineer (provisional, in the capability map) | Final upload permissions |
| OQ-33 | Watermark feasibility and policy | No watermarking. Downloads are time-limited, bound to the user and audited. | Watermarked viewer and PDF |
| OQ-49 | Secure mobile connectivity; route to dedicated deployments | Mobile has a deployment-binding interface and HTTPS validation only. No production endpoint is configured. | Mobile production configuration |
| OQ-64 | One configurable app or per-client builds | Static deployment registry (configuration only) | Mobile distribution design |
| OQ-51 | Public or private app distribution | No store or MDM configuration. Debug builds only. | Release |
| OQ-71 | Azure regions and data residency | `Tenant.region_code` is informational only | Region strategy, dedicated deployments |

## C. Known technical limitations (not blockers)

| # | Limitation | Planned handling |
|---|---|---|
| L-1 | The web refresh token is held in `sessionStorage`; the access token is kept in memory only | Phase 2: move refresh to an httpOnly, SameSite cookie on the API domain |
| L-2 | The Azure adapter issues account-key SAS | Phase 2: user-delegation SAS through managed identity (no account keys) |
| L-3 | The mobile passport screen has no 3D viewer yet | Phase 2: WebView hosting `@passport/viewer3d`, or a native GL approach (decision needed) |
| L-4 | E2E runs in headless Chromium with software WebGL | Says nothing about GPU or mobile performance; add a device lab in Phase 2 |
| L-5 | Unknown non-API URLs return Django's HTML 404, not the JSON error envelope | Add a JSON `handler404` for `/api/` |
| L-6 | ESLint reports 14 style warnings in the mobile code (inline styles, `void`), and no errors | Tidy up in Phase 2 |
| L-7 | The mobile status bar uses light icons on the light sign-in screen, so they have low contrast | Phase 2: set the status bar style per screen |
| L-8 | Android debug builds need a space-free SDK path on Windows (B-07). The build guard enforces this. | Keep the guard. A CI or Linux build is unaffected. |
