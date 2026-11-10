"""Controlled value lists for the passport forms (requirement update 2026-10).

PROVISIONAL master data: BRD v0.4 OQ-16 ("authoritative material and process names; sources conflict") is open, so every
list here is a starting set, offered with "Other / specify". The stored value is always the text the user chose or typed,
never a code that needs this file to be read back, so existing and custom values stay readable if a list changes.
Lists that would define approval or eligibility rules (AMSL criticality classes, mandatory standards OQ-21) are not
defined here.
"""

VERSION = "2026-10-provisional-1"

MATERIAL_GRADES = [
    # (group, grade)
    ("Stainless steel", "AISI 304"), ("Stainless steel", "AISI 304L"), ("Stainless steel", "AISI 316"),
    ("Stainless steel", "AISI 316L"), ("Stainless steel", "SS 316L"), ("Stainless steel", "AISI 420"),
    ("Stainless steel", "AISI 431"), ("Stainless steel", "17-4 PH"), ("Stainless steel", "15-5 PH"),
    ("Stainless steel", "Duplex 2205"), ("Stainless steel", "Super duplex 2507"),
    ("Cast stainless", "CF8"), ("Cast stainless", "CF8M"), ("Cast stainless", "CA6NM"),
    ("Carbon / alloy steel", "C45"), ("Carbon / alloy steel", "S355"), ("Carbon / alloy steel", "AISI 4140"),
    ("Carbon / alloy steel", "AISI 4340"), ("Carbon / alloy steel", "42CrMo4"), ("Tool steel", "H13"),
    ("Tool steel", "Maraging steel 1.2709"),
    ("Cast iron", "GG25 (EN-GJL-250)"), ("Cast iron", "GGG40 (EN-GJS-400)"),
    ("Nickel alloy", "Inconel 625"), ("Nickel alloy", "Inconel 718"), ("Nickel alloy", "Hastelloy C-276"),
    ("Nickel alloy", "Monel 400"),
    ("Copper alloy", "Bronze CC491K"), ("Copper alloy", "CC491K"), ("Copper alloy", "Nickel aluminium bronze CC333G"),
    ("Copper alloy", "Brass CW617N"), ("Copper alloy", "CuCrZr"),
    ("Aluminium", "AlSi10Mg"), ("Aluminium", "AlSi7Mg"), ("Aluminium", "6061-T6"), ("Aluminium", "7075-T6"),
    ("Titanium", "Ti-6Al-4V (Grade 5)"), ("Titanium", "Ti-6Al-4V ELI (Grade 23)"), ("Titanium", "CP Ti Grade 2"),
    ("Cobalt alloy", "CoCrMo"), ("Polymer", "PA12"), ("Polymer", "PA11"), ("Polymer", "PEEK"), ("Polymer", "PTFE"),
]

OPTIONS = {
    "material_grades": [{"value": g, "group": grp} for grp, g in MATERIAL_GRADES],
    "applications": [{"value": v} for v in [
        "Centrifugal pump", "Cooling water pump", "Sea-water pump", "Compressor", "Valve", "Gearbox", "Fan / blower",
        "Conveyor", "Turbine", "Heat exchanger", "Mixer / agitator", "Winch / windlass", "Bearing housing",
        "Structural bracket", "Hydraulic system", "Electrical enclosure"]],
    # Suggestions only (Other / specify always allowed); the company's own recorded OEMs are added by the parts API.
    "manufacturers": [{"value": v} for v in [
        "KSB", "Sulzer", "Flowserve", "Grundfos", "Ebara", "Xylem", "Weir Minerals", "Siemens", "ABB", "SKF", "Atlas Copco",
        "Ingersoll Rand", "Emerson", "Alfa Laval", "Wärtsilä", "MAN Energy Solutions", "Caterpillar", "Cummins"]],
    "operating_environments": [{"value": v} for v in [
        "Indoor, dry", "Outdoor, onshore", "Offshore / marine splash zone", "Sea water immersed", "Fresh / cooling water",
        "Hydrocarbon service", "Chemical / acidic", "High temperature", "Abrasive / slurry", "Food / pharmaceutical"]],
    "manufacturing_processes": [{"value": v} for v in [
        "L-PBF (laser powder bed fusion)", "EB-PBF (electron beam powder bed fusion)", "DED (directed energy deposition)",
        "WAAM (wire arc additive)", "Binder jetting", "Material extrusion (FFF)", "SLS (polymer powder bed)",
        "Hybrid: AM + CNC machining", "CNC machining", "Casting", "Reverse-engineered conventional manufacture"]],
    "feedstocks": [{"value": v} for v in [
        "316L powder 15-45 µm", "17-4 PH powder 15-45 µm", "AlSi10Mg powder 20-63 µm", "Alloy 625 powder 15-53 µm",
        "Alloy 718 powder 15-53 µm", "Ti-6Al-4V powder 15-45 µm", "CuCrZr powder 15-45 µm", "ER316LSi wire 1.2 mm",
        "PA12 powder"]],
    "applicable_standards": [{"value": v} for v in [
        "ISO/ASTM 52900", "ISO/ASTM 52901", "ISO/ASTM 52904", "ISO/ASTM 52920", "ASTM F3184", "ASTM F3056", "ASTM F3318",
        "ASTM F3055", "ASTM F2924", "ASTM F3001", "ASTM F3302", "DNV-ST-B203", "API 20S", "ISO 6892-1", "ISO 2768-1"]],
    "dimensional_tolerances": [{"value": v} for v in [
        "ISO 2768-f", "ISO 2768-m", "ISO 2768-c", "ISO 2768-v", "ISO 2768-mK", "ISO 2768-fH", "ISO 286 fits as per drawing",
        "As per drawing"]],
    "inspection_methods": [{"value": v} for v in [
        "Visual", "Dye penetrant (PT)", "Magnetic particle (MT)", "Ultrasonic (UT)", "Radiography (RT)", "CT scan",
        "Pressure / leak test", "Dimensional (CMM)", "3D scan comparison", "Hardness", "Surface roughness"]],
    "machines": [{"value": v} for v in [
        "EOS M290", "EOS M400", "EOS M300-4", "SLM 280", "SLM 500", "Nikon SLM NXG", "Renishaw AM400", "Renishaw RenAM 500Q",
        "Trumpf TruPrint 1000", "Trumpf TruPrint 3000", "3D Systems DMP Flex 350", "Velo3D Sapphire", "Farsoon FS271M",
        "BLT S310"]],
    "support_strategies": [{"value": v} for v in [
        "Block supports", "Cone / point supports", "Lattice supports", "Solid supports", "Tree supports",
        "Self-supporting (no supports)"]],
    "build_orientations": [{"value": v} for v in [
        "Axis vertical", "Axis horizontal", "Inclined 45°", "Main axis vertical, mounting face on build plate",
        "As per build file"]],
    "inert_gases": [{"value": v} for v in ["Argon", "Nitrogen", "Not required"]],
    "heat_treatments": [{"value": v} for v in [
        "Stress relief", "Solution anneal", "Solution + ageing", "H900 ageing", "H1150 ageing", "HIP", "HIP + solution + ageing",
        "T6", "None"]],
    "post_processing": [{"value": v} for v in [
        "Support removal", "Wire EDM from plate", "Bead blast", "Shot peen", "Tumbling", "Polishing", "Machining",
        "Passivation", "Coating", "HIP"]],
    "process_parameters": [{"value": v} for v in [
        "Laser power", "Scan speed", "Hatch spacing", "Layer thickness", "Spot size", "Volumetric energy density",
        "Oxygen level", "Build plate temperature", "Recoater type"]],
    "proposed_material_reasons": [{"value": v} for v in [
        "Original material no longer available", "Original material not printable", "Improved corrosion resistance",
        "Improved strength / wear resistance", "Lead time", "Cost"]],
    "inspection_frequencies": [{"value": v} for v in [
        "Prior to every build", "Per build", "Per batch", "Sample based along with build", "First article only", "Per order"]],
    "acceptance_standards": [{"value": v} for v in [
        "ISO 6892-1", "ASTM E8/E8M", "ISO 6507-1", "ISO 6508-1", "ASTM E18", "ISO 148-1", "ASTM E23"]],
}

UNITS = {
    "length": ["mm", "cm", "m", "in"],
    "layer": ["µm", "mm"],
    "temperature": ["°C", "°F"],
    "duration": ["h", "min"],
    "speed": ["rpm"],
    "mechanical": ["MPa", "N/mm²", "ksi", "%", "HV", "HRC", "HB", "J"],
    "parameters": ["W", "mm/s", "µm", "mm", "J/mm³", "%", "ppm", "°C", "bar"],
}


def field_options() -> dict:
    return {"version": VERSION, "provisional": True, "decision": "OQ-16", "lists": OPTIONS, "units": UNITS}
