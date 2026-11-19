"""Test companies: marking, queueing for deletion, and the privileged purge (decision of 19 Nov 2026).

Why two steps. The platform deliberately has no hard deletes: 31 tables carry database guards that block UPDATE and DELETE
(audit trail, file versions, assessments, ...), and the application's database login cannot change or disable them (the
deployment verifies this). So the web application never erases protected records. Instead:

1. In the app, an Aries Admin or Manager marks a company as a test company (`set_test`) and may queue it for deletion
   (`request_deletion`). Queueing suspends the company at once: nobody can sign in, it leaves every list, and it can be
   restored (`restore`) until it is purged.
2. `manage.py purge_test_companies`, run with the privileged owner login (the one used for `migrate`), erases the queued
   companies for good (`purge`): every row of the company, its stored files, and the users who belong to nothing else. The
   guards are disabled only inside that one transaction (DDL is transactional on PostgreSQL and SQL Server), so a failure
   rolls everything back, guards included. One audit event in the Aries organisation records the purge.

Only client companies marked as test, queued for deletion and suspended are purged; the Aries organisation never is.
"""
from graphlib import TopologicalSorter

from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.audit.service import record
from apps.core.exceptions import DomainError

from . import mssql
from .context import tenant_context
from .models import Membership, Tenant


# ------------------------------------------------------------------ marking and queueing (inside the app)

def set_test(request, client: Tenant, is_test: bool) -> Tenant:
    if client.kind != Tenant.Kind.CLIENT:
        raise DomainError("not_a_client", "Only client companies can be marked as test companies.", http_status=400)
    if client.deletion_requested_at and not is_test:
        raise DomainError("deletion_queued", "Restore the company first; it is queued for deletion.", http_status=409)
    if client.is_test != is_test:
        client.is_test = is_test
        client.save(update_fields=["is_test", "updated_at"])
        record(request, "client.marked_test" if is_test else "client.unmarked_test", obj=client,
               data={"company": client.name, "slug": client.slug})
    return client


def request_deletion(request, client: Tenant, confirm_name: str) -> Tenant:
    """Suspend a test company at once and queue it for the privileged purge. The company name must be typed exactly."""
    if client.kind != Tenant.Kind.CLIENT:
        raise DomainError("not_a_client", "Only client companies can be deleted.", http_status=400)
    if not client.is_test:
        raise DomainError("not_test_company", "Mark the company as a test company first. Real companies are never deleted here.",
                          http_status=409)
    if client.deletion_requested_at:
        raise DomainError("already_queued", "This company is already queued for deletion.", http_status=409)
    if (confirm_name or "").strip() != client.name:
        raise DomainError("confirmation_mismatch", "Type the company name exactly to confirm.", http_status=400)
    client.status = Tenant.Status.SUSPENDED
    client.deletion_requested_at, client.deletion_requested_by = timezone.now(), request.user
    client.save(update_fields=["status", "deletion_requested_at", "deletion_requested_by", "updated_at"])
    record(request, "client.deletion_requested", obj=client, data={"company": client.name, "slug": client.slug})
    return client


def restore(request, client: Tenant) -> Tenant:
    if not client.deletion_requested_at:
        raise DomainError("not_queued", "This company is not queued for deletion.", http_status=409)
    client.status = Tenant.Status.ACTIVE
    client.deletion_requested_at, client.deletion_requested_by = None, None
    client.save(update_fields=["status", "deletion_requested_at", "deletion_requested_by", "updated_at"])
    record(request, "client.deletion_cancelled", obj=client, data={"company": client.name, "slug": client.slug})
    return client


def queued():
    """Companies the purge may erase."""
    return Tenant.objects.filter(kind=Tenant.Kind.CLIENT, is_test=True, status=Tenant.Status.SUSPENDED,
                                 deletion_requested_at__isnull=False).order_by("name")


# ------------------------------------------------------------------ what belongs to a company

def company_models() -> list:
    """Every model with a `tenant` foreign key, children before parents (so no foreign key is violated)."""
    tenant_owned = [m for m in apps.get_models() if m is not Tenant and any(
        f.name == "tenant" and f.many_to_one and f.related_model is Tenant for f in m._meta.get_fields())]
    members = set(tenant_owned)
    waits_for = {m: set() for m in tenant_owned}  # a parent waits for its children
    for child in tenant_owned:
        for f in child._meta.get_fields():
            # forward links, including one-to-one ones (a passport's part): the linked row must outlive the row pointing at it
            if f.is_relation and f.concrete and (f.many_to_one or f.one_to_one) and f.related_model in members and f.related_model is not child:
                waits_for[f.related_model].add(child)
    return list(TopologicalSorter(waits_for).static_order())


def row_counts(client: Tenant) -> dict[str, int]:
    out = {}
    with tenant_context(client):
        for m in company_models():
            n = m._base_manager.filter(tenant_id=client.pk).count()
            if n:
                out[m._meta.label] = n
    return out


# ------------------------------------------------------------------ database guards (privileged login only)

def _guards() -> list[tuple[str, str]]:
    """(table, trigger name) of every immutability guard."""
    with connection.cursor() as cur:
        if mssql.is_mssql(connection):
            cur.execute("SELECT OBJECT_NAME(parent_id), name FROM sys.triggers WHERE name LIKE N'%[_]guard' AND is_instead_of_trigger = 1")
        else:
            cur.execute("SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                        "WHERE NOT t.tgisinternal AND t.tgname ~ '_guard$'")
        return [(r[0], r[1]) for r in cur.fetchall()]


def _switch_guards(guards, on: bool) -> None:
    word = "ENABLE" if on else "DISABLE"
    with connection.cursor() as cur:
        if not mssql.is_mssql(connection):
            # PostgreSQL refuses ALTER TABLE while deferred foreign-key checks are pending: run them now (any violation
            # surfaces here, before anything is committed)
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
        for table, name in guards:
            if mssql.is_mssql(connection):
                cur.execute(f"{word} TRIGGER dbo.[{name}] ON dbo.[{table}]")
            else:
                cur.execute(f'ALTER TABLE "{table}" {word} TRIGGER "{name}"')


NOTIFICATION_TABLE = "servicerequests_notification"


def _switch_notification_rls(on: bool) -> None:
    """In-app notifications have row-level security with no delete policy, so even the table owner cannot delete them.
    The purge lifts it for its own transaction only (rolled back with everything else on failure)."""
    with connection.cursor() as cur:
        if mssql.is_mssql(connection):
            cur.execute("SELECT DISTINCT SCHEMA_NAME(p.schema_id), p.name FROM sys.security_policies p "
                        "JOIN sys.security_predicates sp ON sp.object_id = p.object_id "
                        "WHERE sp.target_object_id = OBJECT_ID(N'dbo.servicerequests_notification')")
            for schema, name in cur.fetchall():
                cur.execute(f"ALTER SECURITY POLICY [{schema}].[{name}] WITH (STATE = {'ON' if on else 'OFF'})")
        else:
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cur.execute(f"ALTER TABLE {NOTIFICATION_TABLE} {'FORCE' if on else 'NO FORCE'} ROW LEVEL SECURITY")


# ------------------------------------------------------------------ the purge

def _delete_users(user_ids, log) -> tuple[int, int]:
    """Delete the people who belonged only to the erased company; anyone who cannot be deleted is deactivated and kept."""
    from apps.accounts.models import User
    from apps.registrations.models import EmailToken
    from apps.servicerequests.models import Notification

    deleted = kept = 0
    for user in User.objects.filter(pk__in=user_ids, is_staff=False, is_superuser=False):
        if Membership.objects.filter(user=user).exists():  # belongs to something else (for example Aries staff): never deleted
            continue
        try:
            with transaction.atomic():
                Notification.objects.filter(recipient=user)._raw_delete(connection.alias)
                EmailToken.objects.filter(user=user)._raw_delete(connection.alias)
                user.delete()
            deleted += 1
        except (IntegrityError, ProtectedError) as exc:
            User.objects.filter(pk=user.pk).update(is_active=False)
            kept += 1
            log(f"  kept (deactivated): {user.email} ({type(exc).__name__}: {str(exc).splitlines()[0][:160]})")
    return deleted, kept


def purge(client: Tenant, *, log=print) -> dict:
    """Erase one queued test company for good. Must run with the privileged owner login; all or nothing."""
    if client.kind != Tenant.Kind.CLIENT or not (client.is_test and client.deletion_requested_at and client.status == Tenant.Status.SUSPENDED):
        raise DomainError("not_queued", "Only a client company marked as test, suspended and queued for deletion can be purged.", http_status=409)
    from apps.registrations.models import CompanyRegistration
    from apps.servicerequests.models import RequestEnvelope

    operator = Tenant.objects.filter(kind=Tenant.Kind.OPERATOR).order_by("created_at").first()
    name, slug, pk = client.name, client.slug, client.pk
    requested_by = client.deletion_requested_by.email if client.deletion_requested_by_id else ""
    removed: dict[str, int] = {}
    with transaction.atomic():
        guards = _guards()
        _switch_guards(guards, on=False)  # rolled back with everything else if anything below fails
        _switch_notification_rls(on=False)
        with tenant_context(client):
            user_ids = list(Membership.objects.filter(tenant_id=pk).values_list("user_id", flat=True))
            for m in company_models():
                n = m._base_manager.filter(tenant_id=pk)._raw_delete(connection.alias)
                if n:
                    removed[m._meta.label] = n
        if operator is not None:  # the company's records that live in the Aries organisation
            with tenant_context(operator):
                for m in (RequestEnvelope, CompanyRegistration):
                    n = m._base_manager.filter(client_tenant_id=pk)._raw_delete(connection.alias)
                    if n:
                        removed[m._meta.label] = n
        users_deleted, users_kept = _delete_users(user_ids, log)
        Tenant.objects.filter(pk=pk)._raw_delete(connection.alias)
        if operator is not None:
            with tenant_context(operator):
                record(None, "tenant.purged", obj_type="Tenant", obj_id=str(pk), tenant=operator, data={
                    "company": name, "slug": slug, "requested_by": requested_by, "rows": sum(removed.values()),
                    "users_deleted": users_deleted, "users_deactivated": users_kept})
        _switch_notification_rls(on=True)
        _switch_guards(guards, on=True)
    from apps.files.storage import get_storage

    files = get_storage().purge_tenant(pk)  # after the database commit: a rolled-back purge keeps its files
    return {"company": name, "slug": slug, "rows": sum(removed.values()), "tables": removed, "users_deleted": users_deleted,
            "users_deactivated": users_kept, "files": files}
