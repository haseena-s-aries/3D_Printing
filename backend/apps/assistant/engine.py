"""The assistant's answers. Rule-based: a question is matched to an intent and a topic (apps.assistant.language), data
comes from apps.assistant.lookups with the screens' visibility, and how-to answers from apps.assistant.knowledge.
Every answer is {answer, items, links, suggestions}; items are records with a link to open them."""
import logging
import re

from apps.servicerequests import services as svc
from apps.servicerequests.models import ClientRequest, Quotation
from apps.tenancy.permissions import has_capability

from . import knowledge as kb
from . import lookups as data
from .language import (
    FILLER,
    find_refs,
    has,
    intent_of,
    normalise,
    search_terms,
    status_filter,
    topic_of,
)

log = logging.getLogger("passport.assistant")
S, K = ClientRequest.Status, ClientRequest.Kind
FINISHED = {S.COMPLETED, S.CLOSED, S.DECLINED, S.WITHDRAWN}


def _answer(text: str | list[str], items=None, links=None, suggestions=None) -> dict:
    lines = [text] if isinstance(text, str) else text
    return {"answer": "\n".join(x for x in lines if x), "items": items or [], "links": links or [], "suggestions": suggestions or []}


def suggestions(scope: data.Scope) -> list[str]:
    if scope.full:
        return ["How many open requests?", "Requests awaiting acknowledgement", "Requests in production", "Pending registrations",
                "Which quotations are waiting for the client?", "How do I archive a part?"]
    if scope.staff:
        return ["My open requests", "Requests awaiting acknowledgement", "Requests waiting for QA check",
                "How do I do the QA check?", "What is the order flow?"]
    return ["Status of my requests", "How many open requests do I have?", "Requests waiting for my information",
            "How do I request 3D scanning?", "How do I accept a quotation?"]


# ------------------------------------------------------------------ what happens next to a request

def _who(role: str, scope: data.Scope) -> str:
    return "" if not scope.staff else f" ({role})"


def next_step(row: dict, scope: data.Scope) -> list[str]:
    """What the request is waiting for, from its kind, status, quotation and the part's passport now."""
    st, kind = row["status"], row["kind"]
    client = not scope.staff
    if st in FINISHED:
        return [f"It is {data._status_label(st).lower()}: nothing more to do."]
    if st == S.SUBMITTED:
        return ["Next: Aries acknowledges it." if client else "Next: acknowledge it (any Aries staff who can open it)."]
    if st == S.INFORMATION_REQUESTED:
        return ["Aries asked you for information: open the request and send your answer." if client
                else "Waiting for the client to provide the requested information."]
    if kind == K.ENQUIRY:
        out = ["This is a manufacturing enquiry: Aries replies and closes it. It can never be released for production."]
        state = data.passport_state(row["client_id"], row["request_id"])
        if state and state[0] == "Published" and state[1] in ("Eligible", "Eligible subject to authorisation"):
            out.append(f"The part's passport is now {state[0].lower()} and {state[1].lower()}: "
                       + ("submit a new request on the part to get a manufacturing order." if client
                          else "reply and close it, and ask the client to submit a new request on the part; it will arrive as a manufacturing request."))
        else:
            out.append("A request becomes a manufacturing order only when the part's passport is published and eligible at submission.")
        if data.quotation_state(row["client_id"], row["request_id"]) == Quotation.Status.ACCEPTED:
            out.append("A quotation was accepted on this enquiry, but an enquiry cannot be released: the new manufacturing request needs its own quotation.")
        return out
    if kind == K.DIGITISATION:
        return {S.ACKNOWLEDGED: ["Next: Aries schedules the scan."], S.INFORMATION_PROVIDED: ["Next: Aries schedules the scan."],
                S.SCHEDULED: ["Next: Aries starts the scan."], S.IN_PROGRESS: ["Next: Aries completes the scan and creates the draft part."]
                }.get(st, [f"Status: {data._status_label(st)}."])
    if kind == K.ASSESSMENT:
        return ["Next: Aries Engineering answers the assessment request and closes it."]
    # manufacturing order flow
    if st in (S.ACKNOWLEDGED, S.INFORMATION_PROVIDED, S.ANSWERED):
        return [f"Next: the engineering check{_who('Aries Engineer', scope)}."]
    if st == S.ENGINEERING_CHECKED:
        return [f"Next: the QA check{_who('Aries QA, not the engineer who checked it', scope)}."]
    if st == S.QA_APPROVED:
        q = data.quotation_state(row["client_id"], row["request_id"])
        if q == Quotation.Status.ACCEPTED:
            return ["The client accepted the quotation. Next: release for production" + _who("Aries Admin or Manager", scope) + "."]
        if q == Quotation.Status.SENT:
            return ["Next: accept or reject the quotation (open the request, Quotation)." if client
                    else "Waiting for the client to accept the quotation; then the Aries Admin or Manager releases it."]
        if q == Quotation.Status.REJECTED:
            return ["You rejected the quotation; Aries may send a new one." if client
                    else "The client rejected the quotation: send a revised one from the Cost estimate, or close the request."]
        return ["Next: Aries prepares the quotation." if client
                else "Next: choose the production route in the Cost estimate and send the quotation (Aries Admin or Manager)."]
    return {S.RELEASED: [f"Next: start production{_who('Aries Engineer, Admin or Manager', scope)}."],
            S.IN_PRODUCTION: [f"Next: inspection{_who('Aries QA: passed, or failed for rework', scope)}."],
            S.INSPECTED: [f"Next: delivery{_who('Aries Engineer, Admin or Manager marks it delivered', scope)}."],
            }.get(st, [f"Status: {data._status_label(st)}."])


def why_blocked(row: dict, text: str, scope: data.Scope) -> list[str]:
    st, kind = row["status"], row["kind"]
    if has(text, "release", "released", "production"):
        if kind == K.ENQUIRY:
            return ["It cannot be released: it is an enquiry, and only manufacturing requests can be released.", *next_step(row, scope)[1:]]
        if st != S.QA_APPROVED:
            return [f"Release needs the QA check first; it is now {data._status_label(st).lower()}.", *next_step(row, scope)]
        if data.quotation_state(row["client_id"], row["request_id"]) != Quotation.Status.ACCEPTED:
            return ["Release needs the client's accepted quotation for the chosen route.", *next_step(row, scope)]
        return ["Nothing blocks the release: the Aries Admin or Manager can release it now."]
    if has(text, "archive", "archived", "delete", "remove"):
        if st in ("released", "in_production", "inspected"):
            return ["It cannot be archived while the order is released, in production or inspected: finish or close it first."]
        return ["The Aries Admin or Manager can archive it from Incoming requests (Archive on its row)."]
    return next_step(row, scope)


# ------------------------------------------------------------------ pages

PAGES = [
    (("dashboard", "home"), "Dashboard", lambda r, s: "/"),
    (("incoming", "queue"), "Incoming requests", lambda r, s: "/incoming" if has_capability(r, "requests.handle") else None),
    (("my requests", "requests"), "My requests", lambda r, s: "/requests" if s.client_member else ("/incoming" if s.staff else None)),
    (("inventory", "parts", "spare parts"), "Digital inventory", lambda r, s: "/admin/inventory" if s.full else ("/parts" if s.in_client else None)),
    (("passports", "passport"), "Digital passports", lambda r, s: "/passport-register" if s.full else ("/passports" if s.in_client else None)),
    (("archive", "archived"), "Archive", lambda r, s: "/archive" if s.full else None),
    (("clients", "companies", "client"), "Clients", lambda r, s: "/clients" if s.full else None),
    (("users", "people", "members"), "Users", lambda r, s: "/users" if s.users else None),
    (("registrations", "registration"), "Registrations", lambda r, s: "/registrations" if s.full else None),
    (("approvals", "approval"), "Approvals", lambda r, s: "/approvals" if s.full else None),
    (("attention", "needs attention", "notifications"), "Needs attention", lambda r, s: "/attention"),
    (("estimate rates", "rates"), "Estimate rates", lambda r, s: "/estimate-rates" if s.full else None),
]


def page_link(request, scope, text):
    for words, label, to in PAGES:
        if has(text, *words):
            path = to(request, scope)
            return {"label": label, "to": path} if path else None
    return None


# ------------------------------------------------------------------ the answer

def _context_request(request, scope, context) -> dict | None:
    """The request the person is looking at (its page), so "what's next?" needs no number."""
    path = str((context or {}).get("path") or "")
    m = re.fullmatch(r"/(incoming|requests)/([0-9a-f-]{36})", path)
    if not m:
        return None
    for row in data.requests(request, scope, limit=None):
        if row["link"] == path:
            return row
    return None


def _list_requests(request, scope, text, terms):
    statuses = status_filter(text)
    open_only = has(text, "open", "pending", "active", "current") and not statuses
    if has(text, "quotation", "quote") and scope.staff:
        rows = [r for r in data.requests(request, scope, statuses={S.QA_APPROVED}, limit=None)
                if data.quotation_state(r["client_id"], r["request_id"]) == Quotation.Status.SENT]
        return _answer(f"{len(rows)} request(s) wait for the client to accept the quotation." if rows
                       else "No quotation is waiting for the client.", rows[:data.LIMIT], [{"label": "Incoming requests", "to": "/incoming"}])
    if has(text, "message", "messages", "reply") and scope.staff:
        rows = [r for r in data.requests(request, scope, open_only=True, limit=None)]
        from apps.servicerequests.models import RequestEnvelope
        from apps.tenancy.context import tenant_context

        with tenant_context(svc.operator_tenant()):
            waiting = set(RequestEnvelope.objects.filter(awaiting_reply=True).values_list("pk", flat=True))
        rows = [r for r in rows if r["link"].rsplit("/", 1)[-1] in {str(w) for w in waiting}]
        return _answer(f"{len(rows)} request(s) with a client message awaiting reply." if rows else "No client message is waiting for a reply.",
                       rows[:data.LIMIT], [{"label": "Incoming requests", "to": "/incoming?awaiting=true"}])
    rows = data.requests(request, scope, terms=terms, statuses=statuses, open_only=open_only, limit=None)
    if not rows:
        return _answer("No request matches." if (terms or statuses) else "You have no requests yet.", suggestions=suggestions(scope))
    what = "open " if open_only else ""
    head = f"{len(rows)} {what}request(s)" + (f" · {data._status_label(min(statuses)).lower()}" if statuses and len(statuses) == 1 else "")
    base = "/incoming" if scope.staff else "/requests"
    return _answer(head + (f"; the latest {data.LIMIT}:" if len(rows) > data.LIMIT else ":"), rows[:data.LIMIT], [{"label": "Open the list", "to": base}])


def _count(request, scope, text):
    topic = topic_of(text)
    if topic in (None, "request", "quotation"):
        statuses = status_filter(text)
        if topic is None and not statuses and not has(text, "open", "pending"):
            return _overview(request, scope)
        open_only = not statuses and not has(text, "all", "total", "ever")
        rows = data.requests(request, scope, statuses=statuses, open_only=open_only, limit=None)
        label = data._status_label(min(statuses)).lower() if statuses and len(statuses) == 1 else ("open" if open_only else "in total")
        return _answer(f"{len(rows)} request(s) {label}." if label == "in total" else f"{len(rows)} {label} request(s).",
                       links=[{"label": "Open the list", "to": "/incoming" if scope.staff else "/requests"}])
    if topic in ("part", "passport"):
        n_parts, n_passports = data.count_parts_passports(request, scope)
        return _answer(f"{n_parts} spare part(s) and {n_passports} digital passport(s)" + (" across all client companies." if scope.full else "."))
    if topic == "client" and scope.full:
        return _answer(f"{len(data.clients(scope, limit=None))} client companies.", links=[{"label": "Clients", "to": "/clients"}])
    if topic == "user" and (scope.full or scope.users):
        rows = data.users(request, scope, limit=None, inactive=has(text, "inactive", "deactivated", "disabled") or None)
        return _answer(f"{len(rows)} membership(s)" + (" across all organisations." if scope.full else " in your organisation."))
    if topic == "registration" and scope.full:
        rows = data.registrations(request, scope, pending_only=not has(text, "all", "total"), limit=None)
        return _answer(f"{len(rows)} registration(s) {'' if has(text, 'all', 'total') else 'pending approval'}.".replace("  ", " "),
                       links=[{"label": "Registrations", "to": "/registrations"}])
    return _answer("I can't count that for your role.", suggestions=suggestions(scope))


def _overview(request, scope):
    open_rows = data.requests(request, scope, open_only=True, limit=None)
    waiting = sum(1 for r in open_rows if r["status"] == S.SUBMITTED)
    n_parts, n_passports = data.count_parts_passports(request, scope)
    lines = [f"Open requests: {len(open_rows)} ({waiting} awaiting acknowledgement)." if scope.staff else f"Open requests: {len(open_rows)}.",
             f"Spare parts: {n_parts} · Digital passports: {n_passports}."]
    if scope.full:
        lines.append(f"Client companies: {len(data.clients(scope, limit=None))} · Registrations pending: "
                     f"{len(data.registrations(request, scope, pending_only=True, limit=None))}.")
    return _answer(lines, links=[{"label": "Dashboard", "to": "/"}])


def _search_everything(request, scope, terms):
    found = []
    if not terms:
        return None
    found += data.requests(request, scope, terms=terms, limit=5)
    found += data.passports(request, scope, terms=terms, limit=5)
    found += data.parts(request, scope, terms=terms, limit=5)
    if scope.full:
        found += data.clients(scope, terms=terms, limit=5)
        found += data.registrations(request, scope, terms=terms, limit=5)
    if scope.full or scope.users:
        found += data.users(request, scope, terms=terms, limit=5)
    if not found:
        return None
    return _answer(f"Found {len(found)} result(s) for “{' '.join(terms)}”:", found[:12])


def _knowledge(text, scope, prefer_glossary=False, min_score=1):
    words = set(text.split())
    first, second = (kb.GLOSSARY, kb.HOWTO) if prefer_glossary else (kb.HOWTO, kb.GLOSSARY)
    articles = kb.best(first, words, scope.audience, min_score=min_score) or kb.best(second, words, scope.audience, min_score=min_score)
    if not articles:
        return None
    a = articles[0]
    lines = [a.title + ":"] + [f"{i}. {s}" for i, s in enumerate(a.steps, 1)] + list(a.extra)
    more = [f"Also: {b.title}" for b in articles[1:]]
    return _answer(lines + more, links=[{"label": a.link[0], "to": a.link[1]}] if a.link else [])


def reply(request, message: str, context: dict | None = None) -> dict:
    scope = data.scope_of(request)
    raw = (message or "")[:500]
    text = normalise(raw)
    refs = find_refs(raw)
    intent = intent_of(text)
    terms = [t for t in search_terms(text) if not re.fullmatch(r"(arq|mr|dr|ar|dp)-\d{4}-\d+", t)]

    if not text or intent == "help":
        who = "Aries Admin and Manager: you can search every company's requests, parts, passports, clients, users and registrations." if scope.full else \
              "I answer from the records you can open."
        return _answer(["Hello! Ask me about request status, what happens next, counts, or how to do something.", who],
                       suggestions=suggestions(scope))

    # a reference number: passport or request
    if refs["passport"]:
        rows = data.passports(request, scope, ref=refs["passport"][0], limit=1)
        if not rows:
            return _answer(f"I can't find {refs['passport'][0]} among the passports you can open.")
        r = rows[0]
        return _answer(f"{r['title']}: {r['subtitle']}.", rows)
    ref = (refs["intake"] or refs["request"] or [None])[0]
    row = None
    if ref:
        found = data.requests(request, scope, ref=ref, limit=1)
        if not found:
            return _answer(f"I can't find {ref} among the requests you can open.", suggestions=suggestions(scope))
        row = found[0]
    elif intent in ("next", "why"):
        row = _context_request(request, scope, context)

    if row is not None:
        if intent == "why":
            return _answer([f"{row['title']} is {data._status_label(row['status']).lower()}."] + why_blocked(row, text, scope), [row])
        status = f"{row['title']}: {row['subtitle']}."
        return _answer([status] + next_step(row, scope), [row])

    if intent == "next":
        rows = data.requests(request, scope, open_only=True, limit=5)
        return _answer("Which request? Give its number (for example ARQ-2026-00002), or open it and ask again." +
                       (" Your latest open requests:" if rows else ""), rows)
    if intent == "count":
        return _count(request, scope, text)
    if intent in ("howto", "why", "define"):
        found = _knowledge(text, scope, prefer_glossary=intent == "define")
        if found:
            return found
    if intent == "navigate" or has(text, "open", "go"):
        link = page_link(request, scope, text)
        if link and intent == "navigate":
            return _answer(f"Here is {link['label']}.", links=[link])

    topic = topic_of(text)
    if topic in ("request", "quotation") or status_filter(text) or (topic is None and has(text, "message", "messages")):
        return _list_requests(request, scope, text, [t for t in terms if t not in {"request", "requests", "order", "orders", "quotation",
                                                     "quotations", "quote", "message", "messages", "enquiry", "enquiries"} and t not in FILLER])
    item_terms = [t for t in terms if t not in {"part", "parts", "spare", "passport", "passports", "client", "clients", "company",
                                                "companies", "user", "users", "registration", "registrations", "inventory"}]
    if topic == "passport":
        rows = data.passports(request, scope, terms=item_terms)
        return _answer(f"{len(rows)} passport(s){' (first ' + str(data.LIMIT) + ')' if len(rows) >= data.LIMIT else ''}:" if rows else "No passport matches.", rows)
    if topic == "part":
        rows = data.parts(request, scope, terms=item_terms)
        return _answer(f"{len(rows)} spare part(s){' (first ' + str(data.LIMIT) + ')' if len(rows) >= data.LIMIT else ''}:" if rows else "No spare part matches.", rows)
    if topic == "client" and scope.full:
        rows = data.clients(scope, terms=item_terms)
        return _answer(f"{len(rows)} client compan{'y' if len(rows) == 1 else 'ies'}:" if rows else "No client company matches.", rows)
    if topic == "user" and (scope.full or scope.users):
        rows = data.users(request, scope, terms=item_terms, inactive=has(text, "inactive", "deactivated", "disabled") or None)
        return _answer(f"{len(rows)} user(s):" if rows else "No user matches.", rows)
    if topic == "registration" and scope.full:
        rows = data.registrations(request, scope, terms=item_terms, pending_only=has(text, "pending", "waiting", "new"))
        return _answer(f"{len(rows)} registration(s):" if rows else "No registration matches.", rows)

    found = _knowledge(text, scope, min_score=2) if intent is None else None  # a plain search is not a how-to question
    if found and len(terms) <= 4:
        return found
    found = _search_everything(request, scope, terms)
    if found:
        return found
    log.info("assistant: no answer (%s words)", len(text.split()))  # the question text is not logged
    return _answer("Sorry, I didn't understand that. Try one of these, or type a request, passport or part number.",
                   suggestions=suggestions(scope))
