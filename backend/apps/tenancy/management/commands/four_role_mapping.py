"""Map memberships of legacy roles to the four-role model (AccessTest/FOUR-ROLE-MODEL.md §3).

Dry run by default: for every legacy membership it prints the target role and permissions and the rights gained or lost,
computed with the real capabilities_for() and AI member-access rule. Nothing is written.

  manage.py four_role_mapping                       # dry run, all legacy memberships
  manage.py four_role_mapping --json out.json       # dry run, also write the report as JSON
  manage.py four_role_mapping --apply --confirm     # change role and permission fields in place (needs the switch on)

Applying keeps the membership id, user id, project scope and every historical record; only `role` and the permission fields
change, in one transaction, each with a `membership.role_mapped` audit event in the company's and the Aries trail.
Aries Support memberships are never mapped automatically (no place in the four roles; a decision is needed).
"""
import copy
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.service import record
from apps.projects.scoping import allowed_project_ids_for
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role, Tenant
from apps.tenancy.permissions import LEGACY_ROLES, authoring_allowed, capabilities_for, four_roles

R = Role
CLIENT, OPERATOR = Tenant.Kind.CLIENT, Tenant.Kind.OPERATOR
MAPPING = {
    # QA keeps its verification rights and gains no engineering authoring (R1): engineering_authoring is switched off.
    (R.OPERATOR_QA, CLIENT): (R.OPERATOR_ENGINEER, {"qa_permitted": True, "engineering_authoring": False}),
    (R.OPERATOR_QA, OPERATOR): (R.OPERATOR_ENGINEER, {"qa_permitted": True, "contract_reviewer": True, "engineering_authoring": False}),
    (R.CLIENT_ENGINEER, CLIENT): (R.CLIENT_USER, {"part_submission_allowed": True, "technical_access": True, "document_access": "full"}),
    (R.PROCUREMENT, CLIENT): (R.CLIENT_USER, {"procurement_access": True, "document_access": "none"}),
    (R.AUDITOR, CLIENT): (R.CLIENT_USER, {"audit_access": True, "document_access": "none"}),
}


def target(m: Membership):
    return MAPPING.get((m.role, m.tenant.kind))


def mapped_copy(m: Membership) -> Membership | None:
    t = target(m)
    if t is None:
        return None
    new = copy.copy(m)
    new.role = t[0]
    for f, v in t[1].items():
        setattr(new, f, v)
    return new


def ai_default(m: Membership) -> bool | None:
    """AI workspace member access (only meaningful for client roles)."""
    if m.tenant.kind != CLIENT or m.role.startswith("operator_"):
        return None
    from apps.intelligence.disclosure import member_allowed

    with tenant_context(m.tenant):
        return member_allowed(m)


def effects(m: Membership) -> dict:
    """Rights that are not capabilities: who services treat as a responsible engineer, and the AI member-access default."""
    engineer = m.role == R.OPERATOR_ENGINEER and m.tenant.kind == CLIENT and authoring_allowed(m)
    return {"submission_reviewer": engineer,  # notified of client submissions (apps.parts.submissions.reviewers)
            "responsible_engineer": engineer,  # listed as responsible in the Admin inventory (apps.parts.admin_overview)
            "ai_member_access": ai_default(m)}


def scope(m: Membership) -> str:
    """Project scope of Aries staff in a client company (keyed by user and company, so a role change cannot alter it)."""
    if m.tenant.kind != CLIENT or not m.role.startswith("operator_"):
        return "n/a"
    with tenant_context(m.tenant):
        ids = allowed_project_ids_for(m.tenant_id, m.user_id)
    return "company" if ids is None else f"{len(ids)} project(s)"


def plan(m: Membership) -> dict:
    new = mapped_copy(m)
    row = {"membership": str(m.pk), "user": str(m.user_id), "email": m.user.email, "company": m.tenant.slug, "kind": m.tenant.kind,
           "is_active": m.is_active, "from": m.role}
    if new is None:
        return {**row, "to": None, "status": "needs_decision"}
    before, after = set(capabilities_for(m)), set(capabilities_for(new))
    fx_before, fx_after = effects(m), effects(new)
    gained = sorted(after - before) + [f"[effect] {k}" for k in fx_after if fx_after[k] and not fx_before[k]]
    lost = sorted(before - after) + [f"[effect] {k}" for k in fx_before if fx_before[k] and not fx_after[k]]
    return {**row, "to": new.role, "permissions": target(m)[1], "before": sorted(before), "after": sorted(after),
            "effects": {"before": fx_before, "after": fx_after}, "scope": {"before": scope(m), "after": scope(new)},
            "gained": gained, "lost": lost, "status": "equivalent" if not gained and not lost else "changes"}


class Command(BaseCommand):
    help = "Map legacy-role memberships to the four-role model (dry run unless --apply --confirm)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Change the memberships (requires --confirm).")
        parser.add_argument("--confirm", action="store_true", help="Confirm that the dry-run mapping was verified.")
        parser.add_argument("--json", help="Also write the report to this JSON file.")

    def handle(self, *args, **opts):
        if not four_roles():
            raise CommandError("FOUR_ROLE_MODEL_ENABLED is off: the mapped permissions would have no effect.")
        if opts["apply"] and not opts["confirm"]:
            raise CommandError("--apply needs --confirm (run the dry run first and verify it).")
        legacy = Membership.objects.select_related("user", "tenant").filter(role__in=LEGACY_ROLES).order_by("role", "tenant__slug", "user__email")
        rows = [plan(m) for m in legacy]
        summary = {}
        for r in rows:
            key = f"{r['from']} -> {r['to'] or 'unmapped'} ({r['kind']})"
            s = summary.setdefault(key, {"memberships": 0, "equivalent": 0, "changes": 0, "needs_decision": 0, "gained": set(), "lost": set()})
            s["memberships"] += 1
            s[r["status"]] += 1
            s["gained"] |= set(r.get("gained", []))
            s["lost"] |= set(r.get("lost", []))
        accounts = {r["email"] for r in rows}
        unintended = [r for r in rows if r.get("gained") or r.get("lost") or r["status"] == "needs_decision"
                      or (r.get("scope") and r["scope"]["before"] != r["scope"]["after"])]
        self.stdout.write(f"{'APPLY' if opts['apply'] else 'DRY RUN'}: {len(rows)} legacy membership(s) of {len(accounts)} account(s)")
        for key, s in summary.items():
            self.stdout.write(f"  {key}: {s['memberships']} membership(s); equivalent {s['equivalent']}, with changes {s['changes']}, "
                              f"needs decision {s['needs_decision']}")
            self.stdout.write(f"      gained: {', '.join(sorted(s['gained'])) or 'none'}")
            self.stdout.write(f"      lost:   {', '.join(sorted(s['lost'])) or 'none'}")
        self.stdout.write(f"Memberships with any gained or lost right, scope change or open decision: {len(unintended)}")
        if opts["json"]:
            with open(opts["json"], "w", encoding="utf-8") as f:
                json.dump({"applied": bool(opts["apply"]), "accounts": len(accounts), "memberships": len(rows),
                           "with_differences": len(unintended), "rows": rows,
                           "summary": {k: {**v, "gained": sorted(v["gained"]), "lost": sorted(v["lost"])} for k, v in summary.items()}},
                          f, indent=2, default=str)
        if not opts["apply"]:
            self.stdout.write("Nothing changed.")
            return
        applied = 0
        with transaction.atomic():
            for m in legacy:
                new = mapped_copy(m)
                if new is None:
                    continue
                fields = ["role", *target(m)[1]]
                data = {"user": m.user.email, "from": m.role, "to": new.role, "permissions": target(m)[1],
                        "reason": "Four-role model (business decision 2026-10-30)"}
                new.save(update_fields=[*fields, "updated_at"])
                with tenant_context(m.tenant):
                    record(None, "membership.role_mapped", obj=new, tenant=m.tenant, data=data)
                op = Tenant.objects.filter(kind=OPERATOR).order_by("created_at").first()
                if op is not None and op.pk != m.tenant_id:
                    with tenant_context(op):
                        record(None, "membership.role_mapped", obj=new, tenant=op, data={**data, "company": m.tenant.slug})
                applied += 1
        self.stdout.write(self.style.SUCCESS(f"Mapped {applied} membership(s)."))
