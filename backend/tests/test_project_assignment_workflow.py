"""Project-based assignment workflow (2 Nov 2026): Aries Admin creates the client -> creates projects directly -> assigns Aries
Engineers to projects -> engineering work starts. New Aries staff are project-scoped with no projects; company-wide access is an
explicit option; reviewers act only within their projects; clients stay within their company; existing assignments unchanged."""
from apps.audit.models import AuditEvent
from apps.parts.models import SparePart
from apps.projects.models import EngineerAccess, Project
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role, Tenant

from .conftest import PASSWORD, login, make_user

NEW_CLIENT = {"name": "Synthetic Assignment Co", "slug": "synthetic-assignment-co", "trade_licence_number": "TL-1", "licence_authority": "DED",
              "country": "United Arab Emirates", "state": "Abu Dhabi", "city": "Abu Dhabi", "address": "Synthetic street 1",
              "contact_name": "C. Admin", "contact_title": "Manager", "contact_email": "c.admin@assign.test", "contact_phone": "+971 2 000 0000",
              "invite_contact": False}


def _client(world):
    admin = login(world["op_admin"])
    r = admin.post("/api/v1/clients/", NEW_CLIENT, format="json")
    assert r.status_code == 201, r.content
    return admin, Tenant.objects.get(slug=NEW_CLIENT["slug"])


def _assign(admin, client, email, role=Role.OPERATOR_ENGINEER):
    make_user(email, Tenant.objects.get(kind=Tenant.Kind.OPERATOR), role)
    r = admin.post(f"/api/v1/clients/{client.pk}/members/", {"email": email, "role": role}, format="json")
    assert r.status_code == 201, r.content
    return Membership.objects.get(tenant=client, user__email=email)


def test_admin_creates_projects_directly_and_assigns_engineers_per_project(world, settings):
    settings.PART_INTELLIGENCE_ENABLED = True  # so the intelligence endpoints answer with the project rule, not a disabled feature
    admin, client = _client(world)
    url = f"/api/v1/clients/{client.pk}/projects/"
    p1 = admin.post(url, {"code": "PUMPS", "name": "Pump digitisation"}, format="json")
    p2 = admin.post(url, {"code": "VALVES", "name": "Valve digitisation", "description": "Synthetic"}, format="json")
    assert p1.status_code == 201 and p2.status_code == 201, (p1.content, p2.content)
    assert admin.post(url, {"code": "pumps", "name": "Duplicate"}, format="json").status_code == 400  # code unique per company
    assert [r["code"] for r in admin.get(url).json()] == ["PUMPS", "VALVES"]
    with tenant_context(client):
        assert Project.objects.count() == 2 and Project.objects.get(code="PUMPS").created_by == world["op_admin"]
        assert AuditEvent.objects.filter(action="project.created", tenant=client).count() == 2
    assert AuditEvent.objects.filter(action="project.created", tenant=world["operator"]).count() == 2

    # a newly assigned engineer starts with no project access (not company-wide)
    m = _assign(admin, client, "new.eng@example.test")
    with tenant_context(client):
        assert EngineerAccess.objects.get(tenant=client, user=m.user).scope == "projects"
    eng = login(m.user, client)
    assert eng.get("/api/v1/projects/").json()["results"] == []
    r = eng.post("/api/v1/projects/", {"code": "X", "name": "Self-created"}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "project_scope"  # engineers do not create projects for themselves

    # assigned to PUMPS only: sees and works there; VALVES is closed, also by direct id
    acc = admin.put(f"/api/v1/clients/{client.pk}/engineers/{m.pk}/access/", {"scope": "projects", "project_ids": [p1.json()["id"]]}, format="json")
    assert acc.status_code == 200 and [p["code"] for p in acc.json()["projects"]] == ["PUMPS"]
    assert [p["code"] for p in eng.get("/api/v1/projects/").json()["results"]] == ["PUMPS"]
    part = eng.post("/api/v1/parts/", {"part_number": "P-1", "name": "Impeller", "project": p1.json()["id"]}, format="json")
    assert part.status_code == 201, part.content
    assert eng.get(f"/api/v1/projects/{p2.json()['id']}/").status_code == 404
    with tenant_context(client):
        other = SparePart.objects.create(tenant=client, part_number="V-1", name="Valve body", project_id=p2.json()["id"])
    for path in (f"/api/v1/parts/{other.pk}/", f"/api/v1/parts/{other.pk}/feasibility/", f"/api/v1/parts/{other.pk}/recommendations/"):
        assert eng.get(path).status_code == 404, path
    assert eng.post(f"/api/v1/parts/{other.pk}/feasibility/assess/", {}, format="json").status_code == 404
    assert "V-1" not in str(eng.get("/api/v1/parts/?page_size=50").json())

    # company-wide access stays available as an explicit, exceptional grant
    admin.put(f"/api/v1/clients/{client.pk}/engineers/{m.pk}/access/", {"scope": "company"}, format="json")
    assert eng.get(f"/api/v1/parts/{other.pk}/").status_code == 200


def test_reviewer_is_project_scoped(world, settings):
    settings.PART_INTELLIGENCE_ENABLED = True
    admin, client = _client(world)
    url = f"/api/v1/clients/{client.pk}/projects/"
    p1, p2 = (admin.post(url, {"code": c, "name": c}, format="json").json() for c in ("P1", "P2"))
    author = _assign(admin, client, "author@example.test")
    reviewer = _assign(admin, client, "reviewer@example.test")
    admin.put(f"/api/v1/clients/{client.pk}/engineers/{author.pk}/access/", {"scope": "projects", "project_ids": [p1["id"], p2["id"]]}, format="json")
    admin.put(f"/api/v1/clients/{client.pk}/engineers/{reviewer.pk}/access/", {"scope": "projects", "project_ids": [p1["id"]],
                                                                              "edit_reviewer": True}, format="json")
    a = login(author.user, client)
    in_p2 = a.post("/api/v1/parts/", {"part_number": "R-2", "name": "Wear ring", "project": p2["id"]}, format="json").json()
    a.post(f"/api/v1/parts/{in_p2['id']}/feasibility/assess/", {}, format="json")
    rv = login(reviewer.user, client)
    assert rv.get(f"/api/v1/parts/{in_p2['id']}/feasibility/").status_code == 404  # outside the reviewer's project
    assert rv.get("/api/v1/edit-requests/").status_code in (200, 403)


def test_clients_stay_in_their_company_and_existing_assignments_are_unchanged(world):
    admin, client = _client(world)
    p = admin.post(f"/api/v1/clients/{client.pk}/projects/", {"code": "ONLY", "name": "Only"}, format="json").json()
    # only the Aries Admin creates projects here: engineers in the Aries organisation and client roles are refused
    for user, tenant in ((world["op_eng"], world["operator"]), (world["a_admin"], None), (world["a_user"], None)):
        assert login(user, tenant).post(f"/api/v1/clients/{client.pk}/projects/", {"code": "Z", "name": "Z"}, format="json").status_code in (403, 404)
    # a client of another company cannot see the new company's project
    assert all(r["id"] != p["id"] for r in login(world["a_admin"]).get("/api/v1/projects/").json()["results"])
    # the engineer assigned earlier without a scope row (world fixture) keeps company-wide access
    with tenant_context(world["a"]):
        assert not EngineerAccess.objects.filter(tenant=world["a"], user=world["op_eng"]).exists()
    ac = admin.get(f"/api/v1/clients/{world['a'].pk}/details/").json()
    assert next(r for r in ac["aries_staff"] if r["email"] == world["op_eng"].email)["scope"] == "company"
    _ = PASSWORD
