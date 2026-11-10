# CN-007: AI Spare Parts Assessment, Phases 1–6: inventory import, part intelligence, feasibility, cost comparison, recommendation and quarterly assessment

| | |
|---|---|
| **Status** | **Phases 1–6 implemented in the isolated access-test environment only** (27–28 Oct 2026), behind `INVENTORY_IMPORT_ENABLED` and `PART_INTELLIGENCE_ENABLED` (both off by default everywhere else). Phases 2–6 call Gemini only for the synthetic pilot company (§6–17). Phase 3 screens, Phase 4 compares cost and lead time, Phase 5 combines them into preliminary recommendations with an engineering review queue, and Phase 6 runs quarterly assessments with analytics and reports. Nothing approves, authorises, publishes or releases (OQ-35/OQ-36). BRD v0.4 is unchanged; this note becomes a BRD change only through an approved change-control update. |
| **Basis** | - `Requirements/2026-10-27/Handover.txt` (Modules 1–10, sections 6–8 and 10).<br>- The three management recordings, transcribed locally and offline.<br>- Read-only analysis of `Lsit of 573 Spare parts.xlsx`.<br>- The audit of 27 Oct 2026. |
| **Test data** | Synthetic only: four records in the reference workbook's layout (`AccessTest/test-data/inventory/`), imported into **Synthetic Inventory Pilot (test)**. The customer workbook was **not** loaded into any database. |
| **Unchanged** | - Passport creation, approval and publication (OQ-35).<br>- Manufacturing release and eligibility (OQ-36).<br>- The part review workflow (CN-003), edit requests (CN-006), and showcase / engineering-validation data. |

## 1. Phase 1 scope (delivered)

| Requirement | Implementation |
|---|---|
| Client-specific Excel/CSV upload | `POST /inventory-imports/` inside a client company. Reads the first sheet of a .xlsx file, or a CSV (UTF-8 with or without BOM, or cp1252; comma, semicolon or tab separated). Limits are configurable (`IMPORT_MAX_BYTES` 10 MB, `IMPORT_MAX_ROWS` 20,000). The file itself is not stored; its name, size and SHA-256 are. |
| Configurable column mapping and the 573-workbook preset | `apps/imports/mapping.py` `TARGETS`, plus the `sap_material_list` preset. Headers are auto-matched and editable per import (`PATCH`). OEM part number is never mapped automatically. |
| Validation and preview before commit | Every row is analysed; preview writes nothing to parts. Commit needs `confirm: true` and re-analyses inside one transaction. |
| Safe duplicate detection | Identity is (company, customer material number), matching the existing unique constraint. Duplicates inside the file are errors. "Possible duplicate" means the same description and manufacturer under another material number: it is flagged and never merged. |
| Original values and history | Each row keeps the original cell text per column. Import batches and rows are frozen once committed or discarded (database triggers). Each part records the import that last wrote it (`import_record`). |
| Manufacturer normalisation | `manufacturer` is stored verbatim. `manufacturer_normalized` holds the copy with spacing and case cleaned. Placeholder names (e.g. "REPUTED") are flagged. |
| Manufacturer reference vs OEM part number | Two separate new fields: `manufacturer_reference` (customer/ERP code) and `oem_part_number` (verified only; blank after import). |
| Plant, location, tag, ABC | New fields `plant`, `functional_location`, `equipment_tag`, and `customer_abc_class` (labelled "meaning not confirmed"). |
| Unknown classification, unassessed criticality | New category value "Not classified" (`unknown`). Criticality stays "Not assessed". No material, dimensions or criticality is extracted or inferred. |
| Safe re-import | - **Unchanged:** nothing is written.<br>- **Update:** only fields still holding the value an earlier import wrote, and only if the importer chooses to apply updates.<br>- **Conflict:** the value was changed in the application or set outside an import; the current value is kept and the conflict reported.<br>- A number that exists in a project outside the importer's scope is a conflict, never a second record. |
| Data-quality dashboard | `GET /inventory-imports/quality/`: totals, issue counts, parts with flags and possible duplicates, fields edited since import, and open conflicts (superseded ones stay in import history). |
| Isolation, permissions, audit | - Row-level security on both new tables.<br>- Project scope for Aries Engineers.<br>- Audit events: `inventory_import.previewed`, `.committed`, `.discarded`, `.admin_summary_viewed`; membership changes record `inventory_import_allowed`. |

## 2. Permissions

| Role | Rights |
|---|---|
| Aries Engineer (assigned) | Imports inside assigned companies. Project-limited engineers must choose an assigned project and see only those projects' imports. |
| Client Administrator | Only when an Aries Admin sets "May import inventory" (`Membership.inventory_import_allowed`). New parts become client records pending Aries review (CN-003). |
| Aries Admin | - Grants or removes the Client Administrator permission.<br>- Views per-company import summaries (no row contents or part data) and discards open previews.<br>- Does not import into client companies. |
| Everyone else | No import. |

## 3. Data model (all additive)

- `parts.0006_inventory_identifiers`:
  - adds `plant`, `functional_location`, `equipment_tag`, `customer_abc_class`, `manufacturer_reference`, `oem_part_number`, `manufacturer_normalized` and `import_record` to the part;
  - adds the `unknown` category choice.
- `tenancy.0006_membership_inventory_import_allowed`.
- `imports.0001_initial` (`InventoryImport`, `InventoryImportRow`) and `imports.0002_security` (RLS and immutability triggers).
- New dependency: `openpyxl==3.1.5`.

## 4. Data-quality flags

Warnings:
- missing manufacturer, manufacturer reference, plant, functional location or equipment tag;
- placeholder manufacturer;
- description or manufacturer filling the source field limit (40 / 25 characters for the SAP preset);
- very short description;
- possible duplicate.

Information only:
- missing ABC indicator;
- manufacturer had extra spaces;
- description mentions dimensions or a material grade (not extracted; engineering check needed);
- no OEM part number recorded.

## 5. Open decisions (from the audit; still open)

1. Whether the original ADNOC workbook may be loaded into any environment, and into which company.
2. The meaning of the customer ABC indicator (the workbook has C and D only).
3. A source of real OEM part numbers.
4. Whether plants should map to projects.
5. The AI provider and which fields may leave the platform.
6. Approval authority for assessments (OQ-35/OQ-36).
7. Reporting currency and cost sources.
8. ADNOC security baseline and acceptance of an equivalent to the named tool.
9. Change control for BR-001, which merges "OEM/client part number" into one field.

## 6. Phase 2: part intelligence (delivered, access-test only)

On 27 Oct 2026 the instruction replaced the earlier "deterministic only" plan for Phase 2. Gemini is now the preferred AI provider, used behind deterministic Python rules.

| Requirement | Implementation |
|---|---|
| Deterministic analysis in Python | `apps/intelligence/rules.py` (`rules-2026-10-27.1`), computed live. It writes nothing to the part. It covers:<br>- SAP short text, with abbreviations expanded and unknown tokens listed;<br>- part family and category, from the leading noun and its qualifiers;<br>- dimensions and material grades **mentioned** in the text (never treated as verified);<br>- manufacturer: cleaned name, matching key without the legal suffix, possible truncation, alias candidates;<br>- duplicates: same description and manufacturer, or a similar description;<br>- completeness score from 0 to 100, with what is missing. |
| Engineering hard constraints | Rules of three kinds:<br>- `block`: electrical/electronic part; exceeds the build envelope (`AM_BUILD_ENVELOPE_MM`; not checked when unset).<br>- `review`: assembly; a material not produced like-for-like by common AM (carbide, elastomer, grey/cast iron).<br>- `insufficient`: no material, no dimensions, or no drawing/CAD/photo.<br>The rule screening is shown next to the AI suggestion, which never overrides it. |
| Configurable Gemini adapter (official SDK) | `apps/intelligence/gemini.py`, using `google-genai==2.33.0`. Tiers:<br>- `lite` (default): `gemini-3.1-flash-lite`<br>- `flash`: `gemini-3.8-flash` (thinking low)<br>- `pro`: `gemini-3.1-pro-preview` (thinking low)<br>Each tier can be overridden by environment (`GEMINI_MODEL_*`). The engineer chooses whether to escalate. |
| Structured, schema-validated JSON | A `response_json_schema` is sent, then the response is validated strictly on our side (pydantic: extra fields forbidden, enums, confidence between 0 and 1).<br>Invalid JSON or a schema mismatch is retried within the retry limit. If it still fails, it is stored as `invalid_response`, never as a partial suggestion.<br>The schema has no price, cost, supplier, OEM part number or approval field. Any sentence stating an amount of money is removed, and the removal is recorded. |
| Recorded for each suggestion | `PartAssessment` stores:<br>- the model requested and the model version that answered;<br>- timestamp, user, prompt version and rules version;<br>- the exact inputs sent and their hash;<br>- the validated proposed values, confidence and uncertainty;<br>- tokens (input, output, thinking), estimated cost, latency and attempts.<br>Records are immutable (database trigger) and protected by tenant RLS. |
| Suggestions kept apart | A suggestion never changes the part. The engineer records the verified category (`POST …/intelligence/classification/`) with provenance: who verified it, when, a note, and the suggestion considered. |
| Cache | When provider, model, prompt version and inputs are unchanged, the stored suggestion is reused without a call (logged as `cache_hit`). Failed or invalid results are never reused. |
| Rate limits, timeouts, retries, cost log | Environment defaults:<br>- `AI_CALLS_PER_MINUTE` 10 (across all companies) and `AI_CALLS_PER_DAY` 200;<br>- `AI_DAILY_BUDGET_USD` 1.00;<br>- `AI_TIMEOUT_SECONDS` 45 per call;<br>- `AI_MAX_RETRIES` 2, for transient errors only (429, 5xx, timeout, network), with backoff. The SDK's own retry is off.<br>`AIUsageLog` holds every attempt: outcome, tokens and estimated cost. Cost comes from `AI_PRICES`, the list prices read on 27 Oct 2026. The log holds no part text and is under tenant RLS like every tenant table; shared limits and the Aries Admin totals read it company by company. Refusals are logged and audited. |
| Key handling | `GEMINI_API_KEY` exists only in the backend environment. In access test it lives in `AccessTest/secrets/gemini.env`, outside Git, and `run.py` loads it into the API process only.<br>It is never returned by the API, sent to React, or written to logs or the database (all checked). Error text is scrubbed, and the HTTP client loggers stay at WARNING. |
| AI optional | If there is no `AI_PROVIDER`, no key or no permission, the rule analysis, overview and classification still work, and the UI says why AI is not used. |
| Data sent | A whitelist only (`service.ai_inputs`):<br>- the material description;<br>- the cleaned manufacturer name;<br>- the rule findings.<br>Never plant, functional location, equipment tag, ABC indicator, manufacturer reference, remarks, ids, company or user names, files, drawings, CAD, or passport or manufacturing data. |
| Who may use it | External AI requires all of the following:<br>- the company's slug is in `AI_ALLOWED_COMPANIES` (in access test, only `synthetic-inventory-pilot`);<br>- the part is an imported inventory record;<br>- the user is an Aries Engineer within project scope.<br>Real client companies, including the ADNOC company present in access test, stay off the list until data-processing approval and suitable API terms are confirmed.<br>Clients have no access to suggestions. The Aries Admin sees usage and estimated cost only. |
| Not quotations, not approvals | The UI labels read "AI suggestion · not verified" and "Suggestion only: not a feasibility approval or manufacturing release". |

Endpoints:
- `GET /parts/<id>/intelligence/`, with `POST …/assess/` and `POST …/classification/`
- `GET /intelligence/overview/`
- `POST /intelligence/assess-batch/` (at most 10 parts)
- `GET /admin/intelligence-usage/`

Capabilities: `intelligence.view` and `intelligence.assess` (Aries Engineer), `intelligence.usage_admin` (Aries Admin). Migrations: `intelligence.0001_initial`, `0002_security` and `0003_usage_log_rls`.

## 7. Phase 2 integration results (27 Oct 2026, synthetic records only)

- **API project:** 46 models support generateContent. Gemini 3.1 Pro Preview, which has no free tier, answered; that indicates a billed project. Under the paid terms, prompts are not used to improve Google's products. Quota and tier cannot be read through the API, only in AI Studio. `gemini-2.5-pro` is no longer available to this project.
- **Model choice:** all four records were run through four models, and all 16 responses were schema-valid. Per-model results are in `AccessTest/evidence/part-intelligence/model-evaluation.json`.
  - `gemini-3.1-flash-lite` became the default. It judged the carbide insert "unlikely" and invented no materials.
  - `gemini-2.5-flash-lite` was cheaper, but suggested a carbide insert might be printable.
  - `gemini-3.5-flash-lite` and `gemini-3.8-flash` were also tested.
- **Prompt revision `.2`:** Flash labelled the unlabelled wear-ring numbers as inside diameter, outside diameter and width. The prompt now forbids assigning dimension roles, and the model lists their meaning as information needed instead.
- **Results:** classification for all four parts, with tokens and cost, is in `AccessTest/evidence/part-intelligence/results.json`.

## 8. Phase 3: manufacturing feasibility (delivered, access-test only)

For an imported part, three alternatives are screened side by side: **A. OEM procurement**, **B. additive manufacturing** and **C. conventional manufacturing**. The results are preliminary screening outcomes. They are not approvals or recommendations, and no costs, savings or lead times are shown (Phase 4). The phase reuses:
- the part master (`SparePart`), its Phase 1 import record and customer fields;
- the Phase 2 rules and Gemini adapter, field provenance, engineering files and the latest passport revision;
- project scoping, row-level security, audit and the Phase 2 AI limits and usage log.

**Rules (`apps/intelligence/feasibility.py`, methodology `mf-method-2026-10-27.2`).**
- **Evidence states.** Every item has one of four states:
  - *verified*: an engineer-verified part field or an approved passport revision;
  - *recorded*: held but not verified (imported data, a draft passport, a file on record);
  - *mentioned*: in the description text only;
  - *missing*.

  Mentions never make a part suitable. Only verified evidence can disqualify a part.
- **OEM procurement.** Statuses are "Identification / availability not verified" (default) and "OEM part identified: availability requires supplier confirmation" (needs a verified manufacturer and OEM part number).
  - A missing record is never "OEM unavailable".
  - The manufacturer reference is shown as a customer/ERP code, not an OEM part number.
  - Supplier, availability/obsolescence and supersession are always "not held": the platform holds no such records.
- **Additive and conventional manufacturing statuses:**
  - Potentially suitable: requires engineering qualification
  - Potentially suitable with redesign
  - Insufficient technical information
  - Not suitable based on verified constraints
  - Specialist engineering assessment required

  The order of precedence is:
  1. A verified disqualifying constraint (a verified electrical/electronic category, or a verified dimension beyond a configured build envelope).
  2. A specialist constraint (an assembly, a material not produced like-for-like by AM, or a critical part).
  3. Insufficient evidence (no drawing or CAD, or no material or dimensions held).
  4. Otherwise, potentially suitable.
- **Candidate AM process families and conventional methods** follow only from the material class, never from the description's resemblance to a common part. They are textbook families, not an Aries capability list.
  - No machine list is invented.
  - A build envelope is used only when configured (`AM_BUILD_ENVELOPE_MM`; not set, so "Verified AM build envelope" is listed as missing).
- **Factors covered per alternative:**
  - function and category;
  - geometry and dimensions, CAD and drawings;
  - material, tolerances and surface finish;
  - mechanical properties, temperature/pressure/load, wear/corrosion and service conditions;
  - post-processing, inspection and testing, standards and certification;
  - OEM IP status, criticality, quantity and build envelope.

**Gemini view (optional; `apps/intelligence/feasibility_service.py`, prompt `mf-prompt-2026-10-27.1`).**
- **Access.** Same gate as Phase 2: the synthetic pilot company only, imported records only.
- **Models.** Flash-Lite by default; Flash or Pro only when an engineer asks.
- **Response format.** A schema-validated JSON view (`FeasibilityView`, no price, supplier or approval fields).
- **Data sent.**
  - Sent: the description, the cleaned manufacturer name, the rule findings and statuses, and each evidence item's state.
  - Values are sent only for material, dimensions, wear/corrosion, criticality, family/category and the build envelope.
  - Never sent: file titles or contents, drawings, CAD, passport text, OEM part numbers, manufacturer references, locations, tags or the ABC indicator.
- **Rules first.** The rules run before the AI.
  - The AI may lower a favourable rule status (more caution). It never raises one.
  - An AI "not suitable" without a verified constraint becomes "specialist assessment".
  - Sentences with prices or approval/certification/suitability claims are removed.
- **Failure.** If Gemini is off, refused or failing, the rule screening is stored complete with the AI status recorded.
- **Cache.** An unchanged input (same evidence snapshot, methodology, prompt and model) reuses the stored version without a new call.

**Data model (`intelligence` migration `0004_feasibility`, additive).**
- **`FeasibilityAssessment`.** One immutable version per run.
  - It records the company, the project, a version number per part, and the methodology and rules versions.
  - It records the passport number and revision when one exists, the input hash and the evidence snapshot.
  - It holds the three alternatives (status, evidence, constraints, missing information, risks, next actions, candidates and the AI view) and the constraints across alternatives.
  - It holds the missing information and next actions, the AI status, and the AI provenance: model, model version, prompt version, the exact payload sent, the response, usage, cost, adjustments and anything removed.
- **`FeasibilityReview`.** Append-only.
  - It records the alternative (or the whole assessment), the decision, a corrected status, findings, notes, evidence references (free text or a file of this part) and whether the reviewer was independent.
- **Database controls.** Both tables have forced tenant row-level security and triggers that block UPDATE and DELETE. A changed input gives a new version; earlier versions stay.

**Engineering review (capability `intelligence.review`, Aries Engineers only, project-scoped).**
- **Decisions:** confirmed (technical review), corrected, rejected, additional information required, and technical finding.
- **Rules:**
  - Only the latest version can be reviewed.
  - Corrections, rejections, information requests and findings need findings text.
  - A correction to a more favourable status (towards "potentially suitable" or a verified OEM identification) needs an evidence reference. Moving between non-favourable outcomes (e.g. insufficient information → specialist assessment) does not; this was corrected during Phase 4.
  - **The engineer who ran a version cannot confirm it or correct it to a more favourable status** (separation of duties); another assigned Aries Engineer must.
  - "approve", "release", "authorise", "eligible" or "publish" are refused (`formal_approval_not_available`).
- **No effect on gates.** Reviews change no part field, passport, evidence level, manufacturing eligibility or release state. OQ-35/OQ-36 stay open.

**API.** All endpoints are Aries-internal; clients hold no capability.
- `GET /parts/<id>/feasibility/`
- `POST /parts/<id>/feasibility/assess/` with `{tier: null|lite|flash|pro}`
- `POST /parts/<id>/feasibility/<assessment>/reviews/`
- `GET /intelligence/feasibility/`
- `POST /intelligence/feasibility/assess-batch/` (up to 10 parts)

**User interface.**
- **Part Intelligence workspace.** Inventory import → Part intelligence gets a "Manufacturing feasibility" table with "Assess all (rules)" and "Assess all with AI view".
- **Part page.** A "Manufacturing feasibility (Aries internal)" card shows three panels: OEM procurement, additive manufacturing, conventional manufacturing.
  - Each panel shows the preliminary status, the supporting evidence with its state, technical constraints, missing information, risks, required next actions, the AI view (labelled "preliminary, not verified") and the review status.
  - Below the panels: the constraints across alternatives, the missing information, AI provenance, the review form, the review history and earlier versions.

## 9. Phase 3 integration results (27 Oct 2026, four synthetic records only)

| Part | A. OEM procurement | B. Additive manufacturing | C. Conventional manufacturing |
|---|---|---|---|
| 990100000101 Bearing housing cover | Identification / availability not verified | Insufficient technical information (no material, dimensions or drawing) | Insufficient technical information; no method identified without a material |
| 990100000102 Mechanical seal, cartridge | Not verified; no manufacturer name | Specialist assessment (assembly): not printable as one part | Specialist assessment (assembly) |
| 990100000103 Carbide cutting insert | Not verified; possible duplicate of 990100000099 | Specialist assessment: carbide not produced like-for-like by AM; no AM process family | Insufficient technical information; powder metallurgy and grinding follow from the stated material |
| 990100000104 Wear ring, A48-40 | Not verified; manufacturer name may be truncated | Specialist assessment: grey cast iron not produced like-for-like by AM | Insufficient technical information; casting and finish machining follow from the stated material |

- **Evidence gaps.** Every part lists missing drawing, CAD, tolerances, surface finish, service conditions, standards, OEM IP, criticality and quantity.
- **Wear-ring dimensions.** "95 mm, 135 mm, 30 mm" are quoted as mentioned, with roles not stated.
- **Gemini views.**
  - Flash-Lite matched the rule statuses for all four parts; no adjustment was needed and nothing was removed.
  - Flash (wear ring) also matched the rules.
- **Authorisation.** No part received a manufacturing authorisation, and no passport was created.
- **Reviews.** Engineer 1 recorded "additional information required" on each part. Self-confirmation, approval words and an unevidenced favourable correction were refused.
- **Gemini usage for Phase 3.** 10 calls, 9,784 input and 6,914 output tokens, estimated **$0.0172** at list prices:
  - 8 × gemini-3.1-flash-lite: 7,671 in, 5,448 out, $0.0101;
  - 2 × gemini-3.8-flash: 2,113 in, 1,466 out, $0.0071.

  Repeat runs were served from stored versions.

  Two rule runs exist because the methodology was corrected after the first integration run (one constraint per material reading; unverified items named as such).
- **Latency.** Flash-Lite took about 3.4 s per part, except part 101 at about 48 s on both runs. That exceeds the configured 45 s timeout, which the SDK applies between network reads rather than as a total deadline.

## 10. Phase 4: cost and lead-time comparison (delivered, access-test only)

For an imported part with a Phase 3 feasibility assessment, the platform compares OEM procurement, additive manufacturing and conventional manufacturing for one required quantity in one reporting currency. It compares only: it makes no procurement recommendation, gives no manufacturing authorisation, and changes no passport, eligibility or release state.

**Inputs per alternative (`apps/intelligence/costing.py`, method `cost-method-2026-10-27.1`).**
- **Quantity-dependent (per ordered unit):**
  - unit purchase/manufacturing cost (must be greater than 0);
  - post-processing;
  - packaging and logistics, when entered per unit.
- **One-time:**
  - engineering and setup;
  - tooling;
  - testing and qualification;
  - packaging and logistics, when entered per order.
- **Duties and taxes:** a percentage of goods value plus logistics. Duties are never also entered as an amount, so they can't be counted twice.
- **Quantities:**
  - MOQ;
  - order multiple (pack size);
  - qualification units (consumed by testing, not usable).
- **Lead time:** supplier/manufacturer days plus additional engineering/qualification days, assumed to run one after the other.
- **Every figure records:**
  - its currency and data source: *Verified supplier quotation*, *Historical purchase/manufacturing cost*, *Engineering estimate*, *AI-assisted preliminary estimate* or *Missing / unavailable*;
  - "Not applicable" when it is explicitly not needed;
  - an evidence reference (required for quotations and historical figures);
  - a quotation validity date (required for quotations).
- **Validation:** a missing figure has no amount. Zero or negative unit costs, negative amounts, a zero quantity or MOQ, duties over 100 %, negative days, invalid currency codes, future or zero exchange rates, and duplicate rates are refused with field-level errors.

**Calculation.** All arithmetic uses `Decimal`; money is rounded half-up to 2 decimals and percentages to 1 decimal, for display only.
- **Ordered quantity:** max(required + qualification units, MOQ), rounded up to the order multiple.
- **Material and production:** (unit cost + post-processing) × ordered.
- **Setup and tooling:** engineering/setup + tooling.
- **Testing and qualification:** as entered.
- **Logistics:** per order, or per unit × ordered.
- **Duties:** % × (goods + logistics).
- **Total landed/project cost:** the sum of the above.
- **Effective cost per usable unit:** total ÷ required quantity. MOQ or pack surplus is paid for but not usable. Cost per ordered unit is shown too.
- **Currency conversion:** only through explicitly entered, dated rates with a stated source (or the inverse of one, shown as such). A missing rate is never assumed: the total becomes incomplete and the missing rate is listed.
- **Savings:** baseline total − alternative total (baseline OEM by default), and that as a percentage of the baseline total. Lead-time difference = alternative days − baseline days. Savings are computed only between complete totals.
- **Data confidence:** set by the weakest source among the priced inputs. An expired quotation counts as a historical figure and is flagged.

**Technical integration.**
- **Phase 3 link:** a comparison needs the part's latest Phase 3 feasibility version and stores a link to it.
- **Technical status:** taken per alternative, including an engineer's correction from the technical review.
- **Labels:**
  - Additive and conventional are always labelled **"Not technically qualified: <screening status>"**, because no formal engineering approval exists (OQ-35/36).
  - A verified disqualifying constraint gives **"Excluded: not suitable based on verified constraints"**. Its cost is shown, but its savings are not.
  - Savings for a not-qualified option are marked *provisional*.
  - OEM shows "Not verified: OEM identity / availability" until Phase 3 holds a verified OEM part number.
- **Superseded feasibility:** a newer feasibility version is flagged on older comparisons.

**Gemini (optional, prompt `cost-prompt-2026-10-27.1`).**
- **What it does:** assumption notes only (cost drivers, assumptions to verify, missing inputs, lead-time considerations, uncertainty), validated against a schema (`CostNotes`) that has no price, rate, total or recommendation field.
- **Access:** the same gate, limits and usage log as Phases 2–3, plus a scenario marked **synthetic**.
- **Data sent:** component labels, bases, data sources, each component's share of known cost (whole percent), quantities, MOQ, lead-time days, currency codes and technical labels. Never amounts, totals, rates, references or notes.
- **Cleaning:** sentences with prices, approval claims or recommendations are removed. The notes never change the calculated figures.

**Data model (`intelligence` migration `0005_cost_comparison`, additive).**
- **`CostComparison`.** One immutable version per stored scenario:
  - part, project and version;
  - method version, linked feasibility version, and passport number and revision;
  - scenario name and a synthetic flag;
  - quantity and reporting currency;
  - `derived_from` (a what-if saved from an earlier version);
  - input hash, validated inputs (every cost and lead-time component with source, reference, validity and currency, plus the exchange rates);
  - technical status per alternative, calculated results, the date used for quotation validity, and AI status and provenance;
  - creator and timestamp.
- **Database controls:** forced tenant row-level security; a trigger blocks UPDATE and DELETE. Unchanged inputs reuse the stored version.

**API.** All endpoints are Aries-internal: viewing needs `intelligence.view`, storing needs `intelligence.assess`, and clients hold neither.
- `GET /parts/<id>/cost-comparisons/`
- `POST /parts/<id>/cost-comparisons/calculate/`: preview, stores nothing
- `POST /parts/<id>/cost-comparisons/` with `{scenario, tier?, derived_from?}`
- `GET /intelligence/cost-comparisons/`

**User interface.**
- **Workspace:** Inventory import → Part intelligence has a "Cost & Lead-Time Comparison" table (latest version per part).
- **Part page:** a "Cost & Lead-Time Comparison (Aries internal)" card with the three options side by side. Each shows:
  - the technical label and feasibility version;
  - cost lines with entered amount, conversion, source badge, reference and validity;
  - category subtotals, one-time and quantity-dependent costs, the total (or "Incomplete" plus the known costs so far);
  - effective cost per usable unit and cost per ordered unit, and quantities (ordered, MOQ, surplus);
  - lead time with components, data confidence, and the difference against the baseline (provisional when not qualified);
  - missing inputs, warnings and AI notes ("preliminary, not verified").
- **What-if quantity:** recalculates without saving; "Save as new version" stores it linked to the original.
- **Scenario form:** edits every input, the dated rates and the synthetic flag. It has "Calculate preview", "Save version" and, for synthetic scenarios, "Save with AI assumption notes".

## 11. Phase 4 integration results (27 Oct 2026; synthetic scenarios, invented figures)

The four scenarios are named "SYNTHETIC TEST SCENARIO: … (not real prices)". Their figures, references (`SYN-…`) and exchange rates (EUR→USD 1.0850 and AED→USD 0.2723, dated 2026-10-27, "Synthetic test rate … not a market rate") are invented for testing. All amounts are in USD.

| Part (quantity) | A. OEM procurement | B. Additive (not technically qualified) | C. Conventional (not technically qualified) |
|---|---|---|---|
| 101 cover (2) | 4,351.94 total · 2,175.97/unit · 84 d · medium confidence (quotation + historical duty) | 5,820.00 · 2,910.00/unit · 31 d · low (estimates) · 33.7 % higher than OEM | 5,080.00 · 2,540.00/unit · 56 d · MOQ 5 → 3 surplus · 16.7 % higher |
| 102 seal (1) | 912.21 · 56 d · medium (historical, AED) | Incomplete: unit, post-processing, setup, testing and logistics missing; assembly needs specialist assessment | Incomplete: unit, tooling, testing, logistics and supplier lead time missing |
| 103 insert (25) | 665.76 · 26.63/unit · 21 d · MOQ 10 in boxes of 10 → 30 ordered | 6,250.00 · 250.00/unit · 56 d · *very low* (AI-assisted unit estimate) | 19,650.00 · 786.00/unit · 90 d · MOQ 500 and tooling of 16,650 one-time |
| 104 ring (4) | 3,375.75 · 843.94/unit · 70 d · quotation **expired 2026-09-30** (warned; counted as historical) | 6,650.00 · 1,662.50/unit · 40 d · 97.0 % higher | 2,621.88 · 655.47/unit · 42 d · **753.87 (22.3 %) lower, provisional** · 28 d shorter |

- **Wear-ring what-if at 20 units:** saved as a new version derived from the original. The original 4-unit version is unchanged.
- **Gemini for Phase 4:** 4 × gemini-3.1-flash-lite, 9,705 input and 2,088 output tokens, estimated **$0.0056**. Nothing was removed. Repeats reused the stored versions.
- **Accuracy of the AI notes:** the notes are generic. One note mislabels the wear ring's conventional route as needing specialist assessment (its status is insufficient information). They are labelled preliminary.

## 12. Phase 4 review corrections (28 Oct 2026)

**1. Wear-ring OEM total (reconciled; the calculation was correct).** The Phase 4 completion report described the total as "3,780 + 95 plus duty". That explanation was wrong; the stored records and the calculation are right. The stored inputs are:
- unit cost **780.00 USD** (quotation SYN-Q-OEM-104, valid until 2026-09-30);
- logistics 95.00 USD per order;
- duty 5 % (historical);
- no currency conversion.

So the figures are:
- 780.00 × 4 = 3,120.00;
- duty 5 % × (3,120.00 + 95.00) = 160.75;
- total **3,375.75**, or 843.94 per usable unit.

No stored comparison was changed.

To prevent hand-written explanations from drifting from the figures again:
- **Calculation steps:** the method (`cost-method-2026-10-28.2`) now returns the arithmetic of every total (`explanation`). It is generated from the same unrounded values and shown under "How these figures are calculated".
- **Inverse rates:** shown as a division by the entered rate.
- **Regression test:** `test_wear_ring_oem_reconciliation` pins these inputs and steps.

**2. AI notes can no longer contradict the technical status.** The Phase 4 note for the wear ring said both manufacturing routes required "specialist engineering assessment", but the conventional route's status is "insufficient technical information". Now:
- **Status echo:** the cost-notes schema (`cost-prompt-2026-10-28.2`) requires each alternative's recorded technical status code to be repeated. A mismatch rejects the response, which is retried and finally stored as an invalid response.
- **Sentence check:** `apps/intelligence/consistency.py` removes any sentence that names a different screening status for an alternative, claims qualification or approval, or claims a verified OEM identity the record does not hold. Removed sentences are logged in `contradictions`.
- **Lists of needs:** evidence gaps, information to obtain and missing inputs state needs, not claims, so they are not checked.
- **Stored notes:** notes stored before this change are flagged when displayed (`ai_consistency`), never edited. The wear-ring note is shown with a warning to disregard it.
- **Live check:** real Flash-Lite cost notes were regenerated under the new rules for all four parts. All four repeated the recorded statuses, and none contained a contradiction.
- **Phase 3 review rule:** corrected at the same time; see §8.

## 13. Phase 5: recommendation and engineering review (delivered, access-test only)

**Evaluation (`apps/intelligence/recommendation.py`, method `rec-method-2026-10-28.1`).** The rules combine:
- Phase 2: the latest AI suggestion, as context only, plus record completeness, classification and duplicates;
- Phase 3: the latest feasibility version, including corrections from technical review;
- Phase 4: a chosen cost comparison, or the latest.

Steps, in order:
1. **Mandatory requirements, before any commercial ranking.**
   - OEM: identity and part number verified.
   - Additive and conventional, all five required:
     - screening "potentially suitable" (with or without redesign);
     - no verified exclusion;
     - safety/criticality assessed and not critical (the ABC indicator is not used);
     - applicable standards and certification requirements established;
     - OEM IP / reproduction restrictions assessed and not active.
2. **Four separate statuses:**
   - **Commercially cheapest:** the lowest complete total among options not excluded. It is *definitive* only when every such option is complete; otherwise "lowest among complete figures, not definitive". It also notes whether the cheapest option meets the technical requirements and how strong its cost evidence is.
   - **Fastest:** the same rule applied to lead times.
   - **Potentially suitable:** every mandatory requirement met.
   - **Engineering-approved:** always empty, because formal approval, manufacturing authorisation, passport publication and production release stay blocked (OQ-35/OQ-36).
3. **Commercial evidence.**
   - It is *verified current* only when every priced figure is a supplier quotation still valid on the recommendation date.
   - Validity is re-checked on that date, so an expired quotation is never verified-current evidence.
   - Otherwise the evidence is labelled as historical, engineering estimates, AI-assisted estimates or incomplete.
4. **Weights** (cost, lead time, evidence strength; default 0.5/0.3/0.2; configurable and normalised) are applied only among options that meet every mandatory requirement and have complete costs and lead times.
5. **Outcome:**
   - **"No qualified recommendation — additional engineering review required"** when no option meets the mandatory requirements;
   - "Potentially suitable option(s), commercial comparison incomplete: no ranking";
   - or "Preliminary recommendation for further study (not engineering-approved): <option>".

Each recommendation also shows costs, lead times, evidence, missing inputs, risks (including expired quotations and stale sources) and confidence (technical, commercial, overall).

**Gemini (optional, `rec-prompt-2026-10-28.2`).** Gemini only explains the result.
- **Schema checks:** the response must repeat the outcome code and every option's technical status code, or it is rejected and retried.
- **Cleaning:** the same contradiction, price, claim and recommendation filters are applied.
- **Data sent:** statuses, requirement results, completeness, evidence labels, *relative* cost indices (total ÷ lowest complete total), lead days and missing-input labels. Never amounts, references, part numbers or names.
- **Access:** the synthetic pilot company only, and only with a cost comparison marked synthetic.

**Data model (`intelligence` migration `0006_recommendation`).**
- **`Recommendation`** is one immutable version that keeps its source revisions:
  - the Phase 2 suggestion;
  - the feasibility version;
  - the cost comparison version;
  - the passport revision.

  It also stores the weights, the results, the outcome and the AI provenance.
- **`RecommendationReview`** is append-only and records:
  - the decision, option and findings;
  - evidence references;
  - whether the reviewer was independent of the generator;
  - whether the chosen option met the mandatory requirements at review time.
- **Database controls:** both tables have forced tenant row-level security and triggers that block UPDATE and DELETE.
- **New versions:** a changed source, weighting, criticality or date gives a new version; unchanged inputs reuse the stored one.

**Engineering review queue.**
- **Decisions:** *approved for further study* (not an approval), *information requested*, *corrected* (to an option that meets the mandatory requirements, or to "none") and *rejected*.
- **Separation of duties:** the engineer who generated a version cannot approve it for further study or correct it.
- **Other rules:**
  - Excluded options cannot be approved for further study.
  - Only the latest version can be reviewed.
  - Findings are required.
  - Approval, release, publication and authorisation words are refused.
- **Display:** recommendations show "Preliminary: not reviewed" until a decision exists, then "Reviewed: <decision> (<option>), <reviewer> (independent / by the engineer who generated it)".
- **Queue:** the latest version per imported part, filterable by state.
- **Permissions:** engineers view and generate (`intelligence.view` / `intelligence.assess`) and review (`intelligence.review`). Clients have no access. Project scoping and audit (`recommendation.created`, `recommendation.reused`, `recommendation.reviewed`) apply.

**API.**
- `GET/POST /parts/<id>/recommendations/` with `{weights?, tier?, cost_comparison?}`
- `POST /parts/<id>/recommendations/<rid>/reviews/`
- `GET /intelligence/recommendations/?state=`

**User interface.**
- **Part page:** an "AI Recommendation & Engineering Review (Aries internal)" card with:
  - the outcome and review state;
  - sources, the four separate statuses, and the three options side by side (mandatory-requirement checklist, commercial evidence, flags, missing inputs, expired quotations);
  - weights, confidence, risks and missing information;
  - the AI explanation, labelled "preliminary, not verified";
  - the review form, review history and earlier versions.
- **Workspace:** an "Engineering review queue" in Inventory import → Part intelligence.

## 14. Phase 5 integration results (28 Oct 2026; four synthetic parts, synthetic cost scenarios)

| Part | Outcome | Commercially cheapest | Fastest | Why no option qualifies |
|---|---|---|---|---|
| 101 cover | No qualified recommendation — additional engineering review required | OEM, 4,351.94 USD (definitive; not qualified; evidence includes a historical duty rate) | Additive, 31 d (not qualified) | OEM identity not verified. Additive and conventional fail all four of: screening (insufficient information), criticality not assessed, standards not established, OEM IP not assessed. |
| 102 seal | Same | OEM, 912.21 (**not definitive**: additive and conventional costs incomplete) | OEM, 56 d (not definitive) | Additive and conventional are assemblies needing specialist assessment, plus the same safety, certification and IP gaps. |
| 103 insert | Same | OEM, 665.76 (definitive; not qualified) | OEM, 21 d | Additive needs specialist assessment (carbide) and its unit cost is an AI-assisted estimate (very low confidence). Conventional has insufficient information. |
| 104 ring | Same | Conventional, 2,621.88 (definitive; **not technically qualified**; engineering estimates) | Additive, 40 d (not qualified) | OEM quotation **expired**, so it is not verified-current evidence, and OEM identity is not verified. Additive needs specialist assessment; conventional has insufficient information. |

- **Weights:** not applied for any part, because no option met the mandatory requirements.
- **Reviews:** Engineer 1 recorded "information requested" on all four. Their own "approve for further study" was refused (`self_review`), and "approve_for_manufacture" was refused (`formal_approval_not_available`).
- **Not tested in the browser:** independent review. No second Aries Engineer is assigned to project PILOT-A, so it is covered by the backend tests.
- **Untouched:** no passport, part status or eligibility changed.

**Gemini usage, all Flash-Lite:**

| Run | Calls | Input tokens | Output tokens | Estimated cost |
|---|---|---|---|---|
| Phase 4 notes regenerated under the status echo | 4 | 10,061 | 2,148 | $0.0057 |
| Phase 5 explanations | 8 | 8,822 | 4,623 | $0.0091 |

- **Two explanation runs:** the first run's contradiction filter also removed "Verified OEM part number and identity" from the *information to obtain* list. Needs lists are now exempt, and the four explanations were regenerated with nothing removed.
- **Cold start:** the first Gemini call after the API process starts takes about 48 s; later calls take 2–3 s.

## 15. Phase 5 follow-ups (28 Oct 2026)

**Quoted lead times now expire with their quotation.**
- **Rule:** a lead time from a supplier quotation counts as current evidence only while its quotation is valid. Precedence:
  1. If the lead time has its own validity date (independent current evidence), that date decides.
  2. Otherwise it expires with the cost quotation of the same reference.
  3. With neither, it is not current evidence.
- **Effect:** an expired or undated quoted lead time ranks no better than a historical figure. It carries a warning (cost method `cost-method-2026-10-28.3`). The recommendation's "fastest" status names weak lead-time evidence (`rec-method-2026-10-28.2`).
- **Stored results:** results from before this rule are re-checked from their stored quotation references on the evaluation date, never edited.
- **Tests:** `test_quoted_lead_time_expires_with_its_quotation` and `test_stored_results_without_lead_validity_are_rechecked_not_changed`.

**Independent engineering review in the browser** (`AccessTest/tools/flow-independent-review.mjs`, 14/14).
- **Assignment:** the Aries Admin explicitly assigned `engineer2@aries.test` to project PILOT-A through the existing Engineers & Access endpoint (audited).
- **Reviews:** Engineer 2 then:
  - confirmed the wear ring's Phase 3 OEM screening;
  - approved its Phase 5 recommendation for further study (conventional route).

  Both versions had been generated by Engineer 1, and both reviews were recorded as *independent*. The outcome stayed "No qualified recommendation", and no passport, approval or release state changed.
- **Restore:** Engineer 2's original access (projects: PILOT-B; not an edit reviewer) was restored and verified, and the PILOT-A parts were again out of reach. The original access is saved in `evidence/independent-review/original-access.json`.

**Total deadline for external AI.** Every AI request (all attempts, retries and back-off) now ends within `AI_TOTAL_DEADLINE_SECONDS` (default 60).
- **Per attempt:** a single attempt is abandoned after `AI_TIMEOUT_SECONDS` (45), or the time left if less. It runs on a bounded pool of four threads; an abandoned call is ended later by the SDK's HTTP timeout.
- **Effect:** a cold start (about 48 s observed) can no longer hold up an assessment beyond the deadline.
- **Test:** `test_ai_calls_have_a_true_total_deadline`.

## 16. Phase 6: quarterly inventory assessment and analytics (delivered, access-test only)

**Runs (`apps/intelligence/runs.py`, `run-method-2026-10-28.1`).**
- **Starting a run:**
  - **Manual:** "Start assessment run", optionally with Flash-Lite.
  - **Scheduled:** `manage.py run_scheduled_assessments`, run daily by the host scheduler, against a per-company quarterly schedule (months, day, AI tier).
- **Scope:** the imported inventory parts the requester may access (project scope applied).
- **Each run records:** scope, quarter, kind, AI tier, all methodology and prompt versions, part count, done/reused/failed counts, start and finish times, the previous run of the same scope, the dashboard summary and the comparison.
- **Each part (run item) records:** status, attempts, error, input hash, the source revisions used (feasibility, cost comparison, recommendation, Phase 2 suggestion) and a result summary.
- **Database controls:** forced tenant row-level security. Finished runs and finished items cannot be changed (database triggers).

**Background processing.** Runs use the existing PostgreSQL job queue.
- **One part per job:** each part commits on its own, and the next job is enqueued in the same transaction. Concurrency is bounded per scope to one active run, and AI threads are bounded.
- **Retries:** a failing part is retried within the run up to `ASSESSMENT_ITEM_MAX_ATTEMPTS` (2), then marked failed; the run completes *with errors*. **Retry** resumes the failed parts only. **Resume** re-enqueues a run whose worker stopped, without repeating finished parts.
- **Duplicate prevention** (database constraints):
  - one active run per company and scope;
  - one scheduled run per company, quarter and scope;
  - an optional idempotency key returns the existing run.
- **Cache:** a part reuses the previous run's result when its inputs are unchanged. The inputs are:
  - the evidence snapshot and technical-review corrections;
  - the cost scenario (latest stored, not a what-if) and the Phase 2 suggestion;
  - quotation validity on the run date and criticality;
  - the methodology and the AI tier.

  Otherwise the part goes through Phase 3 and Phase 5, which reuse their own cached versions.
- **AI:** Gemini is used only within the existing gate, per-minute and per-day limits, daily budget, cache and total deadline. If a call is refused, the part falls back to rules only, with a note.
- **Fault injection:** a test-only option (`ASSESSMENT_FAULT_INJECTION`) to check partial failure.
- **Access-test worker:** now runs in the queue's documented configuration (ADR-008). It connects as the application role and uses `app_worker` only to claim jobs, because assessments read companies, members and users. Showcase and validation workers are unchanged.

**Dashboard (latest completed run, project scope applied).**
- total parts (in scope / outside scope), assessed / unassessed, insufficient technical data;
- potential AM and conventional candidates (screening potentially suitable), each with a specialist-assessment count;
- OEM: identity verified or not, cost-evidence breakdown, expired evidence, availability not documented;
- potentially obsolete items (part status, description, passport IP status);
- review backlog (live: preliminary plus information requested);
- estimated vs verified savings;
- open evidence gaps;
- changes since the preceding run.

**Savings.**
- **Estimated:** the best positive difference against the OEM baseline among complete, non-excluded options. Labelled provisional, and per part whether the option is technically qualified.
- **Verified:** only when the option meets every mandatory requirement and both it and the OEM baseline rest on verified-current quotations. **A commercially cheap but technically unqualified option is never a verified saving.**

**Comparison with the preceding run**, part by part:
- new AM and conventional candidates;
- technical screening changes;
- evidence gaps opened or closed;
- OEM identity, cost-evidence, lead-time-evidence and obsolescence changes;
- cost changes per option (before, after, delta, scenario versions);
- lead-time changes;
- recommendation outcome changes;
- parts added, removed or unchanged.

**Reports (`apps/intelligence/assessment_reports.py`).**
- **Excel** (openpyxl): sheets Summary, Parts, Changes and Run (with methodology).
- **PDF:** the existing CN-005 renderer, run locally.
- **Content:** both apply the viewer's project scope, state that the figures are preliminary, and contain no files, drawings, CAD or AI prompts. Downloads are audited.

**Permissions and audit.**
- **Engineers** (company-wide or project-scoped) view runs and start them for their scope. Only company-wide engineers may schedule.
- **Clients** have no access.
- **Aries Admin** sees an aggregate per company (`/admin/assessment-summary/`): counts and savings totals only, with no part numbers, descriptions or engineering records.
- **Audit events:** run started, part failed, retried, cancelled, completed, report downloaded, schedule saved.

**API.**
- `GET/POST /intelligence/assessments/`
- `GET /intelligence/assessments/<id>/`, with `retry/`, `cancel/`, `report.xlsx` and `report.pdf`
- `GET/PUT /intelligence/assessment-schedule/`
- `GET /admin/assessment-summary/`

**User interface.**
- **Inventory import → Quarterly assessment:**
  - the run control (with optional Flash-Lite) and live progress;
  - dashboard tiles, changes since the preceding run, and the parts table (status, outcome, screening, OEM evidence, totals, estimated/verified saving, review state, source versions);
  - run history (view an earlier run and its comparison, Excel, PDF, retry, cancel);
  - the quarterly schedule.
- **Admin inventory page:** "Inventory assessments (aggregate)".

**Migration:** `intelligence/0007_assessment_runs` (access-test only).

## 17. Phase 6 integration results (28 Oct 2026; four synthetic parts)

| Run | Kind | Result | Compared with | Changes |
|---|---|---|---|---|
| 1 | manual, rules only | 4 assessed. The first attempt stopped on the old worker configuration; it was resumed through **Retry** and completed. | — | first run |
| 2 | manual, rules only | 4 unchanged (reused) | run 1 | none |
| 3 | manual, Flash-Lite | 4 assessed (AI tier is an input) | run 2 | wear ring: refreshed synthetic OEM quotation (SYN-Q-OEM-104-R1, valid to 2027-03-31). OEM total 3,375.75 → 3,438.75 USD, OEM lead time 70 → 63 days, OEM cost evidence "expired quotation" → historical, lead-time evidence → verified current. |
| 4 | manual, Flash-Lite | 4 unchanged (reused) | run 3 | none |
| 5 | manual, Flash-Lite, test fault injection | First pass: 3 reused, seal failed twice, completed with errors. After **Retry**: completed, seal reused. | run 4 | none |

**Dashboard (run 5).**
- 5 parts in total: 4 in scope, 1 outside (the manually created duplicate test part).
- 4 assessed, 0 unassessed; 4 with insufficient technical data.
- 0 AM candidates (3 need specialist assessment); 0 conventional candidates (1 needs specialist assessment).
- OEM identity verified for 0 of 4; OEM cost evidence "historical" for all 4; 0 with expired OEM evidence after the refresh; availability not documented for 4.
- 0 potentially obsolete.
- Review backlog 4. New recommendation versions need review again; earlier decisions stay on their versions.
- Estimated savings **USD 816.87** (wear ring, conventional route vs OEM, not technically qualified); verified savings **none**.
- 84 open evidence gaps.

**Gemini usage for Phase 6:** 4 Flash-Lite calls (recommendation explanations for run 3), 4,407 input and 2,265 output tokens, estimated **$0.0045**. There were 4 cache hits (feasibility views reused) and 0 refusals. Repeat runs made no calls.

**Total deadline observed live.** The first Gemini call in each newly started process (worker for run 3, API after a restart) hung. It was abandoned at 45 s and answered on the retry about 2–3 s later: 2 attempts, about 50 s in total, inside the 60 s deadline. Normal calls take 2–9 s, so a lower `AI_TIMEOUT_SECONDS` (e.g. 20) would shorten the cold-start delay further. That is a configuration decision.

**Regression re-runs of the earlier flows** made 5 more Flash-Lite calls: Phase 4 notes regenerated under cost method .3, and one explanation. In total this round used 9 Flash-Lite calls, 15,545 input and 4,987 output tokens, estimated **$0.0114**.

## 18. Next phase (not started)

Not started; stopped for review after Phase 6. Open items:
- approval to use external AI for real client companies;
- formal engineering approval rules (OQ-35/OQ-36);
- carrying forward a review decision when a recommendation is regenerated with unchanged technical and commercial inputs (today a new version on a new day needs review again);
- a host scheduler entry for `run_scheduled_assessments`;
- a global cross-company concurrency limit for runs (today: one active run per company scope);
- real quotations, approved exchange rates, OEM supplier, availability and IP records;
- a verified AM build envelope and the Aries process/material list;
- processing the full 573-part inventory, once approved.
