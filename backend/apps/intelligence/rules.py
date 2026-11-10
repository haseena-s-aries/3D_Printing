"""Deterministic part intelligence (CN-007 Phase 2): rules in Python, no external service.

Everything here is a proposal derived from the record's own text and fields. Nothing is written to the part: the
engineer decides. The rules never invent values; what the description does not say stays "not stated".

- Description reading: SAP short text split at commas, known abbreviations expanded (unknown tokens are kept as they
  are and listed), the leading noun gives the part family.
- Dimensions and material grades mentioned in the description are listed as mentions, never as verified values.
- Manufacturer: cleaned name, legal suffixes removed for matching, possible truncation at the source field limit and
  alias candidates among the company's other manufacturers.
- Duplicates: the Phase 1 rule (same description and manufacturer) plus similar descriptions (same expanded words).
- Completeness: a 0-100 score over the identification and engineering fields, with what is missing.
- Hard constraints: engineering screening rules that an AI suggestion can never override.
"""
import re

from django.conf import settings

from apps.imports import mapping as M

RULES_VERSION = "rules-2026-10-31.2"  # .2: a parenthesised remark is not the part noun (post-UAT D-11)

# Common SAP / maintenance short-text abbreviations. Unknown tokens are reported, not guessed.
ABBREVIATIONS = {
    "ASSY": "assembly", "BRG": "bearing", "BRGS": "bearings", "BSH": "bushing", "BUSH": "bushing", "CNTRFGL": "centrifugal",
    "CPLG": "coupling", "CRBDE": "carbide", "CTNGTL": "cutting tool", "CVR": "cover", "CYL": "cylinder", "DBL": "double",
    "DIAPH": "diaphragm", "ELEC": "electrical", "FLG": "flange", "GSKT": "gasket", "HSG": "housing", "IMPLR": "impeller",
    "LNR": "liner", "MECH": "mechanical", "MTR": "motor", "NOZ": "nozzle", "PMP": "pump", "PSTN": "piston", "RTR": "rotor",
    "SGL": "single", "SHFT": "shaft", "SLV": "sleeve", "SPRG": "spring", "STL": "steel", "STTR": "stator", "SS": "stainless steel",
    "VLV": "valve", "WSHR": "washer", "XMTR": "transmitter", "BRKT": "bracket", "PLT": "plate", "CBL": "cable", "SW": "switch",
}
WORDS = {"COVER", "SEAL", "CARTRIDGE", "INSERT", "RING", "WEAR", "VALVE", "GATE", "DISC", "SHAFT", "SLEEVE", "IMPELLER",
         "BEARING", "HOUSING", "GASKET", "BOLT", "NUT", "SCREW", "STUD", "WASHER", "KIT", "SPRING", "GEAR", "PIN", "KEY", "PLATE",
         "LINER", "BLADE", "VANE", "NOZZLE", "CASING", "BODY", "BONNET", "STEM", "SEAT", "PLUG", "BALL", "CAGE", "ROTOR",
         "STATOR", "MOTOR", "CABLE", "SWITCH", "RELAY", "FUSE", "SENSOR", "TRANSMITTER", "BOARD", "PCB", "LAMP", "BATTERY",
         "FILTER", "ELEMENT", "HOSE", "PIPE", "FLANGE", "ELBOW", "TEE", "COUPLING", "BUSHING", "PUMP", "MECHANICAL", "DOUBLE"}

# leading noun (expanded) -> (part family, category, is an assembly by nature)
FAMILIES = {
    "cover": ("Cover / end cover", "mechanical", False), "seal": ("Seal", "mechanical", False),
    "insert": ("Insert", "mechanical", False), "ring": ("Ring", "mechanical", False), "valve": ("Valve", "mechanical", True),
    "disc": ("Disc", "mechanical", False), "shaft": ("Shaft", "mechanical", False), "sleeve": ("Sleeve", "mechanical", False),
    "impeller": ("Impeller", "mechanical", False), "bearing": ("Bearing", "mechanical", True), "housing": ("Housing", "mechanical", False),
    "gasket": ("Gasket", "mechanical", False), "bolt": ("Fastener", "mechanical", False), "nut": ("Fastener", "mechanical", False),
    "screw": ("Fastener", "mechanical", False), "stud": ("Fastener", "mechanical", False), "washer": ("Washer", "mechanical", False),
    "kit": ("Kit", "mechanical", True), "spring": ("Spring", "mechanical", False), "gear": ("Gear", "mechanical", False),
    "pin": ("Pin", "mechanical", False), "key": ("Key", "mechanical", False), "plate": ("Plate", "mechanical", False),
    "liner": ("Liner", "mechanical", False), "blade": ("Blade", "mechanical", False), "vane": ("Vane", "mechanical", False),
    "nozzle": ("Nozzle", "mechanical", False), "casing": ("Casing", "mechanical", False), "bushing": ("Bushing", "mechanical", False),
    "coupling": ("Coupling", "mechanical", True), "flange": ("Flange", "mechanical", False), "filter": ("Filter", "mechanical", True),
    "motor": ("Motor", "electrical", True), "cable": ("Cable", "electrical", False), "switch": ("Switch", "electrical", True),
    "relay": ("Relay", "electrical", True), "fuse": ("Fuse", "electrical", False), "lamp": ("Lamp", "electrical", False),
    "battery": ("Battery", "electrical", True), "sensor": ("Sensor", "electronic", True), "transmitter": ("Transmitter", "electronic", True),
    "board": ("Circuit board", "electronic", True), "pcb": ("Circuit board", "electronic", True),
}
# qualifier sets that refine a family (all words must appear in the expanded description)
REFINEMENTS = [
    ({"seal", "mechanical", "cartridge"}, "Mechanical seal, cartridge type", True),
    ({"seal", "mechanical"}, "Mechanical seal", True),
    ({"insert", "cutting tool"}, "Cutting tool insert (indexable)", False),
    ({"ring", "wear"}, "Wear ring", False),
    ({"cover", "bearing", "housing"}, "Bearing housing cover", False),
]
# material grades / classes mentioned in text -> (reading, material class)
MATERIALS = [
    (re.compile(r"\bA48-?(\d{2})\b", re.I), lambda m: f"ASTM A48 class {m.group(1)} grey cast iron (as written: {m.group(0)})", "grey cast iron"),
    (re.compile(r"\bCRBDE\b|\bCARBIDE\b", re.I), lambda m: "carbide (grade not stated)", "carbide"),
    (re.compile(r"\bSS\s?3(04|16)L?\b", re.I), lambda m: f"stainless steel {m.group(0).upper()}", "stainless steel"),
    (re.compile(r"\bCF8M\b|\bCF3M\b", re.I), lambda m: f"cast stainless steel {m.group(0).upper()}", "stainless steel"),
    (re.compile(r"\bBRONZE\b|\bBRZ\b", re.I), lambda m: "bronze (grade not stated)", "copper alloy"),
    (re.compile(r"\bBRASS\b", re.I), lambda m: "brass (grade not stated)", "copper alloy"),
    (re.compile(r"\bPTFE\b", re.I), lambda m: "PTFE", "fluoropolymer"),
    (re.compile(r"\bNBR\b|\bEPDM\b|\bVITON\b|\bFKM\b|\bRUBBER\b", re.I), lambda m: f"elastomer ({m.group(0).upper()})", "elastomer"),
    (re.compile(r"\bINCONEL\b|\bHASTELLOY\b|\bMONEL\b", re.I), lambda m: f"nickel alloy ({m.group(0).upper()})", "nickel alloy"),
    (re.compile(r"\bDUPLEX\b", re.I), lambda m: "duplex stainless steel", "stainless steel"),
    (re.compile(r"\bCAST IRON\b|\bCI\b", re.I), lambda m: "cast iron (grade not stated)", "cast iron"),
]
# Material classes that cannot be made like-for-like by metal or polymer additive manufacturing: a substitute material
# would need engineering approval. A screening fact, not a statement about any supplier's capability.
NOT_LIKE_FOR_LIKE = {"carbide": "Cemented carbide is not produced like-for-like by common AM processes",
                     "elastomer": "Elastomers are not produced like-for-like by common AM processes",
                     "grey cast iron": "Grey cast iron is not produced like-for-like by common metal AM processes",
                     "cast iron": "Cast iron is not produced like-for-like by common metal AM processes"}
SUFFIXES = re.compile(r"\b(SRL|S\.R\.L\.|LLC|L\.L\.C\.|LTD|LIMITED|GMBH|AG|INC|CO|CORP|CORPORATION|PLC|SPA|S\.P\.A\.|BV|SA|FZE|FZCO)\b\.?", re.I)
DIM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(MM|CM|IN|INCH)\b", re.I)


def expand(description: str) -> dict:
    tokens = [t.strip() for t in (description or "").split(",") if t.strip()]
    expanded, unknown = [], []
    for t in tokens:
        words = []
        for w in re.split(r"\s+", t):
            key = w.upper()
            if key in ABBREVIATIONS:
                words.append(ABBREVIATIONS[key])
            elif DIM_RE.fullmatch(w) or re.fullmatch(r"[A-Z]?\d[\w-]*", key) or key in WORDS:
                words.append(w.lower() if key in WORDS else w)
            else:
                words.append(w.lower())
                if not any(p.search(w) for p, _r, _c in MATERIALS):
                    unknown.append(w)
        expanded.append(" ".join(words))
    return {"tokens": tokens, "expanded": expanded, "unknown_tokens": unknown}


def family(expanded: list[str]) -> dict:
    words = set(" ".join(expanded).split()) | set(expanded)
    phrase = " ".join(expanded)
    lead = re.sub(r"\([^)]*\)?", " ", expanded[0]).split() if expanded else []  # post-UAT D-11: drop "(...)" remarks
    noun = (lead[-1] if lead else "").lower()
    fam = FAMILIES.get(noun)
    out = {"noun": noun, "family": fam[0] if fam else "", "category": fam[1] if fam else "unknown",
           "assembly": fam[2] if fam else None, "basis": "leading noun" if fam else "leading noun not in the rule table"}
    for needed, name, assembly in REFINEMENTS:
        if all((n in words) or (n in phrase) for n in needed):
            out.update(family=name, assembly=assembly, basis="noun and qualifiers")
            break
    return out


def mentions(description: str) -> dict:
    dims = [{"value": float(v.replace(",", ".")), "unit": u.lower(),
             "mm": round(float(v.replace(",", ".")) * {"mm": 1, "cm": 10, "in": 25.4, "inch": 25.4}[u.lower()], 2)}
            for v, u in DIM_RE.findall(description or "")]
    materials, classes = [], []
    for pattern, reading, cls in MATERIALS:
        m = pattern.search(description or "")
        if m:
            materials.append({"text": m.group(0), "reading": reading(m), "class": cls})
            classes.append(cls)
    return {"dimensions": dims, "largest_mm": max((d["mm"] for d in dims), default=None), "materials": materials,
            "material_classes": sorted(set(classes))}


def manufacturer_key(name: str) -> str:
    return re.sub(r"\s+", " ", SUFFIXES.sub("", M.clean_manufacturer(name))).strip(" .,-")


def manufacturer(part, company_manufacturers: set[str], preset_limit: int | None = 25) -> dict:
    raw = part.manufacturer or ""
    cleaned = M.clean_manufacturer(raw)
    key = manufacturer_key(raw)
    out = {"as_supplied": raw, "cleaned": cleaned, "match_key": key, "placeholder": cleaned in M.PLACEHOLDER_MANUFACTURERS,
           "possibly_truncated": bool(preset_limit and len(raw.strip()) >= preset_limit), "alias_candidates": []}
    if not key:
        return out
    for other in sorted(company_manufacturers):
        okey = manufacturer_key(other)
        if not okey or okey == key and other == cleaned:
            continue
        if okey == key or (len(key) >= 8 and (okey.startswith(key) or key.startswith(okey))):
            out["alias_candidates"].append(other)
    return out


def similar(part, company_parts) -> dict:
    mine = set(" ".join(expand(part.name)["expanded"]).split())
    exact, near = [], []
    for o in company_parts:
        if o.pk == part.pk:
            continue
        if M.norm_description(o.name) == M.norm_description(part.name):
            (exact if M.clean_manufacturer(o.manufacturer) == M.clean_manufacturer(part.manufacturer) else near).append(o.part_number)
            continue
        theirs = set(" ".join(expand(o.name)["expanded"]).split())
        if mine and theirs and len(mine & theirs) / len(mine | theirs) >= 0.8:
            near.append(o.part_number)
    return {"same_description_and_manufacturer": sorted(exact)[:10], "similar_description": sorted(near)[:10]}


COMPLETENESS = [  # (key, label, points, test)
    ("description", "Usable description", 10, lambda p, c: len(p.name or "") >= 12),
    ("manufacturer", "Real manufacturer name", 10, lambda p, c: bool(p.manufacturer.strip()) and not c["placeholder"]),
    ("manufacturer_reference", "Manufacturer reference", 5, lambda p, c: bool(p.manufacturer_reference)),
    ("oem_part_number", "Verified OEM part number", 15, lambda p, c: bool(p.oem_part_number)),
    ("location", "Plant, functional location and equipment tag", 10,
     lambda p, c: bool(p.plant and p.functional_location and p.equipment_tag)),
    ("material", "Material recorded (engineering field)", 15, lambda p, c: bool(p.original_material)),
    ("dimensions", "Dimensions recorded (engineering field)", 15, lambda p, c: bool(p.dimensions)),
    ("documents", "Drawing, CAD or photograph on file", 20, lambda p, c: c["documents"] > 0),
]


def completeness(part, ctx: dict) -> dict:
    items = [{"key": k, "label": lbl, "points": pts, "met": bool(test(part, ctx))} for k, lbl, pts, test in COMPLETENESS]
    partial = []
    if not part.original_material and ctx["mentions"]["materials"]:
        partial.append("material")
    if not part.dimensions and ctx["mentions"]["dimensions"]:
        partial.append("dimensions")
    score = sum(i["points"] for i in items if i["met"]) + 5 * len(partial)  # a mention in the text earns 5 of 15
    for i in items:
        i["partial"] = i["key"] in partial
    return {"score": min(score, 100), "items": items, "missing": [i["label"] for i in items if not i["met"]]}


def constraints(part, fam: dict, ment: dict, documents: int) -> list[dict]:
    """Engineering screening rules. kind 'block' = excluded from AM screening; 'review' = needs an engineering decision;
    'insufficient' = cannot be screened on the data held. AI suggestions never override these."""
    out = []
    category = part.category if part.category != "unknown" else fam["category"]
    if category in ("electrical", "electronic"):
        out.append({"code": "electrical_or_electronic", "kind": "block",
                    "text": "Electrical or electronic part: outside additive-manufacturing replacement of mechanical parts."})
    if fam.get("assembly"):
        out.append({"code": "assembly", "kind": "review",
                    "text": "Assembly of several components: each component must be assessed separately; not one printable part."})
    for cls in ment["material_classes"]:
        if cls in NOT_LIKE_FOR_LIKE:
            out.append({"code": f"material_{cls.replace(' ', '_')}", "kind": "review",
                        "text": NOT_LIKE_FOR_LIKE[cls] + "; a substitute material needs engineering approval."})
    envelope = getattr(settings, "AM_BUILD_ENVELOPE_MM", None)
    if envelope and ment["largest_mm"] and ment["largest_mm"] > max(envelope):
        out.append({"code": "exceeds_envelope", "kind": "block",
                    "text": f"A dimension in the description ({ment['largest_mm']} mm) exceeds the configured build envelope."})
    if not (part.original_material or ment["materials"]) or not (part.dimensions or ment["dimensions"]) or documents == 0:
        missing = [n for n, ok in (("material", part.original_material or ment["materials"]),
                                   ("dimensions", part.dimensions or ment["dimensions"]), ("drawing, CAD or photograph", documents))
                   if not ok]
        out.append({"code": "insufficient_data", "kind": "insufficient",
                    "text": "Feasibility cannot be assessed without: " + ", ".join(missing) + "."})
    return out


def screening(cons: list[dict]) -> str:
    kinds = {c["kind"] for c in cons}
    if "block" in kinds:
        return "excluded_by_rule"
    if "insufficient" in kinds:
        return "insufficient_information"
    return "engineering_review_required"


def analyse(part, company_parts, documents: int) -> dict:
    exp = expand(part.name)
    fam = family(exp["expanded"])
    ment = mentions(part.name)
    mfr = manufacturer(part, {M.clean_manufacturer(o.manufacturer) for o in company_parts if o.manufacturer.strip()})
    cons = constraints(part, fam, ment, documents)
    return {
        "rules_version": RULES_VERSION,
        "description": {"as_supplied": part.name, **exp},
        "classification": {**fam, "recorded_category": part.category},
        "mentions": ment,
        "manufacturer": mfr,
        "duplicates": similar(part, company_parts),
        "completeness": completeness(part, {"placeholder": mfr["placeholder"], "documents": documents, "mentions": ment}),
        "constraints": cons,
        "screening": screening(cons),
    }
