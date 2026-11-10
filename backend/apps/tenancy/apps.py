from django.apps import AppConfig


class TenancyConfig(AppConfig):
    name = "apps.tenancy"
    label = "tenancy"

    def ready(self):
        from django.core.signals import request_finished, request_started
        from django.db import connection
        from django.db.models.signals import post_migrate

        from . import mssql
        from .context import reset_session_context

        if not mssql.is_mssql(connection):
            return
        # SQL Server: SESSION_CONTEXT belongs to the connection, so it is cleared around every request (fail closed)
        request_started.connect(reset_session_context, dispatch_uid="tenancy_reset_context_start")
        request_finished.connect(reset_session_context, dispatch_uid="tenancy_reset_context_end")
        post_migrate.connect(_refresh_guards, sender=self, dispatch_uid="tenancy_refresh_guards")


def _refresh_guards(using="default", **_kwargs):
    """Immutability triggers list the columns they write: rebuild them after migrations changed the tables."""
    from django.db import connections

    from . import mssql

    mssql.refresh_guards(connections[using])
