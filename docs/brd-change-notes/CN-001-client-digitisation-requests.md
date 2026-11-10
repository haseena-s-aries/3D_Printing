# CN-001: Client digitisation (3D scanning) requests

| | |
|---|---|
| **Status** | **PROPOSED, not approved.** Draft for business-owner review. |
| **Baseline** | BRD v0.4 and Requirements Register v0.4. Both are unchanged by this note. |
| **Date** | 2026-10-16 |
| **Requirement IDs** | DSR-a to DSR-e are provisional labels. Official IDs are allocated only if this note is approved. |
| **Implementation** | None. No code, data model or screen exists for these items. |

## 1. Why this change is proposed

BRD v0.4 describes the digitisation *service*, but not how a client *starts* it.

**What the BRD has:**
- BR-022 (CONFIRMED): the operator performs site collection, scanning, reverse engineering, model, drawing and
  print-file preparation.
- FR-03 and BR-044 (PROPOSED): projects with steps, owners and status.
- FR-03 names a "client sponsor" and the trigger "Project approved".

**What it lacks:**
- A way for a client to ask for parts to be digitised.
- An operator queue for those requests.
- Client-visible progress.
- Any rule on quotation or approval before work starts.

**Source note:** no stakeholder statement in the transcript or brief explicitly asks for a client request form.
The proposal is derived from the BRD lifecycle (§N.1, steps A–D), FR-03 (client sponsor) and BR-044. It needs
confirmation as a business requirement.

## 2. Existing requirements this note builds on (unchanged)

| ID | Summary | Class (v0.4) | Relation to this note |
|---|---|---|---|
| BR-022 | Operator digitisation service (site visit, scan, RE, model, drawings, print file) | CONFIRMED, Must | The service the request asks for |
| FR-03 | Digitisation projects: steps, owners, status, deliverables; client sponsor; trigger "Project approved" | CONFIRMED / PROPOSED | An accepted request creates a project |
| BR-044 | Project step tracking; a project can't close with a mandatory step open | PROPOSED, Must | Steps reused for request status (DSR-c) |
| FR-05 | Scan and RE records, deliverables, CAD versions, technical review | CONFIRMED / PROPOSED | Deliverables of an accepted request (DSR-d) |
| BR-023 | Platform does not scan or model; inputs are accepted as files | PROPOSED, Must | Scanning stays outside the platform |
| BR-015 | Technical and procurement teams as requesters | CONFIRMED, Should | Basis for who may submit (decision D3) |
| BR-032 | Separate digitisation and maintenance charges; platform handling TBC | CONFIRMED, Should | Basis for optional quotation (DSR-e, D2) |
| BR-053 | Notifications for request status, approvals, quotations | PROPOSED, Should (OQ-25) | Request notifications |
| ACC-001 | Operator access to client data needs role, purpose, time-limited grant, audit | CONFIRMED (terms open, OQ-37) | Operator queue across clients (D5) |
| OQ-31 | Upload size limits | Open | Scan-data limits (D4) |

Not related, and not changed by this note:
- MOB-027 is QR/barcode label scanning.
- BR-016 / OQ-10 cover manufacturing vendor RFQ, which is superseded or deferred.
- OQ-35 and OQ-36 cover passport approval and manufacturing authorisation.

## 3. Proposed requirements

### DSR-a: Client digitisation request

| | |
|---|---|
| **Description** | An authorised client user submits a request to digitise one or more spare parts. |
| **Proposed priority** | Must, if the request flow is approved for MVP |
| **Who** | Client roles decided under D3 |
| **Request header** | Title; site and location; equipment or asset reference; reason (obsolete / long lead time / failure / other); urgency (routine / urgent breakdown); preferred dates; site-access and safety constraints; contact person |
| **Part lines (1..n)** | Part name; OEM or client part number; quantity installed; known material; criticality as the client sees it; existing CAD or drawings (yes/no); notes |
| **Attachments** | Photographs, existing drawings and existing CAD, through the existing validated upload (originals preserved) |
| **Acceptance criteria** | A request can't be submitted without a title, a site and at least one part line. A submitted request gets a reference number and appears in the operator queue. It is visible only to its own organisation and to authorised operator staff. Submission is audited. |

### DSR-b: Operator review and acceptance

| | |
|---|---|
| **Description** | Operator staff review each request. They can request more information, accept it or decline it with a reason. |
| **Proposed priority** | Must, together with DSR-a |
| **Acceptance** | Creates a digitisation project (FR-03) and draft spare-part records (FR-04) from the part lines, linked to the request. No passport is created at this point. |
| **Acceptance criteria** | Every decision records user, time and reason, and the client sees it. A declined request can't be accepted later without resubmission. Accepting creates exactly one project and one draft part per accepted line. |

### DSR-c: Request and project status visible to the client

| | |
|---|---|
| **Description** | The client sees the request status and, after acceptance, the project's step progress (BR-044). |
| **Request states** | Submitted → Information requested → (Quoted → Quote accepted, only if DSR-e is approved) → Accepted / Declined / Withdrawn → In progress → Completed |
| **Project steps (BR-044)** | Site visit → scan → reverse engineering → model verified → drawing → print file → validation → passport draft created |
| **Proposed priority** | Should, or Must if BR-044 is confirmed as Must |
| **Acceptance criteria** | Each state or step change is time-stamped, attributed and visible to the client. The client sees step status but no internal notes. Notifications follow BR-053 once OQ-25 is decided. |

### DSR-d: Scan and reverse-engineering deliverables

| | |
|---|---|
| **Description** | Engineers attach the deliverables of each step to the project and parts. Scanning and CAD work stay outside the platform (BR-023). |
| **Existing support** | STEP models (original preserved, converted to GLB for the 3D viewer), drawings (PDF; DWG stored only, OQ-27), specifications (PDF) and photographs: all versioned. |
| **New, subject to D4** | Raw scan data, e.g. STL, OBJ, PLY, E57 point clouds |
| **Acceptance criteria** | Every deliverable is linked to its step, part and project, versioned and checksummed. The completed STEP model becomes the part's 3D model. The passport draft is created through the existing passport function. Approval and publication remain gated (OQ-35). |

### DSR-e (optional): Digitisation quotation and client acceptance

| | |
|---|---|
| **Description** | Before work starts, the operator issues a quotation for the request; the client accepts or rejects it in the portal. |
| **Proposed priority** | Undecided. Depends on D2. Default is out of MVP, with quotations handled outside the platform. |
| **Acceptance criteria (if approved)** | A quotation is versioned and has a validity date. Only an authorised client role can accept it. Acceptance is audited, and work can't start before acceptance unless the operator records an override with a reason. |
| **Not included** | Pricing calculation, invoicing and payment (BR-031 and BR-032 platform handling is TBC). |

## 4. Out of scope of this note

- Scanning or CAD reconstruction inside the platform (BR-023).
- External scanning-vendor selection or RFQ (in line with OQ-03 / BR-016).
- Passport approval, publication, evidence-level transitions (OQ-35).
- Manufacturing requests and authorisation (OQ-36).
- Billing, invoicing and payment.
- Mobile submission of requests (could follow MOB rules later; needs its own decision).

## 5. Placement (indicative, for review)

| Portal | Proposed location |
|---|---|
| Client Portal | New "Digitisation requests" area: list, new request, request detail with status timeline and messages. A "Request digitisation" action on Projects. Accepted requests link to their project and parts in the digital inventory. |
| Operator Portal | Request queue (new / needs information / accepted / in progress / completed). Request detail with accept, request information and decline. The project gains the BR-044 step tracker with owner, status and deliverables per step. |

## 6. Open decisions for the business owner

| # | Decision | Options | Recommended (proposal) | Why |
|---|---|---|---|---|
| **D1** | Is a client-initiated digitisation request part of MVP? | A) Yes, DSR-a to DSR-d. B) No: the operator creates projects; the client sees status only (DSR-c). C) Later phase. | **A** | Closes the gap at the start of the lifecycle and gives the FR-03 "client sponsor" a real entry point. It reuses projects, parts, files and the viewer that already exist. |
| **D2** | Is quotation and client acceptance (DSR-e) in MVP? | A) Out of MVP: quotes handled offline, the operator records "commercially agreed" with a reference. B) In MVP, without pricing logic. C) In MVP, with pricing. | **A** | BR-032 leaves platform handling of charges TBC, and BR-016 / OQ-10 keep quotation out of MVP. A reference field keeps traceability without commercial features. |
| **D3** | Which client roles may submit and approve requests? | A) Client admin, client engineer and procurement submit; client admin approves (as sponsor). B) All client roles. C) Client admin only. | **A** | Matches BR-015 (technical and procurement requesters) and FR-03 (client sponsor). Client users stay read-only. |
| **D4** | Which scan-data formats are stored, and are they viewable? | A) Store STL/OBJ/PLY (mesh) and E57 (point cloud) as originals only, without a viewer, with provisional size limits. B) Also view meshes in the 3D viewer. C) No raw scan data, only the final STEP. | **A** | Preserves source evidence for traceability, adds no viewer work, and keeps limits provisional until OQ-31. B could follow later (STL/OBJ are simple to view). |
| **D5** | How do operator staff see requests across clients? | A) A dedicated operator intake queue that reads request summaries across client tenants under an audited, explicitly designed policy. B) Operators see requests only inside each client they are assigned to. C) Requests stored in the operator tenant. | **A**, designed together with the W3 operator work queue | B makes intake depend on prior assignment, which doesn't work for a new request. C breaks tenant ownership of client data. A needs a security design that respects ACC-001 and possibly OQ-37. |

## 7. If approved

1. Record the decisions D1 to D5 in the Decision Log.
2. Allocate official requirement IDs.
3. Add the rows to the Requirements Register and a BRD v0.5 change entry. That is a separate step: this note does not modify BRD v0.4.
4. Then propose an implementation batch.
