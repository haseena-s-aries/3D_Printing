"""Dependency and component checks for the Aries 3D Digital Passport backend, run INSIDE the isolated virtual environment
created by Test-Py314Compatibility.ps1. No database connection is made here; nothing outside the package folder is written
except a temporary folder that is removed again.

Usage: <venv>\\Scripts\\python.exe tools\\py314_checks.py <package root> <results json>
"""
import importlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
BACKEND = ROOT / "backend"
results = []


def check(cid, title, fn):
    t0 = time.perf_counter()
    try:
        detail = fn()
        ok = True
    except Exception as e:  # noqa: BLE001 - every failure is reported, the run continues
        ok, detail = False, f"{type(e).__name__}: {e}"
    results.append({"id": cid, "title": title, "ok": ok, "detail": str(detail)[:400], "seconds": round(time.perf_counter() - t0, 2)})
    print(f"{'PASS' if ok else 'FAIL'}  {cid} {title} - {str(detail)[:200]}", flush=True)


def interpreter():
    v = sys.version_info
    isolated = sys.prefix != sys.base_prefix
    if not isolated:
        raise RuntimeError("not running in a virtual environment")
    return f"Python {v.major}.{v.minor}.{v.micro} {'64' if sys.maxsize > 2**32 else '32'}-bit; venv {sys.prefix}; base {sys.base_prefix}"


def pinned_versions():
    from importlib.metadata import distributions
    installed = {d.metadata["Name"].lower().replace("_", "-"): d.version for d in distributions()}
    pins = {}
    for line in (BACKEND / "constraints-sqlserver.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "==" in line:
            name, ver = line.split("==", 1)
            pins[name.lower().replace("_", "-")] = ver
    pins.update({"cadquery-ocp": "8.0.1.1.0", "cadquery-ocp-proxy": "8.0.1.1.0", "vtk": "9.6.2"})
    wrong = {n: (installed.get(n), v) for n, v in pins.items() if installed.get(n) != v}
    if wrong:
        raise RuntimeError(f"differs from the tested versions: {wrong}")
    return f"{len(pins)} packages exactly at the tested versions"


MODULES = ["django", "rest_framework", "rest_framework_simplejwt", "drf_spectacular", "mssql", "pyodbc", "mssql_python", "waitress",
           "PIL", "pypdf", "pypdfium2", "openpyxl", "google.genai", "azure.storage.blob", "dotenv", "pydantic", "cryptography",
           "OCP", "vtk"]


def imports():
    loaded = []
    for m in MODULES:
        mod = importlib.import_module(m)
        loaded.append(f"{m} {getattr(mod, '__version__', '')}".strip())
    return "; ".join(loaded)


def odbc_driver():
    import pyodbc
    drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
    if "ODBC Driver 18 for SQL Server" not in drivers:
        raise RuntimeError(f"ODBC Driver 18 for SQL Server not installed (found: {drivers})")
    return ", ".join(drivers)


def django_env(debug: bool) -> dict:
    # explicit dummy SQL Server configuration: `check` does not connect to any database
    return {**os.environ, "DB_ENGINE": "mssql", "DB_HOST": "127.0.0.1", "DB_NAME": "no_database_used_by_check", "DB_USER": "none",
            "DB_PASSWORD": "none", "DB_DRIVER": "ODBC Driver 18 for SQL Server", "DJANGO_DEBUG": "true" if debug else "false",
            "DJANGO_SECRET_KEY": "py314-compat-check-" + "x" * 50, "DJANGO_ALLOWED_HOSTS": "localhost",
            "LOCAL_STORAGE_ROOT": str(Path(tempfile.gettempdir()) / "dp-py314-check-storage")}


# Django's model checks ask the database backend (e.g. JSONField support), so they need a connection: they run in stage 2
# against the test database. Stage 1 runs every registered check category except those two.
CHECKS = r'''
import json, django
django.setup()
from django.core import checks
from django.core.checks.registry import registry
deploy = __import__("sys").argv[1] == "deploy"
tags = sorted(registry.tags_available(deployment_checks=deploy) - {"models", "database"})
found = checks.run_checks(tags=tags, include_deployment_checks=deploy)
print(json.dumps({"tags": tags, "errors": [str(m) for m in found if m.level >= checks.ERROR],
                  "warnings": [m.id for m in found if m.level < checks.ERROR]}))
'''


def django_check():
    out = {}
    for mode, debug in (("normal", True), ("deploy", False)):
        r = subprocess.run([sys.executable, "-c", CHECKS, mode], cwd=BACKEND, capture_output=True, text=True, timeout=300,
                           env={**django_env(debug), "DJANGO_SETTINGS_MODULE": "config.settings"})
        if r.returncode:
            raise RuntimeError((r.stdout + r.stderr)[-400:])
        out[mode] = json.loads(r.stdout.strip().splitlines()[-1])
        if out[mode]["errors"]:
            raise RuntimeError(f"{mode} check errors: {out[mode]['errors'][:3]}")
    return (f"no errors in {len(out['deploy']['tags'])} check categories ({', '.join(out['deploy']['tags'])}); production warnings "
            f"by design: {', '.join(out['deploy']['warnings']) or 'none'}; model checks run in stage 2")


def django_imports_all_apps():
    code = ("import django; django.setup(); from django.apps import apps as registry; "
            "import apps.tenancy.mssql, apps.core.mssql_backend.base, apps.jobs.queue, apps.files.cad_pipeline, apps.reports.services; "
            "print(len(registry.get_app_configs()))")
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env={**django_env(True), "DJANGO_SETTINGS_MODULE": "config.settings"},
                       capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError((r.stdout + r.stderr)[-400:])
    return f"{r.stdout.strip()} Django apps loaded with the SQL Server backend, queue, CAD and report modules"


def waitress_serves():
    from waitress.server import create_server

    def app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"ok"]
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = create_server(app, host="127.0.0.1", port=port, threads=2)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    try:
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).read()
    finally:
        server.close()
    if body != b"ok":
        raise RuntimeError(f"unexpected body {body!r}")
    return f"served a request on 127.0.0.1:{port} (loopback only, stopped again)"


def cad_conversion():
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.update({k: v for k, v in django_env(True).items() if k.startswith(("DB_", "DJANGO_", "LOCAL_"))})
    import django
    django.setup()
    from apps.files import cad_pipeline
    step = BACKEND / "tests" / "fixtures" / "sleeve_d45_h40_5_synthetic.stp"
    with tempfile.TemporaryDirectory() as tmp:
        glb = Path(tmp) / "sleeve.glb"
        res = cad_pipeline.convert(step, glb)
        size = glb.stat().st_size
    info = {k: v for k, v in vars(res).items() if k in ("triangles", "bbox_mm", "faces", "solids")} if hasattr(res, "__dict__") else str(res)
    if size < 1000:
        raise RuntimeError(f"GLB too small ({size} bytes)")
    return f"application STEP->GLB conversion of the synthetic sleeve: GLB {size} bytes; {info}"


def vtk_pipeline():
    import vtk
    src = vtk.vtkSphereSource()
    src.SetThetaResolution(16)
    src.SetPhiResolution(16)
    src.Update()
    n = src.GetOutput().GetNumberOfPolys()
    if n <= 0:
        raise RuntimeError("no polygons")
    return f"VTK {vtk.vtkVersion.GetVTKVersion()}: sphere with {n} polygons"


def pdf_and_images():
    import io

    import pypdfium2
    from PIL import Image
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    buf = io.BytesIO()
    w.write(buf)
    page = pypdfium2.PdfDocument(buf.getvalue())[0]
    img = page.render(scale=0.5).to_pil()
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG")
    Image.open(io.BytesIO(out.getvalue())).verify()
    return f"pypdf wrote a PDF, pdfium rendered it {img.size}, Pillow encoded/decoded JPEG"


def node_renderer():
    node = subprocess.run(["node", "--version"], capture_output=True, text=True, shell=False) if _which("node") else None
    if not node or node.returncode:
        raise RuntimeError("Node.js not found on PATH (needed for PDF reports; install Node 22 LTS)")
    pw = (ROOT / "node_modules" / "playwright" / "package.json").exists() and (ROOT / "node_modules" / "three" / "package.json").exists()
    return f"Node {node.stdout.strip()}; package node_modules {'present' if pw else 'NOT installed yet (run with -InstallNodePackages)'}"


def _which(cmd):
    from shutil import which
    return which(cmd)


check("C1", "Python 3.14 interpreter in an isolated virtual environment", interpreter)
check("C2", "Installed packages match the tested versions exactly", pinned_versions)
check("C3", "All backend, SQL Server, server and CAD modules import", imports)
check("C4", "Microsoft ODBC Driver 18 for SQL Server available to pyodbc", odbc_driver)
check("C5", "Django system and production (--deploy) checks that need no database, SQL Server engine", django_check)
check("C6", "All Django apps load with the SQL Server backend, job queue, CAD and report modules", django_imports_all_apps)
check("C7", "Waitress serves HTTP (loopback, temporary port)", waitress_serves)
check("C8", "CAD: the application's STEP -> GLB conversion (OCP)", cad_conversion)
check("C9", "VTK pipeline", vtk_pipeline)
check("C10", "PDF and image libraries (pypdf, pypdfium2, Pillow)", pdf_and_images)
check("C11", "Node.js for PDF report rendering", node_renderer)
OUT.write_text(json.dumps({"python": sys.version, "results": results}, indent=2), encoding="utf-8")
failed = [r["id"] for r in results if not r["ok"]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
sys.exit(1 if failed else 0)
