# Passport form: field-by-field control mapping

Requirement update 2026-10 (client spare-part creation and Digital Passport form improvements). Reviewed against BRD v0.4
(BR-006, BR-007, BR-008, BR-009, BR-026, BR-041; OQ-16, OQ-21, OQ-35, OQ-36) and `backend/apps/passports/content.py`.

## Rules applied

- **No field was removed or renamed.** Every key in the stored content stays the same. Structured controls read and write
  the same string, boolean or number as before.
- **Stored values are never converted.** A control rewrites a value only when the user changes it. A stored value that
  does not match the control's format, for example `120.0 x 34.0 mm (Ø x H)` or `SR 650 °C 2 h`, opens as a
  **Custom value**: it stays readable and editable as text, and the user can switch to structured entry.
- **Controlled lists are provisional** (OQ-16 is open). They are served by `GET /api/v1/passport-field-options/` from
  `backend/apps/passports/options.py`, and every list allows **Other / specify**.
- **Engineering judgement stays free text.** No list defines approval, eligibility or AMSL rules.
- **Required fields are unchanged.** Completeness, evidence levels and the approval and manufacturing gates (OQ-35/OQ-36)
  are untouched. Drafts can be saved incomplete.
- **Multi-select storage format:** `A; B; other text`. Text without `;` is one item, so legacy prose stays as written.

## Classification key

| # | Control |
|---|---|
| 1 | Fixed-option dropdown |
| 2 | Searchable dropdown / controlled master data (with Other) |
| 3 | Multi-select (with Other) |
| 4 | Yes / No / Not applicable |
| 5 | Numeric value with unit |
| 6 | Date picker |
| 7 | Free text (engineering judgement) |
| 8 | File / document selector |

## R-L1: identification and operating context (BR-006, BR-009)

| Field (key) | Req. | Before | Now | Class | Notes |
|---|---|---|---|---|---|
| 3D CAD file available (`cad_3d_available`) | Yes | Yes/No | Yes / No + Not applicable | 4 | unchanged |
| 2D drawings available (`drawings_2d_available`) | Yes | Yes/No | Yes / No + Not applicable | 4 | unchanged |
| Original material grade (`original_material_grade`) | Yes | text | searchable material list + Other | 2 | provisional list (OQ-16); pre-filled from part |
| Material identification (`material_identification_method`) | Yes | dropdown | PMI / Destructive / OEM datasheet | 1 | BRD values only; server-validated |
| Proposed material (`proposed_material`) | No | text | searchable material list + Other | 2 | BR-009 |
| Reason for the proposed material (`proposed_material_reason`) | No | text | common reasons + free text | 2/7 | engineering reason stays free text |
| Technical description (`technical_description`) | Yes | textarea | textarea | 7 | engineering judgement |
| Part size (`part_size`) | Yes | text | L×W×H or Ø×H numbers + unit (mm, cm, m, in) | 5 | other formats kept as custom; pre-filled from part |
| Application of part (`application`) | Yes | text | searchable application list + Other | 2 | pre-filled from part |
| Atmosphere (`atmosphere`) | Yes | dropdown | Corrosive / Non-corrosive | 1 | BRD values only |
| Operating environment (`operating_environment`) **new, optional** | No | — | dropdown + Other / specify | 1 | detail beside the atmosphere; not in completeness |
| Static or rotating (`motion`) | Yes | dropdown | Static / Rotating | 1 | unchanged |
| RPM (`rpm`) | if rotating | text | number, unit rpm (stored as a bare number as before) | 5 | `1450 rpm` or `approx 1500` stays custom |
| IP consideration (`ip_status`) | Yes | dropdown | Obsolete / Active | 1 | unchanged |
| Not applicable reasons (`not_applicable`) | — | per field | per field | 7 | unchanged |
| Value sources (`value_sources`) **new, optional** | — | — | client_submitted / aries_verified per pre-filled field | — | provenance only, see below |

## R-L2: manufacturing solution and acceptance (BR-007, BR-026, BR-041)

| Field (key) | Req. | Now | Class | Notes |
|---|---|---|---|---|
| Manufacturing process (`manufacturing_process`) **new, optional** | No | dropdown + Other | 1 | controlled process selection |
| Manufacturing solution (`manufacturing_solution`) | Yes | textarea | 7 | engineering judgement |
| Material selection (`material_selection`) | Yes | searchable material list + Other | 2 | OQ-16 |
| Material category (`material_category`) | Yes | Equivalent / Superior | 1 | unchanged |
| Criticality (AMSL) (`criticality_amsl`) | Yes | free text, provisional | 7 | **no AMSL classes invented** (OQ-36); never used for eligibility |
| Feedstock (`feedstock`) | Yes | searchable list + Other | 2 | |
| Applicable standards (`applicable_standards`) | Yes | multi-select + Other | 3 | mandatory set open (OQ-21) |
| Mechanical acceptance table (`mechanical_acceptance`) | Yes | rows: property (1), requirement (text, e.g. `≥ 485`), unit (2: MPa, %, HV, HRC…), standard (2) | 1/2/5 | structure unchanged |
| Dimensional tolerances (`dimensional_tolerances`) | Yes | searchable class list (ISO 2768-f/m/c/v, -mK…) + free addition | 2 | `ISO 2768-mK; bores H7` stays as written |
| NDT (`ndt`) | Yes | multi-select inspection methods + Other | 3 | |
| Inspection and test plan (`inspection_test_plan`) | Yes | reference text with this passport's document titles suggested | 8/7 | the file itself is linked under R-L3 |
| MTC required (`mtc_required`) | Yes | Yes / No | 4 | unchanged |
| Test coupon details (`test_coupons`) | Yes | textarea | 7 | |
| Spec: job number | Yes | text | 7 | identifier |
| Spec: material | Yes | searchable material list | 2 | |
| Spec: feedstock | Yes | searchable list + lot | 2 | |
| Spec: machine | Yes | searchable machine list + Other | 2 | provisional machine master (OQ-16) |
| Spec: layer thickness | Yes | number + unit (µm, mm) | 5 | |
| Spec: inert gas | Yes | Argon / Nitrogen / Not required + Other | 1 | |
| Spec: support strategy | Yes | dropdown + Other | 1 | |
| Spec: build orientation | Yes | searchable list + free text | 2 | |
| Spec: heat treatment | Yes | process (1) + temperature °C + hold time h (5) → `Stress relief 650 °C / 2 h` | 1/5 | other descriptions kept as custom |
| Spec: post-processing | Yes | multi-select + Other | 3 | |
| Spec: machining | Yes | text | 7 | e.g. `Bore H7` |
| Spec: printing / post-processing hours | Yes | number, h | 5 | already numeric on the server |
| Process parameters (`process_parameters`) | No | rows: name (2), value (numeric text), unit (2: W, mm/s, µm, J/mm³…) | 2/5 | BR-041 |

## R-L3: document evidence (BR-008)

| Field | Req. | Now | Class |
|---|---|---|---|
| ITP, machine details, print orientation, dimensional inspection, material test certificate | Yes | selector of this passport's uploaded files; missing items flagged | 8 |
| Evidence notes | No | textarea | 7 |
| QA verification | — | shown as Pending (OQ-35) | — |

**Date pickers (class 6):** no passport field holds a date in BRD v0.4 or the data model, so none were added.

## Provenance (client-submitted versus Aries-verified)

- **Spare part:** `field_provenance` records, for each master-data field, whether the client or Aries entered it, who
  entered it and whether an Aries Engineer verified it. A client change clears verification; an Aries edit marks the value
  as Aries-entered.
- **Passport R-L1:** values pre-filled from a client submission are tagged `client_submitted` until an engineer marks them
  verified (`aries_verified`) or re-enters them, which removes the tag.

## Gaps and items needing a decision

1. **Temperatures:** BRD v0.4 R-L1/R-L2 has no operating-temperature field. Only heat-treatment temperature is
   structured. Adding operating temperature would need a BRD change.
2. **Controlled lists** are provisional starting sets (OQ-16). An authoritative material, machine and process master
   list, and who maintains it, is still to be decided.
3. **Criticality (AMSL)** stays free text until the classes are approved (OQ-36).
4. **Mandatory standards** (OQ-21) are still open.
