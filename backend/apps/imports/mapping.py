"""Import targets, column-mapping presets and data-quality rules (CN-007 Phase 1).

Targets are the spare-part fields an inventory import may write. Everything else on a part (engineering material,
dimensions, criticality, category, passports) is never written by an import: imported inventory stays distinct from
engineering-verified specifications. Classification is "Not classified" and criticality "Not assessed" on new parts.
"""
import re

# field: (label, required, max length, note shown next to the mapping)
TARGETS = {
    "part_number": ("Customer material number", True, 80, "Identity of the part within the company: re-imports match on it."),
    "name": ("Material description", True, 200, "Stored verbatim as the part name."),
    "manufacturer": ("Manufacturer name", False, 200, "Stored verbatim; a cleaned copy is kept separately for matching."),
    "manufacturer_reference": ("Manufacturer reference", False, 60,
                               "Customer/ERP manufacturer code. Never treated as an OEM part number."),
    "oem_part_number": ("OEM part number", False, 80, "Map only a column that really holds OEM part numbers."),
    "plant": ("Plant", False, 80, ""),
    "functional_location": ("Functional location", False, 80, ""),
    "equipment_tag": ("Equipment tag", False, 60, ""),
    "customer_abc_class": ("Customer ABC indicator", False, 20,
                           "Stored as supplied. Its meaning is not confirmed and it never sets engineering criticality."),
    "client_remarks": ("Remarks", False, 4000, ""),
}
# Fields an import owns on a part (compared on re-import). The identity field is matched, never changed.
OWNED = [f for f in TARGETS if f != "part_number"]

PRESETS = {
    "sap_material_list": {
        "label": "SAP material list (573-part workbook layout)",
        "columns": {
            "part_number": "Material", "name": "Material Description", "manufacturer": "Manufacturer Name",
            "manufacturer_reference": "Manufacturer Number", "plant": "Plant", "functional_location": "Func Loc.",
            "equipment_tag": "Sort field / equipment tag", "customer_abc_class": "ABC indicator",
            "client_remarks": "Remarks 1",
        },
        # SAP short-text limits: values that fill them completely may have been cut off at the source.
        "source_limits": {"name": 40, "manufacturer": 25},
    },
}

PLACEHOLDER_MANUFACTURERS = {"REPUTED", "REPUTED MAKE", "ANY", "VARIOUS", "UNKNOWN", "N/A", "NA", "NIL", "NONE", "-", "TBA",
                             "TBC", "GENERIC", "OTHERS", "OTHER"}

# Data-quality flags: code -> (label, level). "info" flags describe content; nothing is extracted into fields.
FLAGS = {
    "missing_manufacturer": ("Manufacturer name missing", "warning"),
    "missing_manufacturer_reference": ("Manufacturer reference missing", "warning"),
    "placeholder_manufacturer": ("Manufacturer is a placeholder, not a real maker", "warning"),
    "manufacturer_spacing": ("Manufacturer name had extra spaces (cleaned copy kept separately)", "info"),
    "missing_plant": ("Plant missing", "warning"),
    "missing_functional_location": ("Functional location missing", "warning"),
    "missing_equipment_tag": ("Equipment tag missing", "warning"),
    "missing_abc": ("Customer ABC indicator missing", "info"),
    "possibly_truncated_name": ("Description fills the source field limit; may be cut off", "warning"),
    "possibly_truncated_manufacturer": ("Manufacturer name fills the source field limit; may be cut off", "warning"),
    "short_description": ("Very short description; not enough to identify the part", "warning"),
    "possible_duplicate": ("Same description and manufacturer as another material number", "warning"),
    "mentions_dimensions": ("Description mentions dimensions (not extracted; engineering check needed)", "info"),
    "mentions_material": ("Description mentions a material grade (not extracted; engineering check needed)", "info"),
    "no_oem_part_number": ("No OEM part number recorded", "info"),
}
MISSING = {"manufacturer": "missing_manufacturer", "manufacturer_reference": "missing_manufacturer_reference",
           "plant": "missing_plant", "functional_location": "missing_functional_location",
           "equipment_tag": "missing_equipment_tag", "customer_abc_class": "missing_abc"}
DIMENSION_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:MM|CM|IN|INCH)\b|Ø\s*\d", re.I)
MATERIAL_RE = re.compile(r"\b(?:A\d{2,3}-?[A-Z0-9]{1,6}|B\d{3}-?[A-Z0-9]*|SS\s?3\d\d[LH]?|AISI\s?\d{3}|CF8M?|CF3M?|DUPLEX|"
                         r"BRONZE|BRASS|PTFE|PEEK|NYLON|CAST IRON|CARBIDE|CRBDE|UNS\s?[A-Z]\d{4,5}|INCONEL|HASTELLOY|MONEL)\b", re.I)


def norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (h or "").lower()).strip()


def auto_mapping(headers: list[str], preset: str = "") -> dict:
    """Map targets to source headers by preset names, then by matching target labels; unmatched targets stay empty."""
    by_norm = {norm_header(h): h for h in headers if h}
    out = {}
    wanted = PRESETS.get(preset, {}).get("columns", {})
    for field, (label, *_rest) in TARGETS.items():
        for candidate in (wanted.get(field), label, field.replace("_", " ")):
            if candidate and norm_header(candidate) in by_norm:
                out[field] = by_norm[norm_header(candidate)]
                break
    return out


def clean_manufacturer(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "")).strip().upper()


def norm_description(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "")).strip().upper()


def row_flags(values: dict, raw_manufacturer: str, preset: str) -> list[str]:
    flags = [code for field, code in MISSING.items() if not values.get(field)]
    m = values.get("manufacturer", "")
    if m and clean_manufacturer(m) in PLACEHOLDER_MANUFACTURERS:
        flags.append("placeholder_manufacturer")
    if raw_manufacturer and raw_manufacturer != raw_manufacturer.strip() or "  " in (raw_manufacturer or ""):
        flags.append("manufacturer_spacing")
    limits = PRESETS.get(preset, {}).get("source_limits", {})
    name = values.get("name", "")
    if limits.get("name") and len(name) >= limits["name"]:
        flags.append("possibly_truncated_name")
    if limits.get("manufacturer") and len(m) >= limits["manufacturer"]:
        flags.append("possibly_truncated_manufacturer")
    if name and (len(name) < 12 or not re.search(r"[,:;\s]", name)):
        flags.append("short_description")
    if DIMENSION_RE.search(name):
        flags.append("mentions_dimensions")
    if MATERIAL_RE.search(name):
        flags.append("mentions_material")
    if not values.get("oem_part_number"):
        flags.append("no_oem_part_number")
    return flags
