# CN-007 — AI Spare Parts Intelligence: role-based access and client experience

Status: implemented in the access-test environment only (`AI_CLIENT_ACCESS_ENABLED`, synthetic pilot company).
External AI processing and client sharing for any real customer company stay off until reviewed (see §6).

## 1. Audit: current access (before this change)

| Area | How it works today |
|---|---|
| Role capabilities | `apps/tenancy/permissions.py`. The `intelligence.*` capabilities exist only with `PART_INTELLIGENCE_ENABLED`. `intelligence.view`, `.assess` and `.review` belong to Aries Engineers; `intelligence.usage_admin` belongs to the Aries Admin (operator tenant only). No client role holds any AI capability. |
| Company scope | Every AI endpoint reads `request.tenant`. An Aries Engineer works in a client company only through a membership in that tenant (assignment). |
| Project scope | `apps/projects/scoping.restrict`: project-limited engineers see only parts and runs of their assigned projects. |
| Database | Every intelligence table is tenant-owned with forced row-level security (`app.tenant_id`); an empty context matches no rows. Assessment and review rows are append-only by design. |
| External AI | Allowed only for companies in `AI_ALLOWED_COMPANIES` (access-test: `synthetic-inventory-pilot`), with rate limits, daily budget, input whitelist, price stripping and a total deadline. |
| Cost visibility | Engineers see full cost breakdowns, sources, quotation references and estimated savings. The Admin sees AI usage and estimated AI cost per company, and aggregate run counts and savings (`/admin/assessment-summary/`). |
| Recommendation review | Engineers only, with separation of duties: "approved for further study" and "corrected" must come from an engineer other than the one who generated the version. Formal approval is refused (OQ-35/36). |
| Report downloads | Assessment-run Excel/PDF reports are Aries-internal (`intelligence.view`). |
| Frontend | The AI pages sit under Inventory import tabs and the part page, shown only to engineers. Clients see nothing. |
| Client requests | Manufacturing enquiries and 3D-scanning requests (`apps/servicerequests`) notify assigned Aries staff and appear in `/incoming`. There is no "assessment" request. |

Gaps against the intended model:
- The Admin has no management view of coverage, progress or reviews, and no control over client access.
- Clients cannot see results, request assessments, or download anything AI-related.
- There is no disclosure workflow separating internal results from client-visible ones.

## 2. Proposed access (implemented)

New capabilities exist only with `AI_CLIENT_ACCESS_ENABLED` (as well as `PART_INTELLIGENCE_ENABLED`).

| Capability | Roles | Purpose |
|---|---|---|
| `ai.management` | Aries Admin (operator tenant) | AI Management Dashboard: aggregates per client, AI usage and cost, client workspace on/off. |
| `ai.share` | Aries Engineer (assigned, in scope) | Approve a reviewed result for client sharing, share it, withdraw it. |
| `ai.workspace` | Client Admin, Client Engineer, Procurement, Client User, Auditor | Open "My Parts Intelligence". The service also requires the company to be enabled and, except for the Client Admin, member access (§3). |
| `ai.request` | Client Admin, Client Engineer | Request an assessment or reassessment of a part. |
| `ai.prices` | Client Admin, Procurement | See client-facing quoted prices that an engineer explicitly released. |
| `ai.reports` | Client Admin, Client Engineer, Procurement | Download the client-facing assessment report of a shared result. |
| `ai.members` | Client Admin | Grant or remove other members' access to the workspace. |

### What each role can do

**Aries Admin**
- AI Management Dashboard:
  - Client-wise inventory and assessment coverage, classification progress, feasibility status and pending reviews.
  - Estimated vs verified savings and quarterly trends, from completed runs.
  - AI usage and estimated cost.
  - Client workspace on/off.
- All of it is aggregates: no part numbers, descriptions, drawings, files, prices per part or engineering records.
- No technical review, sharing approval or manufacturing approval authority.

**Aries Engineer (assigned)**
- Unchanged: import, part intelligence, feasibility, cost comparison, recommendations, review queue and quarterly runs, within company/project scope and the existing separation of duties.
- New: the client-sharing workflow (§4).

**Client Admin**
- Sees every result shared with the company, including released quoted prices.
- Requests assessments, downloads client reports, views the company dashboard, and manages member access.

**Client Engineer** (allowed by role; the Client Admin can remove access)
- Sees shared technical findings, evidence gaps and the option comparison, without prices.
- Requests assessments and downloads client reports.

**Procurement** (only when granted by the Client Admin)
- Read-only status and the client-safe comparison, plus released quoted prices.
- Downloads client reports.
- Raises manufacturing enquiries / RFQs through the existing request workflow (`requests.create`).

**Client User and Auditor** (only when granted)
- Read-only status and shared summaries: no prices, no downloads, no requests.

Every client can see only its own company. Project-limited Aries staff stay limited. Nothing a client does calls Gemini.

## 3. Company and member access

- **`ClientAIWorkspace` (per client company):** the Aries Admin switches the client workspace on or off. Switching on is
  refused for companies not listed in `AI_CLIENT_SHARING_COMPANIES` (access-test: `synthetic-inventory-pilot`). Real
  companies need a reviewed decision first. While a company is off, its clients see nothing and engineers cannot
  approve or share results for it; withdrawal stays possible.
- **`AIWorkspaceMember` (per member):** the Client Admin grants or removes access for Client Engineers (default
  allowed), Procurement, Client Users and Auditors (default not allowed). The Client Admin's own access follows from
  the role and cannot be removed.
- Every change is audited.

## 4. Disclosure workflow (information sharing only)

States per part:
1. **Internal draft.** A recommendation version exists but has not been reviewed.
2. **Engineering reviewed.** The latest version has an engineering review decision.
3. **Approved for client sharing.** An Aries Engineer who did not generate the version freezes a client-safe snapshot
   of that exact version (`SharedAssessment`). The snapshot holds the client summary written by the engineer, the
   technical status of each option and the mandatory requirements met or not, evidence gaps and the source version
   numbers. Released quoted prices are optional; the engineer enters them explicitly, and they never come from
   internal costs.
4. **Shared with client.** An engineer publishes the approved snapshot; the company's Client Admins are notified. A
   newer shared snapshot of the same part supersedes the previous one.
5. **Withdrawn / superseded.** A withdrawal records a reason and is visible to the client as "withdrawn".

Rules:
- These states are for information disclosure only. They never set approval, publication, eligibility or release, and
  OQ-35/OQ-36 gates stay closed.
- Snapshots are immutable: a database trigger blocks changes to their content; only the status moves forward, and
  every change is an append-only `DisclosureEvent`.
- A new or changed AI result never becomes client-visible by itself. Clients read only shared snapshots, never the
  internal assessment tables.
- The client view never contains AI suggestion text, prompts, model names, internal cost breakdowns, sources,
  supplier or quotation references, margins, savings or reviewer findings. A whitelist builds it, and tests check for
  leaks.

## 5. Client requests

A Client Admin or Client Engineer requests an assessment or reassessment of a part (reason and remarks). It is a
`ClientRequest` of kind `assessment`, using the existing references, history, notifications to the assigned Aries
staff (project scope respected) and the `/incoming` queue. Aries replies, requests information or closes it there.
The client tracks it under My requests and on the part in My Parts Intelligence. Missing documents are provided
through the existing supporting-document upload and request messages.

## 6. Environment and safety

- **Isolation:** the code is shared by all local environments. Everything new is behind `AI_CLIENT_ACCESS_ENABLED`
  (set for access-test only), and the new tables are created only in `passport_access`. The showcase and engineering
  validation databases are not migrated or changed.
- **External AI:** still only for `AI_ALLOWED_COMPANIES`. Client actions never trigger Gemini.
- **Before any real customer company:** a reviewed decision is needed to add it to `AI_ALLOWED_COMPANIES` (external
  AI) or `AI_CLIENT_SHARING_COMPANIES` (client sharing).
