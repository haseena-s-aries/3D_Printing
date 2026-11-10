"""Copy the company profile that registrants actually submitted onto the organisations created from their approved
registrations. Only blank organisation fields are filled; nothing is invented and no other organisation changes.

Registrations are rows of the operator tenant under forced row-level security, so the migration selects the operator
context for this transaction only. Reversing leaves the copied values in place (they are the submitted data).
"""
from django.db import migrations

# organisation field <- registration field
MAP = [("trade_licence_number", "trade_licence_number"), ("licence_authority", "licence_authority"), ("country", "country"),
       ("state", "state"), ("city", "city"), ("address", "address"), ("contact_name", "contact_name"),
       ("contact_title", "job_title"), ("contact_email", "email"), ("contact_phone", "phone")]


def backfill(apps, schema_editor):
    from apps.tenancy import mssql
    from apps.tenancy.context import SETTING, write_setting

    conn = schema_editor.connection
    sql_server = mssql.is_mssql(conn)
    with conn.cursor() as c:
        c.execute("SELECT TOP (1) id FROM tenancy_tenant WHERE kind = 'operator' ORDER BY created_at" if sql_server
                  else "SELECT id FROM tenancy_tenant WHERE kind = 'operator' ORDER BY created_at LIMIT 1")
        row = c.fetchone()
        if row is None:
            return
        write_setting(SETTING, row[0], conn)
        sets = ", ".join(f"{t} = CASE WHEN t.{t} = '' THEN r.{r} ELSE t.{t} END" for t, r in MAP)
        if sql_server:
            c.execute(f"""UPDATE t SET {sets} FROM tenancy_tenant t
                          JOIN registrations_companyregistration r ON r.client_tenant_id = t.id
                          WHERE r.status = 'approved' AND t.kind = 'client'""")
        else:
            c.execute(f"""UPDATE tenancy_tenant t SET {sets}
                          FROM registrations_companyregistration r
                          WHERE r.client_tenant_id = t.id AND r.status = 'approved' AND t.kind = 'client'""")
        write_setting(SETTING, None, conn)


class Migration(migrations.Migration):
    dependencies = [
        ("registrations", "0003_company_profile"),
        ("tenancy", "0005_company_profile"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
