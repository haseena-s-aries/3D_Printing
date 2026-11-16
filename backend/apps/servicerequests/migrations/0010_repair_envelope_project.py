from django.db import migrations


def repair(apps, schema_editor):
    """Fill in the project of existing intake rows. The project used to be read inside the operator's row-level-security
    context, where the client's parts are hidden, so requests whose project comes from their part were stored without a
    project and did not appear in the lists of project-scoped Aries staff."""
    from apps.tenancy.context import tenant_context

    Tenant = apps.get_model("tenancy", "Tenant")
    ClientRequest = apps.get_model("servicerequests", "ClientRequest")
    SparePart = apps.get_model("parts", "SparePart")
    Envelope = apps.get_model("servicerequests", "RequestEnvelope")
    op = Tenant.objects.filter(kind="operator").first()
    if op is None:
        return
    found = {}
    for t in Tenant.objects.filter(kind="client"):
        with tenant_context(t.pk):
            for r in ClientRequest.objects.all().only("id", "project_id", "part_id", "created_part_id"):
                pid = r.project_id
                for part_id in (r.part_id, r.created_part_id):
                    if pid is None and part_id:
                        pid = SparePart.objects.filter(pk=part_id).values_list("project_id", flat=True).first()
                found[r.pk] = pid
    with tenant_context(op.pk):
        for env in Envelope.objects.all().only("id", "request_id", "project_ref"):
            pid = found.get(env.request_id)
            if env.request_id in found and env.project_ref != pid:
                env.project_ref = pid
                env.save(update_fields=["project_ref"])


class Migration(migrations.Migration):

    dependencies = [
        ("servicerequests", "0009_manufacturing_order_flow"),
        ("parts", "0007_submission_revision_and_completion"),
    ]

    operations = [migrations.RunPython(repair, migrations.RunPython.noop)]
