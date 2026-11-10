"""Recommendation (CN-007 Phase 5): deterministic combination of part intelligence (Phase 2), manufacturing feasibility
(Phase 3) and the cost / lead-time comparison (Phase 4). Python only; no external service.

Order of evaluation
1. Mandatory requirements per option, before any commercial ranking:
   - OEM procurement: OEM identity and part number verified (Phase 3 OEM status).
   - Additive / conventional: technical screening "potentially suitable" (with or without redesign, including an
     engineer's correction), no verified exclusion, safety/criticality assessed and not critical, applicable standards
     and certification requirements established, OEM IP / reproduction restrictions assessed and not active.
2. Separate statuses, never merged:
   - Commercially cheapest: lowest complete total among options not excluded. Definitive only when every such
     option's total is complete; otherwise "lowest among complete totals (not definitive)".
   - Fastest: the same rule on complete lead times.
   - Potentially suitable: every mandatory requirement met.
   - Engineering-approved: never set here. Formal approval, manufacturing authorisation, passport publication and
     production release stay blocked (OQ-35, OQ-36).
3. Commercial weights (cost, lead time, evidence strength) are applied only among options that meet every mandatory
   requirement and have complete costs and lead times.
4. Outcome: "No qualified recommendation: additional engineering review required" when no option meets the mandatory
   requirements; "potentially suitable, commercial comparison incomplete" when none of those can be ranked; otherwise a
   preliminary recommendation for further study (never an approval).
Commercial evidence is "verified current" only when every priced figure is a supplier quotation still valid on the
recommendation date; an expired quotation is never verified-current evidence.
"""
from datetime import date
from decimal import Decimal

from .costing import lead_quote_status, quote_validity

METHOD_VERSION = "rec-method-2026-10-28.2"  # .2: quoted lead times re-checked with their quotation
OPTIONS = {"oem": "OEM procurement", "additive": "Additive manufacturing", "conventional": "Conventional manufacturing"}
OUTCOMES = {
    "no_qualified_recommendation": "No qualified recommendation — additional engineering review required",
    "qualified_commercial_incomplete": "Potentially suitable option(s), commercial comparison incomplete: no ranking",
    "preliminary_recommendation": "Preliminary recommendation for further study (not engineering-approved)",
}
DEFAULT_WEIGHTS = {"cost": Decimal("0.5"), "lead_time": Decimal("0.3"), "evidence": Decimal("0.2")}
EVIDENCE = {"verified_current": ("Verified current supplier quotations", Decimal(1)),
            "includes_expired_quotation": ("Includes an expired quotation: not verified-current evidence", Decimal("0.6")),
            "historical": ("Historical costs (not current quotations)", Decimal("0.75")),
            "estimates": ("Engineering estimates", Decimal("0.5")),
            "ai_estimates": ("Includes AI-assisted preliminary estimates", Decimal("0.25")),
            "incomplete": ("Incomplete: missing inputs", None),
            "no_comparison": ("No cost comparison", None)}
SUITABLE = {"potentially_suitable", "potentially_suitable_redesign"}
APPROVAL_NOTE = ("Engineering approval is not available: formal approval, manufacturing authorisation, passport publication "
                 "and production release stay blocked (OQ-35, OQ-36).")


class WeightError(Exception):
    pass


def weights(raw: dict | None) -> dict:
    if not raw:
        return dict(DEFAULT_WEIGHTS)
    out = {}
    for k in DEFAULT_WEIGHTS:
        try:
            v = Decimal(str(raw.get(k, 0)))
        except Exception:  # noqa: BLE001
            raise WeightError(f"{k}: enter a number.")
        if not v.is_finite() or v < 0 or v > 100:
            raise WeightError(f"{k}: must be between 0 and 100.")
        out[k] = v
    unknown = set(raw) - set(DEFAULT_WEIGHTS)
    if unknown:
        raise WeightError(f"Unknown weight(s): {', '.join(sorted(unknown))}.")
    total = sum(out.values())
    if total == 0:
        raise WeightError("At least one weight must be greater than zero.")
    return {k: v / total for k, v in out.items()}


def _ev(panel: dict, key: str) -> dict:
    return next((e for e in panel.get("evidence", []) if e.get("key") == key), {"state": "missing", "value": ""})


def requirements(option: str, tech: dict, fa_panels: dict, criticality: str) -> list[dict]:
    t = tech[option]
    if option == "oem":
        return [{"code": "oem_identity", "label": "OEM identity and part number verified", "kind": "technical",
                 "met": t["qualified"], "detail": t["status_label"]}]
    panel = fa_panels.get(option) or {}
    std, ip = _ev(panel, "standards"), _ev(panel, "ip")
    ip_held = ip["state"] in ("verified", "recorded")
    reqs = [
        {"code": "screening", "label": "Technical screening potentially suitable", "kind": "technical",
         "met": t["status"] in SUITABLE, "detail": t["status_label"] + (" (corrected in technical review)" if t.get("corrected_by_review") else "")},
        {"code": "no_verified_exclusion", "label": "No verified disqualifying constraint", "kind": "technical",
         "met": not t["excluded"], "detail": "Excluded by a verified constraint" if t["excluded"] else "None recorded"},
        {"code": "safety", "label": "Safety / equipment criticality assessed and not critical", "kind": "safety",
         "met": criticality == "non_critical",
         "detail": {"unknown": "Criticality not assessed (the customer ABC indicator is not used)",
                    "critical": "Critical part: specialist qualification required"}.get(criticality, "Non-critical")},
        {"code": "certification", "label": "Applicable standards and certification requirements established", "kind": "certification",
         "met": std["state"] in ("verified", "recorded"),
         "detail": std.get("value") or "Not established"},
        {"code": "ip", "label": "OEM IP / reproduction restrictions assessed and not active", "kind": "ip",
         "met": ip_held and str(ip.get("value")).lower() != "active",
         "detail": ("OEM IP active: reproduction needs OEM permission or legal clearance" if ip_held and str(ip.get("value")).lower() == "active"
                    else ip.get("value") or "Not assessed")},
    ]
    return reqs


def commercial(alt: dict | None, today: date) -> dict:
    """One option's commercial evidence from a Phase 4 result, re-checking quotation validity on `today`."""
    if alt is None:
        return {"available": False, "complete": False, "lead_complete": False, "evidence": "no_comparison",
                "evidence_label": EVIDENCE["no_comparison"][0], "expired_quotations": [], "missing_inputs": []}
    expired, sources = [], set()
    for ln in alt["lines"]:
        if ln.get("not_applicable") or ln.get("reporting_amount") is None:
            continue
        src = ln.get("source")
        if src == "quotation" and ln.get("valid_until") and date.fromisoformat(ln["valid_until"]) < today:
            expired.append(f"{ln['label']}: quotation {ln.get('reference') or ''} expired on {ln['valid_until']}".replace("  ", " "))
            src = "expired"
        sources.add(src)
    # lead time: a quoted lead time expires with its quotation unless it has its own current validity (re-checked today)
    validity = quote_validity(alt["lines"])
    lead_expired, lead_sources = [], set()
    for comp in alt["lead_time"]["components"]:
        if comp.get("not_applicable") or comp.get("days") is None:
            continue
        q = lead_quote_status(comp, validity, today)
        if q and (q["expired"] or q["unknown"]):
            lead_expired.append(f"{comp['label']}: quoted lead time " + (f"expired on {q['valid_until']} (with {q['basis']})"
                                                                          if q["expired"] else "has no validity date"))
            lead_sources.add("expired")
        else:
            lead_sources.add(comp.get("source"))
    if alt["lead_time"]["total_days"] is None:
        lev = "incomplete"
    elif "ai_estimate" in lead_sources:
        lev = "ai_estimates"
    elif "engineering_estimate" in lead_sources:
        lev = "estimates"
    elif "expired" in lead_sources:
        lev = "includes_expired_quotation"
    elif "historical" in lead_sources:
        lev = "historical"
    else:
        lev = "verified_current"
    if not alt["complete"]:
        ev = "incomplete"
    elif "ai_estimate" in sources:
        ev = "ai_estimates"
    elif "engineering_estimate" in sources:
        ev = "estimates"
    elif "expired" in sources:
        ev = "includes_expired_quotation"
    elif "historical" in sources:
        ev = "historical"
    else:
        ev = "verified_current"
    return {"available": True, "complete": alt["complete"], "total": alt["total"], "effective_unit_cost": alt["effective_unit_cost"],
            "known_costs_total": alt["known_costs_total"], "lead_days": alt["lead_time"]["total_days"],
            "lead_complete": alt["lead_time"]["total_days"] is not None, "confidence": alt["confidence"],
            "evidence": ev, "evidence_label": EVIDENCE[ev][0], "expired_quotations": expired,
            "missing_inputs": alt["missing_inputs"], "ordered_quantity": alt["ordered_quantity"],
            "lead_evidence": lev, "lead_evidence_label": EVIDENCE[lev][0], "expired_lead_times": lead_expired,
            "savings_vs_baseline": alt["comparison"]["savings"], "savings_percent": alt["comparison"]["savings_percent"],
            "baseline": alt["comparison"]["baseline"]}


def _extreme(opts: dict, key, label: str, unit: str) -> dict:
    """Cheapest / fastest among options not excluded. Definitive only when every such option has a complete figure."""
    pool = {k: o for k, o in opts.items() if not o["excluded"]}
    have = {k: key(o) for k, o in pool.items() if key(o) is not None}
    if not have:
        return {"option": None, "definitive": False, "text": f"Not determined: no complete {label} figures."}
    best = min(have.values())
    winners = sorted(k for k, v in have.items() if v == best)
    lacking = sorted(set(pool) - set(have))
    definitive = not lacking
    text = (f"{' and '.join(OPTIONS[w] for w in winners)}" + (" (tie)" if len(winners) > 1 else "")
            + (f": lowest {label} among options with complete figures, not definitive because "
               f"{', '.join(OPTIONS[k] for k in lacking)} {'is' if len(lacking) == 1 else 'are'} incomplete" if lacking else f": lowest {label}"))
    notes = []
    for w in winners:
        if not opts[w]["eligible"]:
            notes.append(f"{OPTIONS[w]} does not meet the mandatory technical requirements")
        ev = opts[w]["commercial"].get("evidence" if unit == "cost" else "lead_evidence")
        if ev and ev != "verified_current":
            notes.append(f"{OPTIONS[w]} {'cost' if unit == 'cost' else 'lead-time'} evidence: {EVIDENCE[ev][0].lower()}")
    return {"option": winners[0] if len(winners) == 1 else None, "options": winners, "definitive": definitive,
            "text": text + (". " + "; ".join(notes) + "." if notes else "."), "value": str(best)}


def evaluate(tech: dict, fa_panels: dict, criticality: str, cost_results: dict | None, raw_weights: dict | None, today: date) -> dict:
    w = weights(raw_weights)
    opts = {}
    for k in OPTIONS:
        reqs = requirements(k, tech, fa_panels, criticality)
        com = commercial((cost_results or {}).get("alternatives", {}).get(k) if cost_results else None, today)
        eligible = all(r["met"] for r in reqs)
        opts[k] = {"label": OPTIONS[k], "technical": tech[k], "requirements": reqs, "eligible": eligible,
                   "failed_requirements": [r["label"] + (f": {r['detail']}" if r["detail"] else "") for r in reqs if not r["met"]],
                   "excluded": tech[k]["excluded"], "commercial": com,
                   "flags": {"potentially_suitable": eligible, "engineering_approved": False}}
    cheapest = _extreme(opts, lambda o: Decimal(o["commercial"]["total"]) if o["commercial"].get("complete") else None, "total cost", "cost")
    fastest = _extreme(opts, lambda o: o["commercial"]["lead_days"] if o["commercial"].get("lead_complete") else None, "lead time", "lead")
    for k, o in opts.items():
        o["flags"]["commercially_cheapest"] = k in (cheapest.get("options") or [])
        o["flags"]["cheapest_definitive"] = o["flags"]["commercially_cheapest"] and cheapest["definitive"]
        o["flags"]["fastest"] = k in (fastest.get("options") or [])
        o["flags"]["fastest_definitive"] = o["flags"]["fastest"] and fastest["definitive"]
    eligible = [k for k, o in opts.items() if o["eligible"]]
    rankable = [k for k in eligible if opts[k]["commercial"].get("complete") and opts[k]["commercial"].get("lead_complete")]
    ranking, weights_note = [], ""
    if not eligible:
        weights_note = "Commercial weights not applied: no option meets the mandatory technical requirements."
    elif not rankable:
        weights_note = "Commercial weights not applied: no technically eligible option has complete costs and lead times."
    else:
        min_cost = min(Decimal(opts[k]["commercial"]["total"]) for k in rankable)
        min_days = min(opts[k]["commercial"]["lead_days"] for k in rankable)
        for k in rankable:
            c = opts[k]["commercial"]
            parts = {"cost": (min_cost / Decimal(c["total"])) if Decimal(c["total"]) > 0 else Decimal(1),
                     "lead_time": (Decimal(max(min_days, 1)) / Decimal(max(c["lead_days"], 1))),
                     "evidence": EVIDENCE[c["evidence"]][1] or Decimal(0)}
            score = sum(w[x] * parts[x] for x in w)
            ranking.append({"option": k, "score": str(score.quantize(Decimal("0.001"))),
                            "components": {x: str(parts[x].quantize(Decimal("0.001"))) for x in parts}})
        ranking.sort(key=lambda r: (-Decimal(r["score"]), r["option"]))
        for i, r in enumerate(ranking, 1):
            r["rank"] = i
            opts[r["option"]]["rank"] = i
            opts[r["option"]]["score"] = r["score"]
        weights_note = "Weights applied only among options that meet every mandatory requirement and have complete figures."
    if not eligible:
        code, option = "no_qualified_recommendation", None
    elif not ranking:
        code, option = "qualified_commercial_incomplete", None
    else:
        code, option = "preliminary_recommendation", ranking[0]["option"]
    label = OUTCOMES[code] + (f": {OPTIONS[option]}" if option else "")
    reasons = []
    for k, o in opts.items():
        if not o["eligible"]:
            reasons.append(f"{OPTIONS[k]}: " + "; ".join(o["failed_requirements"]))
    return {
        "method_version": METHOD_VERSION, "as_of": today.isoformat(),
        "weights": {k: str(v.quantize(Decimal("0.0001"))) for k, v in w.items()}, "weights_applied": bool(ranking),
        "weights_note": weights_note,
        "options": opts, "ranking": ranking,
        "statuses": {"commercially_cheapest": cheapest, "fastest": fastest,
                     "potentially_suitable": {"options": eligible, "text": (", ".join(OPTIONS[k] for k in eligible) if eligible else
                                                                            "None: no option meets the mandatory requirements.")},
                     "engineering_approved": {"options": [], "text": APPROVAL_NOTE}},
        "outcome": {"code": code, "label": label, "option": option, "reasons": reasons},
        "statement": "Preliminary until reviewed. Not an engineering approval, manufacturing authorisation, passport "
                     "publication or production release (OQ-35, OQ-36). A lower cost never overrides a technical constraint.",
    }
