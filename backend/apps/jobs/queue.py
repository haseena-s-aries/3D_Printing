"""PostgreSQL-backed job queue (ADR-008). No broker, no always-running infrastructure required.

enqueue()   - called inside a tenant request (RLS context set); inserts a queued job.
claim_next()- worker side; uses the app_worker role when configured, which may see the queue across
              tenants (policy worker_queue) but no tenant business data.
run_one()   - processes one job under that job's tenant context.
"""
import logging
import socket
import traceback

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.tenancy import mssql
from apps.tenancy.context import set_tenant_context, tenant_context

from .models import Job

log = logging.getLogger(__name__)
HANDLERS = {}


class JobFailure(Exception):
    def __init__(self, code: str, detail: str, retry: bool = False):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.retry = code, detail, retry


def handler(kind: str):
    def register(fn):
        HANDLERS[kind] = fn
        return fn
    return register


def enqueue(tenant, kind: str, payload: dict, created_by=None) -> Job:
    return Job.objects.create(tenant=tenant, kind=kind, payload=payload, created_by=created_by)


def worker_id() -> str:
    return f"{socket.gethostname()}:{id(connection)}"


def claim_next():
    """Return (job_id, tenant_id) for the next queued job, or None. Marks it running."""
    role = getattr(settings, "WORKER_DB_ROLE", "")
    if mssql.is_mssql(connection):
        return _claim_next_mssql(role)
    with transaction.atomic():
        set_tenant_context(None)
        with connection.cursor() as cur:
            if role:
                cur.execute(f"SET LOCAL ROLE {connection.ops.quote_name(role)}")
            cur.execute(
                """
                UPDATE jobs_job SET status = 'running', attempts = attempts + 1, locked_by = %s,
                       locked_at = clock_timestamp(), updated_at = clock_timestamp()
                WHERE id = (
                    SELECT id FROM jobs_job
                    WHERE status = 'queued' AND run_after <= clock_timestamp()
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING id, tenant_id
                """,
                [worker_id()],
            )
            row = cur.fetchone()
            if role:
                cur.execute("RESET ROLE")
    return row


def _claim_next_mssql(role: str):
    """SQL Server: the same claim. EXECUTE AS USER replaces SET LOCAL ROLE (the rls_tenant_or_worker predicate lets
    app_worker see the queue only); READPAST replaces SKIP LOCKED; OUTPUT replaces RETURNING."""
    # One batch: the security context switch and its REVERT never span batches (separate batches fail with error 15408
    # once the connection has run other work), and TRY/CATCH guarantees the REVERT.
    as_role = f"EXECUTE AS USER = N'{role.replace(chr(39), '')}';" if role else ""
    revert = "REVERT;" if role else ""
    with transaction.atomic():
        set_tenant_context(None)
        with connection.cursor() as cur:
            cur.execute(
                f"""
                SET NOCOUNT ON;
                DECLARE @claimed TABLE (id char(32), tenant_id char(32));
                {as_role}
                BEGIN TRY
                    WITH next_job AS (
                        SELECT TOP (1) * FROM jobs_job WITH (ROWLOCK, UPDLOCK, READPAST)
                        WHERE status = 'queued' AND run_after <= SYSUTCDATETIME()
                        ORDER BY created_at
                    )
                    UPDATE next_job SET status = 'running', attempts = attempts + 1, locked_by = %s,
                           locked_at = SYSUTCDATETIME(), updated_at = SYSUTCDATETIME()
                    OUTPUT inserted.id, inserted.tenant_id INTO @claimed;
                    {revert}
                END TRY
                BEGIN CATCH
                    {revert}
                    THROW;
                END CATCH;
                SELECT id, tenant_id FROM @claimed;
                """,
                [worker_id()],
            )
            row = cur.fetchone()
    return row


def run_one() -> str | None:
    claimed = claim_next()
    if claimed is None:
        return None
    job_id, tenant_id = claimed
    with tenant_context(tenant_id):
        job = Job.objects.get(pk=job_id)
        fn = HANDLERS.get(job.kind)
        try:
            if fn is None:
                raise JobFailure("unknown_job_kind", job.kind)
            with transaction.atomic():
                fn(job)
            job.status, job.error_code, job.error_detail = Job.Status.SUCCEEDED, "", ""
        except JobFailure as e:
            log.warning("job %s failed: %s", job.pk, e)
            retry = e.retry and job.attempts < job.max_attempts
            job.status = Job.Status.QUEUED if retry else Job.Status.FAILED
            job.error_code, job.error_detail = e.code, e.detail[:2000]
        except Exception as e:  # unexpected: record and do not retry blindly
            log.exception("job %s crashed", job.pk)
            job.status, job.error_code = Job.Status.FAILED, "unexpected_error"
            job.error_detail = "".join(traceback.format_exception_only(type(e), e))[:2000]
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_code", "error_detail", "finished_at", "updated_at"])
        return job.status
