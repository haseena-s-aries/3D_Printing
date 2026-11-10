"""Client access management (2 Nov 2026): the Client Administrator sees every project of the company (also later ones) and
manages which projects each Client User sees; new Client Users start with no project access; an all-projects grant is explicit
and revocable; feature permissions are independent of project access; Aries Engineer scoping and company isolation unchanged;
existing Client Users (no access row) keep their access."""
from django.test import Client as HttpClient

from apps.audit.models import AuditEvent
from apps.parts.models import SparePart
from apps.projects.models import EngineerAccess
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership

from .conftest import PASSWORD, login
from .test_w2_security import invite, token_of


def _accept(email, password=PASSWORD):
    def go(admin):
        token = token_of(invite(admin, email))
        r = HttpClient().post(f"/api/v1/invitation-acceptance/{token}/", {"first_name": email.split("@")[0], "password": password},
                              content_type="application/json")
        assert r.status_code == 200, r.content
        return Membership.objects.get(user__email=email)
    return go


def _setup(world):
    eng = login(world["op_eng"], world["a"])
    p1 = eng.post("/api/v1/projects/", {"code": "P-ONE", "name": "Project one"}, format="json").json()
    p2 = eng.post("/api/v1/projects/", {"code": "P-TWO", "name": "Project two"}, format="json").json()
    part1 = eng.post("/api/v1/parts/", {"part_number": "ONE-1", "name": "Impeller", "project": p1["id"]}, format="json").json()
    part2 = eng.post("/api/v1/parts/", {"part_number": "TWO-1", "name": "Valve body", "project": p2["id"]}, format="json").json()
    pp1 = eng.post("/api/v1/passports/", {"part": part1["id"]}, format="json").json()
    pp2 = eng.post("/api/v1/passports/", {"part": part2["id"]}, format="json").json()
    return eng, p1, p2, part1, part2, pp1, pp2


def codes(c):
    return sorted(p["code"] for p in c.get("/api/v1/projects/").json()["results"])


def test_client_admin_sees_all_own_projects_and_assigns_users_per_project(world, mailoutbox):
    eng, p1, p2, part1, part2, pp1, pp2 = _setup(world)
    admin = login(world["a_admin"])
    assert codes(admin) == ["P-ONE", "P-TWO"]
    later = eng.post("/api/v1/projects/", {"code": "P-LATER", "name": "Created later"}, format="json").json()
    assert codes(admin) == ["P-LATER", "P-ONE", "P-TWO"]  # projects created later appear without any assignment
    assert all(p["code"] != "P-ONE" for p in login(world["b_admin"]).get("/api/v1/projects/").json()["results"])  # other company
    assert login(world["b_admin"]).get(f"/api/v1/projects/{p1['id']}/").status_code == 404

    ma, mb = _accept("user.a@example.test")(admin), _accept("user.b@example.test")(admin)
    with tenant_context(world["a"]):
        assert EngineerAccess.objects.get(tenant=world["a"], user=ma.user).scope == "projects"
    ua = login(ma.user)
    assert codes(ua) == [] and ua.get("/api/v1/parts/").json()["results"] == []  # new Client User: no project access
    assert admin.get(f"/api/v1/users/{ma.pk}/projects/").json() == {"membership_id": str(ma.pk), "scope": "projects", "explicit": True, "projects": []}

    assert admin.put(f"/api/v1/users/{ma.pk}/projects/", {"scope": "projects", "project_ids": [p1["id"]]}, format="json").status_code == 200
    assert admin.put(f"/api/v1/users/{mb.pk}/projects/", {"scope": "projects", "project_ids": [p2["id"]]}, format="json").status_code == 200
    ub = login(mb.user)
    assert codes(ua) == ["P-ONE"] and codes(ub) == ["P-TWO"]
    for client_, mine, other, other_pp, other_project in ((ua, part1, part2, pp2, p2), (ub, part2, part1, pp1, p1)):
        assert client_.get(f"/api/v1/parts/{mine['id']}/").status_code == 200
        for path in (f"/api/v1/projects/{other_project['id']}/", f"/api/v1/parts/{other['id']}/", f"/api/v1/passports/{other_pp['id']}/",
                     f"/api/v1/passports/{other_pp['id']}/reports/"):
            assert client_.get(path).status_code == 404, path
        assert client_.get(f"/api/v1/files/?part={other['id']}").json()["results"] == []
    access = admin.get("/api/v1/users/project-access/").json()
    assert [p["code"] for p in access[str(ma.pk)]["projects"]] == ["P-ONE"]
    with tenant_context(world["a"]):
        assert AuditEvent.objects.filter(action="client_user.project_access_changed").count() == 2

    # all-projects grant: explicit, covers later projects, revocable
    assert admin.put(f"/api/v1/users/{ma.pk}/projects/", {"scope": "company"}, format="json").json()["scope"] == "company"
    assert codes(ua) == ["P-LATER", "P-ONE", "P-TWO"]
    assert admin.put(f"/api/v1/users/{ma.pk}/projects/", {"scope": "projects", "project_ids": []}, format="json").status_code == 200
    assert codes(ua) == [] and ua.get(f"/api/v1/parts/{part1['id']}/").status_code == 404
    _ = later


def test_client_admin_manages_client_users_only_and_features_are_independent(world, mailoutbox, settings):
    settings.FOUR_ROLE_MODEL_ENABLED = True  # feature permissions of Client Users (access-test configuration)
    _eng, p1, *_ = _setup(world)
    admin = login(world["a_admin"])
    ma = _accept("user.c@example.test")(admin)
    # feature permissions stay where they are and do not change project access
    assert admin.patch(f"/api/v1/users/{ma.pk}/", {"technical_access": True, "document_access": "full"}, format="json").status_code == 200
    assert codes(login(ma.user)) == []
    admin.put(f"/api/v1/users/{ma.pk}/projects/", {"scope": "projects", "project_ids": [p1["id"]]}, format="json")
    m = Membership.objects.get(pk=ma.pk)
    assert m.technical_access is True and m.document_access == "full"
    # not for Client Administrators or Aries staff; not across companies; not by Client Users
    own = Membership.objects.get(user=world["a_admin"], tenant=world["a"])
    eng = Membership.objects.get(user=world["op_eng"], tenant=world["a"])
    assert admin.put(f"/api/v1/users/{own.pk}/projects/", {"scope": "projects", "project_ids": []}, format="json").status_code == 400
    assert admin.put(f"/api/v1/users/{eng.pk}/projects/", {"scope": "projects", "project_ids": []}, format="json").status_code in (400, 404)
    assert login(world["b_admin"]).put(f"/api/v1/users/{ma.pk}/projects/", {"scope": "company"}, format="json").status_code == 404
    assert login(ma.user).put(f"/api/v1/users/{ma.pk}/projects/", {"scope": "company"}, format="json").status_code == 403
    assert admin.put(f"/api/v1/users/{ma.pk}/projects/", {"scope": "projects", "project_ids": ["00000000-0000-0000-0000-000000000000"]},
                     format="json").status_code == 400


def test_existing_client_users_and_engineer_scoping_unchanged(world):
    _eng, p1, p2, part1, part2, *_ = _setup(world)
    # the existing Client User (no access row) keeps company-wide visibility: nothing is revoked silently
    assert codes(login(world["a_user"])) == ["P-ONE", "P-TWO"]
    # a project-scoped Client User still sees their own submission without a project
    admin = login(world["a_admin"])
    with tenant_context(world["a"]):
        own = SparePart.objects.create(tenant=world["a"], part_number="OWN-1", name="Own proposal", origin="client",
                                       review_state="pending_review", submission_kind="proposal")
    ma = Membership.objects.get(user=world["a_user"], tenant=world["a"])
    admin.put(f"/api/v1/users/{ma.pk}/projects/", {"scope": "projects", "project_ids": [p1["id"]]}, format="json")
    with tenant_context(world["a"]):
        SparePart.objects.filter(pk=own.pk).update(submitted_by=world["a_user"])
    numbers = {p["part_number"] for p in login(world["a_user"]).get("/api/v1/parts/?catalog=all&page_size=50").json()["results"]}
    assert "OWN-1" in numbers and "ONE-1" in numbers and "TWO-1" not in numbers
    # the company-wide Aries Engineer of the fixture still sees everything
    eng = login(world["op_eng"], world["a"])
    assert {"P-ONE", "P-TWO"} <= set(codes(eng)) and eng.get(f"/api/v1/parts/{part2['id']}/").status_code == 200


def test_client_requests_follow_project_access(world, mailoutbox):
    from apps.servicerequests.models import ClientRequest

    _eng, p1, p2, part1, part2, *_ = _setup(world)
    admin = login(world["a_admin"])
    ma = _accept("user.r@example.test")(admin)
    admin.put(f"/api/v1/users/{ma.pk}/projects/", {"scope": "projects", "project_ids": [p1["id"]]}, format="json")
    with tenant_context(world["a"]):
        mk = lambda ref, **kw: ClientRequest.objects.create(tenant=world["a"], reference=ref, kind="enquiry", **kw)  # noqa: E731
        mk("MR-T-1", part_id=part1["id"], requested_by=world["a_admin"])
        mk("MR-T-2", part_id=part2["id"], requested_by=world["a_admin"])
        mk("DR-T-3", requested_by=ma.user)
    refs = sorted(r["reference"] for r in login(ma.user).get("/api/v1/requests/").json()["results"])
    assert refs == ["DR-T-3", "MR-T-1"]  # own request + the request of the assigned project, not P-TWO's
    assert sorted(r["reference"] for r in admin.get("/api/v1/requests/").json()["results"]) == ["DR-T-3", "MR-T-1", "MR-T-2"]
