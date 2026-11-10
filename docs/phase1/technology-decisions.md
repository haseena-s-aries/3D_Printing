# Technology additions and justification (Phase 1)

The approved stack is listed in Phase 0 doc 01. Everything below was added in Phase 1, with a reason for each.
Nothing here is a paid service or a licensed SDK.

| Addition | Where | Why it is needed | Alternatives considered |
|---|---|---|---|
| `pgserver` 0.1.4 (embedded PostgreSQL), dev/test only | backend tests and local dev | The brief requires PostgreSQL for integration tests, and the container runtime is undecided. This gives a real PostgreSQL 16 with no Docker and no system install. CI uses a normal PostgreSQL service instead. | Docker (not available, B-02); a manual PostgreSQL install (extra setup per developer) |
| `tzdata` (dev/test only) | `scripts/localdb.py` | The pgserver Windows build ships without time zone files. Django needs `SET TIME ZONE 'UTC'`. | None simpler |
| `djangorestframework-simplejwt` (+ token_blacklist) | auth | Signed access and refresh tokens with rotation and revocation. The tenant claims are added and re-validated by our own authentication class. | Session cookies (no good fit for native mobile clients) |
| `drf-spectacular` | API schema | OpenAPI 3 generated from code, which drives the docs and the shared TypeScript types | Hand-written schema (would drift) |
| `openapi-typescript` (dev) | `packages/api-types` | One set of API types for web and mobile, generated from the schema | Hand-written types |
| `react-router-dom` 7 | web | Standard routing for the React SPA | none |
| Vitest + Testing Library + jsdom (dev) | web tests | Native to Vite; runs the same TypeScript and JSX as the build | Jest (needs separate transpilation config) |
| Playwright 1.64 (dev) | `e2e/` | Real-browser E2E covering auth, upload, worker, viewer and download | Cypress (weaker multi-tab and download support) |
| `@react-navigation/native` + native-stack, `react-native-screens`, `react-native-safe-area-context` | mobile | The de facto React Native navigation stack, using native screen containers on iOS and Android | Expo Router (would also need the Expo toolchain) |
| `react-native-keychain` 10 | mobile | Keeps the refresh token in iOS Keychain and Android Keystore-backed storage (`WHEN_UNLOCKED_THIS_DEVICE_ONLY`), never in AsyncStorage | AsyncStorage (not secure) |
| `vtk` 9.6.2 (`--no-deps`) | CAD worker | The `cadquery-ocp` binary needs VTK DLLs at import time; this was shown in Phase 0. It is not used directly. | None: OCP fails to import without it |

No Kubernetes, message broker, Redis or microservices were introduced. The job queue is a PostgreSQL table
claimed with `FOR UPDATE SKIP LOCKED`.
