"""Which fields an edit request may change, how they are classified, and how values are read and validated (CN-006).

Never requestable: tenant/ownership, part origin and review state, clone lineage, files and file bytes, passport status,
evidence level, publication, eligibility, approval records, historical revisions, R-L3 evidence links, engineering
notes (D-13) and job sheets.
"""
import copy

from rest_framework import serializers

from apps.parts.models import SparePart
from apps.passports.content import ManufacturingSpecSerializer, RL1Serializer, RL2Serializer

PART_FIELDS = {
    "part_number": "Part number", "name": "Part name", "description": "Description", "category": "Category",
    "criticality": "Criticality", "equipment_reference": "Equipment / machinery", "manufacturer": "Manufacturer / OEM",
    "application": "Application", "original_material": "Original material", "dimensions": "Dimensions",
    "proposed_material": "Proposed material", "material_change_reason": "Reason for material change", "client_remarks": "Client remarks",
}
# Client-owned descriptive data (on client-submitted or cloned parts). Everything else on a part is Aries-controlled.
CLIENT_DESCRIPTIVE = {"name", "description", "equipment_reference", "manufacturer", "application", "original_material", "dimensions",
                      "proposed_material", "material_change_reason", "client_remarks"}
PART_CHOICES = {"category": [c for c, _ in SparePart.Category.choices], "criticality": [c for c, _ in SparePart.Criticality.choices]}

_RL1_SKIP = {"not_applicable", "value_sources"}
_RL2_SKIP = {"mechanical_acceptance", "manufacturing_spec"}
_SPEC_SKIP = {"process_parameters"}


def _label(key: str) -> str:
    return key.replace("_", " ").capitalize().replace("Rpm", "RPM").replace("Ip ", "IP ").replace("Ndt", "NDT").replace("Mtc", "MTC")


def _kind(field) -> str:
    if isinstance(field, serializers.BooleanField):
        return "bool"
    if isinstance(field, serializers.FloatField):
        return "number"
    if isinstance(field, serializers.ChoiceField):
        return "choice"
    return "text"


def passport_fields() -> dict:
    out = {}
    for key, f in RL1Serializer().fields.items():
        if key not in _RL1_SKIP:
            out[f"rl1.{key}"] = {"label": "R-L1 · " + _label(key), "kind": _kind(f)}
    for key, f in RL2Serializer().fields.items():
        if key not in _RL2_SKIP:
            out[f"rl2.{key}"] = {"label": "R-L2 · " + _label(key), "kind": _kind(f),
                                 **({"choices": list(f.choices)} if isinstance(f, serializers.ChoiceField) else {})}
    for key, f in ManufacturingSpecSerializer().fields.items():
        if key not in _SPEC_SKIP:
            out[f"rl2.manufacturing_spec.{key}"] = {"label": "Specification · " + _label(key), "kind": _kind(f)}
    choices = {"rl1.material_identification_method": ["pmi", "destructive", "oem"], "rl1.atmosphere": ["corrosive", "non_corrosive"],
               "rl1.motion": ["static", "rotating"], "rl1.ip_status": ["obsolete", "active"]}
    for k, c in choices.items():
        out[k].update(kind="choice", choices=c)
    return out


PASSPORT_FIELDS = passport_fields()


def part_value(part: SparePart, field: str):
    v = getattr(part, field)
    return "" if v is None else v


def content_value(content: dict, field: str):
    node = content or {}
    for key in field.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def set_content_value(content: dict, field: str, value) -> dict:
    out = copy.deepcopy(content or {})
    node = out
    keys = field.split(".")
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value
    return out


def same(a, b) -> bool:
    norm = lambda v: "" if v is None else (v.strip() if isinstance(v, str) else v)  # noqa: E731
    return norm(a) == norm(b)


def validate_part_value(field: str, value):
    if field in PART_CHOICES and value not in PART_CHOICES[field]:
        raise serializers.ValidationError({field: f"Must be one of: {', '.join(PART_CHOICES[field])}."})
    model_field = SparePart._meta.get_field(field)
    if not isinstance(value, str):
        raise serializers.ValidationError({field: "Must be text."})
    if getattr(model_field, "max_length", None) and len(value) > model_field.max_length:
        raise serializers.ValidationError({field: f"At most {model_field.max_length} characters."})
    if field in ("part_number", "name") and not value.strip():
        raise serializers.ValidationError({field: "Cannot be empty."})
    return value.strip()


def validate_passport_values(content: dict) -> None:
    """Validate the levels touched, exactly as a direct save would."""
    for level, ser in (("rl1", RL1Serializer), ("rl2", RL2Serializer)):
        if level in content:
            s = ser(data=content[level])
            if not s.is_valid():
                raise serializers.ValidationError({level: s.errors})
