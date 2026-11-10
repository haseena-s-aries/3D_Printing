"""Structured passport content per readiness level (BRD v0.4).

R-L1 identification and operating context (BR-006), R-L2 manufacturing solution and acceptance (BR-007, with the
manufacturing specification of BR-026 and process parameters of BR-041), R-L3 document evidence (BR-008).

All fields are optional while a revision is a draft. `completeness()` reports what is still missing so the UI can
show progress. It is information only: evidence-level transitions and QA verification stay gated (OQ-35).
"""
from rest_framework import serializers

CHOICES_RL1 = {
    "material_identification_method": {"pmi", "destructive", "oem"},
    "atmosphere": {"corrosive", "non_corrosive"},
    "motion": {"static", "rotating"},
    "ip_status": {"obsolete", "active"},
}

RL1_REQUIRED = ["cad_3d_available", "drawings_2d_available", "original_material_grade", "material_identification_method",
                "technical_description", "part_size", "application", "atmosphere", "motion", "ip_status"]
RL2_REQUIRED = ["manufacturing_solution", "material_selection", "material_category", "criticality_amsl", "feedstock",
                "applicable_standards", "mechanical_acceptance", "dimensional_tolerances", "ndt", "inspection_test_plan",
                "mtc_required", "test_coupons"]
SPEC_REQUIRED = ["job_number", "material", "feedstock", "machine", "layer_thickness", "support_strategy", "build_orientation",
                 "inert_gas", "heat_treatment", "post_processing", "machining", "printing_hours", "post_processing_hours"]
# BR-008: the five R-L3 evidence documents
RL3_EVIDENCE = ["itp", "machine_details", "print_orientation", "dimensional_inspection", "material_test_certificate"]


def _text(max_length):
    return serializers.CharField(required=False, allow_blank=True, max_length=max_length)


class RL1Serializer(serializers.Serializer):
    cad_3d_available = serializers.BooleanField(required=False, allow_null=True)
    drawings_2d_available = serializers.BooleanField(required=False, allow_null=True)
    original_material_grade = _text(120)
    proposed_material = _text(120)
    proposed_material_reason = _text(500)  # BR-009: reason for the proposal
    material_identification_method = _text(20)
    technical_description = _text(2000)
    part_size = _text(120)
    application = _text(200)
    atmosphere = _text(20)
    # Optional detail beside the BR-006 corrosive/non-corrosive atmosphere (requirement update 2026-10; not required)
    operating_environment = _text(120)
    motion = _text(20)
    rpm = _text(40)
    ip_status = _text(20)
    # BR-006: a field may be marked "not applicable" with a reason instead of a value
    not_applicable = serializers.DictField(child=serializers.CharField(max_length=300), required=False)
    # Provenance of values taken over from a client-submitted spare-part record (requirement update 2026-10):
    # client_submitted until an Aries Engineer confirms it (aries_verified) or re-enters the value (marker removed).
    value_sources = serializers.DictField(child=serializers.ChoiceField(
        choices=["client_submitted", "aries_verified", "inherited_reference"]), required=False)

    def validate(self, data):
        for key, allowed in CHOICES_RL1.items():
            if data.get(key) and data[key] not in allowed:
                raise serializers.ValidationError({key: f"Must be one of: {', '.join(sorted(allowed))}."})
        unknown = set(data.get("not_applicable", {})) - set(RL1_REQUIRED + ["rpm"])
        if unknown:
            raise serializers.ValidationError({"not_applicable": f"Unknown field(s): {', '.join(sorted(unknown))}."})
        unknown = set(data.get("value_sources", {})) - set(RL1_REQUIRED + ["rpm", "proposed_material", "proposed_material_reason",
                                                                          "operating_environment"])
        if unknown:
            raise serializers.ValidationError({"value_sources": f"Unknown field(s): {', '.join(sorted(unknown))}."})
        if any(not reason.strip() for reason in data.get("not_applicable", {}).values()):
            raise serializers.ValidationError({"not_applicable": "A reason is required for every field marked not applicable."})
        return data


class AcceptanceRowSerializer(serializers.Serializer):
    """One row of the mechanical acceptance table (tensile, yield, elongation, hardness, ...)."""

    property = serializers.ChoiceField(choices=["tensile", "yield", "elongation", "hardness", "impact", "other"])
    requirement = _text(120)
    unit = _text(30)
    standard = _text(120)  # e.g. ISO 6892-1
    # CN-005 R6: how often the test is performed (e.g. "Prior to every build", "Per build"); optional, provisional list
    frequency = _text(120)


class ProcessParameterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    value = _text(80)
    unit = _text(30)


class ManufacturingSpecSerializer(serializers.Serializer):
    """BR-026 manufacturing (printing) specification template; hours are numeric."""

    job_number = _text(60)
    material = _text(120)
    feedstock = _text(120)
    machine = _text(120)
    layer_thickness = _text(40)
    support_strategy = _text(300)
    build_orientation = _text(300)
    inert_gas = _text(60)
    heat_treatment = _text(300)
    post_processing = _text(300)
    machining = _text(300)
    printing_hours = serializers.FloatField(min_value=0, max_value=100000, required=False, allow_null=True)
    post_processing_hours = serializers.FloatField(min_value=0, max_value=100000, required=False, allow_null=True)
    process_parameters = ProcessParameterSerializer(many=True, required=False)  # BR-041


class RL2Serializer(serializers.Serializer):
    manufacturing_solution = _text(2000)
    # Optional controlled process selection beside the free-text solution (requirement update 2026-10; not required)
    manufacturing_process = _text(120)
    material_selection = _text(200)
    material_category = serializers.ChoiceField(choices=["equivalent", "superior"], required=False, allow_blank=True)
    # Provisional free text (AMSL classes are not defined in BRD v0.4). Stored as entered and never used to derive
    # manufacturing eligibility, evidence level or approval; those stay read-only until OQ-35/OQ-36 are decided.
    criticality_amsl = _text(60)
    feedstock = _text(200)
    applicable_standards = _text(500)
    mechanical_acceptance = AcceptanceRowSerializer(many=True, required=False)
    dimensional_tolerances = _text(500)
    ndt = _text(500)
    inspection_test_plan = _text(1000)
    mtc_required = serializers.BooleanField(required=False, allow_null=True)
    test_coupons = _text(500)
    manufacturing_spec = ManufacturingSpecSerializer(required=False)


class RL3Serializer(serializers.Serializer):
    """Links each R-L3 evidence category to a file of this passport (checked by the view)."""

    evidence = serializers.DictField(child=serializers.UUIDField(allow_null=True), required=False)
    notes = _text(2000)

    def validate_evidence(self, value):
        unknown = set(value) - set(RL3_EVIDENCE)
        if unknown:
            raise serializers.ValidationError(f"Unknown evidence type(s): {', '.join(sorted(unknown))}.")
        return {k: (str(v) if v else None) for k, v in value.items()}


class RevisionContentSerializer(serializers.Serializer):
    rl1 = RL1Serializer(required=False)
    rl2 = RL2Serializer(required=False)
    rl3 = RL3Serializer(required=False)
    notes = _text(4000)


def _filled(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True  # booleans (including False) and numbers count as answered


def completeness(content: dict) -> dict:
    """Missing fields per level. Information only; it does not change the evidence level (OQ-35)."""
    content = content or {}
    rl1 = content.get("rl1") or {}
    na = rl1.get("not_applicable") or {}
    rl1_required = RL1_REQUIRED + (["rpm"] if rl1.get("motion") == "rotating" else [])
    rl1_missing = [k for k in rl1_required if not _filled(rl1.get(k)) and k not in na]

    rl2 = content.get("rl2") or {}
    spec = rl2.get("manufacturing_spec") or {}
    rl2_missing = [k for k in RL2_REQUIRED if not _filled(rl2.get(k))]
    rl2_missing += [f"manufacturing_spec.{k}" for k in SPEC_REQUIRED if not _filled(spec.get(k))]

    evidence = (content.get("rl3") or {}).get("evidence") or {}
    rl3_missing = [k for k in RL3_EVIDENCE if not evidence.get(k)]

    def level(required: int, missing: list) -> dict:
        return {"total": required, "done": required - len(missing), "missing": missing, "complete": not missing}

    return {
        "rl1": level(len(rl1_required), rl1_missing),
        "rl2": level(len(RL2_REQUIRED) + len(SPEC_REQUIRED), rl2_missing),
        "rl3": level(len(RL3_EVIDENCE), rl3_missing),
    }


def captured_level(content: dict) -> str:
    """Highest level whose data, and every lower level's, is complete: none, rl1, rl2 or rl3 (guidance only)."""
    c = completeness(content)
    level = "none"
    for key in ("rl1", "rl2", "rl3"):
        if not c[key]["complete"]:
            break
        level = key
    return level
