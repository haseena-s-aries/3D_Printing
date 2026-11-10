"""Row-level security and immutability, tested directly at the database layer (PostgreSQL, and SQL Server security
policies / INSTEAD OF triggers from apps.tenancy.mssql). These tests prove isolation even if application code forgets a
tenant filter."""
import pytest
from django.db import DatabaseError, connection, transaction

from apps.audit.models import AuditEvent
from apps.files.models import EngineeringFile, FileVersion
from apps.jobs.models import Job
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport, PassportRevision
from apps.tenancy.context import set_tenant_context, tenant_context


def seed_part(tenant, number):
    with tenant_context(tenant):
        return SparePart.objects.create(tenant=tenant, part_number=number, name=f"Part {number}")


MSSQL = connection.vendor == "microsoft"


def test_app_role_cannot_bypass_rls(db):
    with connection.cursor() as cur:
        if MSSQL:  # SQL Server applies security policies to every user (dbo and sysadmin included); a sysadmin could drop them
            cur.execute("SELECT IS_SRVROLEMEMBER('sysadmin'), p.is_enabled FROM sys.security_policies p "
                        "WHERE p.name = 'rls_parts_sparepart'")
            assert tuple(cur.fetchone()) == (0, True)
            return
        cur.execute("select rolsuper, rolbypassrls from pg_roles where rolname = current_user")
        assert cur.fetchone() == (False, False)
        cur.execute("select relforcerowsecurity from pg_class where relname = 'parts_sparepart'")
        assert cur.fetchone()[0] is True


def test_no_tenant_context_sees_nothing(world):
    seed_part(world["a"], "A-1")
    seed_part(world["b"], "B-1")
    with transaction.atomic():
        set_tenant_context(None)
        assert SparePart.objects.count() == 0  # fail closed


def test_context_limits_unfiltered_queries(world):
    seed_part(world["a"], "A-1")
    seed_part(world["b"], "B-1")
    with tenant_context(world["a"]):
        assert list(SparePart.objects.values_list("part_number", flat=True)) == ["A-1"]  # no .filter() used
        with connection.cursor() as cur:
            cur.execute("select count(*) from parts_sparepart")
            assert cur.fetchone()[0] == 1


def test_insert_for_other_tenant_rejected(world):
    with tenant_context(world["a"]):
        with pytest.raises(DatabaseError), transaction.atomic():
            SparePart.objects.create(tenant=world["b"], part_number="X", name="cross-tenant insert")


def test_move_row_to_other_tenant_rejected(world):
    part = seed_part(world["a"], "A-1")
    with tenant_context(world["a"]):
        with pytest.raises(DatabaseError), transaction.atomic():
            SparePart.objects.filter(pk=part.pk).update(tenant=world["b"])


def test_other_tenant_rows_cannot_be_updated_or_deleted(world):
    part_b = seed_part(world["b"], "B-1")
    with tenant_context(world["a"]):
        assert SparePart.objects.filter(pk=part_b.pk).update(name="changed") == 0
        assert SparePart.objects.filter(pk=part_b.pk).delete()[0] == 0
    with tenant_context(world["b"]):
        assert SparePart.objects.get(pk=part_b.pk).name == "Part B-1"


def test_worker_role_sees_queue_but_not_tenant_data(world):
    seed_part(world["a"], "A-1")
    with tenant_context(world["a"]):
        Job.objects.create(tenant=world["a"], kind="noop")
    with tenant_context(world["b"]):
        Job.objects.create(tenant=world["b"], kind="noop")
    with transaction.atomic():
        set_tenant_context(None)
        with connection.cursor() as cur:
            cur.execute("EXECUTE AS USER = N'app_worker'" if MSSQL else "SET LOCAL ROLE app_worker")
            cur.execute("select count(*) from jobs_job")
            assert cur.fetchone()[0] == 2  # queue across tenants
            cur.execute("select count(*) from parts_sparepart")
            assert cur.fetchone()[0] == 0  # tenant data still isolated
            cur.execute("REVERT" if MSSQL else "RESET ROLE")


def test_api_role_does_not_inherit_the_worker_queue_policy(world):
    """Regression (db-role-rls-finding): app_user may SET ROLE app_worker but must not inherit its queue policy."""
    with tenant_context(world["a"]):
        Job.objects.create(tenant=world["a"], kind="noop")
    with tenant_context(world["b"]):
        Job.objects.create(tenant=world["b"], kind="noop")
    with connection.cursor() as cur:
        if MSSQL:  # the queue predicate checks the identity itself: the application may impersonate, never inherit
            cur.execute("SELECT CASE WHEN USER_NAME() = N'app_worker' THEN 1 ELSE 0 END, "
                        "HAS_PERMS_BY_NAME(N'app_worker', N'USER', N'IMPERSONATE')")
            assert tuple(cur.fetchone()) == (0, 1)
        else:
            cur.execute("select pg_has_role('app_user', 'app_worker', 'USAGE'), pg_has_role('app_user', 'app_worker', 'SET')")
            assert cur.fetchone() == (False, True)
    with tenant_context(world["a"]):
        assert Job.objects.count() == 1  # only tenant A's job, not B's
    with transaction.atomic():
        set_tenant_context(None)
        assert Job.objects.count() == 0  # no context: nothing


def make_revision(tenant, status="draft"):
    with tenant_context(tenant):
        part = SparePart.objects.create(tenant=tenant, part_number=f"P-{status}", name="p")
        pp = DigitalPassport.objects.create(tenant=tenant, part=part, passport_number=f"DP-{status}", title="t")
        return PassportRevision.objects.create(tenant=tenant, passport=pp, revision_number=1, status=status, content={"a": 1})


def test_approved_revision_is_immutable(world):
    rev = make_revision(world["a"], status="approved")
    with tenant_context(world["a"]):
        with pytest.raises(DatabaseError, match="immutable_record"), transaction.atomic():
            PassportRevision.objects.filter(pk=rev.pk).update(content={"a": 2})
        with pytest.raises(DatabaseError, match="immutable_record"), transaction.atomic():
            PassportRevision.objects.filter(pk=rev.pk).delete()
        # the only permitted change: approved -> superseded with unchanged content
        assert PassportRevision.objects.filter(pk=rev.pk).update(status="superseded") == 1
        with pytest.raises(DatabaseError, match="immutable_record"), transaction.atomic():
            PassportRevision.objects.filter(pk=rev.pk).update(status="draft")


def test_draft_revision_is_editable(world):
    rev = make_revision(world["a"], status="draft")
    with tenant_context(world["a"]):
        assert PassportRevision.objects.filter(pk=rev.pk).update(content={"a": 3}) == 1


def test_file_versions_and_audit_are_immutable(world):
    a = world["a"]
    with tenant_context(a):
        part = SparePart.objects.create(tenant=a, part_number="F-1", name="p")
        ef = EngineeringFile.objects.create(tenant=a, part=part, kind="pdf", title="doc")
        fv = FileVersion.objects.create(tenant=a, file=ef, version_number=1, original_filename="x.pdf", size_bytes=1,
                                        sha256="0" * 64, detected_format="pdf", content_type="application/pdf",
                                        storage_key="tenants/x/originals/1")
        ev = AuditEvent.objects.create(tenant=a, action="test")
        for qs in (FileVersion.objects.filter(pk=fv.pk), AuditEvent.objects.filter(pk=ev.pk)):
            with pytest.raises(DatabaseError, match="immutable_record"), transaction.atomic():
                qs.update(created_at=fv.created_at)
            with pytest.raises(DatabaseError, match="immutable_record"), transaction.atomic():
                qs.delete()
