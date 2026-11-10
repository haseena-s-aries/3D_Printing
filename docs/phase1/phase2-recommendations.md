# Phase 2 development recommendations

The order below follows dependencies. Items marked **decision** need the business owner (or Legal/Ops) before
they can start. Nothing here changes BRD v0.4.

## 1. Before Phase 2 coding starts (decisions and inputs)

1. **Supply real samples (B-01).** About 5 to 10 STEP files (single parts and at least one assembly, including
   the largest expected) and 3 to 5 DWG files. They will be processed locally only. These samples drive CAD
   fidelity acceptance and the OQ-31 limits.
2. **Choose the container runtime (B-02).** Docker Desktop (licensing depends on company size), Podman or
   Rancher Desktop. All three can build the same OCI images.
3. **Approve a minimal Azure dev/test footprint (B-03), decision plus spend.** That means one resource group
   with PostgreSQL Flexible Server, a Storage account, Key Vault, Container Apps (API and worker) and Entra ID
   app registrations. Estimate the cost before provisioning.
4. **Arrange a macOS build path (B-04).** Either a Mac mini or a macOS CI runner, plus an Apple Developer
   account. Without it the iOS app can't be built.
5. **Close the critical decisions** in this order, because each one unblocks the most work:
   - **OQ-35:** the approval and publication workflow.
   - **OQ-36:** manufacturing eligibility.
   - **OQ-49 and OQ-64:** the mobile connectivity and distribution model.
   - **OQ-27:** the DWG approach. This is a licensing decision, for example the ODA Drawings SDK or a
     server-side DWG→PDF/SVG route.
   - **OQ-37 and OQ-38:** consent and ownership (Legal).

## 2. Recommended Phase 2 batches

| # | Batch | Depends on | Notes |
|---|---|---|---|
| 1 | **CI live and containerised** | B-02, repository remote | Push the repository and fix any first-run CI issues (Linux OCCT wheels, Android SDK). Add Dockerfiles for the API and the worker. Make the E2E spec portable (remove the Windows venv path) and run it in CI. |
| 2 | **Azure dev environment** | B-03 approval | Use Bicep or Terraform. Use managed identity everywhere and user-delegation SAS (L-2), with secrets in Key Vault. Run the existing test suite against Azure PostgreSQL. |
| 3 | **CAD fidelity with real samples** | B-01 | Write golden-file tests: triangle count, bounding box and visual snapshots. Set time and memory limits per job, with retries and dead-lettering, and measure them to propose OQ-31 limits. Add assembly structure in the GLB node tree. |
| 4 | **Passport workflow** | OQ-35 (and OQ-05 roles) | Implement it behind the existing `policies.seams` with the "publication" seam. Add a server-side state machine with audited transitions and evidence-level rules. Keep the DB immutability triggers. |
| 5 | **Manufacturing eligibility** | OQ-36 | Use the same seam pattern. Add inventory filters by evidence level and eligibility (MOB-010). |
| 6 | **Mobile completion** | OQ-49, OQ-64, B-04 | Add a 3D viewer in a WebView reusing `@passport/viewer3d` (L-3), and PDF viewing. Production deployment configuration. Biometric unlock for the stored refresh token. Device testing on at least 2 Android and 2 iOS devices (B-05), including the ARM builds, which so far are compiled but have never run. Release signing and an embedded JS bundle; only the debug APK has been built (B-07 is closed). Set the status bar style per screen (L-7). |
| 7 | **Web hardening** | none | Move refresh to an httpOnly cookie (L-1). Set a CSP and security headers. Add a JSON 404 for `/api/` (L-5). Run accessibility checks (axe) in E2E. |
| 8 | **DWG viewing** | OQ-27 licence | Add it as a new derivative kind through the same worker and job pattern. Storage and the API need no changes. |
| 9 | **Watermarking** | OQ-33 | Apply it at derivative generation or download time. The download path already centralises access. |
| 10 | **Operational readiness** | 2 | Structured logs to Azure Monitor, plus a request-id dashboard. Alerts on job failures. Backup and restore drill for PostgreSQL and Blob storage, including point-in-time restore. Rate limits beyond login. |

## 3. Keep doing

- Every new tenant table gets RLS in a `0002_security`-style migration. The regression test fails if one is missed.
- Gate every open-policy action through `apps/policies/seams.py`; don't add ad-hoc flags.
- Regenerate `docs/openapi.yaml` and `packages/api-types` on every API change. CI checks for drift.
- Don't send customer CAD files to external services.
- Windows Android builds need a space-free SDK path. Keep the guard in `mobile/android/app/build.gradle`; it
  can be removed only once the toolchain stops using 8.3 short names for compilers in paths with spaces.
