"""How-to answers and definitions, written from the platform's screens and rules. Each article names who it is for:
"admin" (Aries Admin or Manager), "aries" (any Aries staff), "client" (client company members) or "all". Matching is by
keyword overlap with the question, so adding a question is adding an article or a keyword here, without other code."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Article:
    key: str
    title: str
    keywords: tuple[str, ...]
    audience: str  # admin | aries | client | all
    steps: tuple[str, ...]
    link: tuple[str, str] | None = None  # (label, path)
    extra: tuple[str, ...] = field(default_factory=tuple)


HOWTO: list[Article] = [
    Article("archive_part", "Archive a spare part (with its passport)", ("archive", "part", "passport", "delete", "remove", "hide"), "admin",
            ("Open Digital inventory and find the part (list or grid).", "Click Archive on the part and confirm.",
             "The part and its passport are hidden everywhere; the part number becomes free.",
             "Not possible while the part has open requests (close or archive them first) or a published passport (unpublish it first)."),
            ("Digital inventory", "/admin/inventory?view=parts"), ("Nothing is erased: restore it from the Archive tab.",)),
    Article("archive_request", "Archive a request", ("archive", "request", "order", "enquiry", "delete", "remove", "hide"), "admin",
            ("Open Incoming requests.", "Click Archive on the request row and confirm.",
             "Not possible while the order is released, in production or inspected: finish or close it first."),
            ("Incoming requests", "/incoming"), ("Nothing is erased: restore it from the Archive tab.",)),
    Article("restore", "Restore an archived part or request", ("restore", "undo", "archive", "archived", "bring", "back", "recover"), "admin",
            ("Open the Archive tab.", "Click Restore on the item.",
             "A part cannot be restored while another part uses its part number: rename that one first."), ("Archive", "/archive")),
    Article("deactivate_user", "Deactivate (or reactivate) a user", ("deactivate", "reactivate", "user", "disable", "block", "remove", "delete", "login", "access"), "admin",
            ("Aries staff: open Users. Client users: open Clients, the company, then the Client Users tab.",
             "Click Deactivate and confirm. The person can no longer sign in; open sessions end at once.",
             "An Aries staff member deactivated in the Aries organisation also loses every client company they were assigned to.",
             "Click Reactivate to restore their access exactly as before."), ("Users", "/users"),
            ("Nothing is erased: the audit trail keeps their actions.",)),
    Article("unpublish", "Unpublish a digital passport", ("unpublish", "passport", "catalog", "withdraw", "publish"), "aries",
            ("Open Digital passports and the passport.", "Click Unpublish and give the reason (the client sees it).",
             "The part leaves the client's manufacturing catalog; new requests on it become enquiries."), ("Digital passports", "/passport-register")),
    Article("quotation", "Send a quotation", ("quotation", "quote", "price", "estimate", "cost", "send", "route"), "admin",
            ("Open the request under Incoming requests (a manufacturing request at QA approved).",
             "In Cost estimate, compare the routes (OEM, conventional, 3D printing) and choose the production route.",
             "Send the quotation: method, price, delivery days and validity. The client sees only those.",
             "The client accepts or rejects it; release waits for the accepted quotation."), ("Incoming requests", "/incoming")),
    Article("release", "Release an order for production", ("release", "production", "order", "start", "manufacture"), "admin",
            ("The order must be QA approved and the client must have accepted the quotation for the chosen route.",
             "Open the request under Incoming requests and click Release for production.",
             "Then: Start production, Inspection passed, Mark delivered."), ("Incoming requests", "/incoming")),
    Article("order_flow", "The manufacturing order flow", ("flow", "workflow", "steps", "order", "manufacturing", "process", "stages", "lifecycle"), "all",
            ("Submitted, then Acknowledged by Aries.", "Engineering check by an Aries Engineer.",
             "QA check by Aries QA (not the engineer who checked it).",
             "Cost estimate and quotation by the Aries Admin or Manager; the client accepts it.",
             "Release for production, Start production, Inspection, Delivered.")),
    Article("enquiry", "Why a request is an enquiry, and what to do", ("enquiry", "enquiries", "convert", "order", "manufacturing", "why"), "all",
            (("A request becomes a manufacturing order only if, when it is submitted, the part's passport is published and "
              "eligible (Eligible, or Eligible subject to authorisation). Otherwise it is an enquiry."),
             "An enquiry is replied to and closed; it cannot be released for production.",
             ("Once the passport is published and eligible, the client submits a new request on the part: it arrives as a "
              "manufacturing request."))),
    Article("acknowledge", "Acknowledge a client request", ("acknowledge", "acknowledgement", "new", "request", "incoming"), "aries",
            ("Open Incoming requests; new requests are marked Submitted · awaiting acknowledgement.",
             "Open the request and click Acknowledge."), ("Incoming requests", "/incoming?status=submitted")),
    Article("engineering_check", "Do the engineering check", ("engineering", "check", "engineer", "review"), "aries",
            ("Open the acknowledged manufacturing request under Incoming requests.",
             "Review the part, passport and documents, then click Engineering check passed."), ("Incoming requests", "/incoming")),
    Article("qa_check", "Do the QA check", ("qa", "quality", "check", "approve", "inspection"), "aries",
            ("Open the request at Engineering checked under Incoming requests.",
             "Click QA approve (Aries QA; not the engineer who did the engineering check).",
             "Later, after production, QA records Inspection passed or Inspection failed."), ("Incoming requests", "/incoming")),
    Article("registrations", "Approve a company or staff registration", ("registration", "register", "approve", "company", "signup", "staff"), "admin",
            ("Open Registrations: pending registrations are listed first.", "Open one, check the details and possible duplicates, then approve or reject with a reason."),
            ("Registrations", "/registrations")),
    Article("test_company", "Delete a test company", ("delete", "test", "company", "purge", "remove"), "admin",
            ("Open Clients, the company, Overview tab, Test company card.", "Tick This is a test company, then Delete this test company, type its name and Queue for deletion.",
             "The company is suspended at once and can still be restored.",
             "A server operator erases it for good with python manage.py purge_test_companies."), ("Clients", "/clients")),
    # client company members
    Article("client_order", "Request manufacturing of a part", ("request", "order", "manufacture", "manufacturing", "buy", "new", "part", "send"), "client",
            ("Open Digital inventory.", "On the part, open its menu and choose Request.",
             "Fill in quantity, required date and delivery location, and send it.",
             "If the part's passport is published and eligible it becomes a manufacturing request; otherwise an enquiry."),
            ("Digital inventory", "/parts")),
    Article("client_scan", "Request 3D scanning of a part", ("scan", "scanning", "3d", "digitise", "digitisation", "measure"), "client",
            ("Open Digital inventory and click Request 3D scanning (or use the dashboard entry).",
             "Describe the part, site and preferred date, and send it."), ("Request 3D scanning", "/requests/new-scan")),
    Article("client_submit", "Submit a part's details", ("submit", "part", "details", "add", "new", "create"), "client",
            ("Open Submit a part.", "Enter the part's details and documents, and submit it for Aries review."), ("Submit a part", "/parts/submit")),
    Article("client_clone", "Clone a part (a variant)", ("clone", "copy", "variant", "duplicate", "similar"), "client",
            ("Open Digital inventory and choose the part.", "Click Clone part, change what differs and submit it.",
             "Once Aries approves it, its manufacturing request is sent automatically."), ("Digital inventory", "/parts?catalog=all")),
    Article("client_quotation", "Accept or reject a quotation", ("quotation", "quote", "accept", "reject", "price", "approve"), "client",
            ("Open My requests and the request.", "Under Quotation, check the method, price, delivery days and validity.",
             "Click Accept or Reject (with a reason). Aries starts the order after you accept."), ("My requests", "/requests")),
    Article("client_info", "Answer Aries' request for information", ("information", "answer", "reply", "message", "question"), "client",
            ("Open My requests: requests waiting for you show Information requested.", "Open it, write your answer and attach files if needed, then send."),
            ("My requests", "/requests?status=information_requested")),
    # everyone
    Article("password", "Reset your password", ("password", "forgot", "reset", "change", "login", "sign"), "all",
            ("Sign out, then on the sign-in page click Forgot password?", "Enter your email and follow the link you receive.")),
    Article("switch_org", "Work in another organisation", ("switch", "change", "organisation", "company", "client", "workspace"), "all",
            ("Use the organisation switcher at the top of the menu (Change client).", "Each organisation shows only its own records.")),
    Article("notifications", "Notifications", ("notification", "notifications", "bell", "alert", "alerts", "new", "updates"), "all",
            ("The bell at the top shows new notifications; the menu shows counts next to each section.",
             "New items are highlighted in the lists; opening an item marks its notifications read.")),
]

GLOSSARY: list[Article] = [
    Article("rl", "R-L1, R-L2 and R-L3 data levels", ("rl1", "rl2", "rl3", "r-l1", "r-l2", "r-l3", "level", "levels", "data", "captured"), "all",
            ("R-L1, R-L2 and R-L3 are the passport's data sections, each on its own tab with its own completeness.",
             ("An Aries Engineer fills in R-L1 and R-L2 completely before the passport is completed and published; R-L3 "
              "evidence documents may follow in a later revision."),
             "The data level shown (for example R-L1–R-L2 data complete) guides data entry; the official evidence level is a separate field.")),
    Article("eligibility", "Manufacturing eligibility", ("eligible", "eligibility", "authorisation", "authorization", "subject"), "all",
            ("Eligible, and Eligible subject to authorisation: with a published passport, requests on the part become manufacturing requests.",
             "Not eligible or Suspended: requests on it become enquiries.")),
    Article("published", "Published passport", ("published", "publish", "publication", "catalog", "draft"), "all",
            ("A published passport puts the part in the client's manufacturing catalog.",
             "Draft, Submitted or Complete passports are still being prepared by Aries.")),
    Article("statuses", "Request statuses", ("status", "statuses", "submitted", "acknowledged", "released", "inspected", "answered"), "all",
            ("Submitted: waiting for Aries to acknowledge.", "Acknowledged: Aries is working on it.",
             "Information requested: Aries is waiting for the client.", "Engineering checked, QA approved: order checks done.",
             "Released, In production, Inspected, Completed (delivered): the order flow.", "Closed, Declined, Withdrawn: finished.")),
    Article("archive_def", "Archive", ("archive", "archived"), "all",
            (("Archiving hides a part (with its passport) or a request everywhere. Nothing is erased; the Aries Admin or "
              "Manager can restore it from the Archive tab."),)),
]


def _audience_ok(article: Article, audience: set[str]) -> bool:
    return article.audience == "all" or article.audience in audience


def best(articles: list[Article], words: set[str], audience: set[str], limit: int = 2, min_score: int = 1) -> list[Article]:
    """The articles sharing the most keywords with the question (at least `min_score`), for this person's role."""
    scored = []
    for a in articles:
        if not _audience_ok(a, audience):
            continue
        score = len(words & set(a.keywords)) + (1 if words & set(a.title.lower().split()) else 0)
        if score >= min_score:
            scored.append((score, a))
    scored.sort(key=lambda s: -s[0])
    if not scored:
        return []
    top = scored[0][0]
    return [a for s, a in scored if s >= max(top - 1, min_score)][:limit]
