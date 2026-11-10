"""Manufacturing feasibility screening (CN-007 Phase 3): deterministic rules in Python, no external service.

For one spare part, three alternatives side by side: A. OEM procurement, B. additive manufacturing (AM), C. conventional
manufacturing. Each gets a preliminary screening status, the evidence it rests on (and how far that evidence is
verified), technical constraints, missing information, risks and next actions.

Principles
- Evidence states: verified (engineer-verified part field or an approved passport revision), recorded (held but not
  verified: imported customer data, draft passport content, files on record), mentioned (only in the description text),
  missing. Mentions never make a part suitable; only verified evidence can disqualify one.
- No machine capability list is invented: a build envelope is used only when configured (AM_BUILD_ENVELOPE_MM). Process
  and method families are generic, never a statement about Aries' or any supplier's capability.
- A missing OEM record gives "Identification / availability not verified", never "OEM unavailable".
- Nothing here is an approval. No manufacturing authorisation, passport state, evidence level or manufacturing
  eligibility is derived from these results (OQ-35, OQ-36 stay open).
- External AI (apps.intelligence.service) may explain and add gaps; it can never make a status more favourable.
"""
from django.conf import settings

from apps.files.models import EngineeringFile
from apps.passports.models import DigitalPassport, PassportRevision

from .rules import NOT_LIKE_FOR_LIKE, mentions

METHODOLOGY_VERSION = "mf-method-2026-10-31.3"  # .3: proposed material assessed; clone geometry revision; .2: one class per material reading

OEM_STATUS = {
    "not_verified": "Identification / availability not verified",
    "identified_confirmation_required": "OEM part identified: availability requires supplier confirmation",
}
MF_STATUS = {  # AM and conventional manufacturing (screening outcomes, not approvals)
    "potentially_suitable": "Potentially suitable: requires engineering qualification",
    "potentially_suitable_redesign": "Potentially suitable with redesign",
    "insufficient_information": "Insufficient technical information",
    "not_suitable_verified": "Not suitable based on verified constraints",
    "specialist_assessment": "Specialist engineering assessment required",
}
# How favourable a status is. AI views may lower a status (more caution), never raise it.
FAVOURABILITY = {"potentially_suitable": 4, "potentially_suitable_redesign": 3, "specialist_assessment": 2,
                 "insufficient_information": 1, "not_suitable_verified": 0}
STATE_LABEL = {"verified": "Verified", "recorded": "Recorded, not verified", "mentioned": "Mentioned in description only",
               "missing": "Not held"}
AM_PROCESSES = {
    "metal_powder_bed_fusion": "Metal powder bed fusion (L-PBF)", "directed_energy_deposition": "Directed energy deposition",
    "binder_jetting": "Binder jetting", "polymer_powder_bed_fusion": "Polymer powder bed fusion",
    "material_extrusion": "Material extrusion", "none": "No AM process family indicated",
}
CONVENTIONAL_METHODS = {
    "cnc_machining": "CNC machining", "casting": "Casting", "forging": "Forging", "welding_fabrication": "Welding / fabrication",
    "sheet_metal": "Sheet-metal fabrication", "injection_molding": "Injection moulding",
    "powder_metallurgy": "Powder metallurgy (pressing and sintering)", "grinding": "Grinding", "other": "Other method",
}
# Generic process / method families for a material class (textbook associations, not anyone's capability).
AM_BY_MATERIAL = {
    "stainless steel": ["metal_powder_bed_fusion", "directed_energy_deposition", "binder_jetting"],
    "nickel alloy": ["metal_powder_bed_fusion", "directed_energy_deposition"],
    "copper alloy": ["metal_powder_bed_fusion", "binder_jetting"],
}
CONVENTIONAL_BY_MATERIAL = {
    "grey cast iron": [("casting", "Grey cast iron is normally cast"), ("cnc_machining", "Finish machining of cast surfaces")],
    "cast iron": [("casting", "Cast iron is normally cast"), ("cnc_machining", "Finish machining of cast surfaces")],
    "stainless steel": [("cnc_machining", "From bar or plate"), ("casting", "Investment or sand casting"), ("forging", "For wrought grades")],
    "nickel alloy": [("cnc_machining", "From bar or plate"), ("casting", "Investment casting"), ("forging", "For wrought grades")],
    "copper alloy": [("casting", "Sand or centrifugal casting"), ("cnc_machining", "From bar or cast blanks")],
    "carbide": [("powder_metallurgy", "Cemented carbide is pressed and sintered"), ("grinding", "Finish grinding of sintered blanks")],
    "elastomer": [("injection_molding", "Compression or injection moulding of elastomers")],
    "fluoropolymer": [("cnc_machining", "Machining from moulded billet"), ("other", "Compression moulding")],
}
METHOD_NEEDS = {
    "cnc_machining": "a dimensioned drawing with tolerances and surface finish",
    "casting": "a pattern or tooling decision (depends on quantity) and a machining allowance",
    "forging": "die tooling (depends on quantity) and a wrought material grade",
    "powder_metallurgy": "press tooling and a specified carbide grade (specialist producer)",
    "grinding": "finished-dimension tolerances",
    "injection_molding": "a mould tool (depends on quantity) and a compound specification",
    "other": "a specialist route review",
}


# ------------------------------------------------------------------ evidence

def _ev(key, label, state, value="", source="", note=""):
    return {"key": key, "label": label, "state": state, "state_label": STATE_LABEL[state], "value": value or "",
            "source": source, "note": note}


def _verified(part, field) -> bool:
    return bool(((part.field_provenance or {}).get(field) or {}).get("verified_by"))


def passport_info(part) -> dict | None:
    passport = DigitalPassport.objects.filter(tenant=part.tenant_id, part=part).first()
    if passport is None:
        return None
    rev = PassportRevision.objects.filter(passport=passport).order_by("-revision_number").first()
    return {"passport_number": passport.passport_number, "passport_id": str(passport.pk),
            "revision_id": str(rev.pk) if rev else None, "revision_number": rev.revision_number if rev else None,
            "revision_status": rev.status if rev else None, "content": (rev.content or {}) if rev else {}}


def documents(part) -> list[dict]:
    return [{"id": str(f.pk), "kind": f.kind, "category": f.category, "title": f.title}
            for f in EngineeringFile.objects.filter(tenant=part.tenant_id, part=part).order_by("created_at")]


def _passport_value(pp, level, key):
    """(value, state) from the latest passport revision: verified when that revision is approved, else recorded."""
    if not pp:
        return "", "missing"
    v = ((pp["content"].get(level) or {}).get(key))
    if v in (None, "", [], {}):
        return "", "missing"
    state = "verified" if pp["revision_status"] in ("approved", "superseded") else "recorded"
    return v, state


def collect(part, analysis: dict, docs: list[dict], pp: dict | None) -> dict:
    """Every evidence item the three alternatives use, each with its state and source."""
    a = analysis
    src_part = "customer inventory import" if part.import_record else "part record"
    pp_src = f"passport {pp['passport_number']} rev {pp['revision_number']} ({pp['revision_status']})" if pp else ""
    E = {}
    mfr = a["manufacturer"]
    if not mfr["cleaned"] or mfr["placeholder"]:
        E["manufacturer"] = _ev("manufacturer", "Manufacturer / OEM identity", "missing", mfr["as_supplied"], src_part,
                                "No real manufacturer name" + (" (placeholder value)" if mfr["placeholder"] else ""))
    else:
        note = "As supplied by the customer; not confirmed as the original equipment manufacturer."
        if mfr["possibly_truncated"]:
            note += " The name may be truncated at the source field limit."
        E["manufacturer"] = _ev("manufacturer", "Manufacturer / OEM identity", "verified" if _verified(part, "manufacturer") else "recorded",
                                mfr["cleaned"], src_part, note)
    E["oem_part_number"] = _ev("oem_part_number", "OEM part number",
                               ("verified" if _verified(part, "oem_part_number") else "recorded") if part.oem_part_number else "missing",
                               part.oem_part_number, "part record" if part.oem_part_number else "",
                               "" if part.oem_part_number else "No OEM part number is held.")
    E["manufacturer_reference"] = _ev("manufacturer_reference", "Manufacturer reference code",
                                      "recorded" if part.manufacturer_reference else "missing", part.manufacturer_reference,
                                      src_part if part.manufacturer_reference else "",
                                      "Customer/ERP reference code: not an OEM part number.")
    E["supplier"] = _ev("supplier", "Authorised supplier", "missing", note="No authorised-supplier record is held.")
    E["availability"] = _ev("availability", "Availability / obsolescence", "missing",
                            note="No availability or obsolescence information is documented.")
    E["supersession"] = _ev("supersession", "Replacement / supersession", "missing", note="No replacement or supersession is evidenced.")

    # classification
    cls = a["classification"]
    if part.category != "unknown" and _verified(part, "category"):
        E["category"] = _ev("category", "Technical category", "verified", part.category, "engineer classification")
    elif part.category != "unknown" and not part.import_record:
        E["category"] = _ev("category", "Technical category", "recorded", part.category, "part record")
    elif cls["category"] != "unknown":
        E["category"] = _ev("category", "Technical category", "mentioned", cls["category"], "rule reading of the description")
    else:
        E["category"] = _ev("category", "Technical category", "missing")
    E["function"] = _ev("function", "Part function / family", "mentioned" if cls["family"] else "missing", cls["family"],
                        "rule reading of the description" if cls["family"] else "",
                        "Assembly of several components (from the description)" if cls.get("assembly") else "")

    # material: a proposed material change (clone or variant) is what would be manufactured, so it is assessed instead of the
    # original; it is never treated as verified unless an engineer verified it (passport R-L1 first, then the part record)
    grade, gstate = _passport_value(pp, "rl1", "original_material_grade")
    proposed, pstate = _passport_value(pp, "rl1", "proposed_material")
    mats = a["mentions"]["materials"]
    original = part.original_material or grade
    change = (f"Proposed material change from {original or 'an unrecorded material'}"
              + (f" (reason: {part.material_change_reason})" if part.material_change_reason else "")
              + "; suitability of the proposed material is not assessed or approved.")
    if proposed:
        E["material"] = _ev("material", "Material grade (proposed change)", pstate, proposed, pp_src, change)
    elif part.proposed_material:
        E["material"] = _ev("material", "Material grade (proposed change)", "verified" if _verified(part, "proposed_material") else "recorded",
                            part.proposed_material, "clone / variant request" if part.source_part_id else "part record",
                            change + " Client-submitted unless verified by Aries.")
    elif part.original_material:
        E["material"] = _ev("material", "Material grade", "verified" if _verified(part, "original_material") else "recorded",
                            part.original_material, "part record")
    elif grade:
        E["material"] = _ev("material", "Material grade", gstate, grade, pp_src)
    elif mats:
        E["material"] = _ev("material", "Material grade", "mentioned", "; ".join(m["reading"] for m in mats), "description text",
                            "Read from the description; grade, condition and properties not verified.")
    else:
        E["material"] = _ev("material", "Material grade", "missing")
    # material classes from the description and from a held (recorded or verified) material value: both count
    held = mentions(E["material"]["value"])["material_classes"] if E["material"]["state"] in ("verified", "recorded") else []
    E["material_classes"] = sorted(set(a["mentions"]["material_classes"]) | set(held))

    # dimensions and geometry
    size, sstate = _passport_value(pp, "rl1", "part_size")
    dims = a["mentions"]["dimensions"]
    if part.dimensions:
        E["dimensions"] = _ev("dimensions", "Dimensions", "verified" if _verified(part, "dimensions") else "recorded", part.dimensions, "part record")
    elif size:
        E["dimensions"] = _ev("dimensions", "Dimensions", sstate, size, pp_src)
    elif dims:
        E["dimensions"] = _ev("dimensions", "Dimensions", "mentioned", ", ".join(f"{d['value']:g} {d['unit']}" for d in dims),
                              "description text", "Numbers as written; their roles (diameter, width, length) are not stated.")
    else:
        E["dimensions"] = _ev("dimensions", "Dimensions", "missing")
    cad = [d for d in docs if d["kind"] == "step" or d["category"] == "3d_model"]
    drw = [d for d in docs if d["kind"] == "dwg" or d["category"] == "drawing"]
    photos = [d for d in docs if d["category"] == "photo" or d["kind"] == "image"]
    E["cad"] = _ev("cad", "3D CAD / STEP model", "recorded" if cad else "missing", ", ".join(d["title"] for d in cad)[:200],
                   "engineering files" if cad else "", "File on record; not checked against the part here." if cad else "")
    E["drawing"] = _ev("drawing", "Engineering drawing", "recorded" if drw else "missing", ", ".join(d["title"] for d in drw)[:200],
                       "engineering files" if drw else "")
    E["photo"] = _ev("photo", "Photographs", "recorded" if photos else "missing", f"{len(photos)} file(s)" if photos else "",
                     "engineering files" if photos else "")
    tol, tstate = _passport_value(pp, "rl2", "dimensional_tolerances")
    E["tolerances"] = _ev("tolerances", "Dimensional tolerances", tstate, tol, pp_src if tol else "")
    E["surface_finish"] = _ev("surface_finish", "Surface finish", "missing", note="No surface-finish requirement is held.")

    # service conditions, properties, quality
    service = {k: (pp["content"].get("rl1") or {}).get(k) for k in ("application", "atmosphere", "motion", "rpm", "operating_environment")} if pp else {}
    service = {k: v for k, v in service.items() if v}
    sstate2 = ("verified" if pp and pp["revision_status"] in ("approved", "superseded") else "recorded") if service else "missing"
    E["service_conditions"] = _ev("service_conditions", "Service conditions (application, atmosphere, motion)", sstate2,
                                  ", ".join(f"{k}: {v}" for k, v in service.items()), pp_src if service else "")
    E["temperature_pressure"] = _ev("temperature_pressure", "Temperature, pressure and load", "missing",
                                    note="Operating temperature, pressure and load are not held.")
    E["wear_corrosion"] = _ev("wear_corrosion", "Wear and corrosion exposure",
                              "recorded" if service.get("atmosphere") else ("mentioned" if "wear" in (cls["family"] or "").lower() else "missing"),
                              service.get("atmosphere", "") or ("wear service implied by the part family" if "wear" in (cls["family"] or "").lower() else ""))
    mech, mstate = _passport_value(pp, "rl2", "mechanical_acceptance")
    E["mechanical_properties"] = _ev("mechanical_properties", "Mechanical property requirements", mstate,
                                     f"{len(mech)} requirement(s)" if mech else "", pp_src if mech else "")
    std, ststate = _passport_value(pp, "rl2", "applicable_standards")
    E["standards"] = _ev("standards", "Applicable standards and certification", ststate, std, pp_src if std else "")
    itp, istate = _passport_value(pp, "rl2", "inspection_test_plan")
    insp_docs = [d for d in docs if d["category"] in ("inspection", "certificate", "mat_cert", "mech_test", "chem_analysis", "lab_test")]
    E["inspection"] = _ev("inspection", "Inspection and testing requirements", istate if itp else ("recorded" if insp_docs else "missing"),
                          itp or (f"{len(insp_docs)} quality document(s)" if insp_docs else ""), pp_src if itp else ("engineering files" if insp_docs else ""))
    ip, ipstate = _passport_value(pp, "rl1", "ip_status")
    E["ip"] = _ev("ip", "OEM IP / reproduction restrictions", ipstate, ip, pp_src if ip else "",
                  "" if ip else "Whether the OEM restricts reproduction has not been assessed.")
    crit = part.criticality
    E["criticality"] = _ev("criticality", "Safety / equipment criticality", "missing" if crit == "unknown" else "recorded",
                           "" if crit == "unknown" else part.get_criticality_display(), "part record" if crit != "unknown" else "",
                           "Not assessed. The customer ABC indicator is not used as engineering criticality.")
    E["quantity"] = _ev("quantity", "Required quantity", "missing", note="No required quantity is recorded (drives tooling decisions).")
    E["build_envelope"] = _ev("build_envelope", "Verified AM build envelope",
                              "verified" if settings.AM_BUILD_ENVELOPE_MM else "missing",
                              " x ".join(f"{v:g}" for v in settings.AM_BUILD_ENVELOPE_MM) + " mm" if settings.AM_BUILD_ENVELOPE_MM else "",
                              "configuration" if settings.AM_BUILD_ENVELOPE_MM else "",
                              "" if settings.AM_BUILD_ENVELOPE_MM else "No verified machine build envelope is configured.")
    return E


def _held(e) -> bool:
    return e["state"] in ("verified", "recorded")


def _items(E, keys):
    return [E[k] for k in keys]


def _gap(e) -> str:
    """A missing-information entry: the label when nothing is held, else what still needs verifying."""
    return e["label"] if e["state"] == "missing" else f"{e['label']}: verification needed ({e['state_label'].lower()})"


def _missing(E, keys):
    return [_gap(E[k]) for k in keys if E[k]["state"] != "verified" and not (E[k]["state"] == "recorded" and k in ("cad", "drawing", "photo"))]


# ------------------------------------------------------------------ the three alternatives

def oem(E, analysis) -> dict:
    keys = ["manufacturer", "oem_part_number", "manufacturer_reference", "supplier", "availability", "supersession"]
    identified = E["oem_part_number"]["state"] == "verified" and E["manufacturer"]["state"] == "verified"
    status = "identified_confirmation_required" if identified else "not_verified"
    constraints, risks = [], []
    if E["manufacturer_reference"]["state"] != "missing":
        constraints.append({"code": "reference_not_oem_pn", "kind": "note",
                            "text": "The manufacturer reference is a customer/ERP code and is not used as an OEM part number."})
    if analysis["manufacturer"]["possibly_truncated"]:
        risks.append("The manufacturer name may be truncated; the OEM identity could be misread.")
    if E["manufacturer"]["state"] == "missing":
        risks.append("No real manufacturer name: the OEM cannot be identified from the record.")
    dup = analysis["duplicates"]["same_description_and_manufacturer"]
    if dup:
        risks.append(f"Possible duplicate record(s) {', '.join(dup)}: consolidate the identification before procurement.")
    if analysis["manufacturer"]["alias_candidates"]:
        risks.append("Other spellings of this manufacturer exist in the company inventory: "
                     + ", ".join(analysis["manufacturer"]["alias_candidates"][:5]) + ".")
    actions = []
    if E["manufacturer"]["state"] != "verified" or E["oem_part_number"]["state"] != "verified":
        actions.append("Confirm the OEM identity and OEM part number from the nameplate, OEM documentation or purchasing records, "
                       "and record them as verified values with the evidence reference.")
    actions.append("Request availability, obsolescence and any supersession from the OEM or an authorised distributor "
                   "(supplier confirmation).")
    return {"status": status, "status_label": OEM_STATUS[status], "evidence": _items(E, keys), "constraints": constraints,
            "missing": [_gap(E[k]) for k in keys if E[k]["state"] != "verified" and k != "manufacturer_reference"],
            "risks": risks, "next_actions": actions,
            "note": "A missing OEM record means availability is unknown, not that the OEM part is unavailable."}


def _common_review(E, cls):
    """Constraints both manufacturing routes share. kind: block (verified, disqualifying), review (specialist)."""
    out = []
    if E["category"]["state"] == "verified" and E["category"]["value"] in ("electrical", "electronic"):
        out.append({"code": "electrical_or_electronic", "kind": "block", "verified": True,
                    "text": "Electrical or electronic part (verified category): outside manufacturing replacement of mechanical parts."})
    elif E["category"]["value"] in ("electrical", "electronic"):
        out.append({"code": "electrical_or_electronic", "kind": "review", "verified": False,
                    "text": "Description reads as an electrical or electronic part (not verified)."})
    if cls.get("assembly"):
        out.append({"code": "assembly", "kind": "review", "verified": False,
                    "text": "Assembly of several components (from the description): each component needs its own assessment; "
                            "not one manufacturable part."})
    if E["criticality"]["value"] == "Critical":
        out.append({"code": "critical", "kind": "review", "verified": False,
                    "text": "Recorded as a critical part: specialist engineering assessment and qualification are needed."})
    return out


def _status(constraints, sufficient) -> str:
    kinds = {c["kind"] for c in constraints}
    if "block" in kinds:
        return "not_suitable_verified"
    if "review" in kinds:
        return "specialist_assessment"
    if not sufficient:
        return "insufficient_information"
    return "potentially_suitable"


def _sufficient(E) -> bool:
    return (_held(E["cad"]) or _held(E["drawing"])) and _held(E["material"]) and _held(E["dimensions"])


def additive(E, analysis) -> dict:
    cls = analysis["classification"]
    keys = ["function", "category", "dimensions", "cad", "drawing", "photo", "material", "build_envelope", "tolerances",
            "surface_finish", "mechanical_properties", "temperature_pressure", "wear_corrosion", "service_conditions",
            "inspection", "standards", "ip", "criticality"]
    cons = _common_review(E, cls)
    for c in E["material_classes"]:
        if c in NOT_LIKE_FOR_LIKE:
            verified = E["material"]["state"] == "verified"
            cons.append({"code": f"material_{c.replace(' ', '_')}", "kind": "review", "verified": verified,
                         "text": NOT_LIKE_FOR_LIKE[c] + (" (material verified)" if verified else f" (material {E['material']['state_label'].lower()})")
                                 + "; a substitute material needs specialist engineering assessment."})
    env = settings.AM_BUILD_ENVELOPE_MM
    largest = mentions(E["dimensions"]["value"])["largest_mm"] if E["dimensions"]["value"] else None
    if env and E["dimensions"]["state"] == "verified" and largest and largest > max(env):
        cons.append({"code": "exceeds_envelope", "kind": "block", "verified": True,
                     "text": f"A verified dimension ({largest:g} mm) exceeds the configured build envelope."})
    elif env and largest and largest > max(env):
        cons.append({"code": "may_exceed_envelope", "kind": "review", "verified": False,
                     "text": f"A dimension in the description ({largest:g} mm) may exceed the configured build envelope (not verified)."})
    status = _status(cons, _sufficient(E))
    procs, basis = [], ""
    classes = [c for c in E["material_classes"] if c in AM_BY_MATERIAL]
    if classes:
        for c in classes:
            procs += [p for p in AM_BY_MATERIAL[c] if p not in procs]
        basis = (f"Generic AM process families for {', '.join(classes)} ({E['material']['state_label'].lower()}). "
                 "No Aries machine or material qualification is implied.")
    elif E["material_classes"]:
        basis = "No common AM process produces the stated material like-for-like."
    else:
        basis = "No AM process family can be identified without a material."
    risks = []
    if E["dimensions"]["state"] == "mentioned":
        risks.append("Dimension roles are not stated: geometry cannot be derived from the description.")
    if cls.get("assembly"):
        risks.append("Sealing faces, springs and elastomers of an assembly have different material and process needs.")
    if any(c in NOT_LIKE_FOR_LIKE for c in E["material_classes"]):
        risks.append("A substitute material changes wear, hardness or corrosion behaviour and must be qualified.")
    actions = []
    if not (_held(E["cad"]) or _held(E["drawing"])):
        actions.append("Obtain a drawing or 3D model (or scan the part) to establish geometry and tolerances.")
    if E["material"]["state"] != "verified":
        actions.append("Verify the material grade (OEM documentation, material certificate or PMI).")
    actions.append("Record service conditions (temperature, pressure, load, wear, corrosion) and criticality.")
    actions.append("Assess OEM IP / reproduction restrictions before any reproduction.")
    if status in ("specialist_assessment", "not_suitable_verified"):
        actions.append("Refer to a specialist engineer for an AM route decision.")
    actions.append("Any AM route needs engineering qualification: post-processing, inspection and testing to defined standards.")
    return {"status": status, "status_label": MF_STATUS[status], "evidence": _items(E, keys), "constraints": cons,
            "missing": _missing(E, [k for k in keys if k not in ("function", "category", "photo")]),
            "risks": risks, "next_actions": actions,
            "candidate_processes": [{"process": p, "label": AM_PROCESSES[p], "basis": basis} for p in procs],
            "process_basis": basis,
            "qualification": ["Engineering qualification of material, process and part before any use",
                              "Post-processing (heat treatment, machining, surface finishing) to be defined",
                              "Inspection and testing against defined acceptance criteria"]}


def conventional(E, analysis) -> dict:
    cls = analysis["classification"]
    keys = ["function", "category", "material", "dimensions", "drawing", "cad", "tolerances", "surface_finish", "quantity",
            "mechanical_properties", "inspection", "standards", "ip", "criticality"]
    cons = _common_review(E, cls)
    status = _status(cons, _sufficient(E))
    methods = []
    for c in E["material_classes"]:
        for m, why in CONVENTIONAL_BY_MATERIAL.get(c, []):
            if m not in [x["method"] for x in methods]:
                methods.append({"method": m, "label": CONVENTIONAL_METHODS[m], "basis":
                                f"{why}; consistent with the material {E['material']['state_label'].lower()}.",
                                "needs": METHOD_NEEDS.get(m, "")})
    basis = ("Methods follow from the material only, never from the description's resemblance to a common part."
             if methods else "No method can be identified without a material.")
    risks = []
    if E["dimensions"]["state"] == "mentioned":
        risks.append("Dimension roles are not stated: a part cannot be made from the description.")
    if cls.get("assembly"):
        risks.append("An assembly combines several materials and processes; conventional manufacture of each component "
                     "needs its own route.")
    if E["quantity"]["state"] == "missing" and any(m["method"] in ("casting", "forging", "injection_molding", "powder_metallurgy") for m in methods):
        risks.append("Tooling-based methods depend on the required quantity, which is not recorded.")
    actions = []
    if not _held(E["drawing"]):
        actions.append("Obtain a dimensioned drawing with tolerances and surface finish (or reverse-engineer the part).")
    if E["material"]["state"] != "verified":
        actions.append("Verify the material grade and condition.")
    actions.append("Record the required quantity and the inspection and certification requirements.")
    if status == "specialist_assessment":
        actions.append("Refer to a specialist engineer for a manufacturing route decision.")
    return {"status": status, "status_label": MF_STATUS[status], "evidence": _items(E, keys), "constraints": cons,
            "missing": _missing(E, [k for k in keys if k not in ("function", "category")]), "risks": risks,
            "next_actions": actions, "candidate_methods": methods, "method_basis": basis,
            "qualification": ["First-article inspection against the drawing", "Material certification to the specified grade"]}


GEOMETRY_ACTION = "Provide revised CAD and an engineering drawing for the clone's modified dimensions (the original geometry does not apply)."


def geometry_revision(part, E) -> dict | None:
    """Post-UAT Case C: a clone whose dimensions differ from the original's is not described by the original CAD or drawings.
    Until the clone holds its own CAD or drawing, both manufacturing routes need that revision (specialist review)."""
    if not part.source_part_id:
        return None
    original = str((part.source_snapshot or {}).get("dimensions") or "").strip().lower()
    changed = bool(part.dimensions) and str(part.dimensions).strip().lower() != original
    if not changed or _held(E["cad"]) or _held(E["drawing"]):
        return None
    return {"code": "geometry_revision_required", "kind": "review", "verified": False,
            "text": f"Modified dimensions ({part.dimensions}; original {original or 'not recorded'}): the original CAD and drawings do "
                    "not describe this clone. Revised CAD or a drawing is required."}


def assess(part, analysis: dict, docs: list[dict], pp: dict | None) -> dict:
    E = collect(part, analysis, docs, pp)
    o, am, cv = oem(E, analysis), additive(E, analysis), conventional(E, analysis)
    geo = geometry_revision(part, E)
    if geo:
        for alt, labels in ((am, MF_STATUS), (cv, MF_STATUS)):
            alt["constraints"] = [*alt["constraints"], geo]
            alt["status"] = _status(alt["constraints"], _sufficient(E))
            alt["status_label"] = labels[alt["status"]]
            alt["next_actions"] = [GEOMETRY_ACTION, *[x for x in alt["next_actions"] if x != GEOMETRY_ACTION]]
    cons, seen = [], set()
    for scope, alt in (("additive", am), ("conventional", cv)):
        for c in alt["constraints"]:
            if c["code"] not in seen and c["kind"] in ("block", "review"):
                seen.add(c["code"])
                cons.append({**c, "applies_to": [s for s, x in (("additive", am), ("conventional", cv))
                                                 if any(y["code"] == c["code"] for y in x["constraints"])]})
    missing = []
    for alt in (o, am, cv):
        missing += [m for m in alt["missing"] if m not in missing]
    actions = []
    for alt in (o, am, cv):
        actions += [x for x in alt["next_actions"] if x not in actions]
    return {"methodology_version": METHODOLOGY_VERSION, "oem": o, "additive": am, "conventional": cv,
            "constraints": cons, "missing_information": missing, "next_actions": actions,
            "evidence": {k: v for k, v in E.items() if k != "material_classes"}, "material_classes": E["material_classes"],
            "authorisation": {"manufacturing_authorised": False,
                              "text": "Screening only. No manufacturing authorisation, passport approval, publication or "
                                      "manufacturing eligibility is given or changed (OQ-35, OQ-36)."}}
