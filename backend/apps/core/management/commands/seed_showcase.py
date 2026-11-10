"""Seed the synthetic demonstration dataset (three fictitious client organisations) - development only.

  python manage.py seed_showcase                 # requires a database whose name ends in "_demo"
  python manage.py seed_showcase --only demo-energy
Idempotent: organisations, users, projects, parts, passports and documents are looked up first and only created
when missing, so running it again creates nothing new. Everything goes through the platform's own REST API
(validation, audit trail, row-level security, conversion queue), signed in as the demo operator staff.

Never sets evidence level, publication state or manufacturing eligibility, and never records approvals or QA
verification (OQ-35/OQ-36). STEP files are queued for conversion; run the CAD worker to produce the 3D views.
DWG files are not generated: no licensed or validated DWG writer is available (see docs/demo-showcase.md).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.views import tokens_for
from apps.files.models import EngineeringFile
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport
from apps.projects.models import Project
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role, Tenant

ROUND = {"pump_impeller", "shaft_coupling", "pipe_flange", "spacer_sleeve", "fan_hub", "pump_cover", "thrust_collar"}
FAMILY_TEXT = {
    "pump_impeller": "Closed-back centrifugal impeller with radial vanes, keyed bore",
    "shaft_coupling": "Flanged rigid coupling half with keyed bore and bolt circle",
    "valve_body": "Two-flange globe-style valve body with bonnet boss",
    "pipe_flange": "Weld-neck flange with raised face and bolt circle",
    "bearing_housing": "Pillow-block bearing housing with base mounting holes",
    "spacer_sleeve": "Plain cylindrical spacer sleeve with chamfered end",
    "bracket": "L-bracket with gussets and mounting holes",
    "gear_housing": "Open-top gearbox housing with bearing bosses",
    "fan_hub": "Fan hub with radial blade-mounting arms",
    "pump_cover": "Pump casing cover with spigot, seal boss and bolt circle",
    "thrust_collar": "Bearing thrust collar with axial tapped holes",
}


class Api:
    """In-process REST client signed in as one membership (no password needed: tokens are issued directly)."""

    def __init__(self, membership: Membership):
        self.c = APIClient(HTTP_HOST="127.0.0.1")
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens_for(membership)['access']}")

    def call(self, method: str, path: str, data=None, fmt="json", ok=(200, 201)):
        r = getattr(self.c, method)(f"/api/v1{path}", data, format=fmt)
        if r.status_code not in ok:
            raise CommandError(f"{method.upper()} {path} -> {r.status_code}: {r.content[:400]!r}")
        return r.json() if r.content else None


class Command(BaseCommand):
    help = "Create the synthetic demonstration dataset (development only, idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--only", action="append", default=[], help="Seed only this organisation slug (repeatable).")
        parser.add_argument("--allow-any-database", action="store_true",
                            help="Allow a database whose name does not end in _demo (the E2E database should stay separate).")
        parser.add_argument("--inventory", default=str(Path(settings.BASE_DIR) / ".showcase" / "inventory.json"))

    def handle(self, *args, **opts):
        from showcase import data  # noqa: PLC0415 - dev tooling, imported on use

        if not settings.DEBUG:
            raise CommandError("seed_showcase is for development only (DJANGO_DEBUG must be true).")
        db = settings.DATABASES["default"]["NAME"]
        if not db.endswith("_demo") and not opts["allow_any_database"]:
            raise CommandError(f"Database '{db}' is not a demo database. Use scripts/demo_db.py (passport_demo), "
                               "or pass --allow-any-database deliberately.")
        try:
            from showcase import cad  # noqa: F401, PLC0415
        except ImportError as e:
            raise CommandError(f"The CAD packages are needed to generate the sample STEP files (requirements-cad.txt): {e}")

        self.password = os.environ.get("DEMO_PASSWORD") or ("Demo-" + secrets.token_urlsafe(12))
        self.inventory: list[dict] = []
        self.created = {"organisations": 0, "users": 0, "projects": 0, "parts": 0, "passports": 0, "files": 0, "versions": 0}
        clients = [c for c in data.CLIENTS if not opts["only"] or c.slug in opts["only"]]
        if not clients:
            raise CommandError(f"No organisation matches {opts['only']}.")

        operator, admin_m, eng_user = self.operator_staff(data)
        op_api = Api(admin_m)
        for cdef in clients:
            tenant = self.client_org(op_api, cdef)
            self.members(op_api, tenant, cdef, eng_user)
            eng_m = Membership.objects.get(user=eng_user, tenant=tenant)
            self.seed_client(Api(eng_m), tenant, cdef)

        out = Path(opts["inventory"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.inventory, indent=1), encoding="utf8")
        self.report(clients, out)

    # ---- organisations and users ------------------------------------------------------------------------------

    def user(self, email, first, last) -> tuple[User, bool]:
        user, created = User.objects.get_or_create(email=email, defaults={"first_name": first, "last_name": last, "username": email})
        if created or os.environ.get("DEMO_PASSWORD"):
            user.set_password(self.password)
            user.save()
        self.created["users"] += created
        return user, created

    def operator_staff(self, data):
        with transaction.atomic():
            op, _ = Tenant.objects.get_or_create(slug="operator", defaults={"name": "Platform Operator (demo)", "kind": Tenant.Kind.OPERATOR})
            users = {}
            for email, role, first, last in data.OPERATOR_STAFF:
                users[role], _ = self.user(email, first, last)
                Membership.objects.get_or_create(user=users[role], tenant=op, defaults={"role": role})
        return op, Membership.objects.get(user=users["operator_admin"], tenant=op), users["operator_engineer"]

    def client_org(self, op_api, cdef) -> Tenant:
        tenant = Tenant.objects.filter(slug=cdef.slug).first()
        if tenant is None:
            # Demo organisations get a clearly synthetic company profile; demo accounts are created below, so no invitation.
            op_api.call("post", "/clients/", {
                "name": cdef.name, "slug": cdef.slug, "region_code": "demo", "invite_contact": False,
                "trade_licence_number": f"DEMO-{cdef.slug.upper()}", "licence_authority": "Synthetic demo licensing authority",
                "country": "United Arab Emirates", "state": "Dubai", "address": "Synthetic demo address (not a real location)",
                "contact_name": " ".join(cdef.admin), "contact_title": "Client Administrator (demo)",
                "contact_email": f"admin@{cdef.domain}", "contact_phone": "+971 4 000 0000"})
            tenant = Tenant.objects.get(slug=cdef.slug)
            self.created["organisations"] += 1
        return tenant

    def members(self, op_api, tenant, cdef, eng_user):
        wanted = [(f"admin@{cdef.domain}", Role.CLIENT_ADMIN, *cdef.admin), (f"user@{cdef.domain}", Role.CLIENT_USER, *cdef.user)]
        for email, role, first, last in wanted:
            user, _ = self.user(email, first, last)
            if not Membership.objects.filter(user=user, tenant=tenant).exists():
                op_api.call("post", f"/clients/{tenant.pk}/members/", {"email": email, "role": role, "first_name": first, "last_name": last})
        # the operator engineer is assigned to every demo client (W1: operator staff assigned by the operator admin)
        if not Membership.objects.filter(user=eng_user, tenant=tenant).exists():
            op_api.call("post", f"/clients/{tenant.pk}/members/", {"email": eng_user.email, "role": Role.OPERATOR_ENGINEER})
            # new assignments start project-scoped (2 Nov 2026); the demo engineer keeps the company-wide access it always had
            mid = Membership.objects.get(user=eng_user, tenant=tenant).pk
            op_api.call("put", f"/clients/{tenant.pk}/engineers/{mid}/access/", {"scope": "company"})

    # ---- catalog ------------------------------------------------------------------------------------------------

    def seed_client(self, api: Api, tenant: Tenant, cdef):
        from showcase import cad  # noqa: PLC0415

        with tenant_context(tenant):
            projects = dict(Project.objects.filter(tenant=tenant).values_list("code", "pk"))
        for code, name, desc in cdef.projects:
            if code not in projects:
                projects[code] = api.call("post", "/projects/", {"code": code, "name": name, "description": desc})["id"]
                self.created["projects"] += 1
        for part in cdef.parts:
            model = cad.build(part.family, **part.params)
            self.seed_part(api, tenant, cdef, part, model, projects[part.project])

    def seed_part(self, api, tenant, cdef, part, model, project_id):
        from showcase import cad, documents as D, render  # noqa: PLC0415

        with tenant_context(tenant):
            sp = SparePart.objects.filter(tenant=tenant, part_number=part.number).first()
            passport = DigitalPassport.objects.filter(part=sp).first() if sp else None
        if sp is None:
            sx, sy, sz = model.size
            dims = f"Ø{max(sx, sy):.0f} x {sz:.1f} mm" if part.family in ROUND else f"{sx:.0f} x {sy:.0f} x {sz:.0f} mm"
            body = {"part_number": part.number, "name": part.name, "project": project_id, "category": part.category,
                    "criticality": part.criticality, "original_material": part.material, "dimensions": dims,
                    "application": part.application, "equipment_reference": part.equipment, "status": part.status,
                    "description": f"{FAMILY_TEXT[part.family]}. Synthetic demonstration part; not a real component."}
            part_id = api.call("post", "/parts/", body)["id"]
            self.created["parts"] += 1
        else:
            part_id = str(sp.pk)

        content = build_content(part, model)
        passport_id = str(passport.pk) if passport else None
        if part.scenario != "nopass" and passport_id is None:
            passport_id = api.call("post", "/passports/", {"part": part_id, "title": f"{part.name} (sample)"})["id"]
            self.created["passports"] += 1
        if passport_id:
            self.ensure_content(api, tenant, passport_id, {k: v for k, v in content.items() if k != "rl3"})

        if not part.docs:
            return
        edges = cad.edge_polylines(model)
        slug = part.name.lower().replace(",", "").replace(" ", "_")[:40]
        files = {}
        files["step"] = self.ensure_file(api, tenant, cdef, part, part_id, passport_id, "3d_model", f"{part.number} 3D model (STEP)",
                                         f"{part.number}_{slug}.stp", lambda: cad.step_bytes(model, f"{part.number} {part.name} (synthetic sample)"))
        files["photo"] = self.ensure_file(api, tenant, cdef, part, part_id, passport_id, "photo", f"{part.number} part image (synthetic render)",
                                          f"{part.number}_render.jpg", lambda: render.render_png(cad.triangles(model), title=f"{part.number} {part.name} - synthetic sample"))
        if part.scenario in ("rl1", "rl2", "rl3docs"):
            files["drawing"] = self.ensure_file(api, tenant, cdef, part, part_id, passport_id, "drawing", f"{part.number} general arrangement drawing",
                                                f"{part.number}_GA_drawing.pdf", lambda: D.drawing(cdef, part, model, edges))
        if part.scenario in ("rl2", "rl3docs"):
            files["spec"] = self.ensure_file(api, tenant, cdef, part, part_id, passport_id, "specification", f"{part.number} manufacturing specification",
                                             f"{part.number}_MTS.pdf", lambda: D.specification(cdef, part, model, content))
            if part.spec_v2:
                self.ensure_version(api, tenant, files["spec"], 2, f"{part.number}_MTS_revB.pdf", lambda: D.specification(
                    cdef, part, model, content, rev="B", change_note="Heat-treatment step and coupon count clarified (sample revision)."),
                    "Rev B: heat-treatment step clarified (sample)")
            files["itp"] = self.ensure_file(api, tenant, cdef, part, part_id, passport_id, "inspection", f"{part.number} inspection and test plan",
                                            f"{part.number}_ITP.pdf", lambda: D.itp(cdef, part, content))
            files["wi"] = self.ensure_file(api, tenant, cdef, part, part_id, passport_id, "specification", f"{part.number} manufacturing work instruction",
                                           f"{part.number}_work_instruction.pdf", lambda: D.work_instruction(cdef, part, content))
        if part.scenario == "rl3docs":
            files["machine"] = self.ensure_file(api, tenant, cdef, part, part_id, passport_id, "other", f"{part.number} machine details (sample)",
                                                f"{part.number}_machine_details.pdf", lambda: D.machine_details(cdef, part, content))
            files["orientation"] = self.ensure_file(api, tenant, cdef, part, part_id, passport_id, "other", f"{part.number} print orientation (sample)",
                                                    f"{part.number}_print_orientation.pdf", lambda: D.print_orientation(cdef, part, model, edges, content))
            files["dir"] = self.ensure_file(api, tenant, cdef, part, part_id, passport_id, "inspection", f"{part.number} dimensional inspection report TEMPLATE",
                                            f"{part.number}_DIR_template.pdf", lambda: D.dimensional_inspection_template(cdef, part, model))
            files["mtc"] = self.ensure_file(api, tenant, cdef, part, part_id, passport_id, "certificate", f"{part.number} material test certificate TEMPLATE (no results)",
                                            f"{part.number}_MTC_template.pdf", lambda: D.mtc_template(cdef, part, content))
            rl3 = {"evidence": {"itp": files["itp"], "machine_details": files["machine"], "print_orientation": files["orientation"],
                                "dimensional_inspection": files["dir"], "material_test_certificate": files["mtc"]},
                   "notes": "Sample evidence documents attached for demonstration only. Templates contain no results. "
                            "Not QA-verified; evidence-level transitions are disabled (OQ-35)."}
            self.ensure_content(api, tenant, passport_id, {"rl3": rl3})

    def ensure_content(self, api, tenant, passport_id, levels: dict):
        with tenant_context(tenant):
            current = DigitalPassport.objects.get(pk=passport_id).revisions.order_by("-revision_number").first()
            stored = current.content or {}
            number = current.revision_number
        if all(_same(stored.get(k), v) for k, v in levels.items()):
            return
        api.call("patch", f"/passports/{passport_id}/revisions/{number}/", {"content": levels})

    def ensure_file(self, api, tenant, cdef, part, part_id, passport_id, category, title, filename, make) -> str:
        with tenant_context(tenant):
            ef = EngineeringFile.objects.filter(tenant=tenant, part_id=part_id, title=title).first()
            if ef is not None:
                for v in ef.versions.order_by("version_number"):
                    self.note(cdef, part, ef, v.version_number, v.original_filename, v.size_bytes, v.sha256)
                return str(ef.pk)
        content = make()
        body = {"part": part_id, "category": category, "title": title, "file": SimpleUploadedFile(filename, content)}
        if passport_id:
            body["passport"] = passport_id
        r = api.call("post", "/files/", body, fmt="multipart")
        self.created["files"] += 1
        self.created["versions"] += 1
        self.inventory.append({"organisation": cdef.slug, "part": part.number, "title": title, "kind": r["kind"], "category": category,
                               "version": 1, "filename": filename, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        return r["id"]

    def ensure_version(self, api, tenant, file_id, number, filename, make, note):
        with tenant_context(tenant):
            if EngineeringFile.objects.get(pk=file_id).versions.filter(version_number=number).exists():
                return
        content = make()
        api.call("post", f"/files/{file_id}/versions/", {"file": SimpleUploadedFile(filename, content), "note": note}, fmt="multipart")
        self.created["versions"] += 1

    def note(self, cdef, part, ef, version, filename, size, sha):
        self.inventory.append({"organisation": cdef.slug, "part": part.number, "title": ef.title, "kind": ef.kind, "category": ef.category,
                               "version": version, "filename": filename, "bytes": size, "sha256": sha})

    def report(self, clients, inventory_path):
        w = self.stdout.write
        w(self.style.SUCCESS("Showcase dataset ready (development only)."))
        w("Created this run: " + ", ".join(f"{k} {v}" for k, v in self.created.items()))
        for c in clients:
            t = Tenant.objects.get(slug=c.slug)
            with tenant_context(t):
                counts = (Project.objects.filter(tenant=t).count(), SparePart.objects.filter(tenant=t).count(),
                          DigitalPassport.objects.filter(tenant=t).count(), EngineeringFile.objects.filter(tenant=t).count())
            w(f"  {c.name:32s} projects {counts[0]}  parts {counts[1]}  passports {counts[2]}  documents {counts[3]}")
            w(f"    sign in: admin@{c.domain} (client admin), user@{c.domain} (client user)")
        w("  engineer@operator.demo is assigned to every demo organisation (choose it at sign-in or switch).")
        w(f"  File inventory: {inventory_path}")
        if os.environ.get("DEMO_PASSWORD"):
            w("  Passwords: the DEMO_PASSWORD value.")
        elif self.created["users"]:
            w(f"  Password for the accounts created now: {self.password}")
        w("Next: run the CAD worker against this database to convert the queued STEP files (scripts/run_demo.py worker).")


def _same(a, b) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def build_content(part, model) -> dict:
    """R-L1 / R-L2 passport content for the part's scenario (synthetic values; requirements, never results)."""
    from showcase.data import MATERIALS  # noqa: PLC0415

    sx, sy, sz = model.size
    size = f"{max(sx, sy):.1f} x {sz:.1f} mm (Ø x H)" if part.family in ROUND else f"{sx:.0f} x {sy:.0f} x {sz:.0f} mm"
    if part.scenario == "nopass":
        return {}
    if part.scenario == "none":
        return {"rl1": {"original_material_grade": part.material, "application": part.application, "part_size": size}}
    rl1 = {
        "cad_3d_available": part.docs, "drawings_2d_available": part.docs,
        "original_material_grade": part.material, "proposed_material": part.proposed,
        "proposed_material_reason": f"Original {part.material.replace(' (sample)', '')} casting no longer available from the OEM; "
                                    f"{part.proposed} proposed for additive manufacturing (sample rationale).",
        "material_identification_method": "pmi" if part.criticality == "critical" else "oem",
        "technical_description": f"{FAMILY_TEXT[part.family]}. Overall size {size}. Synthetic demonstration data.",
        "part_size": size, "application": part.application, "atmosphere": part.atmosphere, "motion": part.motion,
        "ip_status": "obsolete" if part.number[-1] in "13579" else "active",
    }
    if part.motion == "rotating":
        rl1["rpm"] = part.rpm
    content = {"rl1": rl1}
    if part.scenario in ("rl2", "rl3docs"):
        feed, process, heat, standard, rows = MATERIALS[part.proposed]
        volume_cm3 = model.volume_mm3 / 1000
        critical = part.criticality == "critical"
        content["rl2"] = {
            "manufacturing_solution": f"{process} in {part.proposed}; {heat}; functional faces and bores finish-machined (sample route).",
            "material_selection": part.proposed,
            "material_category": "superior" if part.proposed in ("SS 316L", "Inconel 625") else "equivalent",
            "criticality_amsl": "AMSL-1 (sample)" if critical else "AMSL-3 (sample)",
            "feedstock": feed, "applicable_standards": f"{standard}; ISO/ASTM 52900 terminology",
            "mechanical_acceptance": [{"property": p, "requirement": r, "unit": u, "standard": s} for p, r, u, s in rows],
            "dimensional_tolerances": "ISO 2768-mK; bores H7; sealing faces Ra 1.6 (sample)",
            "ndt": "Visual + dye penetrant; CT scan of first article (sample)" if critical else "Visual + dye penetrant (sample)",
            "inspection_test_plan": f"{part.number}-ITP rev A (sample)", "mtc_required": True,
            "test_coupons": "3 tensile coupons + 1 density cube per build (sample)",
            "manufacturing_spec": {
                "job_number": f"SMP-{part.number}", "material": part.proposed, "feedstock": feed,
                "machine": "L-PBF system, 250 x 250 x 300 mm build volume (sample)",
                "layer_thickness": "40 µm" if part.proposed != "AlSi10Mg" else "30 µm",
                "support_strategy": "Block supports on down-facing surfaces below 45° (sample)",
                "build_orientation": "Main axis vertical, mounting face on build plate (sample)",
                "inert_gas": "Argon" if part.proposed != "AlSi10Mg" else "Argon (O₂ < 0.1 %)",
                "heat_treatment": heat, "post_processing": "Support removal, bead blasting (sample)",
                "machining": "Bores and sealing faces finish-machined (sample)",
                "printing_hours": round(2 + volume_cm3 / 9, 1), "post_processing_hours": round(1.5 + volume_cm3 / 60, 1),
                "process_parameters": [{"name": "Laser power", "value": "200", "unit": "W"},
                                       {"name": "Scan speed", "value": "900", "unit": "mm/s"},
                                       {"name": "Hatch distance", "value": "0.10", "unit": "mm"}],
            },
        }
    return content
