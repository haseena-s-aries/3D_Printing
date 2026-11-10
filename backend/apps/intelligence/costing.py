"""Cost and lead-time comparison (CN-007 Phase 4): deterministic calculations in Python, no external service.

Three sourcing alternatives (OEM procurement, additive and conventional manufacturing) are costed from entered inputs
for one required quantity in one reporting currency. Nothing here recommends an alternative or authorises manufacture.

Inputs per alternative
- Quantity-dependent (per ordered unit): unit purchase/manufacturing cost, post-processing; logistics when per unit.
- One-time (per order/project): engineering and setup, tooling, testing and qualification; logistics when per order.
- Duties/taxes: a percentage of goods value plus logistics (never also entered as an amount: no double counting).
- MOQ, order multiple (pack size) and qualification units (consumed by testing, not usable).
- Lead time: supplier/manufacturer lead time plus additional engineering/qualification time (sequential).
Every figure carries a source: verified supplier quotation, historical cost, engineering estimate, AI-assisted
preliminary estimate, or missing. "Not applicable" is explicit. Quotations need a reference and a validity date.

Calculation (Decimal throughout; rounding only for display: money 2 dp half-up, percentages 1 dp)
- ordered = max(required + qualification units, MOQ), rounded up to the order multiple.
- material & production = (unit cost + post-processing) x ordered; setup & tooling = engineering/setup + tooling;
  testing & qualification; logistics = per order, or per unit x ordered; duties = % x (unit cost x ordered + logistics).
- total landed/project cost = the sum; effective cost per usable unit = total / required quantity (surplus units from
  an MOQ or pack size are paid for but not counted as usable).
- Currency: each amount is converted with an explicitly entered, dated rate (or the inverse of one, shown as such).
  A missing rate is never assumed: the alternative's total is then incomplete.
- Savings = baseline total - alternative total (positive = lower than the baseline); percentage of the baseline total.
  Only complete totals are compared. Lead-time difference = alternative days - baseline days.
"""
import re
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation

METHOD_VERSION = "cost-method-2026-10-28.3"  # .2: arithmetic returned (`explanation`); .3: quoted lead times expire with their quotation
ALTERNATIVES = {"oem": "OEM procurement", "additive": "Additive manufacturing", "conventional": "Conventional manufacturing"}
SOURCES = {
    "quotation": "Verified supplier quotation",
    "historical": "Historical purchase/manufacturing cost",
    "engineering_estimate": "Engineering estimate",
    "ai_estimate": "AI-assisted preliminary estimate",
    "missing": "Missing / unavailable",
}
SOURCE_RANK = {"quotation": 4, "historical": 3, "engineering_estimate": 2, "ai_estimate": 1}
CONFIDENCE = {4: "High: verified supplier quotations", 3: "Medium: includes historical costs",
              2: "Low: includes engineering estimates", 1: "Very low: includes AI-assisted preliminary estimates"}
# key -> (label, category, basis); basis "per_unit" or "one_time" ("logistics" chooses its own)
COSTS = {
    "unit_cost": ("Unit purchase / manufacturing cost", "material_production", "per_unit"),
    "post_processing": ("Post-processing", "material_production", "per_unit"),
    "engineering_setup": ("Engineering and setup", "setup_tooling", "one_time"),
    "tooling": ("Tooling", "setup_tooling", "one_time"),
    "testing_qualification": ("Testing and qualification", "testing_qualification", "one_time"),
    "logistics": ("Packaging and logistics", "logistics", None),
}
CATEGORIES = {"material_production": "Material and production / purchase", "setup_tooling": "Setup and tooling",
              "testing_qualification": "Testing and qualification", "logistics": "Packaging and logistics",
              "duties_taxes": "Duties and taxes"}
LEAD = {"supplier_days": "Supplier / manufacturer lead time", "engineering_days": "Additional engineering / qualification time"}
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
MAX_AMOUNT = Decimal("1000000000")
CENT, TENTH = Decimal("0.01"), Decimal("0.1")


class CostInputError(Exception):
    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(f"{e['field']}: {e['message']}" for e in errors))
        self.errors = errors


def money(x) -> str | None:
    return None if x is None else str(Decimal(x).quantize(CENT, ROUND_HALF_UP))


def fm(x) -> str:
    """Money for explanations: rounded half-up like `money`, with thousands separators."""
    return f"{Decimal(x).quantize(CENT, ROUND_HALF_UP):,}"


def pct(x) -> str | None:
    return None if x is None else str(Decimal(x).quantize(TENTH, ROUND_HALF_UP))


# ------------------------------------------------------------------ validation

def _int(v, field, errors, lo, hi, default=None):
    if v in (None, "") and default is not None:
        return default
    try:
        if isinstance(v, bool):
            raise ValueError
        n = int(str(v).strip())
    except (TypeError, ValueError):
        errors.append({"field": field, "message": "Enter a whole number."})
        return None
    if not lo <= n <= hi:
        errors.append({"field": field, "message": f"Must be between {lo} and {hi}."})
        return None
    return n


def _dec(v, field, errors, positive=False, hi=MAX_AMOUNT):
    try:
        d = Decimal(str(v).strip())
        if not d.is_finite():
            raise InvalidOperation
    except (InvalidOperation, ValueError, TypeError):
        errors.append({"field": field, "message": "Enter a number."})
        return None
    if d < 0 or (positive and d == 0):
        errors.append({"field": field, "message": "Must be greater than zero." if positive else "Must not be negative."})
        return None
    if d > hi:
        errors.append({"field": field, "message": "Too large."})
        return None
    if d.as_tuple().exponent < -4:
        errors.append({"field": field, "message": "At most 4 decimal places."})
        return None
    return d


def _date(v, field, errors, required=False):
    if not v:
        if required:
            errors.append({"field": field, "message": "Required."})
        return None
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        errors.append({"field": field, "message": "Use YYYY-MM-DD."})
        return None


def _text(v, n=300) -> str:
    return str(v or "").strip()[:n]


def _source(c, field, errors):
    s = c.get("source") or ""
    if s not in SOURCES:
        errors.append({"field": f"{field}.source", "message": "Choose the data source."})
        return None
    if s in ("quotation", "historical") and not _text(c.get("reference")):
        errors.append({"field": f"{field}.reference", "message": "A quotation or historical figure needs its evidence reference."})
    return s


def _component(c, field, errors, positive=False, needs_currency=True):
    c = c or {}
    if c.get("not_applicable"):
        if positive:
            errors.append({"field": field, "message": "Cannot be marked not applicable."})
        return {"not_applicable": True, "note": _text(c.get("note"))}
    s = _source(c, field, errors)
    out = {"not_applicable": False, "source": s, "reference": _text(c.get("reference")), "note": _text(c.get("note"))}
    if s == "missing":
        if c.get("amount") not in (None, ""):
            errors.append({"field": f"{field}.amount", "message": "A missing figure has no amount; choose its source."})
        return {**out, "amount": None}
    if c.get("amount") in (None, ""):
        if s:
            errors.append({"field": f"{field}.amount", "message": "Enter the amount, or set the source to Missing / unavailable."})
        return {**out, "amount": None}
    out["amount"] = _dec(c.get("amount"), f"{field}.amount", errors, positive=positive)
    if needs_currency:
        cur = str(c.get("currency") or "").upper()
        if not CURRENCY_RE.match(cur):
            errors.append({"field": f"{field}.currency", "message": "Use a 3-letter currency code (ISO 4217)."})
        out["currency"] = cur
    if s == "quotation":
        out["valid_until"] = _date(c.get("valid_until"), f"{field}.valid_until", errors, required=True)
    elif c.get("valid_until"):
        out["valid_until"] = _date(c.get("valid_until"), f"{field}.valid_until", errors)
    return out


def validate(scenario: dict, today: date) -> dict:
    """Return a normalised scenario (Decimals and dates) or raise CostInputError with every problem found."""
    errors = []
    sc = scenario if isinstance(scenario, dict) else {}
    out = {"name": _text(sc.get("name"), 120), "synthetic": bool(sc.get("synthetic")),
           "quantity": _int(sc.get("quantity"), "quantity", errors, 1, 1_000_000),
           "reporting_currency": str(sc.get("reporting_currency") or "").upper(), "baseline": sc.get("baseline") or "oem",
           "notes": _text(sc.get("notes"), 1000), "exchange_rates": [], "alternatives": {}}
    if not out["name"]:
        errors.append({"field": "name", "message": "Name the scenario."})
    if not CURRENCY_RE.match(out["reporting_currency"]):
        errors.append({"field": "reporting_currency", "message": "Use a 3-letter currency code (ISO 4217)."})
    if out["baseline"] not in ALTERNATIVES:
        errors.append({"field": "baseline", "message": "Choose oem, additive or conventional."})
    seen = set()
    for i, r in enumerate(sc.get("exchange_rates") or []):
        f = f"exchange_rates[{i}]"
        r = r or {}
        a, b = str(r.get("from") or "").upper(), str(r.get("to") or "").upper()
        if not (CURRENCY_RE.match(a) and CURRENCY_RE.match(b)) or a == b:
            errors.append({"field": f, "message": "Give two different 3-letter currency codes."})
            continue
        if frozenset((a, b)) in seen:
            errors.append({"field": f, "message": f"More than one rate for {a}/{b}."})
            continue
        seen.add(frozenset((a, b)))
        rate = _dec(r.get("rate"), f"{f}.rate", errors, positive=True, hi=Decimal("1000000"))
        rd = _date(r.get("rate_date"), f"{f}.rate_date", errors, required=True)
        if rd and rd > today:
            errors.append({"field": f"{f}.rate_date", "message": "A rate date cannot be in the future."})
        src = _text(r.get("source"))
        if not src:
            errors.append({"field": f"{f}.source", "message": "State where the rate comes from (approved source or entered)."})
        out["exchange_rates"].append({"from": a, "to": b, "rate": rate, "rate_date": rd, "source": src})
    alts = sc.get("alternatives") or {}
    for key in ALTERNATIVES:
        a = alts.get(key) or {}
        f = f"alternatives.{key}"
        alt = {"moq": _int(a.get("moq"), f"{f}.moq", errors, 1, 1_000_000, default=1),
               "order_multiple": _int(a.get("order_multiple"), f"{f}.order_multiple", errors, 1, 1_000_000, default=1),
               "qualification_units": _int(a.get("qualification_units"), f"{f}.qualification_units", errors, 0, 100_000, default=0),
               "notes": _text(a.get("notes"), 1000), "costs": {}, "lead_time": {}}
        costs = a.get("costs") or {}
        for ck in COSTS:
            alt["costs"][ck] = _component(costs.get(ck), f"{f}.costs.{ck}", errors, positive=(ck == "unit_cost"))
        lg = alt["costs"]["logistics"]
        if not lg.get("not_applicable"):
            basis = (costs.get("logistics") or {}).get("basis") or "per_order"
            if basis not in ("per_order", "per_unit"):
                errors.append({"field": f"{f}.costs.logistics.basis", "message": "Choose per order or per unit."})
            lg["basis"] = basis
        d = costs.get("duties") or {}
        if d.get("not_applicable"):
            alt["costs"]["duties"] = {"not_applicable": True, "note": _text(d.get("note"))}
        else:
            s = _source(d, f"{f}.costs.duties", errors)
            p = None if s == "missing" else _dec(d.get("percent"), f"{f}.costs.duties.percent", errors, hi=Decimal("100"))
            alt["costs"]["duties"] = {"not_applicable": False, "source": s, "percent": p, "reference": _text(d.get("reference")),
                                      "note": _text(d.get("note"))}
        lead = a.get("lead_time") or {}
        for lk in LEAD:
            c = lead.get(lk) or {}
            if c.get("not_applicable") and lk == "engineering_days":
                alt["lead_time"][lk] = {"not_applicable": True}
                continue
            s = _source(c, f"{f}.lead_time.{lk}", errors)
            days = None if s == "missing" else _int(c.get("days"), f"{f}.lead_time.{lk}.days", errors, 0, 3650)
            alt["lead_time"][lk] = {"not_applicable": False, "source": s, "days": days, "reference": _text(c.get("reference")),
                                    "note": _text(c.get("note"))}
            if c.get("valid_until"):  # a quoted lead time may carry its own validity; otherwise it follows its quotation
                alt["lead_time"][lk]["valid_until"] = _date(c.get("valid_until"), f"{f}.lead_time.{lk}.valid_until", errors)
        out["alternatives"][key] = alt
    if errors:
        raise CostInputError(errors)
    return out


# ------------------------------------------------------------------ calculation

def quote_validity(lines: list) -> dict:
    """{quotation reference: earliest validity date} from cost lines (stored results or calculation lines)."""
    out = {}
    for ln in lines:
        if ln.get("source") == "quotation" and ln.get("reference") and ln.get("valid_until"):
            d = ln["valid_until"] if isinstance(ln["valid_until"], date) else date.fromisoformat(ln["valid_until"])
            out[ln["reference"]] = min(d, out.get(ln["reference"], d))
    return out


def lead_quote_status(comp: dict, validity: dict, today: date) -> dict | None:
    """Validity of a lead time taken from a supplier quotation. Its own validity date counts first (independent current
    evidence); otherwise it expires with the cost quotation of the same reference; with neither, it is not current."""
    if comp.get("not_applicable") or comp.get("source") != "quotation" or comp.get("days") is None:
        return None
    own = comp.get("valid_until")
    if own:
        vu, basis = (own if isinstance(own, date) else date.fromisoformat(own)), "its own validity date"
    elif comp.get("reference") in validity:
        vu, basis = validity[comp["reference"]], f"quotation {comp['reference']}"
    else:
        return {"valid_until": None, "basis": "no validity date and no matching quotation", "expired": False, "unknown": True}
    return {"valid_until": vu.isoformat(), "basis": basis, "expired": vu < today, "unknown": False}


def _converter(rates, reporting):
    table = {}
    for r in rates:
        table[(r["from"], r["to"])] = (r["rate"], r, False)
        table.setdefault((r["to"], r["from"]), (Decimal(1) / r["rate"], r, True))

    def convert(amount: Decimal, currency: str):
        if currency == reporting:
            return amount, None
        hit = table.get((currency, reporting))
        if hit is None:
            return None, None
        rate, r, inverse = hit
        return amount * rate, {"from": currency, "to": reporting, "rate": str(rate if not inverse else r["rate"]),
                               "inverse": inverse, "rate_date": r["rate_date"].isoformat(), "source": r["source"]}
    return convert


def _ordered(required, alt) -> int:
    need = max(required + alt["qualification_units"], alt["moq"])
    m = alt["order_multiple"]
    return int((Decimal(need) / m).to_integral_value(ROUND_CEILING)) * m


def calculate_alternative(key: str, alt: dict, required: int, reporting: str, convert, today: date) -> dict:
    ordered = _ordered(required, alt)
    lines, missing, warnings, used_rates, ranks, explain = [], [], [], [], [], []
    cat = {k: Decimal(0) for k in CATEGORIES}
    known = {k: True for k in CATEGORIES}
    goods = None
    logistics_value = Decimal(0)
    for ck, (label, category, basis) in COSTS.items():
        c = alt["costs"][ck]
        if c.get("not_applicable"):
            lines.append({"key": ck, "label": label, "category": category, "not_applicable": True, "source_label": "Not applicable"})
            continue
        b = c.get("basis") or basis
        line = {"key": ck, "label": label, "category": category, "basis": "per unit" if b == "per_unit" else "one-time",
                "source": c["source"], "source_label": SOURCES[c["source"]], "reference": c["reference"], "note": c["note"],
                "amount": money(c["amount"]) if c["amount"] is not None else None, "currency": c.get("currency", ""),
                "multiplier": ordered if b == "per_unit" else 1, "not_applicable": False}
        if c.get("valid_until"):
            line["valid_until"] = c["valid_until"].isoformat()
            if c["source"] == "quotation" and c["valid_until"] < today:
                line["expired"] = True
                warnings.append(f"{label}: quotation expired on {c['valid_until'].isoformat()}.")
        if c["amount"] is None:
            missing.append(label)
            known[category] = False
            lines.append({**line, "reporting_amount": None})
            continue
        conv, rinfo = convert(c["amount"], c["currency"])
        if conv is None:
            missing.append(f"Exchange rate {c['currency']} to {reporting} (for {label.lower()})")
            known[category] = False
            lines.append({**line, "reporting_amount": None, "missing_rate": True})
            continue
        if rinfo and rinfo not in used_rates:
            used_rates.append(rinfo)
        extended = conv * line["multiplier"]
        cat[category] += extended
        ranks.append(3 if line.get("expired") else SOURCE_RANK[c["source"]])  # an expired quotation counts as historical
        if ck == "unit_cost":
            goods = conv * ordered
        if ck == "logistics":
            logistics_value = extended
        lines.append({**line, "reporting_amount": money(extended), "reporting_unit_amount": money(conv), "conversion": rinfo})
        step = f"{fm(c['amount'])} {c['currency']}"
        if rinfo:
            step += (f" ÷ {rinfo['rate']} (entered {reporting}→{c['currency']} rate)" if rinfo["inverse"] else f" × {rinfo['rate']}")                 + f" = {fm(conv)} {reporting}"
        if line["multiplier"] > 1:
            step += f" × {line['multiplier']} ordered"
        explain.append(f"{label}: {step} = {fm(extended)} {reporting}" if (rinfo or line["multiplier"] > 1) else f"{label}: {step}")
    d = alt["costs"]["duties"]
    if d.get("not_applicable"):
        lines.append({"key": "duties", "label": "Duties and taxes", "category": "duties_taxes", "not_applicable": True,
                      "source_label": "Not applicable"})
    else:
        line = {"key": "duties", "label": "Duties and taxes", "category": "duties_taxes", "basis": "percentage of goods and logistics",
                "source": d["source"], "source_label": SOURCES[d["source"]], "reference": d["reference"], "note": d["note"],
                "percent": pct(d["percent"]) if d["percent"] is not None else None, "not_applicable": False}
        if d["percent"] is None or goods is None or not known["logistics"]:
            missing.append("Duties and taxes" if d["percent"] is None else "Duties and taxes (goods value or logistics unknown)")
            known["duties_taxes"] = False
            lines.append({**line, "reporting_amount": None})
        else:
            duty = (goods + logistics_value) * d["percent"] / 100
            explain.append(f"Duties and taxes: {d['percent']}% × ({fm(goods)} goods + {fm(logistics_value)} logistics) = {fm(duty)} {reporting}")
            cat["duties_taxes"] += duty
            ranks.append(SOURCE_RANK[d["source"]])
            lines.append({**line, "reporting_amount": money(duty)})
    complete = all(known.values())
    if complete:
        parts = [cat[k] for k in CATEGORIES if cat[k]]
        total_ = sum(cat.values(), Decimal(0))
        explain.append(f"Total: {' + '.join(fm(x) for x in parts) or '0.00'} = {fm(total_)} {reporting} "
                       "(each figure rounded for display; the total uses unrounded values)")
        explain.append(f"Effective cost per usable unit: {fm(total_)} ÷ {required} required = {fm(total_ / required)} {reporting}")
    else:
        explain.append("Total not calculated: " + "; ".join(missing) + ".")
    total = sum(cat.values(), Decimal(0)) if complete else None
    per_order = alt["costs"]["logistics"].get("basis") == "per_order"  # absent when logistics is not applicable
    one_time = cat["setup_tooling"] + cat["testing_qualification"] + (cat["logistics"] if per_order else 0)
    variable = cat["material_production"] + (0 if per_order else cat["logistics"])
    # lead time
    lt, lead_missing, lead_ranks, days = [], [], [], 0
    validity = quote_validity(lines)
    for lk, label in LEAD.items():
        c = alt["lead_time"][lk]
        if c.get("not_applicable"):
            lt.append({"key": lk, "label": label, "not_applicable": True, "source_label": "Not applicable", "days": 0})
            continue
        comp = {"key": lk, "label": label, "days": c["days"], "source": c["source"], "source_label": SOURCES[c["source"]],
                "reference": c["reference"], "note": c["note"], "not_applicable": False}
        if c.get("valid_until"):
            comp["valid_until"] = c["valid_until"].isoformat()
        q = lead_quote_status(c, validity, today)
        if q:
            comp["quotation_validity"] = q
            if q["expired"]:
                warnings.append(f"{label}: quoted lead time expired on {q['valid_until']} (with {q['basis']}).")
            elif q["unknown"]:
                warnings.append(f"{label}: quoted lead time has no validity date and no matching quotation: not current evidence.")
        lt.append(comp)
        if c["days"] is None:
            lead_missing.append(label)
        else:
            days += c["days"]
            # an expired (or undated) quoted lead time is no better than a historical figure
            lead_ranks.append(3 if q and (q["expired"] or q["unknown"]) else SOURCE_RANK[c["source"]])
    lead_total = None if lead_missing else days
    return {
        "key": key, "label": ALTERNATIVES[key], "required_quantity": required, "ordered_quantity": ordered,
        "moq": alt["moq"], "order_multiple": alt["order_multiple"], "qualification_units": alt["qualification_units"],
        "surplus_units": ordered - required - alt["qualification_units"], "lines": lines,
        "categories": {k: {"label": v, "amount": money(cat[k]) if known[k] else None} for k, v in CATEGORIES.items()},
        "one_time_total": money(one_time) if complete else None, "quantity_dependent_total": money(variable) if complete else None,
        "duties_total": money(cat["duties_taxes"]) if complete else None,
        "complete": complete, "total": money(total), "known_costs_total": money(sum(cat.values(), Decimal(0))),
        "effective_unit_cost": money(total / required) if complete else None,
        "cost_per_ordered_unit": money(total / ordered) if complete else None,
        "setup_tooling_per_usable_unit": money(cat["setup_tooling"] / required) if known["setup_tooling"] else None,
        "missing_inputs": missing + [f"Lead time: {m.lower()}" for m in lead_missing], "warnings": warnings,
        "exchange_rates_used": used_rates,
        "confidence": ("Incomplete: missing inputs" if not complete else CONFIDENCE[min(ranks)] if ranks else "No priced inputs"),
        "lead_time": {"components": lt, "total_days": lead_total, "complete": lead_total is not None,
                      "confidence": ("Incomplete: missing inputs" if lead_missing else CONFIDENCE[min(lead_ranks)] if lead_ranks else "Not applicable"),
                      "assumption": "Engineering / qualification time and supplier lead time run one after the other."},
        "notes": alt["notes"], "explanation": explain, "_total": total, "_days": lead_total,
    }


def calculate(scenario: dict, technical: dict, today: date) -> dict:
    """scenario: the output of validate(). technical: {alternative: {excluded: bool, qualified: bool, ...}} from Phase 3."""
    req, rep = scenario["quantity"], scenario["reporting_currency"]
    convert = _converter(scenario["exchange_rates"], rep)
    alts = {k: calculate_alternative(k, scenario["alternatives"][k], req, rep, convert, today) for k in ALTERNATIVES}
    base_key = scenario["baseline"]
    base = alts[base_key]
    for k, a in alts.items():
        t = technical.get(k, {})
        a["technical"] = t
        cmp = {"baseline": base_key, "baseline_label": ALTERNATIVES[base_key], "savings": None, "savings_percent": None,
               "lead_time_difference_days": None, "provisional": not t.get("qualified", False), "reason": ""}
        if k == base_key:
            cmp["reason"] = "Baseline"
        elif t.get("excluded"):
            cmp["reason"] = "Excluded by a verified technical constraint: no savings shown."
        elif base["_total"] is None or a["_total"] is None:
            cmp["reason"] = "Totals incomplete: savings cannot be calculated."
        else:
            s = base["_total"] - a["_total"]
            cmp["savings"] = money(s)
            cmp["savings_percent"] = pct(s / base["_total"] * 100) if base["_total"] > 0 else None
            cmp["reason"] = ("Provisional: this alternative is not technically qualified." if cmp["provisional"] else "")
        if k != base_key and base["_days"] is not None and a["_days"] is not None:
            cmp["lead_time_difference_days"] = a["_days"] - base["_days"]
        a["comparison"] = cmp
    for a in alts.values():
        a.pop("_total"), a.pop("_days")
    return {"method_version": METHOD_VERSION, "as_of": today.isoformat(), "quantity": req, "reporting_currency": rep,
            "baseline": base_key, "alternatives": alts,
            "exchange_rates": [{**r, "rate": str(r["rate"]), "rate_date": r["rate_date"].isoformat()} for r in scenario["exchange_rates"]],
            "statement": "Comparison only. No procurement recommendation, manufacturing authorisation or release is made; "
                         "a lower cost never overrides technical constraints or missing engineering approval."}


def serialisable(scenario: dict) -> dict:
    """The validated scenario as JSON (Decimals and dates as strings), stored as the comparison's inputs."""
    def conv(v):
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v
    return conv(scenario)
