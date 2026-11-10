"""AI text must not contradict the recorded technical screening (CN-007 Phase 4 review, Phase 5).

`contradictions()` reads AI text sentence by sentence. A sentence about an alternative (by its notes section, or by
naming it: OEM, additive/AM/printing, conventional/casting/machining/forging) contradicts the record when it
- names a screening status for that alternative other than the recorded one (and not the recorded one as well), or
- claims technical qualification or engineering approval the alternative does not have, or
- claims a verified OEM identity or part number while the OEM status is "not verified".
`scrub()` removes such sentences (keeping a list); stored AI text is never changed, only checked (`check_stored`).
"""
import re

STATUS_PATTERNS = {
    "specialist_assessment": r"\bspecialist\s+(?:engineering\s+)?(?:assessment|review|evaluation)",
    "insufficient_information": r"\binsufficient\s+(?:technical\s+)?(?:information|data|evidence)",
    "not_suitable_verified": r"\bnot\s+suitable\b|\bunsuitable\b|\bexcluded\b",
    "potentially_suitable": r"(?<!not\s)\bpotentially\s+suitable\b(?!\s+with\s+redesign)",
    "potentially_suitable_redesign": r"\bsuitable\s+with\s+redesign\b",
}
QUALIFIED_CLAIM = re.compile(r"(?<!not\s)(?<!\bun)\b(?:technically\s+qualified|engineering[-\s]approved|qualified\s+for\s+"
                             r"(?:use|production|manufactur\w*|service)|approved\s+for\s+(?:use|production|manufactur\w*|service))", re.I)
OEM_CLAIM = re.compile(r"(?<!not\s)(?<!\bun)\b(?:verified|confirmed)\s+(?:OEM|original equipment manufacturer|OEM part number|"
                       r"part number|identity)\b|\bOEM\s+(?:identity|part number)\s+(?:is|has been)\s+(?:verified|confirmed)\b", re.I)
ALT_PATTERNS = {
    "oem": re.compile(r"\bOEM\b|original equipment", re.I),
    "additive": re.compile(r"\badditive\b|(?-i:\bAM\b)|3D[-\s]?print|\bprint(?:ed|ing)\b", re.I),
    # method words only: "cast iron" is a material, "machine" may be an AM machine
    "conventional": re.compile(r"\bconventional\b|\bcasting\b|\bmachining\b|\bforging\b", re.I),
}
MARKER = "[statement contradicting the recorded technical status removed]"
# lists of things still needed ("Verified OEM part number") state a need, not a claim: they are not checked
NEED_KEYS = {"evidence_gaps", "information_to_obtain", "information_needed", "missing_inputs", "assumptions_to_verify"}
SENTENCE = re.compile(r"(?<=[.!?])\s+")  # clauses joined by ";" are read together


def _sentence(s: str, statuses: dict, scope: str | None) -> list[dict]:
    alts = {a for a, p in ALT_PATTERNS.items() if p.search(s)}
    if scope:
        alts.add(scope)
    out = []
    for a in sorted(alts):
        rec = statuses.get(a)
        if not rec:
            continue
        if a == "oem":
            if rec != "identified_confirmation_required" and OEM_CLAIM.search(s):
                out.append({"alternative": a, "recorded": rec, "stated": "OEM identity verified", "sentence": s})
            continue
        stated = {st for st, p in STATUS_PATTERNS.items() if re.search(p, s, re.I)}
        if stated and rec not in stated:
            out.append({"alternative": a, "recorded": rec, "stated": ", ".join(sorted(stated)), "sentence": s})
        elif QUALIFIED_CLAIM.search(s):
            out.append({"alternative": a, "recorded": rec, "stated": "technically qualified / approved", "sentence": s})
    return out


def contradictions(text: str, statuses: dict, scope: str | None = None) -> list[dict]:
    found = []
    for s in SENTENCE.split(text or ""):
        if s.strip():
            found += _sentence(s.strip(), statuses, scope)
    return found


def _walk(obj, statuses, scope, found, edit):
    if isinstance(obj, dict):
        return {k: (v if k in NEED_KEYS else _walk(v, statuses, k if k in statuses else scope, found, edit)) for k, v in obj.items()}
    if isinstance(obj, str):
        hits = []
        kept = []
        for s in SENTENCE.split(obj):
            h = _sentence(s.strip(), statuses, scope) if s.strip() else []
            hits += h
            kept.append(MARKER if (h and edit) else s)
        found += hits
        return " ".join(kept).strip() if edit else obj
    if isinstance(obj, list):
        return [_walk(x, statuses, scope, found, edit) for x in obj]
    return obj


def scrub(obj, statuses: dict) -> tuple[object, list[dict]]:
    """Remove contradicting sentences. statuses: {alternative: recorded status}. Keys named after an alternative scope
    the text below them to that alternative."""
    found = []
    return _walk(obj, statuses, None, found, edit=True), found


def check_stored(obj, statuses: dict) -> list[dict]:
    """Report contradictions in stored AI text without changing it (stored versions are immutable)."""
    found = []
    _walk(obj, statuses, None, found, edit=False)
    return found
