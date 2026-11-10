# CN-005: Digital Passport PDF report (PROPOSAL, for review before implementation)

| | |
|---|---|
| **Status** | **R1–R8 APPROVED (26 Oct 2026), with clarifications.** Implemented in the isolated access-test environment; see §9. Sections 1–8 keep the proposal for reference. |
| **Date** | 2026-10-26 |
| **Basis** | - Meeting `3d pr.mp3`: report requirement 09:49–13:33 ("a button where he can generate a report, PDF"; "we have to fix a format… all these things come in a single page"); front/top/isometric views 05:25–05:50.<br>- Project 1 sample report (`Sample Projects/Project 1/Sample report - Final expected report…pdf`, 8 pages, read locally only).<br>- BRD v0.4: BR-025/026/041, FR-08/09, BR-027 and OQ-33 (watermark), OQ-35/36.<br>- CN-002 (roles, D-13 notes), CN-003, CN-004 (job sheets internal). |
| **Sample layouts** | `AccessTest/evidence/report-sample/sample-passport-report-client.pdf` (2 pages) and `…-internal.pdf` (3 pages). Synthetic data only; produced by `AccessTest/tools/report-sample.mjs`. |
| **Unchanged** | Production-release rules, approval and eligibility gates, databases |

## 1. Project 1 sample report: structure (what the business expects)

| Pages | Content | In the platform today |
|---|---|---|
| 1–2 | **Manufacturing & Test Specification (MTS).**<br>- Header: logo, title, document number, revision.<br>- Title line.<br>- Specification block: job no., revision, company name, location, part name, drawing no., 3D printing technology, feedstock specification, applicable standards, substrate plate material.<br>- **3 build-preparation views** with supports.<br>- **Quantity to be produced** (part plus vertical/horizontal tensile, density cube, hardness cube, vertical/horizontal Charpy specimens).<br>- **Manufacturing process** steps 1–8 (feedstock, design for AM, 3D printing incl. machine, layers and gas, heat treatment, wire EDM, support removal, post-processing, machining).<br>- **Inspection and test specifications** (test method, reference document, acceptance criteria, inspection frequency).<br>- Marked "CONFIDENTIAL". | Mostly in passport R-L2 / BR-026 / BR-041 and the job sheet (CN-004). Some fields are missing (§3). |
| 3 | 2D drawing | Drawing file (PDF) on the part or passport |
| 4 | Final quality inspection report: dimensions, nominal, tolerance, instrument, reading; quantities accepted and rejected; prepared, checked, verified and approved roles | Only as an uploaded document (R-L3 "dimensional inspection"); no structured inspection data |
| 5–8 | Laboratory test reports (tensile, hardness) | Only as uploaded documents |

**Observation.** The sample is an **internal, order-level** document (job number, quantities and test specimens per build).
The meeting asks for a **client-shareable** report from the passport. Two variants are therefore proposed:
- a **client-facing passport report** with permitted content;
- an **Aries-internal report** that adds the manufacturing specification.

The order-level MTS with job number and specimen quantities fits the CN-004 job sheet, as a later "job-sheet report"
(decision R2).

## 2. Field mapping

**Variant columns:** **C** = client-facing; **I** = Aries-internal; **–** = never in a PDF.

**Source marks printed next to each value:**
- **V**: from an approved passport revision.
- **D**: from a passport draft, not approved.
- **C**: client-submitted, not verified.
- **M**: not recorded. Missing values are printed as "Not recorded" and never filled in.

| Report section / field | Sample report | Source in the platform | C | I | Needs engineer confirmation |
|---|---|---|---|---|---|
| **Header**: report number, passport number, revision and status, generated at/by, page x of y, fingerprint | Doc no., revision | Report record (new); `DigitalPassport.passport_number`; `PassportRevision.revision_number/status` | ✓ | ✓ | no |
| Status banner (Draft / Not verified / Not approved; not a manufacturing authorisation) | n/a | revision status, evidence level, eligibility (stored states only) | ✓ | ✓ | no |
| Client company, project | Company name, location | `Tenant.name`, `Project` | ✓ | ✓ | no |
| Part number, name, category, equipment, OEM, application | Part name, drawing no. | `SparePart` + `field_provenance` | ✓ | ✓ | when marked C |
| Criticality | n/a | `SparePart.criticality` (existing classes only; AMSL not defined, OQ-36) | ✓ | ✓ | yes |
| Model views: front, top, isometric | 3 build-prep views (with supports) | Rendered from the passport's STEP → GLB (§6); **not** build-preparation screenshots | ✓ | ✓ | engineer selects the STEP version |
| Original material, identification method | Feedstock "SS316L" | R-L1 `original_material_grade`, `material_identification_method` | ✓ | ✓ | when D or C |
| Proposed material and reason; suitability | n/a | R-L1 `proposed_material(_reason)`; clone/enquiry; suitability "Not assessed" | ✓ | ✓ | yes |
| Dimensions, atmosphere, environment, motion, RPM, IP, CAD/drawings available | n/a | R-L1 | ✓ | ✓ | when D |
| Applicable standards, tolerances, NDT, MTC required, test coupons | Applicable standards; inspection table | R-L2 | ✓ (R3) | ✓ | when D |
| Mechanical acceptance (property, requirement, unit, standard) | Acceptance criteria | R-L2 `mechanical_acceptance` | ✓ (R3) | ✓ | when D |
| Inspection frequency per test | "Prior to every build", "Sample based…" | **missing** (no field) | – | – | new field needed (R6) |
| Manufacturing process / 3D printing technology | Laser powder bed fusion | R-L2 `manufacturing_process` | – (R3) | ✓ | when D |
| Feedstock, machine, layer thickness, inert gas, support strategy, build orientation, heat treatment, post-processing, machining, printing/post-processing hours | Process steps 1–8 | R-L2 `manufacturing_spec` (BR-026) | – | ✓ | when D |
| Process parameters (BR-041) | Layer 40/80 µm, gas purity | R-L2 `process_parameters` | – | ✓ | when D |
| Manufacturing solution (free text) | Design-for-AM notes | R-L2 `manufacturing_solution` | – | ✓ | when D |
| Substrate plate material | C45 – 1.0503 | **missing** (no field) | – | – | new field (R6) |
| Job number, quantities, test-specimen quantities | Job no.; Qty to be produced | Job sheet (CN-004) and enquiry quantity | – | – | belongs to the job-sheet report (R2) |
| Document references: title, category, version, upload date, SHA-256 prefix, R-L3 role, QA verification "Pending (OQ-35)" | Appended drawing, QC and test reports | `EngineeringFile` / `FileVersion`; R-L3 `evidence` | ✓ (only files the client may view) | ✓ | no |
| Appended PDF pages (drawing, inspection, test reports) | Pages 3–8 | linked PDF files | – (R4) | – (R4) | yes: choose which |
| Data completeness R-L1/R-L2/R-L3 | n/a | `completeness()` (guidance only) | ✓ | ✓ | no |
| Engineering notes (D-13) | n/a | revision `content.notes` | **–** | **–** | never printed |
| Job sheets (CN-004), internal remarks | n/a | job sheet tables | **–** | **–** | never printed |
| Original STEP/DWG files | n/a | files | **–** | **–** | never attached |

### Information missing for a report like the sample

These are not in the data model and must not be invented:
- Aries document-control number (the "QHSE/…" style; R7)
- substrate plate material
- inspection frequency per test
- test-specimen quantities
- structured dimensional-inspection results and signatories
- certificate data

Until decided, they appear only as attached documents or "Not recorded".

## 3. Confidential Aries manufacturing information

Excluded from the client-facing version:
- the manufacturing specification (BR-026)
- process parameters (BR-041)
- the manufacturing solution text
- the manufacturing process selection (subject to R3)
- printing and post-processing hours (commercial)
- the passport-spec job number
- job sheets
- engineering notes

The sample report itself is marked "CONFIDENTIAL". The meeting asked for a client report to share with third parties
(11:23–13:33), which conflicts with this classification and with IP/download policy (meeting-analysis K3, OQ-33,
OQ-38). Decision **R3** sets the client content.

## 4. Roles

Proposed, in line with CN-002:

| Role | Client-facing version | Aries-internal version |
|---|---|---|
| Aries Engineer (assigned company/project) | generate, preview, download | generate, preview, download |
| Aries QA (assigned) | preview, download | preview, download |
| Aries Admin | none (D3a: summaries only) | none |
| Client Administrator, Client Engineer | generate (from the current revision), preview, download | none |
| Client User | preview (download per **R5**) | none |
| Procurement, Auditor | preview (R5) | none |
| Other companies | none (tenant row-level security) | none |

Project-limited engineers only for parts in their projects (CN-002 D4).

## 5. Revisions, verification and history

- **One report = one immutable PDF** generated from one passport revision. The record keeps:
  - passport and revision number
  - revision status at generation
  - variant
  - content fingerprint (SHA-256 of the data)
  - generated by and at
  - PDF SHA-256 and size
- **Report number** (provisional, R7): `RPT-<passport>-R<rev>-<seq>`, plus `-INT` for the internal variant.
- **Banner and watermark:**
  - While the revision is not approved: "DRAFT · NOT VERIFIED · NOT APPROVED".
  - Once approval rules exist (OQ-35): "APPROVED REVISION N", but still "not a manufacturing authorisation" (OQ-36).
- Each value carries a **source mark** (V/D/C/M). QA verification of R-L3 documents shows "Pending (OQ-35)".
- **History:** a "Reports" tab on the passport lists generated reports (number, revision, variant, by, when, size).
  Earlier reports stay downloadable and are marked "superseded" when a newer revision exists.
- **Downloads:** short-lived signed links (like file downloads), audited as `passport_report.downloaded`; generation is
  audited as `passport_report.generated`.
- **Watermark** with recipient and organisation name (BR-027) is optional; the policy is still open (OQ-33). Proposed:
  the client variant carries "Issued to <company> · <date>" in the footer.

## 6. Technical approach (proposed)

- **Rendering:** HTML template to PDF on the server.
  - Option A (proposed): Chromium (Playwright) in the background worker. It is already used for testing, needs no new
    licence, and matches the sample layout exactly.
  - Option B: ReportLab (pure Python, BSD).
  - Generation runs as a background job; the PDF is stored like a file derivative with its SHA-256.
- **Model views:** generated once per STEP version by rendering the existing GLB derivative in the same headless browser
  with the viewer's standard cameras (front, top, isometric). The three images are stored as derivatives.
  - If no GLB exists, the report prints "View not available (no 3D model)".
  - Build-preparation screenshots with supports, as in the sample, can only be included as uploaded images (e.g. R-L3
    "print orientation"). Internal variant only.
- **Nothing is sent to external services.**

## 7. Decisions required

| # | Decision | Options | Recommendation |
|---|---|---|---|
| R1 | Variants | A) client-facing and Aries-internal (proposed); B) one report | **A** |
| R2 | Order-level MTS (job no., quantities, specimens) | A) later "job-sheet report" from CN-004; B) in the passport report | **A** |
| R3 | Client-facing content | A) identification, material, dimensions, views, quality and acceptance requirements, document references; no process parameters (proposed); B) also manufacturing process name; C) full specification (meeting wish; needs IP decision) | **A**, with the process *name* optional (B) |
| R4 | Appending document pages (drawing, inspection, test reports) | none / drawing only / selected PDFs | **Internal:** selected PDFs. **Client:** drawing only, if the client may download it (CN-002). |
| R5 | Download by Client User, Procurement, Auditor | preview only / download | preview only |
| R6 | New fields to match the sample: substrate plate, inspection frequency, specimen quantities | add to R-L2 / job sheet / omit | add inspection frequency to the acceptance rows; substrate plate and specimens to the job sheet |
| R7 | Report and document numbering (Aries QHSE document control) | provisional `RPT-…` / Aries format | provisional until Aries supplies the format |
| R8 | Branding: logo and company details in the header | text only / Aries logo file supplied by Aries | supplied logo; no logo copied from samples |

## 8. Implementation outline (after approval)

1. **Data:** `PassportReport` record (tenant row-level security, immutable) and a report file in storage.
2. **Worker jobs:** model-view rendering and PDF generation.
3. **API:**
   - `POST /passports/{id}/reports/` with `{variant, revision}`
   - `GET /passports/{id}/reports/`
   - `POST /passports/{id}/reports/{n}/download-link/`
4. **Web:** "Generate report" and the "Reports" tab on the passport; client entry on the part and passport pages.
5. **Tests:**
   - variant content: the client PDF never contains BR-026/041 fields, notes or job data
   - source marks and missing values
   - draft watermark
   - roles and tenant/project isolation
   - audit of generate and download
   - immutability and history
   - no change to passport or approval states


## 9. Approved and implemented (26 Oct 2026)

### Clarifications and how they are met

| # | Requirement | Implementation |
|---|---|---|
| R1 | Separate client-facing and Aries-internal reports | `PassportReport.variant` = client / internal. The internal number ends with `-INT`; every internal page carries an "ARIES CONFIDENTIAL" banner and footer. |
| R2 | Job numbers, quantities, specimens and job-level specifications stay in the Job Sheet | The passport report never reads job sheets. The internal report shows only the passport specification's own `job_number` field. |
| R3 | Client content limits; unverified status unmistakable | Client report: identification, materials, dimensions, CAD views, quality requirements, document references. Process parameters, the BR-026 specification, manufacturing solution and process, and engineering notes are never collected for it. Draft and client values carry D/C marks; a red status banner and the watermark are shown. |
| R4 | Attachments | Client: only `drawing` PDFs, and only when the user holds `files.download_original`. Internal: selected PDFs of the passport's part. Appended after the report pages (`pypdf`). STEP/DWG are never attached. An unreadable PDF is refused (400). |
| R5 | Roles, enforced server-side | `reports.generate_client` (Aries Engineer, Client Administrator, Client Engineer)<br>`reports.download_client` (+ Aries QA)<br>`reports.preview_client` (+ Client User; **page images only**, never the PDF file)<br>`reports.generate_internal` (Aries Engineer)<br>`reports.view_internal` (Aries Engineer, QA)<br>Procurement and Auditor have no report access (they hold no 3D/preview right in CN-002). The Aries Admin has none. |
| R6 | Inspection frequency | `mechanical_acceptance[].frequency` (optional, provisional list `inspection_frequencies`); the R-L2 form has an "Inspection frequency" column |
| R7 | Provisional numbering | `RPT-<passport>-R<rev>-<seq>`, plus `-INT` |
| R8 | Branding | Text-only "ARIES" until an approved logo and company details are supplied (`REPORT_BRAND_NAME`) |
| 1 | Watermark on unapproved revisions | Every page of a report from a non-approved revision carries **DRAFT — NOT APPROVED FOR MANUFACTURING**. Approved revisions are not watermarked but still state "not a manufacturing authorisation". |
| 2 | Header and footer content | Header: report number, passport number, exact revision and status, generation date and role. Footer on every page: report number, variant, passport, revision, status, date, "Page x of y". Verification legend in the last section. |
| 3 | CAD views | Front, top and isometric images rendered from the newest STEP version with a converted GLB, on the passport first, otherwise the part. Same camera directions as the 3D viewer; neutral material. The model title, version and SHA-256 are printed. Without a model, or if rendering fails, each view reads "View not available"; no image is substituted. |
| 4–5 | Provenance marks | V only for values from an approved revision. D for draft. C for client values not verified (part provenance, R-L1 `value_sources`). M for missing. Printing never upgrades a mark. |
| 6–7 | Access | Report endpoints are actions on the passport (tenant RLS plus project scope via `get_object`). The client variant never reads notes, job sheets or CAD originals. |
| 8 | History | `PassportReport` and `PassportReportEvent` (generated, previewed, downloaded; user and time) are append-only (immutability triggers) and audited as `passport_report.*` |
| 9 | External sharing | Not implemented: no email or link sharing. The report and tab state that sharing is subject to OQ-33/OQ-38. |
| 10 | Layout validation | `AccessTest/tools/validate-reports.py` (49 checks): watermark on every page, header and footer fields, legend, sections not split from their tables, three embedded view images, attachment page order, no confidential content in client reports |

### Technical notes

- **Renderer:** `backend/scripts/report_render.mjs` runs locally with the repository's Playwright Chromium. It handles the GLB views and the HTML-to-PDF step; there is no network access, because every non-local request is aborted.
- **New Python dependencies:** `pypdf` (merging) and `pypdfium2` (preview page images), both BSD/Apache licensed.
- **Production prerequisite:** the worker host needs Node and Chromium (or a later change to a pure-Python renderer). Generation is currently synchronous in the request; a background job is advisable for production.
- **API:**
  - `GET/POST /api/v1/passports/{id}/reports/`
  - `GET …/reports/{rid}/pdf/`
  - `GET …/reports/{rid}/pages/{n}/`
- **Web:** passport **Reports** tab with the generate form, history, page preview and download.
- **Migrations:** `reports.0001_initial`, `reports.0002_security`. Applied to `passport_access` only.

### Test results (26 Oct 2026)

| Suite | Result |
|---|---|
| Backend, full | 268 passed, including 8 in `tests/test_passport_reports.py`: variant content, honest marks, unavailable views, roles, attachments, isolation and project scope, history/audit/immutability with gates unchanged, current-revision rule for clients |
| Web | 73 passed; build passes |
| Browser, reports (`flow-reports.mjs`) | 19/19 |
| PDF layout validation | 49/49 |
| Regressions | inventory 23/23, job sheet 32/32, forms 28/28, clone 37/37, submissions 33/33, CN-002 24/24 |

### Still open

- OQ-33 (watermark and distribution policy)
- OQ-38 (IP and redistribution)
- Aries logo and company details (R8)
- the document-control number format (R7)
- report access for Procurement and Auditor, if wanted (they currently have no 3D/preview right)
- the production rendering host

## 10. Enhancement: report templates and Report Builder (27 Oct 2026, access-test only)

The existing module was extended, not rebuilt. It uses the same renderer, storage, immutable report history, page previews and download audit.

### Templates

| Template | Audience | Content |
|---|---|---|
| **Manufacturing & Test Specification** (`mts`, number suffix `-MTS`) | Aries confidential | Layout of the 8-page Project 1 sample (§10.4) |
| **Standard Digital Passport** (`standard`) | Client-facing | The approved R3 client layout, plus an attached-documents index |
| **Aries Internal Engineering Report** (`internal`, suffix `-INT`) | Aries confidential | The approved internal layout, plus an attached-documents index |

Reports generated before this change are immutable. The API reports their template from their audience: internal reports show as "internal", client-facing ones as "standard".

### Supporting documents

These use the existing part/passport document repository; there is no second repository.

- **Classes:**
  - Engineering drawing, QC/inspection report and Other supporting document (existing categories).
  - New: material certificate (`mat_cert`), mechanical test report (`mech_test`), chemical analysis report (`chem_analysis`), laboratory test report (`lab_test`).
- **Upload checks:**
  - The PDF opens with PDFium.
  - It is not encrypted.
  - It has no `/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFile`, `/RichMedia` or `/XFA` content.
  - It has at most `PDF_MAX_PAGES` pages (300). The page count is stored on the version.
- **Client visibility:** new per-document flag `client_visible`.
  - Existing documents keep their visibility.
  - Aries-uploaded PDFs start **hidden** until an Aries Engineer releases them (an audited change).
  - Client-supplied documents are visible.
  - Client users never list, open, preview or attach a hidden document. All of this is enforced server-side.

### Report Builder (Digital Passport → Reports)

- Choose a template and a revision.
- Select PDF documents, set their order, pin a version, or exclude them.
- Upload a supporting PDF (Aries Engineers).
- Release or withdraw a document for clients.
- **Preview complete PDF** returns the exact assembled document without storing it (audited `passport_report.draft_previewed`).
- **Generate** stores the immutable report.
- Rights are the same as generation:
  - MTS and Internal: `reports.generate_internal` (Aries Engineers).
  - Standard: `reports.generate_client`.
  - A client-facing report may attach only released documents, and only for users with `files.download_original`.

### Assembly

1. The template is rendered by Chromium.
2. The body is rendered twice, so every body page shows "Page x of N" for the whole assembled document and the index shows where each attachment starts.
3. Each attachment's stored bytes are checked against the recorded SHA-256, opened with PDFium and appended in order. The originals are never modified.
4. Limits: `REPORT_ATTACHMENT_MAX_PAGES` (100) per attachment and `REPORT_MAX_PAGES` (400) in total.

Any failure stops generation, so no partial report is stored.

Each report records its attachments in order, with: file, version number, version id, title, class, SHA-256, pages, first page and client visibility at the time. It also records the user and the time.

### What is recorded vs not invented

Wording on every template: "Attaching a certificate, test or inspection report does not mean Aries has verified it". Unapproved revisions keep **DRAFT — NOT APPROVED FOR MANUFACTURING**.

### 10.4 MTS template compared with the Project 1 sample

The sample was read locally only. None of its contents are used in synthetic test reports.

| Sample element | MTS template |
|---|---|
| Header: logo · "Manufacturing & Test Specifications Report" · Document No. / Revision No | Same structure. The brand is text-only (R8, no approved logo yet). Document No. = report number. Revision = passport revision. |
| Title line | Built from the part name and the recorded manufacturing process |
| Manufacturing Specifications grid: Job No, Revision, Company name, Location, Part name, Dwg No, 3D printing technology, Feedstock, Applicable standards, Substrate plate material | Same ten cells from passport data. Company name and location come from settings `REPORT_COMPANY_NAME` / `REPORT_COMPANY_LOCATION` and are "Not recorded" until set. Substrate plate material has no passport field, so it is "Not recorded". |
| Three build-preparation views with supports | Front, top and isometric views rendered from the passport's STEP model. Support structures are not modelled. |
| Qty to be produced: part and specimens | Part quantity "Not recorded (job-specific)". Test coupons/specimens from R-L2. |
| Manufacturing Process 1–8 | Six steps from the specification fields: feedstock, design for AM (supports, orientation), 3D printing (machine, layer, gas, parameters), heat treatment, support removal and post-processing, machining. Wire-cut EDM has no passport field and is not invented. |
| Inspection and Test Specifications (test method, reference, acceptance, frequency) | From R-L2 mechanical acceptance rows, plus NDT and dimensional tolerance rows |
| CONFIDENTIAL stamp, "Page N" | CONFIDENTIAL watermark, plus the DRAFT watermark when not approved. Footer: report number, status and "Page x of N". |
| Pages 3–8: drawing, QC inspection report, lab test reports | The selected supporting PDFs in the chosen order, reproduced unchanged (landscape pages keep their orientation). An attached-documents index on the body pages lists class, title, version, SHA-256, pages and first page. |
| (none) | Added: a V/D/C/M value mark on every printed value, and the verification disclaimer |

**Migrations:**
- `files.0005_report_documents` (`client_visible`, `page_count`, new categories);
- `reports.0003_report_templates`.

**Tests:**
- Backend `tests/test_report_builder.py` (3 tests).
- Web `report-builder.test.tsx`.
- Browser `flow-report-builder.mjs` (27 checks). The existing CN-005 flow and tests were adapted to the explicit-release rule.
