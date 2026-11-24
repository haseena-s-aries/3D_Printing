"""Understanding a question without an AI service: normalising, correcting typos against the platform's own vocabulary
(standard-library difflib), finding reference numbers and recognising the intent and topic from keywords."""
import difflib
import re

# Reference numbers people type or paste
REF_PATTERNS = {
    "intake": re.compile(r"\bARQ-\d{4}-\d{3,6}\b", re.IGNORECASE),            # Aries intake number
    "request": re.compile(r"\b(?:MR|DR|AR)-\d{4}-\d{3,6}\b", re.IGNORECASE),   # client request reference
    "passport": re.compile(r"\bDP-\d{4}-\d{3,6}\b", re.IGNORECASE),
}

# Words the assistant understands; a misspelt word close to one of these is read as that word ("quatation" -> "quotation")
VOCABULARY = [
    "request", "requests", "passport", "passports", "part", "parts", "spare", "client", "clients", "company", "companies",
    "user", "users", "registration", "registrations", "quotation", "quotations", "quote", "release", "released", "archive",
    "archived", "restore", "acknowledge", "acknowledgement", "acknowledged", "production", "inspection", "inspected",
    "deliver", "delivered", "delivery", "enquiry", "enquiries", "published", "publish", "unpublish", "open", "pending",
    "awaiting", "status", "approve", "approved", "approval", "approvals", "engineering", "deactivate", "reactivate",
    "invitation", "notification", "notifications", "dashboard", "inventory", "incoming", "scan", "scanning", "clone",
    "submit", "submitted", "password", "eligible", "eligibility", "manufacturing", "order", "orders", "closed", "completed",
    "estimate", "accepted", "rejected", "information", "message", "messages", "search", "show", "list", "how", "many",
    "next", "step", "why", "cannot", "where", "what", "which", "count", "total", "login", "sign", "progress",
]

STOP = {"the", "a", "an", "is", "are", "of", "for", "to", "my", "me", "i", "we", "our", "do", "does", "in", "on", "at", "and",
        "or", "it", "this", "that", "be", "can", "please", "pls", "with", "all", "any", "there", "have", "has", "from", "by",
        "you", "your", "about", "give", "tell", "want", "need", "know"}


def normalise(text: str) -> str:
    """Lower case, punctuation as spaces (reference numbers keep their hyphens), single spaces, typos corrected."""
    text = (text or "").strip().lower()
    text = re.sub(r"[^\w\s\-./@]", " ", text)
    out = []
    for word in text.split():
        if len(word) > 3 and word.isalpha() and word not in VOCABULARY:
            close = difflib.get_close_matches(word, VOCABULARY, n=1, cutoff=0.8)
            out.append(close[0] if close else word)
        else:
            out.append(word)
    return " ".join(out)


def find_refs(text: str) -> dict[str, list[str]]:
    return {kind: sorted({m.group(0).upper() for m in rx.finditer(text or "")}) for kind, rx in REF_PATTERNS.items()}


def has(text: str, *phrases: str) -> bool:
    """Whole-word / whole-phrase match on normalised text."""
    return any(re.search(rf"(?<![\w-]){re.escape(p)}(?![\w-])", text) for p in phrases)


def search_terms(text: str) -> list[str]:
    """Words worth searching for (not stop words or the assistant's own command words)."""
    command = {"show", "list", "find", "search", "which", "what", "where", "how", "many", "status", "open", "get", "see", "look"}
    return [w for w in text.split() if len(w) >= 2 and w not in STOP and w not in command]


# intents, checked in this order; each is a list of trigger phrases on the normalised text
INTENTS: list[tuple[str, tuple[str, ...]]] = [
    ("help", ("help", "what can you do", "hello", "hi", "hey", "good morning", "good afternoon", "good evening", "menu", "options")),
    ("count", ("how many", "count", "number of", "total", "how much")),
    ("why", ("why", "cannot", "can't", "cant", "unable", "not able", "blocked", "won't", "wont", "not working", "stuck", "not allowed")),
    ("next", ("next step", "next", "what now", "what should", "what do i do", "what to do", "pending step", "who should")),
    ("howto", ("how do i", "how to", "how can i", "how should i", "steps to", "where do i", "where can i", "process", "procedure", "guide")),
    ("define", ("what is", "what does", "what are", "meaning", "mean", "define", "definition", "explain")),
    ("navigate", ("go to", "take me to", "open the", "navigate", "page")),
    ("list", ("show", "list", "find", "search", "which", "display", "all", "latest", "recent")),
]


def intent_of(text: str) -> str | None:
    for name, phrases in INTENTS:
        if has(text, *phrases):
            if name == "help" and len(text.split()) > 4:  # "hi, what is the status of ..." is not a greeting
                continue
            return name
    return None


# what a question is about
TOPICS: list[tuple[str, tuple[str, ...]]] = [
    ("quotation", ("quotation", "quotations", "quote", "price", "estimate")),
    ("registration", ("registration", "registrations", "register", "sign up", "signup")),
    # a question about requests stays about requests even when it names a client or a part ("requests from client B")
    ("request", ("request", "requests", "order", "orders", "enquiry", "enquiries", "scan", "scanning", "intake")),
    ("user", ("user", "users", "member", "members", "staff", "account", "accounts", "login", "sign in", "invitation", "deactivate", "reactivate")),
    ("client", ("client", "clients", "company", "companies", "organisation", "organisations", "organization", "customer", "customers")),
    ("passport", ("passport", "passports")),
    ("part", ("part", "parts", "spare", "spares", "inventory", "component", "components")),
]


def topic_of(text: str) -> str | None:
    for name, words in TOPICS:
        if has(text, *words):
            return name
    return None


# request status filters people say in words
STATUS_WORDS: list[tuple[tuple[str, ...], set[str]]] = [  # checked in this order (longer phrases first)
    (("awaiting acknowledgement", "awaiting ack", "not acknowledged", "new request", "new requests", "submitted", "unacknowledged"), {"submitted"}),
    (("information requested", "waiting for information", "waiting for my information", "my information", "info requested"), {"information_requested"}),
    (("engineering checked", "awaiting qa", "waiting for qa", "qa check", "for qa"), {"engineering_checked"}),
    (("qa approved", "awaiting release", "ready to release", "ready for release"), {"qa_approved"}),
    (("engineering check", "engineering"), {"acknowledged", "information_provided", "answered"}),
    (("released",), {"released"}),
    (("in production", "production", "manufacturing now"), {"in_production"}),
    (("inspected", "ready to deliver"), {"inspected"}),
    (("delivered", "completed", "finished", "done"), {"completed"}),
    (("closed",), {"closed"}),
    (("declined", "rejected"), {"declined"}),
]


# words that only describe a status or a list ("awaiting acknowledgement", "open"): not search terms
FILLER = {w for words, _ in STATUS_WORDS for phrase in words for w in phrase.split()} | {
    "open", "pending", "active", "current", "new", "latest", "recent", "waiting", "awaiting", "now", "today", "are", "is", "ready"}


def status_filter(text: str) -> set[str] | None:
    for words, statuses in STATUS_WORDS:
        if has(text, *words):
            return statuses
    return None
